"""
experiments/swat_a4a5_g0_evaluation.py
=======================================
TCMIM Stage 2 Candidate-Edge Gating Evaluation with G0_STRUCTURAL_MASK enabled vs disabled.

Evaluates identical SWaT A4/A5 July 2019 event inputs under two configurations:
- Configuration A: G0 disabled (structural_mask=None, legacy behavior)
- Configuration B: G0 enabled (structural_mask loaded from register, allow_unknown=False)

Reports:
- Paired candidate-edge counts entering each gate and surviving the full pipeline.
- Breakdown of edges rejected as physically prohibited vs unverified/unknown.
- Retention of documented and inferred physical relationships.
- Per-attack-interval metrics for all six documented attack intervals (A1 to A6).
- Rejection reason frequency summaries.

Scientific integrity:
- Attack labels are used strictly post hoc for evaluation grouping, never for model inputs.
- Candidate reduction is reported as structural edge filtering, not causal discovery precision.
- Distinguishes documentary evidence, engineering inference, and unexcited actuators.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

# Add repository src to python path
_project_root = Path(__file__).resolve().parent.parent
_src_dir = _project_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from tcmim.data.swat_a4a5 import (
    A4A5_ACTUATOR_STATE_MAP,
    A4A5_MODALITY_MAP,
    A4A5Attack,
    GapAwareWindowBuilder,
    SWAT_A4A5_ATTACK_SCHEDULE,
    load_swat_a4a5_dataframe,
)
from tcmim.features.extractor import FeatureExtractor
from tcmim.gating.gates import GatingConfig, GatingPipeline
from tcmim.gating.structural_mask import (
    DEFAULT_UNEXCITED_ACTUATORS,
    PhysicalStructuralMask,
    StructuralStatus,
    get_default_register_path,
)
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.propagation.matcher import EventMatcher
from tcmim.schemas import AnomalyRecord, EventRecord, PropagationObservation, Provenance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("swat_a4a5_g0_evaluation")


@dataclass
class EvaluationConfig:
    """Configuration for Stage 2 G0 structural mask evaluation."""
    data_path: Path
    output_dir: Path
    register_path: Optional[Path] = None
    window_seconds: float = 30.0
    step_seconds: float = 30.0
    min_samples: int = 2
    max_internal_gap_s: float = 15.0
    baseline_start_idx: int = 10
    baseline_end_idx: int = 280      # Windows 10..279 (8,100 s)
    eval_start_idx: int = 280
    eval_end_idx: int = 500          # Windows 280..499
    z_percentile_threshold: float = 95.0
    min_z_threshold: float = 3.0
    matcher_min_delay_s: float = 0.0
    matcher_max_delay_s: float = 600.0
    gating_min_delay_s: float = 0.0
    gating_max_delay_s: float = 600.0
    gating_require_positive_dt: bool = True
    gating_require_same_modality: bool = False
    allow_unknown_config_b: bool = False
    provenance: Provenance = Provenance.PUBLIC_DATASET

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_path": str(self.data_path),
            "output_dir": str(self.output_dir),
            "register_path": str(self.register_path) if self.register_path else "default_project_register",
            "window_seconds": self.window_seconds,
            "step_seconds": self.step_seconds,
            "min_samples": self.min_samples,
            "max_internal_gap_s": self.max_internal_gap_s,
            "baseline_partition": f"Windows {self.baseline_start_idx}..{self.baseline_end_idx-1} (04:35:00 to 06:50:00 UTC)",
            "eval_partition": f"Windows {self.eval_start_idx}..{self.eval_end_idx-1} (06:50:00 to 08:40:00 UTC)",
            "z_percentile_threshold": self.z_percentile_threshold,
            "min_z_threshold": self.min_z_threshold,
            "matcher_min_delay_s": self.matcher_min_delay_s,
            "matcher_max_delay_s": self.matcher_max_delay_s,
            "gating_min_delay_s": self.gating_min_delay_s,
            "gating_max_delay_s": self.gating_max_delay_s,
            "gating_require_positive_dt": self.gating_require_positive_dt,
            "gating_require_same_modality": self.gating_require_same_modality,
            "allow_unknown_config_b": self.allow_unknown_config_b,
            "provenance": self.provenance.value,
        }


def run_g0_paired_evaluation(config: EvaluationConfig) -> Dict[str, Any]:
    """Execute paired Stage 2 gating evaluation on SWaT A4/A5."""
    start_time = time.perf_counter()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading SWaT A4/A5 workbook from %s...", config.data_path)
    df, meta = load_swat_a4a5_dataframe(config.data_path)

    # 1. Gap-aware window construction
    logger.info("Constructing gap-aware windows (size=%.1fs, step=%.1fs)...",
                config.window_seconds, config.step_seconds)
    window_builder = GapAwareWindowBuilder(
        window_seconds=config.window_seconds,
        step_seconds=config.step_seconds,
        min_samples=config.min_samples,
        max_internal_gap_s=config.max_internal_gap_s,
    )
    all_windows, _ = window_builder.build_and_audit(
        df, machine_id="SWAT_A4A5", provenance=config.provenance
    )
    logger.info("Constructed %d total windows.", len(all_windows))

    # 2. Multimodal feature extraction
    logger.info("Extracting multimodal features across all %d windows...", len(all_windows))
    fe = FeatureExtractor(
        sampling_rate_hz=1.0,
        channel_modality_map=A4A5_MODALITY_MAP,
        channel_state_map=A4A5_ACTUATOR_STATE_MAP,
    )
    all_samples = fe.extract_all(all_windows)

    flat_samples: List[Dict[str, float]] = []
    for s in all_samples:
        flat: Dict[str, float] = {}
        for mod_feats in s.features.values():
            flat.update(mod_feats)
        flat_samples.append(flat)
    df_feats = pd.DataFrame(flat_samples)

    # 3. Standardized Z-scores strictly relative to baseline (Windows 10..279)
    base_idx = slice(config.baseline_start_idx, config.baseline_end_idx)
    base_feats = df_feats.iloc[base_idx]
    feat_means = base_feats.mean()
    feat_stds = base_feats.std(ddof=1)

    valid_cols = feat_stds[feat_stds >= 1e-12].index.tolist()
    constant_cols = feat_stds[feat_stds < 1e-12].index.tolist()
    logger.info("Features: %d total, %d valid baseline variance, %d zero variance.",
                df_feats.shape[1], len(valid_cols), len(constant_cols))

    Z_matrix = (df_feats[valid_cols] - feat_means[valid_cols]) / feat_stds[valid_cols]
    Z_matrix = Z_matrix.fillna(0.0)

    # 4. Calibrate per-channel statistical monitoring thresholds on baseline
    channels = sorted(list(set(c.split("__")[0] for c in valid_cols)))
    logger.info("Active channels evaluated: %d channels.", len(channels))

    channel_thresholds: Dict[str, float] = {}
    for ch in channels:
        ch_cols = [c for c in valid_cols if c.startswith(f"{ch}__")]
        ch_z_base = Z_matrix[ch_cols].iloc[base_idx].abs().max(axis=1)
        tau_val = float(np.percentile(ch_z_base, config.z_percentile_threshold))
        channel_thresholds[ch] = max(config.min_z_threshold, tau_val)

    # 5. Adapt channel anomaly scores into discrete EventRecords
    adapter = AnomalyToEventAdapter(
        EventAdapterConfig(
            min_burst_windows=1,
            max_gap_s=config.window_seconds * 2.0,
            score_aggregation="peak",
        )
    )

    events_by_channel: Dict[str, List[EventRecord]] = {}
    event_index: Dict[str, EventRecord] = {}
    channel_event_counts: Dict[str, int] = {}

    eval_idx_range = range(config.eval_start_idx, config.eval_end_idx)
    for ch in channels:
        ch_cols = [c for c in valid_cols if c.startswith(f"{ch}__")]
        ch_z = Z_matrix[ch_cols].abs().max(axis=1)
        records: List[AnomalyRecord] = []
        for w_idx in eval_idx_range:
            w = all_windows[w_idx]
            val = float(ch_z.iloc[w_idx])
            is_ano = val > channel_thresholds[ch]
            rec = AnomalyRecord(
                timestamp=w.window_start,
                machine_id=ch,
                anomaly_score=val,
                is_anomaly=is_ano,
                detector="per_channel_max_z",
                provenance=config.provenance,
            )
            records.append(rec)

        ch_events = adapter.adapt(
            records, modality=A4A5_MODALITY_MAP.get(ch), machine_id=ch
        )
        if ch_events:
            events_by_channel[ch] = ch_events
            channel_event_counts[ch] = len(ch_events)
            for ev in ch_events:
                event_index[ev.event_id] = ev

    total_events = sum(len(evs) for evs in events_by_channel.values())
    logger.info("Detected %d discrete events across %d active channels.",
                total_events, len(events_by_channel))

    # 6. Candidate edge matching (identical candidate universe for both configs)
    matcher = EventMatcher(
        min_delay_s=config.matcher_min_delay_s,
        max_delay_s=config.matcher_max_delay_s,
    )
    candidates = matcher.match_all_pairs(events_by_channel)
    # Sort chronologically by source onset
    candidates.sort(
        key=lambda o: event_index[o.source_event].onset_time
        if o.source_event in event_index
        else datetime.min.replace(tzinfo=timezone.utc)
    )
    logger.info("Matched %d initial candidate edges in window [%.1f, %.1f] s.",
                len(candidates), config.matcher_min_delay_s, config.matcher_max_delay_s)

    # 7. Load Physical Structural Mask
    mask = PhysicalStructuralMask.load_from_csv(config.register_path)
    register_hash = mask.register_sha256
    logger.info("Loaded structural mask with %d registered edges (SHA-256: %s).",
                len(mask.all_records()), register_hash[:16])

    # 8. Execute Gating: Configuration A (G0 Disabled)
    logger.info("Executing Configuration A (G0 Disabled)...")
    pipe_a = GatingPipeline(
        GatingConfig(
            min_delay_s=config.gating_min_delay_s,
            max_delay_s=config.gating_max_delay_s,
            require_positive_dt=config.gating_require_positive_dt,
            require_same_modality=config.gating_require_same_modality,
            structural_mask=None,       # G0 Disabled
            allow_unknown=True,
        )
    )
    acc_a, rej_a = pipe_a.apply(candidates, event_index=event_index)
    logger.info("Config A: %d accepted, %d rejected.", len(acc_a), len(rej_a))

    # 9. Execute Gating: Configuration B (G0 Enabled)
    logger.info("Executing Configuration B (G0 Enabled, allow_unknown=%s)...",
                config.allow_unknown_config_b)
    pipe_b = GatingPipeline(
        GatingConfig(
            min_delay_s=config.gating_min_delay_s,
            max_delay_s=config.gating_max_delay_s,
            require_positive_dt=config.gating_require_positive_dt,
            require_same_modality=config.gating_require_same_modality,
            structural_mask=mask,       # G0 Enabled
            allow_unknown=config.allow_unknown_config_b,
        )
    )
    acc_b, rej_b = pipe_b.apply(candidates, event_index=event_index)
    logger.info("Config B: %d accepted, %d rejected.", len(acc_b), len(rej_b))

    # 10. Granular per-candidate tracking and comparison
    # Map rejected observations for fast lookup
    rej_a_map: Dict[str, PropagationObservation] = {o.obs_id: o for o in rej_a}
    rej_b_map: Dict[str, PropagationObservation] = {o.obs_id: o for o in rej_b}
    acc_a_set: Set[str] = {o.obs_id for o in acc_a}
    acc_b_set: Set[str] = {o.obs_id for o in acc_b}

    comparison_records: List[Dict[str, Any]] = []

    # Count breakdown for Config B
    b_rejected_g0_disallowed = 0
    b_rejected_g0_unknown = 0
    b_rejected_g1 = 0
    b_rejected_other = 0

    # Retained/removed documentary relationships
    doc_retained = 0
    doc_removed = 0
    inf_retained = 0
    inf_removed = 0

    # Rejection reason tallies
    rejection_reasons_a: Dict[str, int] = {}
    rejection_reasons_b: Dict[str, int] = {}

    # Per-attack-interval tracking
    attack_intervals: Dict[str, A4A5Attack] = SWAT_A4A5_ATTACK_SCHEDULE
    per_attack_counts: Dict[str, Dict[str, int]] = {
        aid: {
            "initial_candidates": 0,
            "config_a_accepted": 0,
            "config_a_rejected": 0,
            "config_b_accepted": 0,
            "config_b_rejected": 0,
            "config_b_g0_rejected": 0,
            "config_b_g0_disallowed": 0,
            "config_b_g0_unknown": 0,
        }
        for aid in attack_intervals
    }
    per_attack_counts["outside_attacks"] = {
        "initial_candidates": 0,
        "config_a_accepted": 0,
        "config_a_rejected": 0,
        "config_b_accepted": 0,
        "config_b_rejected": 0,
        "config_b_g0_rejected": 0,
        "config_b_g0_disallowed": 0,
        "config_b_g0_unknown": 0,
    }

    for obs in candidates:
        src_ev = event_index.get(obs.source_event)
        tgt_ev = event_index.get(obs.target_event)
        src_time = src_ev.onset_time if src_ev else None
        tgt_time = tgt_ev.onset_time if tgt_ev else None

        # Determine overlapping attack intervals (closed interval [start, end])
        overlapping_attacks: List[str] = []
        if src_time:
            for aid, atk in attack_intervals.items():
                if atk.start_utc <= src_time <= atk.end_utc:
                    overlapping_attacks.append(aid)

        assigned_attack = overlapping_attacks[0] if overlapping_attacks else "outside_attacks"

        # Register metadata lookup
        reg_record = mask.get_record(obs.source_machine, obs.target_machine)
        mask_status = mask.get_status(obs.source_machine, obs.target_machine)
        doc_status = reg_record.documentary_status if reg_record else "UNREGISTERED"
        base_ident = reg_record.baseline_identifiability if reg_record else "UNREGISTERED_UNKNOWN"
        dyn_val = reg_record.dynamically_validated if reg_record else False

        # Config A outcome
        in_acc_a = obs.obs_id in acc_a_set
        rej_a_obs = rej_a_map.get(obs.obs_id)
        decision_a = "accepted" if in_acc_a else "rejected"
        reason_a = rej_a_obs.reject_reason if rej_a_obs else None
        gate_a = "ALL_PASSED" if in_acc_a else _extract_gate_name(reason_a)

        if reason_a:
            rejection_reasons_a[reason_a] = rejection_reasons_a.get(reason_a, 0) + 1

        # Config B outcome
        in_acc_b = obs.obs_id in acc_b_set
        rej_b_obs = rej_b_map.get(obs.obs_id)
        decision_b = "accepted" if in_acc_b else "rejected"
        reason_b = rej_b_obs.reject_reason if rej_b_obs else None
        gate_b = "ALL_PASSED" if in_acc_b else _extract_gate_name(reason_b)

        if reason_b:
            rejection_reasons_b[reason_b] = rejection_reasons_b.get(reason_b, 0) + 1

        # Classify Config B rejection
        if not in_acc_b:
            if "status=0" in (reason_b or "") or "Prohibited" in (reason_b or ""):
                b_rejected_g0_disallowed += 1
                per_attack_counts[assigned_attack]["config_b_g0_disallowed"] += 1
                per_attack_counts[assigned_attack]["config_b_g0_rejected"] += 1
            elif "status=?" in (reason_b or "") or "conservative policy" in (reason_b or ""):
                b_rejected_g0_unknown += 1
                per_attack_counts[assigned_attack]["config_b_g0_unknown"] += 1
                per_attack_counts[assigned_attack]["config_b_g0_rejected"] += 1
            elif "outside feasible window" in (reason_b or ""):
                b_rejected_g1 += 1
            else:
                b_rejected_other += 1

        # Relationship retention audit
        if doc_status == "DOCUMENTED":
            if in_acc_b:
                doc_retained += 1
            else:
                doc_removed += 1
        elif doc_status == "INFERRED":
            if in_acc_b:
                inf_retained += 1
            else:
                inf_removed += 1

        # Update per-attack counters
        per_attack_counts[assigned_attack]["initial_candidates"] += 1
        if in_acc_a:
            per_attack_counts[assigned_attack]["config_a_accepted"] += 1
        else:
            per_attack_counts[assigned_attack]["config_a_rejected"] += 1

        if in_acc_b:
            per_attack_counts[assigned_attack]["config_b_accepted"] += 1
        else:
            per_attack_counts[assigned_attack]["config_b_rejected"] += 1

        comparison_records.append({
            "obs_id": obs.obs_id,
            "source_channel": obs.source_machine,
            "target_channel": obs.target_machine,
            "delta_t_s": obs.delta_t_s,
            "source_onset_utc": src_time.isoformat() if src_time else "",
            "target_onset_utc": tgt_time.isoformat() if tgt_time else "",
            "attack_interval": assigned_attack,
            "documentary_status": doc_status,
            "physical_mask_status": mask_status.value,
            "baseline_identifiability": base_ident,
            "dynamically_validated": dyn_val,
            "config_a_decision": decision_a,
            "config_a_gate": gate_a,
            "config_a_reject_reason": reason_a or "NONE",
            "config_b_decision": decision_b,
            "config_b_gate": gate_b,
            "config_b_reject_reason": reason_b or "NONE",
        })

    total_candidates = len(candidates)
    accepted_a = len(acc_a)
    accepted_b = len(acc_b)

    abs_reduction = accepted_a - accepted_b
    pct_reduction = (
        round((abs_reduction / accepted_a) * 100.0, 2)
        if accepted_a > 0
        else "N/A"
    )

    elapsed_s = round(time.perf_counter() - start_time, 2)

    # 11. Compile Top-Level Metrics
    metrics_summary = {
        "milestone": "Stage 2 Candidate-Edge Gating Evaluation with G0_STRUCTURAL_MASK",
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "runtime_seconds": elapsed_s,
        "input_dataset": {
            "path": str(config.data_path),
            "rows": len(df),
            "columns": len(df.columns),
            "total_windows": len(all_windows),
            "baseline_windows": config.baseline_end_idx - config.baseline_start_idx,
            "eval_windows": config.eval_end_idx - config.eval_start_idx,
        },
        "structural_register": {
            "path": str(mask.register_path) if mask.register_path else "default",
            "sha256": register_hash,
            "total_registered_edges": len(mask.all_records()),
        },
        "events_summary": {
            "total_discrete_events": total_events,
            "active_event_channels_count": len(events_by_channel),
            "channel_counts": channel_event_counts,
        },
        "candidate_counts": {
            "initial_matched_candidates": total_candidates,
            "config_a_g0_disabled": {
                "g0_applied": False,
                "entering_g1": total_candidates,
                "accepted_surviving_all_gates": accepted_a,
                "rejected_total": len(rej_a),
            },
            "config_b_g0_enabled": {
                "g0_applied": True,
                "rejected_at_g0_total": b_rejected_g0_disallowed + b_rejected_g0_unknown,
                "rejected_at_g0_prohibited": b_rejected_g0_disallowed,
                "rejected_at_g0_unknown": b_rejected_g0_unknown,
                "entering_g1": total_candidates - (b_rejected_g0_disallowed + b_rejected_g0_unknown),
                "rejected_at_g1": b_rejected_g1,
                "rejected_at_subsequent_gates": b_rejected_other,
                "accepted_surviving_all_gates": accepted_b,
                "rejected_total": len(rej_b),
            },
            "comparison": {
                "absolute_candidate_reduction": abs_reduction,
                "percentage_candidate_reduction": pct_reduction,
                "prohibited_edges_removed_count": b_rejected_g0_disallowed,
                "unverified_unknown_edges_removed_count": b_rejected_g0_unknown,
                "documented_relationships_retained_count": doc_retained,
                "documented_relationships_removed_count": doc_removed,
                "inferred_relationships_retained_count": inf_retained,
                "inferred_relationships_removed_count": inf_removed,
            },
        },
        "per_attack_interval_summary": per_attack_counts,
    }

    # 12. Save machine-readable outputs
    logger.info("Saving experiment outputs to %s...", config.output_dir)

    # A. Metrics JSON
    with open(config.output_dir / "g0_off_vs_on_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics_summary, f, indent=2)

    # B. Evaluation Config JSON
    with open(config.output_dir / "evaluation_config.json", "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)

    # C. Candidate Edge Comparison CSV
    df_comp = pd.DataFrame(comparison_records)
    df_comp.to_csv(config.output_dir / "candidate_edge_comparison.csv", index=False)

    # D. Per-Attack-Interval Metrics CSV
    interval_rows = []
    for aid, cnts in per_attack_counts.items():
        atk = attack_intervals.get(aid)
        target_tags = ";".join(atk.target_tags) if atk else "N/A"
        desc = atk.action if atk else "Events observed outside documented attack intervals"
        a_acc = cnts["config_a_accepted"]
        b_acc = cnts["config_b_accepted"]
        red_abs = a_acc - b_acc
        red_pct = round((red_abs / a_acc) * 100.0, 2) if a_acc > 0 else "N/A"

        interval_rows.append({
            "attack_id": aid,
            "target_channels": target_tags,
            "attack_description": desc,
            "initial_candidates": cnts["initial_candidates"],
            "config_a_accepted": a_acc,
            "config_a_rejected": cnts["config_a_rejected"],
            "config_b_accepted": b_acc,
            "config_b_rejected": cnts["config_b_rejected"],
            "config_b_g0_rejected": cnts["config_b_g0_rejected"],
            "config_b_g0_prohibited": cnts["config_b_g0_disallowed"],
            "config_b_g0_unknown": cnts["config_b_g0_unknown"],
            "absolute_reduction": red_abs,
            "percentage_reduction": red_pct,
        })
    df_intervals = pd.DataFrame(interval_rows)
    df_intervals.to_csv(config.output_dir / "per_attack_interval_metrics.csv", index=False)

    # E. Rejection Reason Summary CSV
    all_reasons = set(rejection_reasons_a.keys()) | set(rejection_reasons_b.keys())
    reason_rows = [
        {
            "rejection_reason": r,
            "gate": _extract_gate_name(r),
            "config_a_count": rejection_reasons_a.get(r, 0),
            "config_b_count": rejection_reasons_b.get(r, 0),
        }
        for r in sorted(all_reasons)
    ]
    df_reasons = pd.DataFrame(reason_rows)
    df_reasons.to_csv(config.output_dir / "rejection_reason_summary.csv", index=False)

    logger.info("G0 Paired Evaluation finished in %.2fs.", elapsed_s)
    return metrics_summary


def _extract_gate_name(reason: Optional[str]) -> str:
    """Extract gate name from human-readable reject reason."""
    if not reason:
        return "UNKNOWN"
    if "physical structural mask" in reason or "conservative policy" in reason:
        return "G0_STRUCTURAL_MASK"
    if "outside feasible window" in reason:
        return "G1_DELAY_FEASIBILITY"
    if "target did not follow source" in reason:
        return "G2_ORDERING"
    if "direction_consistency" in reason:
        return "G3_DIRECTION_CONSISTENCY"
    if "health_score" in reason:
        return "G4_HEALTH_CONSISTENCY"
    if "modality mismatch" in reason:
        return "G5_RELATIONSHIP_CONSISTENCY"
    return "UNKNOWN_GATE"


def main() -> None:
    parser = argparse.ArgumentParser(description="TCMIM Stage 2 G0 Evaluation Runner")
    parser.add_argument(
        "--data-path",
        type=Path,
        default=_project_root / "data" / "raw" / "SWAT_A4_A5_JULY_2019" / "SWaT_dataset_Jul 19 v2.xlsx",
        help="Path to SWaT A4/A5 raw telemetry Excel workbook",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_project_root / "experiments" / "results" / "swat_a4a5_g0_evaluation",
        help="Directory to save evaluation artifacts",
    )
    parser.add_argument(
        "--register-path",
        type=Path,
        default=None,
        help="Path to physical_connectivity_register.csv (defaults to project location)",
    )
    args = parser.parse_args()

    cfg = EvaluationConfig(
        data_path=args.data_path,
        output_dir=args.output_dir,
        register_path=args.register_path,
    )
    summary = run_g0_paired_evaluation(cfg)
    print("\n=== Stage 2 G0 Evaluation Complete ===")
    print(f"Total candidates: {summary['candidate_counts']['initial_matched_candidates']}")
    print(f"Config A (G0 OFF) Accepted: {summary['candidate_counts']['config_a_g0_disabled']['accepted_surviving_all_gates']}")
    print(f"Config B (G0 ON)  Accepted: {summary['candidate_counts']['config_b_g0_enabled']['accepted_surviving_all_gates']}")
    print(f"Candidate Reduction: {summary['candidate_counts']['comparison']['percentage_candidate_reduction']}%")


if __name__ == "__main__":
    main()
