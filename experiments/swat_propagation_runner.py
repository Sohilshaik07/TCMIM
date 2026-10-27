"""
experiments/swat_propagation_runner.py
=======================================
Reproducible SWaT Anomaly Detection and Stage 2 Propagation Experiment Runner.

Project:
  Temporal Cross-Machine Influence Modelling and Cascade Risk Estimation (TCMIM)
  for Early Failure Propagation in Interconnected Industrial Machines.

SCIENTIFIC INTEGRITY AND CONTRACTUAL BOUNDARIES
-----------------------------------------------
1. REAL DATA INTEGRITY:
   - Designed strictly for the Secure Water Treatment (SWaT) physical testbed dataset
     (iTrust, Singapore University of Technology and Design).
   - If the real SWaT dataset is absent, execution halts with an actionable error.
     It NEVER downloads without authorization, invents data, or reports synthetic
     fixtures as real-world industrial findings.
2. LOGICAL PROCESS ENTITIES != INDEPENDENT ROTATING MACHINES:
   - SWaT stages P1–P6 are logical process sections in a continuous fluid pipeline
     (e.g., Raw Water, Chemical Dosing, Ultrafiltration, Dechlorination, Reverse Osmosis,
     Distribution). They are hydraulically and chemically coupled via physical pipes and
     intermediate tanks, NOT six mechanically independent rotating machines.
3. TEMPORAL PRECEDENCE != PHYSICAL CAUSALITY:
   - An observed alert order (Stage Pi -> Stage Pj with Δt > 0) indicates empirical
     sequential detection across thresholds, NOT mathematical proof of physical causality.
4. ESTIMATED DETECTION DELAY != FLUID TRANSIT TIME:
   - Inferred detection delay represents alert arrival offset, NOT hydrodynamic fluid
     transit time (which depends on physical pipe volumes and volumetric flow rates V/Q).
5. STRICT GROUND-TRUTH ISOLATION:
   - Ground-truth attack labels ('Normal' vs 'Attack') are strictly segregated.
   - Labels are NEVER passed to WindowBuilder, FeatureExtractor, AnomalyDetector,
     or Stage2Pipeline.
   - Window-level label alignment (via 'any' and 'majority' overlap methods) is conducted
     strictly POST-PREDICTION for evaluation reporting.
6. ACTUATOR STATE ENCODING:
   - Feature extraction explicitly uses SWAT_ACTUATOR_STATE_MAP (1.0=OFF/0, 2.0=ON/1)
     to ensure discrete actuator transitions are never lost or conflated with continuous signals.
7. THREE SCIENTIFIC EVALUATION PROTOCOLS:
   - Protocol A (Recommended Primary): Train baseline strictly on normal operational
     telemetry (SWaT_Dataset_Normal_v1.csv); evaluate on attack data (SWaT_Dataset_Attack_v0.csv).
   - Protocol B (Autonomous Chronological): Train baseline on initial chronological
     fraction (e.g. 20%) of attack telemetry without consulting labels; evaluate remaining.
   - Protocol C (Supervised Comparison): Train baseline on label-filtered 'Normal' samples
     from attack telemetry. Clearly tagged as supervised comparison.

OUTPUT ARTIFACTS
----------------
Outputs are saved to experiments/results/swat/:
- swat_runner_results.json (or swat_experiment_<protocol>_<run_id>.json)
- SWaT_Experiment_Report.md (or swat_experiment_<protocol>_<run_id>.md)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

# Ensure 'src' is in python path
_project_root = Path(__file__).resolve().parent.parent
_src_dir = _project_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from tcmim.analysis.orchestrator import PipelineResult, Stage2Pipeline
from tcmim.config import (
    EdgeLifecycleConfig,
    MatchingConfig,
)
from tcmim.cri.calculator import CRIConfig
from tcmim.gating.gates import GatingConfig
from tcmim.graph.dynamic_graph import GraphConfig
from tcmim.graph.path_finder import PathFinderConfig, PropagationPath
from tcmim.propagation.delay import DelayEstimatorConfig
from tcmim.propagation.occ_ccd import OCCCDConfig
from tcmim.data.swat import (
    SWAT_ACTUATOR_STATE_MAP,
    SWAT_MODALITY_MAP,
    SWAT_STAGE_MAP,
    SWAT_TAG_REGISTRY,
    SWaTProcessStage,
    align_swat_labels_to_windows,
    analyze_sampling_continuity,
    evaluate_swat_window_predictions,
    infer_sampling_frequency,
    load_swat_dataframe,
    partition_swat_by_stage,
    verify_no_ground_truth_leakage,
)
from tcmim.data.windower import WindowBuilder, WindowedData
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import IsolationForestAnomalyDetector
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.schemas import (
    AnomalyRecord,
    EdgeRecord,
    EdgeState,
    EventRecord,
    Modality,
    PropagationObservation,
    Provenance,
)

logger = logging.getLogger("swat_runner")


# ---------------------------------------------------------------------------
# Configuration & Result Schemas
# ---------------------------------------------------------------------------

@dataclass
class SWaTExperimentConfig:
    """Configuration parameters for a reproducible SWaT experiment run."""
    protocol: Literal["protocol_a", "protocol_b", "protocol_c"] = "protocol_a"
    normal_csv: Optional[Union[str, Path]] = None
    attack_csv: Optional[Union[str, Path]] = None
    data_dir: Optional[Union[str, Path]] = None
    window_seconds: float = 60.0
    overlap_frac: float = 0.0
    baseline_frac: float = 0.2
    normal_baseline_frac: float = 0.9
    contamination: float = 0.05
    random_seed: int = 42
    min_baseline_windows: int = 2
    min_burst_windows: int = 1
    max_event_gap_s: float = 120.0
    max_rows: Optional[int] = None
    output_dir: Union[str, Path] = Path("experiments/results/swat")
    run_id: Optional[str] = None
    stage_filter: Optional[List[str]] = None
    provenance: Provenance = Provenance.PUBLIC_DATASET

    # Stage 2 Orchestration parameters
    stage2_matching_min_delay_s: float = 1.0
    stage2_matching_max_delay_s: float = 600.0
    stage2_estimator: str = "median"


@dataclass
class StageEvaluationResult:
    """Per-stage anomaly detection and post-prediction evaluation metrics."""
    stage_name: str
    n_windows: int
    n_anomalies: int
    n_events: int
    any_metrics: Dict[str, Any]
    majority_metrics: Dict[str, Any]
    sampling_hz: float
    feature_count: int
    excluded_features_count: int
    baseline_window_count: int


@dataclass
class SWaTExperimentResult:
    """Complete structured output from a SWaT experiment run."""
    run_id: str
    protocol: str
    timestamp_utc: str
    provenance: str
    dataset_metadata: Dict[str, Any]
    config: Dict[str, Any]
    stage_results: Dict[str, StageEvaluationResult]
    overall_evaluation: Dict[str, Any]
    stage2_summary: Dict[str, Any]
    scientific_limitations: List[str]
    warnings: List[str]
    output_artifacts: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Path Resolution Helper
# ---------------------------------------------------------------------------

def resolve_swat_dataset_paths(
    protocol: str = "protocol_a",
    normal_csv: Optional[Union[str, Path]] = None,
    attack_csv: Optional[Union[str, Path]] = None,
    data_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Path]:
    """Resolve SWaT dataset CSV file paths on disk.

    Raises FileNotFoundError with actionable instructions if files are missing.
    """
    env_dir = os.environ.get("TCMIM_SWAT_DATA_PATH")
    dir_candidates = [
        Path(data_dir) if data_dir else None,
        Path(env_dir) if env_dir and Path(env_dir).is_dir() else None,
        Path("data/raw"),
        Path("data"),
        Path("."),
        Path(".."),
        _project_root / "data/raw",
        _project_root,
    ]

    normal_names = ["SWaT_Dataset_Normal_v1.csv", "SWaT_Dataset_Normal_v0.csv", "Normal.csv"]
    attack_names = ["SWaT_Dataset_Attack_v0.csv", "Attack.csv", "SWaT.csv"]

    resolved: Dict[str, Path] = {}

    # 1. Resolve Normal CSV if needed
    if protocol == "protocol_a":
        if normal_csv and Path(normal_csv).is_file():
            resolved["normal_csv"] = Path(normal_csv).resolve()
        elif env_dir and Path(env_dir).is_file() and "normal" in Path(env_dir).name.lower():
            resolved["normal_csv"] = Path(env_dir).resolve()
        else:
            for d in dir_candidates:
                if d and d.exists() and d.is_dir():
                    for name in normal_names:
                        cand = d / name
                        if cand.is_file():
                            resolved["normal_csv"] = cand.resolve()
                            break
                    if "normal_csv" in resolved:
                        break

    # 2. Resolve Attack CSV (needed for all protocols)
    if attack_csv and Path(attack_csv).is_file():
        resolved["attack_csv"] = Path(attack_csv).resolve()
    elif env_dir and Path(env_dir).is_file() and "attack" in Path(env_dir).name.lower():
        resolved["attack_csv"] = Path(env_dir).resolve()
    elif env_dir and Path(env_dir).is_file() and protocol in ("protocol_b", "protocol_c"):
        resolved["attack_csv"] = Path(env_dir).resolve()
    else:
        for d in dir_candidates:
            if d and d.exists() and d.is_dir():
                for name in attack_names:
                    cand = d / name
                    if cand.is_file():
                        resolved["attack_csv"] = cand.resolve()
                        break
                if "attack_csv" in resolved:
                    break

    # Validate based on requested protocol
    missing = []
    if protocol == "protocol_a":
        if "normal_csv" not in resolved:
            missing.append("Normal CSV ('SWaT_Dataset_Normal_v1.csv')")
        if "attack_csv" not in resolved:
            missing.append("Attack CSV ('SWaT_Dataset_Attack_v0.csv')")
    elif protocol in ("protocol_b", "protocol_c"):
        if "attack_csv" not in resolved:
            missing.append("Attack CSV ('SWaT_Dataset_Attack_v0.csv')")

    if missing:
        error_msg = (
            f"SWaT dataset files missing for {protocol.upper()}: {', '.join(missing)}.\n"
            "The SWaT dataset is restricted under academic license by iTrust (SUTD).\n"
            "Actionable Instructions:\n"
            "  1. Place 'SWaT_Dataset_Normal_v1.csv' and 'SWaT_Dataset_Attack_v0.csv' in 'data/raw/'.\n"
            "  2. Or set the environment variable:\n"
            "     PowerShell: $env:TCMIM_SWAT_DATA_PATH = 'C:\\path\\to\\SWaT_folder'\n"
            "     Bash:       export TCMIM_SWAT_DATA_PATH='/path/to/SWaT_folder'\n"
            "  3. Or pass explicit CLI paths:\n"
            "     python experiments/swat_propagation_runner.py --normal-csv <path> --attack-csv <path>\n"
            "Per TCMIM integrity policy, synthetic fixtures are never represented as real SWaT findings."
        )
        raise FileNotFoundError(error_msg)

    return resolved


# ---------------------------------------------------------------------------
# Custom JSON Serializer for Numpy and Dataclasses
# ---------------------------------------------------------------------------

class TCMIMJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.float32, np.float64)):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, (np.int32, np.int64)):
            return int(obj)
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "value"):  # Enum
            return obj.value
        if hasattr(obj, "__dict__"):
            return asdict(obj) if hasattr(obj, "__dataclass_fields__") else obj.__dict__
        if isinstance(obj, float) and math.isnan(obj):
            return None
        return super().default(obj)


# ---------------------------------------------------------------------------
# Core Experiment Execution Pipeline
# ---------------------------------------------------------------------------

def run_swat_experiment(config: SWaTExperimentConfig) -> SWaTExperimentResult:
    """Execute the full SWaT experiment pipeline according to the configured protocol.

    Parameters
    ----------
    config : SWaTExperimentConfig defining dataset paths, protocol, and parameters.

    Returns
    -------
    SWaTExperimentResult containing all metrics, Stage 2 graph states, and audit trails.
    """
    run_timestamp = datetime.now(timezone.utc)
    run_id = config.run_id or f"swat_{config.protocol}_{run_timestamp.strftime('%Y%m%d_%H%M%S')}"
    warnings: List[str] = []

    logger.info("Starting SWaT experiment run: %s (Protocol: %s)", run_id, config.protocol)

    # 1. Resolve dataset file paths
    resolved_paths = resolve_swat_dataset_paths(
        protocol=config.protocol,
        normal_csv=config.normal_csv,
        attack_csv=config.attack_csv,
        data_dir=config.data_dir,
    )

    # 2. Ingest Data according to Protocol
    # Protocol A: Normal CSV for baseline, Attack CSV for evaluation
    # Protocol B: Attack CSV only; chronological split for baseline and evaluation
    # Protocol C: Attack CSV only; label-informed filtering for baseline
    normal_df: Optional[pd.DataFrame] = None
    attack_df: pd.DataFrame
    attack_labels: Optional[pd.Series] = None

    if config.protocol == "protocol_a":
        logger.info("Protocol A: Ingesting Normal telemetry from %s", resolved_paths["normal_csv"])
        normal_df, _ = load_swat_dataframe(
            resolved_paths["normal_csv"],
            max_rows=config.max_rows,
            sort_timestamps=True,
        )
        logger.info("Protocol A: Ingesting Attack telemetry from %s", resolved_paths["attack_csv"])
        attack_df, attack_labels = load_swat_dataframe(
            resolved_paths["attack_csv"],
            max_rows=config.max_rows,
            sort_timestamps=True,
        )
    elif config.protocol in ("protocol_b", "protocol_c"):
        logger.info(
            "Protocol %s: Ingesting Attack telemetry from %s",
            config.protocol[-1].upper(),
            resolved_paths["attack_csv"],
        )
        attack_df, attack_labels = load_swat_dataframe(
            resolved_paths["attack_csv"],
            max_rows=config.max_rows,
            sort_timestamps=True,
        )
    else:
        raise ValueError(f"Unrecognized experimental protocol: {config.protocol}")

    # 3. Ground-Truth Isolation Verification (Pre-extraction)
    verify_no_ground_truth_leakage(df=attack_df)
    if normal_df is not None:
        verify_no_ground_truth_leakage(df=normal_df)

    # Analyze sampling continuity on evaluation data
    continuity_report = analyze_sampling_continuity(attack_df.index)
    inferred_hz = continuity_report.inferred_frequency_hz
    if continuity_report.gap_count > 0:
        warnings.append(
            f"Detected {continuity_report.gap_count} timestamp gap(s) exceeding "
            f"1.5x median interval ({continuity_report.median_interval_s:.2f}s)."
        )

    dataset_metadata = {
        "attack_csv": str(resolved_paths.get("attack_csv")),
        "normal_csv": str(resolved_paths.get("normal_csv")),
        "attack_rows": len(attack_df),
        "attack_start_time": attack_df.index[0].isoformat() if len(attack_df) > 0 else None,
        "attack_end_time": attack_df.index[-1].isoformat() if len(attack_df) > 0 else None,
        "sampling_median_interval_s": continuity_report.median_interval_s,
        "inferred_sampling_hz": inferred_hz,
        "gaps_count": continuity_report.gap_count,
        "duplicates_count": continuity_report.duplicate_count,
        "has_labels": attack_labels is not None,
    }

    # 4. Partition by verified physical testbed stages (P1 to P6)
    attack_stages = partition_swat_by_stage(attack_df)
    normal_stages = partition_swat_by_stage(normal_df) if normal_df is not None else {}

    # Filter stages if requested
    stage_names = list(attack_stages.keys())
    if config.stage_filter:
        stage_names = [s for s in stage_names if s in config.stage_filter]

    logger.info("Processing %d logical process stages: %s", len(stage_names), stage_names)

    # 5. Initialize WindowBuilder, FeatureExtractor, Detector, and EventAdapter
    window_builder = WindowBuilder(
        window_seconds=config.window_seconds,
        overlap_frac=config.overlap_frac,
    )

    # CRITICAL: FeatureExtractor constructed with explicit SWaT actuator state mapping
    feature_extractor = FeatureExtractor(
        sampling_rate_hz=inferred_hz if inferred_hz > 0 else 1.0,
        channel_modality_map=SWAT_MODALITY_MAP,
        channel_state_map=SWAT_ACTUATOR_STATE_MAP,
    )

    adapter = AnomalyToEventAdapter(
        EventAdapterConfig(
            min_burst_windows=config.min_burst_windows,
            max_gap_s=config.max_event_gap_s,
            score_aggregation="peak",
        )
    )

    stage_results: Dict[str, StageEvaluationResult] = {}
    events_by_machine: Dict[str, List[EventRecord]] = {}
    all_stage_predictions: List[AnomalyRecord] = []
    all_stage_aligned_any: List[float] = []
    all_stage_aligned_majority: List[float] = []

    # 6. Execute Stage 1 (Feature Extraction -> Detection -> Event Adaptation) per stage
    for stage_name in stage_names:
        logger.info("--- Processing stage: %s ---", stage_name)
        s_attack_df = attack_stages[stage_name]
        attack_windows = window_builder.build(
            s_attack_df,
            machine_id=stage_name,
            provenance=config.provenance,
        )

        if len(attack_windows) < 2:
            warnings.append(f"Stage {stage_name} produced insufficient attack windows ({len(attack_windows)}). Skipping.")
            continue

        attack_samples = feature_extractor.extract_all(attack_windows)
        verify_no_ground_truth_leakage(samples=attack_samples)

        # Baseline fitting strategy per protocol
        detector = IsolationForestAnomalyDetector(
            baseline_frac=config.baseline_frac,
            contamination=config.contamination,
            random_state=config.random_seed,
            min_baseline_windows=config.min_baseline_windows,
        )

        predictions: List[AnomalyRecord] = []
        baseline_windows_count = 0

        try:
            if config.protocol == "protocol_a":
                # Protocol A: Baseline fitted on normal operational data
                s_normal_df = normal_stages.get(stage_name)
                if s_normal_df is None or len(s_normal_df) == 0:
                    warnings.append(f"Stage {stage_name} missing normal data; skipping.")
                    continue

                normal_windows = window_builder.build(
                    s_normal_df,
                    machine_id=stage_name,
                    provenance=config.provenance,
                )
                normal_samples = feature_extractor.extract_all(normal_windows)

                if len(normal_samples) < config.min_baseline_windows:
                    warnings.append(
                        f"Stage {stage_name} has insufficient normal windows "
                        f"({len(normal_samples)} < {config.min_baseline_windows}). Skipping."
                    )
                    continue

                norm_base_frac = min(0.99, max(0.01, config.normal_baseline_frac))
                detector = IsolationForestAnomalyDetector(
                    baseline_frac=norm_base_frac,
                    contamination=config.contamination,
                    random_state=config.random_seed,
                    min_baseline_windows=config.min_baseline_windows,
                )
                detector.fit(normal_samples)
                predictions = detector.predict_score(attack_samples)
                baseline_windows_count = detector.split_info_.n_baseline if detector.split_info_ else len(normal_samples)

            elif config.protocol == "protocol_b":
                # Protocol B: Chronological baseline on initial fraction of attack data
                detector = IsolationForestAnomalyDetector(
                    baseline_frac=config.baseline_frac,
                    contamination=config.contamination,
                    random_state=config.random_seed,
                    min_baseline_windows=config.min_baseline_windows,
                )
                predictions, _ = detector.fit_and_score(attack_samples, score_baseline=True)
                baseline_windows_count = detector.split_info_.n_baseline if detector.split_info_ else 0

            elif config.protocol == "protocol_c":
                # Protocol C: Supervised comparison (normal-filtered timestamps from attack file)
                # Find normal window indices using labels strictly for baseline selection
                if attack_labels is None:
                    raise ValueError("Protocol C requires labels to identify baseline samples.")
                aligned_labels_temp = align_swat_labels_to_windows(attack_labels, attack_windows, method="any")
                normal_indices = [i for i, val in enumerate(aligned_labels_temp) if val == 0.0]
                if len(normal_indices) < config.min_baseline_windows:
                    warnings.append(f"Stage {stage_name} has insufficient clean normal windows ({len(normal_indices)}) in attack CSV.")
                    continue
                normal_subset = [attack_samples[i] for i in normal_indices]

                norm_base_frac = min(0.99, max(0.01, config.normal_baseline_frac))
                detector = IsolationForestAnomalyDetector(
                    baseline_frac=norm_base_frac,
                    contamination=config.contamination,
                    random_state=config.random_seed,
                    min_baseline_windows=config.min_baseline_windows,
                )
                detector.fit(normal_subset)
                predictions = detector.predict_score(attack_samples)
                baseline_windows_count = detector.split_info_.n_baseline if detector.split_info_ else len(normal_subset)

        except ValueError as err:
            warn_msg = f"Stage {stage_name} detector fitting failed: {err}. Skipping stage."
            warnings.append(warn_msg)
            logger.warning(warn_msg)
            continue

        # Audit detector and predictions for leakage
        verify_no_ground_truth_leakage(detector=detector)
        verify_no_ground_truth_leakage(records=predictions)

        # Event generation
        events = adapter.adapt(predictions, machine_id=stage_name)
        events_by_machine[stage_name] = events

        # Post-prediction Evaluation against isolated labels
        any_metrics: Dict[str, Any] = {}
        maj_metrics: Dict[str, Any] = {}
        if attack_labels is not None:
            aligned_any = align_swat_labels_to_windows(attack_labels, attack_windows, method="any")
            aligned_maj = align_swat_labels_to_windows(attack_labels, attack_windows, method="majority")

            any_metrics = evaluate_swat_window_predictions(aligned_any, predictions)
            maj_metrics = evaluate_swat_window_predictions(aligned_maj, predictions)

            all_stage_predictions.extend(predictions)
            all_stage_aligned_any.extend(aligned_any)
            all_stage_aligned_majority.extend(aligned_maj)

        n_anom = sum(1 for p in predictions if p.is_anomaly)
        stage_results[stage_name] = StageEvaluationResult(
            stage_name=stage_name,
            n_windows=len(attack_windows),
            n_anomalies=n_anom,
            n_events=len(events),
            any_metrics=any_metrics,
            majority_metrics=maj_metrics,
            sampling_hz=inferred_hz,
            feature_count=len(detector.feature_names_),
            excluded_features_count=len(detector.excluded_features_),
            baseline_window_count=baseline_windows_count,
        )

    # 7. Overall Stage 1 Evaluation
    overall_evaluation: Dict[str, Any] = {}
    if all_stage_predictions and attack_labels is not None:
        overall_evaluation = {
            "pooled_any": evaluate_swat_window_predictions(
                np.array(all_stage_aligned_any), all_stage_predictions
            ),
            "pooled_majority": evaluate_swat_window_predictions(
                np.array(all_stage_aligned_majority), all_stage_predictions
            ),
        }

    # 8. Stage 2 Multi-Stage Propagation & Cascade Risk Index (CRI)
    logger.info("Executing Stage 2 propagation pipeline across stages...")
    pipeline = Stage2Pipeline(
        matching_config=MatchingConfig(
            min_delay_s=config.stage2_matching_min_delay_s,
            max_delay_s=config.stage2_matching_max_delay_s,
        ),
        gating_config=GatingConfig(),
        occcd_config=OCCCDConfig(),
        edge_config=EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=3,
            stable_threshold=10,
        ),
        graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.001),
        cri_config=CRIConfig(),
        delay_config=DelayEstimatorConfig(estimator=config.stage2_estimator),
    )

    total_events = sum(len(evs) for evs in events_by_machine.values())
    stage2_summary: Dict[str, Any] = {
        "total_events_input": total_events,
        "matched_observations_count": 0,
        "accepted_observations_count": 0,
        "rejected_observations_count": 0,
        "candidate_edges_count": 0,
        "provisional_edges_count": 0,
        "stable_edges_count": 0,
        "paths_count": 0,
        "cri_targets": {},
        "edges_detail": [],
    }

    if total_events > 0:
        eval_time = attack_df.index[-1].to_pydatetime() if len(attack_df) > 0 else run_timestamp
        pipeline_result: PipelineResult = pipeline.run(
            events_by_machine=events_by_machine,
            cycle_timestamp=eval_time,
        )

        # Summarize observations and edges
        candidate_edges = [e for e in pipeline_result.edges if e.state == EdgeState.CANDIDATE]
        provisional_edges = [e for e in pipeline_result.edges if e.state == EdgeState.PROVISIONAL]
        stable_edges = [e for e in pipeline_result.edges if e.state in (EdgeState.CONFIRMED, EdgeState.STABLE)]

        stage2_summary = {
            "total_events_input": total_events,
            "matched_observations_count": len(pipeline_result.matched_observations),
            "accepted_observations_count": pipeline_result.accepted_count,
            "rejected_observations_count": pipeline_result.rejected_count,
            "candidate_edges_count": len(candidate_edges),
            "provisional_edges_count": len(provisional_edges),
            "stable_edges_count": len(stable_edges),
            "paths_count": len(pipeline_result.paths),
            "cri_targets": {
                cri.target_machine: {
                    "cri": cri.cri,
                    "paths_used": cri.paths_used,
                    "contributions": cri.contributions,
                }
                for cri in pipeline_result.cri_records
            },
            "edges_detail": [
                {
                    "source": e.source,
                    "target": e.target,
                    "state": e.state.value,
                    "evidence_count": e.evidence_count,
                    "est_delay_s": e.est_delay_s,
                    "confidence": e.confidence,
                }
                for e in pipeline_result.edges
            ],
            "rejected_reasons": [
                {"source": obs.source_machine, "target": obs.target_machine, "reason": obs.reject_reason}
                for obs in pipeline_result.rejected_observations
            ],
        }
    else:
        logger.info("No events generated across any stage; Stage 2 skipped.")

    # 9. Document Scientific Limitations
    scientific_limitations = [
        "SWaT stages P1–P6 are logical process sections in a single connected water treatment plant, not independent physical rotating machines.",
        "Observed inter-stage alert lags (Δt > 0) reflect empirical sequential detection across thresholds, NOT proof of physical causality.",
        "Estimated delay Δt represents alert arrival offset, NOT hydrodynamic fluid transit time (which requires pipe volume/flow rate V/Q verification).",
        "Cyber-physical attack labels indicate actuation manipulation windows, which may exhibit physical latency before process deviation manifests.",
        "Single-machine or single-testbed datasets cannot validate cross-machine cascade risk models without multi-system empirical deployments.",
    ]

    # 10. Compile and Save Results
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = SWaTExperimentResult(
        run_id=run_id,
        protocol=config.protocol,
        timestamp_utc=run_timestamp.isoformat(),
        provenance=config.provenance.value,
        dataset_metadata=dataset_metadata,
        config={k: (v.value if hasattr(v, "value") else str(v) if isinstance(v, Path) else v) for k, v in asdict(config).items()},
        stage_results=stage_results,
        overall_evaluation=overall_evaluation,
        stage2_summary=stage2_summary,
        scientific_limitations=scientific_limitations,
        warnings=warnings,
    )

    # Save JSON results
    json_path = output_dir / f"{run_id}.json"
    latest_json_path = output_dir / "swat_runner_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2, cls=TCMIMJSONEncoder)
    with open(latest_json_path, "w", encoding="utf-8") as f:
        json.dump(asdict(result), f, indent=2, cls=TCMIMJSONEncoder)

    result.output_artifacts["json"] = str(json_path)
    result.output_artifacts["latest_json"] = str(latest_json_path)

    # Save Markdown report
    md_path = output_dir / f"{run_id}.md"
    latest_md_path = output_dir / "SWaT_Experiment_Report.md"
    md_content = _generate_markdown_report(result)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(latest_md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    result.output_artifacts["report_md"] = str(md_path)
    result.output_artifacts["latest_report_md"] = str(latest_md_path)

    logger.info("SWaT experiment completed successfully. Artifacts saved to %s", output_dir)
    return result


# ---------------------------------------------------------------------------
# Markdown Report Generation
# ---------------------------------------------------------------------------

def _generate_markdown_report(res: SWaTExperimentResult) -> str:
    """Generate comprehensive GitHub-style Markdown report for the SWaT experiment."""
    lines = [
        f"# TCMIM — SWaT Experiment Execution Report",
        f"",
        f"**Run Identifier:** `{res.run_id}`  ",
        f"**Execution Timestamp:** `{res.timestamp_utc}`  ",
        f"**Protocol:** `{res.protocol.upper()}`  ",
        f"**Data Provenance:** `{res.provenance}`  ",
        f"",
        f"---",
        f"",
        f"## 1. Scientific Integrity and Methodological Contract",
        f"",
        f"> [!IMPORTANT]",
        f"> **Logical Process Stages vs Independent Machines:** SWaT stages P1–P6 represent logical",
        f"> functional sections of a continuous water treatment testbed (Raw Water, Chemical Dosing,",
        f"> Ultrafiltration, Dechlorination, Reverse Osmosis, Distribution) connected via pipelines.",
        f"> They are not mechanically independent industrial machines.",
        f"",
        f"> [!NOTE]",
        f"> **Temporal Precedence vs Causality:** Any observed inter-stage alert sequence (Stage Pi -> Stage Pj",
        f"> with Δt > 0) is an empirical sequential detection across statistical thresholds. It does",
        f"> not constitute mathematical or physical proof of causality.",
        f"",
        f"> [!WARNING]",
        f"> **Estimated Delay vs Fluid Transit Time:** The inferred delay Δt reflects alert arrival timing,",
        f"> not hydrodynamic fluid velocity or transit lag through piping (V/Q).",
        f"",
        f"---",
        f"",
        f"## 2. Dataset & Sampling Summary",
        f"",
        f"| Metric | Value |",
        f"| :--- | :--- |",
        f"| **Attack Telemetry File** | `{res.dataset_metadata.get('attack_csv')}` |",
        f"| **Normal Telemetry File** | `{res.dataset_metadata.get('normal_csv')}` |",
        f"| **Attack Observations** | {res.dataset_metadata.get('attack_rows')} rows |",
        f"| **Sampling Rate** | {res.dataset_metadata.get('inferred_sampling_hz', 1.0):.2f} Hz (Median Δt: {res.dataset_metadata.get('sampling_median_interval_s', 1.0):.2f}s) |",
        f"| **Timestamp Gaps (>1.5x Δt)** | {res.dataset_metadata.get('gaps_count', 0)} |",
        f"| **Timestamp Duplicates** | {res.dataset_metadata.get('duplicates_count', 0)} |",
        f"| **Ground-Truth Labels** | {'Present (Segregated)' if res.dataset_metadata.get('has_labels') else 'None'} |",
        f"",
        f"---",
        f"",
        f"## 3. Stage 1: Unsupervised Anomaly Detection & Post-Prediction Evaluation",
        f"",
        f"Features extracted using nominal 60s windows, explicit `SWAT_ACTUATOR_STATE_MAP` (1.0=OFF, 2.0=ON),",
        f"and fitted Isolation Forest detector (contamination={res.config.get('contamination')}, baseline_frac={res.config.get('baseline_frac')}).",
        f"",
        f"### Per-Stage Evaluation Metrics",
        f"",
        f"| Stage | Windows | Anomalies | Events | Precision (Any) | Recall (Any) | F1 (Any) | Precision (Maj) | Recall (Maj) | F1 (Maj) |",
        f"| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for stage_name, st in res.stage_results.items():
        any_p = st.any_metrics.get("precision")
        any_r = st.any_metrics.get("recall")
        any_f1 = st.any_metrics.get("f1")
        maj_p = st.majority_metrics.get("precision")
        maj_r = st.majority_metrics.get("recall")
        maj_f1 = st.majority_metrics.get("f1")

        s_any_p = f"{any_p:.3f}" if any_p is not None and not np.isnan(any_p) else "N/A"
        s_any_r = f"{any_r:.3f}" if any_r is not None and not np.isnan(any_r) else "N/A"
        s_any_f1 = f"{any_f1:.3f}" if any_f1 is not None and not np.isnan(any_f1) else "N/A"
        s_maj_p = f"{maj_p:.3f}" if maj_p is not None and not np.isnan(maj_p) else "N/A"
        s_maj_r = f"{maj_r:.3f}" if maj_r is not None and not np.isnan(maj_r) else "N/A"
        s_maj_f1 = f"{maj_f1:.3f}" if maj_f1 is not None and not np.isnan(maj_f1) else "N/A"

        lines.append(
            f"| `{stage_name}` | {st.n_windows} | {st.n_anomalies} | {st.n_events} | "
            f"{s_any_p} | {s_any_r} | {s_any_f1} | {s_maj_p} | {s_maj_r} | {s_maj_f1} |"
        )

    lines.extend([
        f"",
        f"*(Note: 'Any' method flags a window if ≥1 attack timestamp is present; 'Majority' requires >50% attack overlap. Exact 50% evaluates to Normal.)*",
        f"",
        f"---",
        f"",
        f"## 4. Stage 2: Temporal Propagation Modelling & Cascade Risk Index (CRI)",
        f"",
        f"| Propagation Metric | Count / State |",
        f"| :--- | :--- |",
        f"| **Total Event Records** | {res.stage2_summary.get('total_events_input', 0)} |",
        f"| **Candidate Observations** | {res.stage2_summary.get('matched_observations_count', 0)} |",
        f"| **Accepted Observations** | {res.stage2_summary.get('accepted_observations_count', 0)} |",
        f"| **Rejected Observations** | {res.stage2_summary.get('rejected_observations_count', 0)} |",
        f"| **Candidate Edges** | {res.stage2_summary.get('candidate_edges_count', 0)} |",
        f"| **Provisional Edges** | {res.stage2_summary.get('provisional_edges_count', 0)} |",
        f"| **Stable / Confirmed Edges** | {res.stage2_summary.get('stable_edges_count', 0)} |",
        f"| **Discovered Propagation Paths** | {res.stage2_summary.get('paths_count', 0)} |",
        f"",
    ])

    edges_detail = res.stage2_summary.get("edges_detail", [])
    if edges_detail:
        lines.extend([
            f"### Discovered Cross-Stage Edges",
            f"",
            f"| Source Stage | Target Stage | Lifecycle State | Evidence Count | Est. Delay (s) | Confidence |",
            f"| :--- | :--- | :---: | :---: | :---: | :---: |",
        ])
        for e in edges_detail:
            delay_str = f"{e['est_delay_s']:.2f}" if e.get("est_delay_s") is not None else "N/A"
            lines.append(
                f"| `{e['source']}` | `{e['target']}` | `{e['state']}` | {e['evidence_count']} | {delay_str} | {e['confidence']:.3f} |"
            )
        lines.append("")

    cri_targets = res.stage2_summary.get("cri_targets", {})
    if cri_targets:
        lines.extend([
            f"### Cascade Risk Index (CRI) by Stage",
            f"",
            f"| Target Stage | CRI Score | Paths Used |",
            f"| :--- | :---: | :--- |",
        ])
        for tgt, cinfo in cri_targets.items():
            paths_str = ", ".join(cinfo.get("paths_used", [])) if cinfo.get("paths_used") else "None"
            lines.append(
                f"| `{tgt}` | {cinfo.get('cri', 0.0):.4f} | `{paths_str}` |"
            )
        lines.append("")

    if res.warnings:
        lines.extend([
            f"---",
            f"",
            f"## 5. Execution Warnings",
            f"",
        ])
        for w in res.warnings:
            lines.append(f"- :warning: {w}")
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"## 6. Scientific Limitations and Research Boundaries",
        f"",
    ])
    for lim in res.scientific_limitations:
        lines.append(f"- {lim}")
    lines.extend([
        f"",
        f"---",
        f"*End of TCMIM SWaT Experiment Execution Report.*",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI Argument Parser & Entry Point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TCMIM Reproducible SWaT Anomaly Detection & Propagation Experiment Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--protocol",
        choices=["protocol_a", "protocol_b", "protocol_c"],
        default="protocol_a",
        help=(
            "Experimental protocol: "
            "'protocol_a' = Normal-operation baseline (recommended); "
            "'protocol_b' = Single-file chronological baseline; "
            "'protocol_c' = Label-informed supervised baseline."
        ),
    )
    parser.add_argument("--normal-csv", type=str, default=None, help="Path to SWaT normal telemetry CSV")
    parser.add_argument("--attack-csv", type=str, default=None, help="Path to SWaT attack telemetry CSV")
    parser.add_argument("--data-dir", type=str, default=None, help="Directory containing SWaT CSV files")
    parser.add_argument("--window-size", type=float, default=60.0, help="Window duration in seconds")
    parser.add_argument("--overlap-frac", type=float, default=0.0, help="Window overlap fraction [0.0, 1.0)")
    parser.add_argument("--baseline-frac", type=float, default=0.2, help="Fraction of chronological windows for baseline")
    parser.add_argument("--contamination", type=float, default=0.05, help="Isolation Forest expected contamination")
    parser.add_argument("--random-seed", type=int, default=42, help="PRNG random seed for detector initialization")
    parser.add_argument("--max-rows", type=int, default=None, help="Optional maximum rows to load (for smoke tests)")
    parser.add_argument("--output-dir", type=str, default="experiments/results/swat", help="Directory for output artifacts")
    parser.add_argument("--run-id", type=str, default=None, help="Optional custom run identifier")
    return parser


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = build_parser()
    args = parser.parse_args()

    config = SWaTExperimentConfig(
        protocol=args.protocol,
        normal_csv=args.normal_csv,
        attack_csv=args.attack_csv,
        data_dir=args.data_dir,
        window_seconds=args.window_size,
        overlap_frac=args.overlap_frac,
        baseline_frac=args.baseline_frac,
        contamination=args.contamination,
        random_seed=args.random_seed,
        max_rows=args.max_rows,
        output_dir=Path(args.output_dir),
        run_id=args.run_id,
    )

    try:
        result = run_swat_experiment(config)
        print("\n" + "=" * 70)
        print("TCMIM SWaT EXPERIMENT EXECUTION COMPLETED")
        print("=" * 70)
        print(f"Run ID:        {result.run_id}")
        print(f"Protocol:      {result.protocol.upper()}")
        print(f"JSON Results:  {result.output_artifacts.get('latest_json')}")
        print(f"Markdown Doc:  {result.output_artifacts.get('latest_report_md')}")
        print("=" * 70)
        return 0
    except FileNotFoundError as fnf:
        print("\n" + "!" * 70, file=sys.stderr)
        print("DATASET ABSENCE NOTIFICATION:", file=sys.stderr)
        print(str(fnf), file=sys.stderr)
        print("!" * 70, file=sys.stderr)
        return 2
    except Exception as exc:
        logger.exception("SWaT experiment execution failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
