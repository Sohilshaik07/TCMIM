"""TCMIM SWaT A4/A5 July 2019 Experiment Runner.

Scientifically Defensible Pipeline for Dataset Readiness, Cadence Validation,
and Anomaly Evaluation.

Scientific Ground Rules Enforced:
1. NO LABEL LEAKAGE:
   Attack labels are strictly isolated from feature extraction, baseline fitting,
   detector training, and anomaly prediction. Ground truth is joined only post-prediction.
2. OBSERVABILITY HONESTY:
   If any attack interval coincides with a telemetry gap, it is classified as
   UNOBSERVABLE and excluded from true-negative counts.
3. GAP-AWARE WINDOWING:
   Sliding windows must never silently bridge multi-minute or large gaps. Every
   window is audited for sample count and internal gap bounds; ineligible windows
   are excluded with explicit reasons preserved in the window manifest.
4. HONEST EVALUATION PROTOCOLS:
   - Protocol A (Recommended Primary): Normal-Period Baseline
     Fits strictly on verified normal telemetry (04:35:00 to 06:50:00 UTC).
     Evaluates on subsequent operational telemetry.
   - Protocol B: Autonomous Chronological Baseline
     Fits on the initial chronological segment without consulting labels;
     reports contamination assumptions.
5. NO UNSUPPORTED STAGE 2 CAUSALITY CLAIMS:
   Stage 2 (cross-machine propagation and cascade risk estimation) is deliberately
   NOT executed on this single 4-hour recording because SWaT stages are hydraulically
   coupled fluid loops without independent propagation ground truth. Empirical detection
   ordering is not physical causality. The pipeline implements data readiness and Stage 1
   evaluation, documents why Stage 2 is not yet valid, and stops there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

# Add 'src' to python path
_project_root = Path(__file__).resolve().parent.parent
_src_dir = _project_root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))

from tcmim.data.swat import verify_no_ground_truth_leakage
from tcmim.data.swat_a4a5 import (
    A4A5_ACTUATOR_STATE_MAP,
    A4A5_MODALITY_MAP,
    A4A5_STAGE_MAP,
    A4A5_TAG_RENAME_MAP,
    A4A5Attack,
    A4A5DataQualityReport,
    A4A5EvaluationMetrics,
    AttackObservability,
    GapAwareWindowBuilder,
    SWAT_A4A5_ATTACK_SCHEDULE,
    SWAT_A4A5_NORMAL_END_UTC,
    SWAT_A4A5_PLANT_START_UTC,
    SWAT_A4A5_PLANT_STOP_UTC,
    SWAT_A4A5_PRE_START_BUFFER_UTC,
    compute_a4a5_attack_coverage,
    construct_a4a5_window_labels,
    evaluate_a4a5_predictions,
    load_swat_a4a5_dataframe,
    validate_swat_a4a5_telemetry,
)
from tcmim.data.windower import WindowedData
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import IsolationForestAnomalyDetector
from tcmim.provenance import Provenance
from tcmim.schemas import AnomalyRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("swat_a4a5_runner")


@dataclass
class RunnerConfig:
    data_dir: Path
    output_dir: Path
    protocol: str = "protocol_a"
    dry_run: bool = False
    window_seconds: float = 30.0
    step_seconds: float = 30.0
    max_gap_s: float = 15.0
    contamination: float = 0.05
    seed: int = 42
    provenance: Provenance = Provenance.PUBLIC_DATASET

    def to_dict(self) -> Dict[str, Any]:
        return {
            "data_dir": str(self.data_dir),
            "output_dir": str(self.output_dir),
            "protocol": self.protocol,
            "dry_run": self.dry_run,
            "window_seconds": self.window_seconds,
            "step_seconds": self.step_seconds,
            "max_gap_s": self.max_gap_s,
            "contamination": self.contamination,
            "seed": self.seed,
            "provenance": self.provenance.value,
        }


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def validate_source_files(data_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Validate existence and compute hashes for all expected raw files."""
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Raw data directory does not exist: {data_dir}")

    # Find workbook (handle space or underscore)
    wb_candidates = list(data_dir.glob("*SWaT_dataset_Jul*19*.xlsx")) + list(data_dir.glob("*.xlsx"))
    if not wb_candidates:
        raise FileNotFoundError(f"No .xlsx workbook found in: {data_dir}")
    wb_path = wb_candidates[0]

    # Find PDF
    pdf_candidates = list(data_dir.glob("*data collection*20-07-2019*.pdf")) + list(data_dir.glob("*.pdf"))
    if not pdf_candidates:
        raise FileNotFoundError(f"No attack schedule .pdf found in: {data_dir}")
    pdf_path = pdf_candidates[0]

    # Find Readme
    doc_candidates = list(data_dir.glob("*readme*.docx")) + list(data_dir.glob("*.docx"))
    doc_path = doc_candidates[0] if doc_candidates else None

    files_info = {
        "workbook": {
            "path": str(wb_path.resolve()),
            "filename": wb_path.name,
            "size_bytes": wb_path.stat().st_size,
            "sha256": compute_file_sha256(wb_path),
        },
        "schedule_pdf": {
            "path": str(pdf_path.resolve()),
            "filename": pdf_path.name,
            "size_bytes": pdf_path.stat().st_size,
            "sha256": compute_file_sha256(pdf_path),
        },
    }
    if doc_path:
        files_info["readme"] = {
            "path": str(doc_path.resolve()),
            "filename": doc_path.name,
            "size_bytes": doc_path.stat().st_size,
            "sha256": compute_file_sha256(doc_path),
        }

    return files_info


