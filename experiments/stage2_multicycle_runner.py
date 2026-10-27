"""
experiments/stage2_multicycle_runner.py
=======================================
Chronological multi-cycle benchmark execution script for TCMIM Stage 2.

Feeds events in chronological time windows (cycles) to evaluate:
1. Progressive edge evidence accumulation across time windows.
2. Lifecycle state progression (CANDIDATE -> PROVISIONAL -> STABLE).
3. Graph view comparison at each cycle without modifying EdgeManager state.
4. Spurious edge filtering behavior over multi-cycle observation.

Outputs:
- experiments/results/stage2/stage2_multicycle_results.json
- experiments/results/stage2/Stage2_MultiCycle_Benchmark.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.benchmark.multicycle import (
    multicycle_results_to_markdown,
    run_multicycle_benchmark,
)
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.delay import DelayEstimatorConfig
from tcmim.schemas import EdgeState


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TCMIM Stage 2 Chronological Multi-Cycle Benchmark."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Master random seed for scenario generation (default: 42).",
    )
    parser.add_argument(
        "--cycle-duration",
        type=float,
        default=600.0,
        help="Duration of each evaluation window in seconds (default: 600.0s).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(project_root / "experiments" / "results" / "stage2"),
        help="Directory to save output JSON and Markdown reports.",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("TCMIM Stage 2 — Chronological Multi-Cycle Benchmark Runner")
    print(f"Seed: {args.seed} | Window Duration: {args.cycle_duration}s")
    print("=" * 80)

    start_time = time.perf_counter()
    results = run_multicycle_benchmark(
        seed=args.seed,
        cycle_duration_s=args.cycle_duration,
    )
    duration = time.perf_counter() - start_time
    print(f"Executed {len(results)} scenarios in {duration:.2f}s.")

    # 1. Save JSON
    json_path = out_dir / "stage2_multicycle_results.json"
    json_data = {
        "seed": args.seed,
        "cycle_duration_s": args.cycle_duration,
        "execution_time_s": duration,
        "scenarios": [r.to_dict() for r in results],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=2)
    print(f"Saved JSON results: {json_path}")

    # 2. Save Markdown
    md_path = out_dir / "Stage2_MultiCycle_Benchmark.md"
    md_text = multicycle_results_to_markdown(results)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"Saved Markdown report: {md_path}")

    print("\n" + "=" * 80)
    print("MULTI-CYCLE BENCHMARK SUMMARY (FINAL-CYCLE METRICS)")
    print("=" * 80)
    print(f"{'Scenario':<35} | {'View':<12} | {'P':<6} | {'R':<6} | {'F1':<6} | {'FPR':<6} | {'Path R':<6}")
    print("-" * 80)
    for res in results:
        for v in ["CANDIDATE", "PROVISIONAL", "STABLE"]:
            p = res.final_precision.get(v)
            r = res.final_recall.get(v)
            f = res.final_f1.get(v)
            fpr = res.final_fpr.get(v, 0.0)
            pr = res.path_recall_at_final.get(v)
            p_s = f"{p:<6.3f}" if p is not None else "N/A   "
            r_s = f"{r:<6.3f}" if r is not None else "N/A   "
            f_s = f"{f:<6.3f}" if f is not None else "N/A   "
            pr_s = f"{pr:<6.3f}" if pr is not None else "N/A   "
            print(f"{res.scenario_name[:35]:<35} | {v:<12} | {p_s} | {r_s} | {f_s} | {fpr:<6.3f} | {pr_s}")
        print("-" * 80)

    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
