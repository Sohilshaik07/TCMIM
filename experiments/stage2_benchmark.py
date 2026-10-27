"""
experiments/stage2_benchmark.py
================================
Reproducible synthetic benchmark suite execution script for TCMIM Stage 2.

Evaluates recovery of known machine-to-machine temporal propagation relationships
across 7 controlled synthetic scenarios:
1. Linear Chain (A -> B -> C)
2. Branching Fork (A -> B and A -> C)
3. Feedback Ring (A -> B -> C -> A)
4. Negative Control (Independent Streams)
5. Reversed Temporal Order (Target Precedes Source)
6. Common Cause Disturbance (Shared Environmental Shock)
7. Noisy Cascade (Jitter, Dropout, Spurious Events)

Outputs:
- experiments/results/stage2/stage2_benchmark_results.json
- experiments/results/stage2/stage2_benchmark_summary.csv
- experiments/results/stage2/Stage2_Benchmark_Report.md
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from pathlib import Path

# Add project root to path if executed directly
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from tcmim.benchmark.runner import run_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run TCMIM Stage 2 Synthetic Multi-Machine Benchmark Suite."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Master random seed for reproducible scenario generation (default: 42).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(project_root / "experiments" / "results" / "stage2"),
        help="Directory to store JSON, CSV, and Markdown benchmark reports.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("TCMIM Stage 2 — Synthetic Multi-Machine Benchmark Suite")
    print(f"Random Seed: {args.seed}")
    print(f"Output Directory: {out_dir}")
    print("=" * 80)

    # 1. Execute benchmark
    benchmark_result = run_benchmark(seed=args.seed)

    # 2. Save JSON results
    json_path = out_dir / "stage2_benchmark_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_result.to_dict(), f, indent=2)
    print(f"Saved machine-readable JSON: {json_path}")

    # 3. Save CSV summary
    csv_path = out_dir / "stage2_benchmark_summary.csv"
    fieldnames = [
        "scenario_id",
        "scenario_name",
        "n_machines",
        "gt_edges_count",
        "pred_edges_count",
        "tp",
        "fp",
        "fn",
        "tn",
        "precision",
        "recall",
        "f1_score",
        "fpr",
        "lag_mae_s",
        "lag_rmse_s",
        "missing_lag_rate",
        "execution_time_s",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ev in benchmark_result.evaluations:
            writer.writerow({
                "scenario_id": ev.scenario_id,
                "scenario_name": ev.scenario_name,
                "n_machines": len(set([s for s, t in ev.ground_truth_edges + ev.predicted_edges])),
                "gt_edges_count": len(ev.ground_truth_edges),
                "pred_edges_count": len(ev.predicted_edges),
                "tp": ev.tp,
                "fp": ev.fp,
                "fn": ev.fn,
                "tn": ev.tn,
                "precision": ev.precision,
                "recall": ev.recall,
                "f1_score": ev.f1_score,
                "fpr": ev.fpr,
                "lag_mae_s": round(ev.lag_mae_s, 3) if not math.isnan(ev.lag_mae_s) else "",
                "lag_rmse_s": round(ev.lag_rmse_s, 3) if not math.isnan(ev.lag_rmse_s) else "",
                "missing_lag_rate": ev.missing_lag_rate,
                "execution_time_s": ev.execution_time_s,
            })
    print(f"Saved tabular CSV summary: {csv_path}")

    # 4. Save Markdown report
    md_path = out_dir / "Stage2_Benchmark_Report.md"
    md_content = benchmark_result.to_markdown()
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Saved comprehensive Markdown report: {md_path}")

    # 5. Print console summary table
    print("\n" + "=" * 80)
    print("BENCHMARK EXECUTION SUMMARY")
    print("=" * 80)
    print(f"{'Scenario':<35} | {'P':<6} | {'R':<6} | {'F1':<6} | {'FPR':<6} | {'Lag MAE':<9} | {'Time':<6}")
    print("-" * 80)
    for ev in benchmark_result.evaluations:
        p_str = f"{ev.precision:<6.3f}" if ev.precision is not None else "N/A   "
        r_str = f"{ev.recall:<6.3f}" if ev.recall is not None else "N/A   "
        f1_str = f"{ev.f1_score:<6.3f}" if ev.f1_score is not None else "N/A   "
        mae_str = f"{ev.lag_mae_s:.2f}s" if not math.isnan(ev.lag_mae_s) else "N/A"
        print(
            f"{ev.scenario_name[:35]:<35} | "
            f"{p_str} | "
            f"{r_str} | "
            f"{f1_str} | "
            f"{ev.fpr:<6.3f} | "
            f"{mae_str:<9} | "
            f"{ev.execution_time_s:.2f}s"
        )
    print("-" * 80)
    m = benchmark_result.metrics
    mean_mae_str = f"{m.mean_lag_mae_s:.2f}s" if not math.isnan(m.mean_lag_mae_s) else "N/A"
    mp_str = f"{m.mean_precision:<6.3f}" if m.mean_precision is not None else "N/A   "
    mr_str = f"{m.mean_recall:<6.3f}" if m.mean_recall is not None else "N/A   "
    mf1_str = f"{m.mean_f1:<6.3f}" if m.mean_f1 is not None else "N/A   "
    print(
        f"{'MACRO AVERAGE':<35} | "
        f"{mp_str} | "
        f"{mr_str} | "
        f"{mf1_str} | "
        f"{m.mean_fpr:<6.3f} | "
        f"{mean_mae_str:<9} | "
        f"{m.total_runtime_s:.2f}s"
    )
    print("=" * 80 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