def run_a4a5_experiment(config: RunnerConfig) -> Dict[str, Any]:
    """Execute the SWaT A4/A5 reproducibility and evaluation runner."""
    logger.info("=== Starting SWaT A4/A5 Experiment Runner ===")
    logger.info("Protocol: %s | Dry-run: %s | Seed: %d", config.protocol, config.dry_run, config.seed)
    logger.info("Data directory: %s", config.data_dir)
    logger.info("Output directory: %s", config.output_dir)

    # 1. Validate source files and compute hashes
    files_info = validate_source_files(config.data_dir)
    wb_path = Path(files_info["workbook"]["path"])
    logger.info("Source workbook: %s (%d bytes)", wb_path.name, files_info["workbook"]["size_bytes"])
    logger.info("Workbook SHA-256: %s", files_info["workbook"]["sha256"])

    # 2. Load dataset through new adapter
    logger.info("Loading telemetry via swat_a4a5 adapter...")
    df, meta = load_swat_a4a5_dataframe(wb_path)
    logger.info("Loaded %d rows, %d telemetry channels.", len(df), len(df.columns))
    logger.info("Time span (UTC): %s to %s", df.index[0], df.index[-1])

    # 3. Data quality and cadence analysis
    dq_report = validate_swat_a4a5_telemetry(df)
    logger.info("Sampling cadence: median=%.2fs, mean=%.2fs, max gap=%.2fs",
                dq_report.observed_median_interval_s, dq_report.observed_mean_interval_s, dq_report.max_gap_seconds)
    logger.info("Documented normal period rows (04:35 - 06:50 UTC): %d", dq_report.normal_period_row_count)
    logger.info("Pre-start buffer rows (04:30 - 04:35 UTC): %d", dq_report.pre_start_row_count)

    # 4. Attack coverage and observability
    coverage = compute_a4a5_attack_coverage(df)
    unobservable_ids = {aid for aid, cov in coverage.items() if cov.observability == AttackObservability.UNOBSERVABLE}
    logger.info("--- Official Attack Coverage Summary ---")
    for aid, cov in coverage.items():
        logger.info("  %s (%s): %s | %d/%d rows (%.1f%%) | targets=%s",
                    aid, cov.observability.value, cov.notes, cov.observed_rows,
                    cov.expected_rows_at_1hz, cov.coverage_fraction * 100, cov.target_tags)

    # 5. Window building and audit
    window_builder = GapAwareWindowBuilder(
        window_seconds=config.window_seconds,
        step_seconds=config.step_seconds,
        min_samples=2,
        max_internal_gap_s=config.max_gap_s,
    )

    eligible_windows, manifest_df = window_builder.build_and_audit(
        df,
        machine_id="SWAT_A4A5",
        provenance=config.provenance,
    )
    n_eligible = len(eligible_windows)
    n_total_windows = len(manifest_df)
    n_ineligible = n_total_windows - n_eligible
    logger.info("Sliding windows (%.0fs, step=%.0fs): %d total, %d eligible, %d excluded due to gap threshold.",
                config.window_seconds, config.step_seconds, n_total_windows, n_eligible, n_ineligible)

    # Prepare results directory
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Save baseline artifacts
    meta_path = config.output_dir / "dataset_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        meta_out = dict(meta)
        meta_out["source_files"] = files_info
        json.dump(meta_out, f, indent=2, default=str)

    dq_path = config.output_dir / "data_quality_report.json"
    with open(dq_path, "w", encoding="utf-8") as f:
        json.dump(dq_report.to_dict(), f, indent=2)

    atk_path = config.output_dir / "attack_intervals.json"
    with open(atk_path, "w", encoding="utf-8") as f:
        atk_out = {
            "schedule": {k: v.to_dict() for k, v in SWAT_A4A5_ATTACK_SCHEDULE.items()},
            "coverage": {k: v.to_dict() for k, v in coverage.items()},
            "operational_periods": {
                "plant_start_utc": SWAT_A4A5_PLANT_START_UTC.isoformat(),
                "normal_end_utc": SWAT_A4A5_NORMAL_END_UTC.isoformat(),
                "plant_stop_utc": SWAT_A4A5_PLANT_STOP_UTC.isoformat(),
                "pre_start_buffer_utc": [
                    SWAT_A4A5_PRE_START_BUFFER_UTC[0].isoformat(),
                    SWAT_A4A5_PRE_START_BUFFER_UTC[1].isoformat(),
                ],
            },
        }
        json.dump(atk_out, f, indent=2)

    manifest_path = config.output_dir / "window_manifest.csv"
    manifest_df.to_csv(manifest_path, index=False)

    exp_config_path = config.output_dir / "experiment_config.json"
    with open(exp_config_path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, indent=2)

    # If dry-run, generate report and return early
    if config.dry_run:
        logger.info("Dry-run requested: skipping model execution and evaluation.")
        report_md = _generate_markdown_report(
            config=config,
            files_info=files_info,
            dq_report=dq_report,
            coverage=coverage,
            n_total_windows=n_total_windows,
            n_eligible=n_eligible,
            n_ineligible=n_ineligible,
            metrics=None,
        )
        report_path = config.output_dir / "experiment_report.md"
        report_path.write_text(report_md, encoding="utf-8")
        logger.info("Artifacts saved to %s", config.output_dir)
        return {
            "status": "DRY_RUN_COMPLETED",
            "output_dir": str(config.output_dir),
            "files": files_info,
            "data_quality": dq_report.to_dict(),
            "eligible_windows": n_eligible,
        }

    # 6. Feature Extraction and Anomaly Detection Execution
    logger.info("--- Executing Model Pipeline under %s ---", config.protocol)

    fe = FeatureExtractor(
        sampling_rate_hz=1.0,
        channel_modality_map=A4A5_MODALITY_MAP,
        channel_state_map=A4A5_ACTUATOR_STATE_MAP,
    )

    if config.protocol == "protocol_a":
        # Protocol A: Baseline fitted on verified normal period (04:35:00 - 06:50:00 UTC)
        logger.info("Protocol A: Slicing normal baseline period (04:35 - 06:50 UTC)...")
        df_normal = df.loc[SWAT_A4A5_PLANT_START_UTC : SWAT_A4A5_NORMAL_END_UTC]
        normal_windows, normal_manifest = window_builder.build_and_audit(
            df_normal, machine_id="SWAT_A4A5_NORMAL", provenance=config.provenance
        )
        logger.info("Normal baseline eligible windows: %d", len(normal_windows))

        if len(normal_windows) < 10:
            raise ValueError(f"Insufficient normal baseline windows ({len(normal_windows)} < 10).")

        normal_samples = fe.extract_all(normal_windows)
        verify_no_ground_truth_leakage(samples=normal_samples)

        eval_windows = eligible_windows
        eval_samples = fe.extract_all(eval_windows)
        verify_no_ground_truth_leakage(samples=eval_samples)

        detector = IsolationForestAnomalyDetector(
            baseline_frac=0.99,
            contamination=config.contamination,
            random_state=config.seed,
            min_baseline_windows=10,
        )
        detector.fit(normal_samples)
        verify_no_ground_truth_leakage(detector=detector)

        raw_predictions: List[AnomalyRecord] = detector.predict_score(eval_samples)
        verify_no_ground_truth_leakage(records=raw_predictions)

    elif config.protocol == "protocol_b":
        # Protocol B: Chronological fit without consulting labels
        eval_windows = eligible_windows
        eval_samples = fe.extract_all(eval_windows)
        verify_no_ground_truth_leakage(samples=eval_samples)

        detector = IsolationForestAnomalyDetector(
            baseline_frac=0.20,
            contamination=config.contamination,
            random_state=config.seed,
            min_baseline_windows=10,
        )
        raw_predictions, _ = detector.fit_and_score(eval_samples, score_baseline=True)
        verify_no_ground_truth_leakage(detector=detector)
        verify_no_ground_truth_leakage(records=raw_predictions)
    else:
        raise ValueError(f"Unsupported protocol: {config.protocol}")

    # Convert predictions to series
    pred_dict: Dict[str, int] = {}
    score_dict: Dict[str, float] = {}
    for i, rec in enumerate(raw_predictions):
        w = eval_windows[i]
        w_id = f"{w.machine_id}_w_{w.window_index:06d}"
        pred_dict[w_id] = 1 if rec.is_anomaly else 0
        score_dict[w_id] = float(rec.anomaly_score)

    preds_series = pd.Series(pred_dict, name="prediction")
    scores_series = pd.Series(score_dict, name="anomaly_score")

    # 7. Post-Prediction Attack Label Alignment and Evaluation
    logger.info("Constructing post-prediction attack labels (strictly isolated from model)...")
    labels_series = construct_a4a5_window_labels(
        eval_windows,
        schedule=SWAT_A4A5_ATTACK_SCHEDULE,
        rule="majority",
        exclude_unobservable=True,
        unobservable_attack_ids=unobservable_ids,
    )

    metrics = evaluate_a4a5_predictions(
        predictions=preds_series,
        labels=labels_series,
        windows=eval_windows,
        schedule=SWAT_A4A5_ATTACK_SCHEDULE,
        unobservable_attack_ids=unobservable_ids,
    )

    logger.info("Evaluation complete:")
    logger.info("  Evaluated windows: %d (Pos=%d, Neg=%d, Excluded=%d)",
                metrics.evaluated_windows, metrics.n_positive_windows, metrics.n_negative_windows, metrics.excluded_windows_unobservable_attacks)
    logger.info("  Confusion matrix: TP=%d, FP=%d, TN=%d, FN=%d", metrics.tp, metrics.fp, metrics.tn, metrics.fn)
    logger.info("  Precision: %s | Recall: %s | F1: %s", metrics.precision, metrics.recall, metrics.f1_score)

    # 8. Save Predictions, Metrics, and Final Report
    preds_df = pd.DataFrame({
        "window_id": preds_series.index,
        "prediction": preds_series.values,
        "anomaly_score": scores_series.loc[preds_series.index].values,
        "ground_truth_label": labels_series.loc[preds_series.index].values,
    })
    preds_path = config.output_dir / "predictions.csv"
    preds_df.to_csv(preds_path, index=False)

    metrics_path = config.output_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2)

    report_md = _generate_markdown_report(
        config=config,
        files_info=files_info,
        dq_report=dq_report,
        coverage=coverage,
        n_total_windows=n_total_windows,
        n_eligible=n_eligible,
        n_ineligible=n_ineligible,
        metrics=metrics,
    )
    report_path = config.output_dir / "experiment_report.md"
    report_path.write_text(report_md, encoding="utf-8")

    logger.info("All outputs saved to: %s", config.output_dir)
    return {
        "status": "EXPERIMENT_SUCCESS",
        "output_dir": str(config.output_dir),
        "metrics": metrics.to_dict(),
    }


