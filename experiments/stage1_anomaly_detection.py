"""
TCMIM — Stage 1 Experiment: Real-Data Unsupervised Anomaly Detection (MetroPT-3).

Project:
  Temporal Cross-Machine Influence Modelling and Cascade Risk Estimation
  for Early Failure Propagation in Interconnected Industrial Machines.

Milestone: ML Stage 1 (M8)
Provenance: PUBLIC_DATASET
Status: EXEC

INTEGRITY SAFEGUARDS & SCIENTIFIC CONTRACT
------------------------------------------
1. Real Data Only: Loaded directly from MetroPT-3 (Air Compressor). No synthetic
   data or synthetic labels are used in this experiment.
2. Temporal Integrity: Strict chronological ordering. No window shuffling.
   Feature selection, median imputation, and model fitting are conducted
   strictly on the candidate baseline period without look-ahead.
3. Unverified Baseline: The first 20% of chronological windows is used as a
   candidate baseline. It is documented as an unverified operational assumption;
   no ground truth exists proving the machine was 100% healthy during this period.
4. Non-Causal & Non-Failure Claim: Anomaly score reflects statistical deviation
   from baseline. An anomaly is NOT a confirmed failure or causal propagation event.
5. Single-Machine Scope: MetroPT-3 represents a single compressor system. It does
   NOT evaluate cross-machine cascade propagation.
6. No Supervised Metrics: Precision, recall, F1, and accuracy are NOT reported
   because verified sample-level ground-truth labels do not exist.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tcmim.config import CUSUMConfig
from tcmim.data.metropt3 import SENSOR_COLUMNS, load_metropt3_dataframe
from tcmim.data.validator import validate_dataframe
from tcmim.data.windower import WindowBuilder
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import (
    IsolationForestAnomalyDetector,
    run_cusum_comparison,
    summarize_anomalies_by_day,
)
from tcmim.schemas import AnomalyRecord, Provenance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("stage1_experiment")

# Approximate published failure and maintenance event annotations
# Source: Baptista, Goebel, & Henriques (2022), "A dataset for anomaly detection
#         and condition monitoring in urban railway systems", Data in Brief.
# Documented events have date-level uncertainty (+/- 24h).
PUBLISHED_EVENTS = [
    {
        "name": "Air Leak 1 (Reported)",
        "start": "2020-05-19 00:00:00",
        "end": "2020-05-20 23:59:59",
        "uncertainty": "+/- 24h (Maintenance work order window)",
    },
    {
        "name": "Component Failure / Service",
        "start": "2020-07-15 00:00:00",
        "end": "2020-07-15 23:59:59",
        "uncertainty": "+/- 12h (Unscheduled compressor servicing)",
    },
]


def resolve_metropt3_path(cli_path: Optional[str]) -> Path:
    """Locate MetroPT-3 CSV candidate on disk."""
    if cli_path:
        p = Path(cli_path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Specified CSV path does not exist: {cli_path}")

    candidates = [
        Path("../MetroPT3(AirCompressor).csv"),
        Path("MetroPT3(AirCompressor).csv"),
        Path("data/raw/MetroPT3(AirCompressor).csv"),
        Path(__file__).parent.parent.parent / "MetroPT3(AirCompressor).csv",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    raise FileNotFoundError(
        "MetroPT-3 CSV not found in standard candidate locations. "
        "Please provide --csv-path <path_to_csv>."
    )


def plot_results(
    if_records: List[AnomalyRecord],
    cusum_records: List[AnomalyRecord],
    daily_df: pd.DataFrame,
    baseline_end: datetime,
    output_path: Path,
    title_suffix: str = "",
) -> None:
    """Generate high-resolution multi-panel diagnostic plot."""
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 11), sharex=False)
    plt.subplots_adjust(hspace=0.35)

    times = [r.timestamp for r in if_records]
    if_scores = [r.anomaly_score for r in if_records]
    cusum_scores = [r.anomaly_score for r in cusum_records]

    # Panel 1: Isolation Forest Decision Function
    ax1.plot(times, if_scores, color="#1f77b4", linewidth=1.0, label="IF Anomaly Score (decision_function)")
    ax1.axhline(0.0, color="#d62728", linestyle="--", linewidth=1.2, label="Anomaly Threshold (< 0.0)")
    ax1.axvspan(times[0], baseline_end, color="#2ca02c", alpha=0.15, label="Candidate Baseline Period")

    # Annotate published events if they fall within time bounds
    t_min, t_max = min(times), max(times)
    for ev in PUBLISHED_EVENTS:
        ev_start = datetime.fromisoformat(ev["start"]).replace(tzinfo=timezone.utc)
        ev_end = datetime.fromisoformat(ev["end"]).replace(tzinfo=timezone.utc)
        if ev_start <= t_max and ev_end >= t_min:
            ax1.axvspan(ev_start, ev_end, color="#ff7f0e", alpha=0.3, label=f"Pub. Event: {ev['name']}")
            ax2.axvspan(ev_start, ev_end, color="#ff7f0e", alpha=0.3)

    ax1.set_ylabel("Anomaly Score\n(Lower = More Anomalous)")
    ax1.set_title(f"TCMIM Stage 1 — Isolation Forest Anomaly Detection {title_suffix}\n"
                  f"(Candidate Baseline Fit on Initial Period; No Ground-Truth Inferred)", fontsize=11)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))

    # Panel 2: Deterministic CUSUM Health Degradation S_t
    ax2.plot(times, cusum_scores, color="#9467bd", linewidth=1.0, label="CUSUM S_t Statistic (Degradation)")
    ax2.axvspan(times[0], baseline_end, color="#2ca02c", alpha=0.15, label="Candidate Baseline Period")
    ax2.set_ylabel("CUSUM S_t\n(Higher = More Degraded)")
    ax2.set_title("Deterministic Baseline: Health Indicator Z-Scores + CUSUM Cumulative Sum", fontsize=11)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M"))

    # Panel 3: Daily Anomaly Rate (%) & Observed Window Volume
    if not daily_df.empty:
        daily_dates = [datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) for d in daily_df.index]
        rates_pct = daily_df["anomaly_rate"] * 100.0
        ax3.bar(daily_dates, rates_pct, width=0.6, color="#ff7f0e", alpha=0.7, label="IF Anomaly Rate (%)")
        ax3.set_ylabel("Anomaly Rate (%)")
        ax3.set_xlabel("Observation Date (UTC)")
        ax3.set_title("Daily Observed Window Anomaly Rate (Accounting for Gaps & Operating Hours)", fontsize=11)
        ax3.grid(True, linestyle=":", alpha=0.6)
        ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

        # Twin axis for window count
        ax3_twin = ax3.twinx()
        ax3_twin.plot(daily_dates, daily_df["window_count"], color="#2ca02c", marker="o", markersize=4,
                      linestyle="-", label="Windows Observed")
        ax3_twin.set_ylabel("Daily Windows Count")
        ax3.legend(loc="upper left", fontsize=8)
        ax3_twin.legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=200)
    plt.close()
    logger.info("Saved diagnostic plot to: %s", output_path)


def run_experiment(
    csv_path: Path,
    max_rows: Optional[int] = 50000,
    window_seconds: float = 300.0,
    overlap_frac: float = 0.0,
    baseline_frac: float = 0.2,
    contamination: float = 0.05,
    random_seed: int = 42,
    output_dir: Path = Path("experiments/results/stage1"),
) -> Dict[str, Any]:
    """Execute Stage 1 Anomaly Detection pipeline on MetroPT-3."""
    logger.info("=" * 70)
    logger.info("TCMIM STAGE 1 — UNSUPERVISED ANOMALY DETECTION EXPERIMENT")
    logger.info("=" * 70)
    logger.info("Data source: %s", csv_path)
    logger.info("Max rows: %s", max_rows if max_rows else "ALL (full dataset)")
    logger.info("Window size: %.1fs | Overlap: %.1f%%", window_seconds, overlap_frac * 100)
    logger.info("Candidate baseline fraction: %.1f%% (chronological)", baseline_frac * 100)
    logger.info("Contamination assumption: %.3f | Random seed: %d", contamination, random_seed)

    # 1. Ingestion & Validation
    t0 = datetime.now(timezone.utc)
    logger.info("Loading MetroPT-3 dataframe...")
    df = load_metropt3_dataframe(csv_path, max_rows=max_rows)
    logger.info("Loaded %d rows across %d sensor channels.", len(df), len(df.columns) - 1)

    val_report = validate_dataframe(df)
    logger.info("Validation report: total_checked=%d, passed=%s, out_of_order=%d, range_violations=%d",
                val_report.total_checked, val_report.passed, val_report.out_of_order_count,
                val_report.range_violation_count)

    # 2. Windowing
    logger.info("Building non-overlapping time windows...")
    wb = WindowBuilder(window_seconds=window_seconds, overlap_frac=overlap_frac)
    windows = wb.build(df, "metropt3_compressor", Provenance.PUBLIC_DATASET)
    logger.info("Created %d chronological windows.", len(windows))

    # 3. Multimodal Feature Extraction
    logger.info("Extracting features at 0.1 Hz nominal MetroPT-3 rate...")
    extractor = FeatureExtractor(sampling_rate_hz=0.1)
    feature_samples = extractor.extract_all(windows)
    logger.info("Extracted multimodal feature samples for %d windows.", len(feature_samples))

    # 4. Stage 1 ML Isolation Forest Detector
    logger.info("Fitting Isolation Forest strictly on first %.1f%% baseline windows...", baseline_frac * 100)
    detector = IsolationForestAnomalyDetector(
        baseline_frac=baseline_frac,
        contamination=contamination,
        random_state=random_seed,
        min_baseline_windows=10,
    )
    if_records, if_summary = detector.fit_and_score(feature_samples)
    logger.info("Isolation Forest fitted and scored: %d windows, %d flagged anomalies (%.2f%%).",
                if_summary["total_scored_windows"], if_summary["anomaly_count"], if_summary["anomaly_rate"] * 100)

    # 5. Deterministic Comparison Baseline (Health Z-scores + CUSUM)
    logger.info("Running deterministic CUSUM comparison baseline...")
    cusum_records, cusum_summary = run_cusum_comparison(
        feature_samples,
        baseline_frac=baseline_frac,
        cusum_config=CUSUMConfig(k=0.5, h=5.0),
    )
    logger.info("CUSUM baseline complete: %d alarm windows (%.2f%%).",
                cusum_summary["alarm_count"], cusum_summary["alarm_rate"] * 100)

    # 6. Daily Summary Aggregation (accounting for data gaps)
    daily_df = summarize_anomalies_by_day(if_records)

    # 7. Serialise Outputs
    output_dir.mkdir(parents=True, exist_ok=True)
    results_json_path = output_dir / "stage1_experiment_results.json"
    records_csv_path = output_dir / "stage1_anomaly_records.csv"
    daily_csv_path = output_dir / "stage1_daily_summary.csv"
    plot_path = output_dir / "stage1_score_over_time.png"

    # Export records CSV
    rec_rows = []
    for ir, cr in zip(if_records, cusum_records):
        rec_rows.append({
            "timestamp": ir.timestamp.isoformat(),
            "machine_id": ir.machine_id,
            "if_score": ir.anomaly_score,
            "is_if_anomaly": int(ir.is_anomaly),
            "cusum_score": cr.anomaly_score,
            "is_cusum_alarm": int(cr.is_anomaly),
            "provenance": str(ir.provenance),
        })
    pd.DataFrame(rec_rows).to_csv(records_csv_path, index=False)
    logger.info("Saved anomaly records to: %s", records_csv_path)

    # Export daily CSV
    daily_df.to_csv(daily_csv_path)
    logger.info("Saved daily summary to: %s", daily_csv_path)

    # Plot
    baseline_end = datetime.fromisoformat(if_summary["split_info"]["baseline_end"])
    plot_results(
        if_records=if_records,
        cusum_records=cusum_records,
        daily_df=daily_df,
        baseline_end=baseline_end,
        output_path=plot_path,
        title_suffix=f"({len(df):,} rows / {len(windows)} windows)",
    )

    # Export comprehensive metadata JSON
    experiment_results = {
        "experiment_name": "Stage 1 Unsupervised Anomaly Detection",
        "milestone": "M8 / ML-S1",
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": Provenance.PUBLIC_DATASET.value,
        "data_source": str(csv_path),
        "total_rows_loaded": len(df),
        "total_windows": len(windows),
        "sampling_rate_hz": 0.1,
        "window_seconds": window_seconds,
        "isolation_forest": if_summary,
        "cusum_comparison": cusum_summary,
        "daily_breakdown": {
            d.strftime("%Y-%m-%d"): {
                "window_count": int(row["window_count"]),
                "anomaly_count": int(row["anomaly_count"]),
                "anomaly_rate": float(row["anomaly_rate"]),
            }
            for d, row in daily_df.iterrows()
        },
        "scientific_integrity_disclaimer": (
            "1. Anomaly scores reflect statistical divergence from the candidate baseline. "
            "They are NOT confirmed component failures.\n"
            "2. The candidate baseline period is unverified; no sample-level ground-truth "
            "labels exist in MetroPT-3.\n"
            "3. Supervised metrics (precision, recall, F1, accuracy) are omitted to avoid "
            "scientific misrepresentation.\n"
            "4. MetroPT-3 is a single-machine dataset and does NOT validate cross-machine cascade propagation."
        ),
    }

    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump(experiment_results, f, indent=2)
    logger.info("Saved metadata results JSON to: %s", results_json_path)

    logger.info("=" * 70)
    logger.info("EXPERIMENT COMPLETE")
    logger.info("=" * 70)
    return experiment_results


def main() -> None:
    parser = argparse.ArgumentParser(description="TCMIM Stage 1 ML Anomaly Detection Experiment.")
    parser.add_argument("--csv-path", type=str, default=None, help="Path to MetroPT-3 CSV file.")
    parser.add_argument("--max-rows", type=int, default=50000, help="Max rows to process (0 for full CSV).")
    parser.add_argument("--window-seconds", type=float, default=300.0, help="Window length in seconds.")
    parser.add_argument("--overlap-frac", type=float, default=0.0, help="Window overlap fraction [0, 1).")
    parser.add_argument("--baseline-frac", type=float, default=0.2, help="Fraction for candidate baseline [0, 1).")
    parser.add_argument("--contamination", type=float, default=0.05, help="IsolationForest contamination rate.")
    parser.add_argument("--random-seed", type=int, default=42, help="Random state seed.")
    parser.add_argument("--output-dir", type=str, default="experiments/results/stage1", help="Output directory.")

    args = parser.parse_args()
    csv_path = resolve_metropt3_path(args.csv_path)
    max_rows = None if args.max_rows == 0 else args.max_rows

    run_experiment(
        csv_path=csv_path,
        max_rows=max_rows,
        window_seconds=args.window_seconds,
        overlap_frac=args.overlap_frac,
        baseline_frac=args.baseline_frac,
        contamination=args.contamination,
        random_seed=args.random_seed,
        output_dir=Path(args.output_dir),
    )


if __name__ == "__main__":
    main()