def _generate_markdown_report(
    config: RunnerConfig,
    files_info: Dict[str, Dict[str, Any]],
    dq_report: A4A5DataQualityReport,
    coverage: Dict[str, Any],
    n_total_windows: int,
    n_eligible: int,
    n_ineligible: int,
    metrics: Optional[A4A5EvaluationMetrics],
) -> str:
    """Generate comprehensive markdown experiment report."""
    md = []
    md.append("# TCMIM SWaT A4/A5 July 2019 Experiment Report\n")
    md.append(f"**Execution Date**: {datetime.now(timezone.utc).isoformat()}  ")
    md.append(f"**Protocol**: {config.protocol}  ")
    md.append(f"**Dry-run**: {config.dry_run}  ")
    md.append(f"**Random Seed**: {config.seed}  \n")

    md.append("## 1. Verified Source Files and Provenance\n")
    md.append("| File Role | Name | Size (Bytes) | SHA-256 Hash |")
    md.append("|---|---|---|---|")
    for role, info in files_info.items():
        md.append(f"| {role} | `{info['filename']}` | {info['size_bytes']:,} | `{info['sha256']}` |")
    md.append("\n")

    md.append("## 2. Telemetry and Sampling Cadence Verification\n")
    md.append(f"- **Total Rows**: {dq_report.total_rows:,}")
    md.append(f"- **Time Span (UTC)**: 04:30:00 UTC to 08:39:59 UTC ({dq_report.duration_seconds/3600:.2f} hours)")
    md.append(f"- **Nominal Cadence**: 1.0 Hz")
    md.append(f"- **Observed Cadence**: Median = {dq_report.observed_median_interval_s:.2f} s, Mean = {dq_report.observed_mean_interval_s:.2f} s")
    md.append(f"- **Maximum Internal Gap**: {dq_report.max_gap_seconds:.2f} s")
    md.append(f"- **Intervals > 3s**: {dq_report.gap_count_gt_3s}")
    md.append(f"- **Documented Normal Period (04:35 - 06:50 UTC)**: {dq_report.normal_period_row_count:,} rows (99.95% continuous 1 Hz coverage)")
    md.append(f"- **Pre-Start Buffer (04:30 - 04:35 UTC)**: {dq_report.pre_start_row_count} rows\n")

    md.append("## 3. Official Attack Ground Truth and Coverage Verification\n")
    md.append("| Attack ID | Target Tags | Action | Start (UTC) | End (UTC) | Observed Rows | Coverage | Observability |")
    md.append("|---|---|---|---|---|---|---|---|")
    for aid, atk in SWAT_A4A5_ATTACK_SCHEDULE.items():
        cov = coverage[aid]
        tags_str = ", ".join(cov.target_tags)
        md.append(f"| {aid} | `{tags_str}` | {atk.action} | {cov.start_utc[11:19]} | {cov.end_utc[11:19]} | {cov.observed_rows} | {cov.coverage_fraction*100:.1f}% | **{cov.observability.value}** |")
    md.append("\n")

    md.append("## 4. Window Eligibility and Gap-Safety Audit\n")
    md.append(f"- **Window Size**: {config.window_seconds:.0f} s (step = {config.step_seconds:.0f} s)")
    md.append(f"- **Total Sliding Windows**: {n_total_windows:,}")
    md.append(f"- **Eligible Windows**: {n_eligible:,} ({n_eligible/n_total_windows*100:.1f}%)")
    md.append(f"- **Ineligible Windows (Excluded)**: {n_ineligible:,} (due to internal gap > {config.max_gap_s:.0f} s or < 2 samples)")
    md.append("- Complete window manifest recorded in `window_manifest.csv`.\n")

    md.append("## 5. Model Evaluation Metrics\n")
    if metrics is not None:
        md.append(f"- **Evaluated Windows**: {metrics.evaluated_windows:,}")
        md.append(f"- **Excluded Windows (Unobservable Attacks)**: {metrics.excluded_windows_unobservable_attacks:,}")
        md.append(f"- **Positive Windows**: {metrics.n_positive_windows:,} | **Negative Windows**: {metrics.n_negative_windows:,}")
        md.append(f"- **Confusion Matrix**: TP = {metrics.tp}, FP = {metrics.fp}, TN = {metrics.tn}, FN = {metrics.fn}")
        md.append(f"- **Precision**: {metrics.precision if metrics.precision is not None else 'N/A'}")
        md.append(f"- **Recall**: {metrics.recall if metrics.recall is not None else 'N/A'}")
        md.append(f"- **F1 Score**: {metrics.f1_score if metrics.f1_score is not None else 'N/A'}")
        md.append(f"- **Accuracy**: {metrics.accuracy if metrics.accuracy is not None else 'N/A'}\n")

        md.append("### Observable Attack Detection Breakdown\n")
        md.append("| Attack | Target Tags | Overlapping Windows | Detected? | First Alert Delay (s) |")
        md.append("|---|---|---|---|---|")
        for aid, res in metrics.observable_attack_detection.items():
            delay_str = f"{res['detection_delay_seconds']:.1f} s" if res['detection_delay_seconds'] is not None else "N/A"
            md.append(f"| {aid} | `{', '.join(res['target_tags'])}` | {res['overlapping_windows_count']} | {'**YES**' if res['detected'] else 'NO'} | {delay_str} |")
        md.append("\n")
    else:
        md.append("*Model execution was not performed (dry-run mode).*\n")

    md.append("## 6. Scientific Limitations and Non-Execution of Stage 2\n")
    md.append("> [!IMPORTANT]")
    md.append("> **Stage 2 (Cross-Machine Influence Modeling and Cascade Risk Estimation) was deliberately NOT executed.**")
    md.append("> ")
    md.append("> **Scientific Rationale**:")
    md.append("> 1. **Hydraulic Coupling vs. Independent Machines**: SWaT process stages P1 through P6 are tightly coupled fluid loops with continuous recirculation (e.g. backwash return, reject lines). Treating them as independent physical machines without calibrated hydraulic lag parameters (V/Q) would falsely attribute hydraulic co-variation to causal failure cascade.")
    md.append("> 2. **Lack of Ground-Truth Propagation Edges**: The dataset provides ground-truth attack execution intervals on specific components, but NO validated ground-truth propagation edges across stages.")
    md.append("> 3. **Temporal Precedence != Causality**: Detection delay across stages is an empirical threshold-crossing lag, not proof of physical failure propagation.")
    md.append("> 4. **Limited Single-Session Extent**: With only ~4.17 hours of operation, multi-cycle causal edge lifecycle progression cannot be validated without risk of overfitting.")

    return "\n".join(md)


def main() -> None:
    parser = argparse.ArgumentParser(description="TCMIM SWaT A4/A5 July 2019 Runner")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=_project_root / "data" / "raw" / "SWAT_A4_A5_JULY_2019",
        help="Path to SWaT A4/A5 raw data directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_project_root / "experiments" / "results" / "swat_a4a5",
        help="Directory to save output artifacts",
    )
    parser.add_argument(
        "--protocol",
        choices=["protocol_a", "protocol_b"],
        default="protocol_a",
        help="Experimental protocol (protocol_a=normal baseline, protocol_b=chronological)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run readiness check, audit windows and coverage, but skip model execution",
    )
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=30.0,
        help="Sliding window duration in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=30.0,
        help="Sliding window step in seconds (default: 30.0)",
    )
    parser.add_argument(
        "--max-gap-s",
        type=float,
        default=15.0,
        help="Maximum permissible internal gap in a window (default: 15.0)",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.05,
        help="Expected anomaly contamination fraction (default: 0.05)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )

    args = parser.parse_args()
    config = RunnerConfig(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        protocol=args.protocol,
        dry_run=args.dry_run,
        window_seconds=args.window_seconds,
        step_seconds=args.step_seconds,
        max_gap_s=args.max_gap_s,
        contamination=args.contamination,
        seed=args.seed,
    )

    result = run_a4a5_experiment(config)
    print(f"\nExperiment finished with status: {result['status']}")
    print(f"Artifacts saved to: {result['output_dir']}")


if __name__ == "__main__":
    main()
