"""
src/tcmim/benchmark/runner.py
=============================
Benchmark suite runner and report generator for TCMIM Stage 2.

Executes real Stage2Pipeline instances against benchmark scenarios, computes
rigorous ground-truth comparison metrics, and outputs structured evaluations.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import numpy as np

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.benchmark.metrics import (
    BenchmarkMetrics,
    ScenarioEvaluation,
    evaluate_scenario,
)
from tcmim.benchmark.scenarios import (
    BenchmarkScenario,
    generate_all_scenarios,
)
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.schemas import EdgeState

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkSuiteResult:
    """Complete results for the benchmark suite run."""
    timestamp: str
    random_seed: int
    evaluations: List[ScenarioEvaluation]
    metrics: BenchmarkMetrics
    configuration_name: str = "default"

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "random_seed": self.random_seed,
            "configuration_name": self.configuration_name,
            "metrics": asdict(self.metrics),
            "scenarios": [ev.to_dict() for ev in self.evaluations],
        }

    def to_markdown(self) -> str:
        """Render a concise, human-readable scientific markdown report."""
        p_macro = f"{self.metrics.mean_precision:.4f} (n={self.metrics.n_scenarios_precision_defined})" if self.metrics.mean_precision is not None else f"N/A (0/{self.metrics.total_scenarios})"
        p_micro = f"{self.metrics.overall_precision:.4f}" if self.metrics.overall_precision is not None else "N/A"
        r_macro = f"{self.metrics.mean_recall:.4f} (n={self.metrics.n_scenarios_recall_defined})" if self.metrics.mean_recall is not None else f"N/A (0/{self.metrics.total_scenarios})"
        r_micro = f"{self.metrics.overall_recall:.4f}" if self.metrics.overall_recall is not None else "N/A"
        f1_macro = f"{self.metrics.mean_f1:.4f} (n={self.metrics.n_scenarios_f1_defined})" if self.metrics.mean_f1 is not None else f"N/A (0/{self.metrics.total_scenarios})"
        f1_micro = f"{self.metrics.overall_f1:.4f}" if self.metrics.overall_f1 is not None else "N/A"
        fpr_micro = self.metrics.overall_fp / max(1, self.metrics.overall_fp + self.metrics.overall_tn)

        lines = [
            "# TCMIM Stage 2 - Synthetic Multi-Machine Benchmark Report",
            f"**Execution Timestamp:** {self.timestamp} (UTC)  ",
            f"**Configuration:** {self.configuration_name}  ",
            f"**Random Seed:** {self.random_seed}  ",
            f"**Total Scenarios:** {self.metrics.total_scenarios}  ",
            f"**Total Runtime:** {self.metrics.total_runtime_s:.2f}s  ",
            "",
            "---",
            "",
            "## 1. Executive Summary & Aggregate Metrics",
            "",
            "| Metric | Macro Average (Mean per Scenario) | Micro Aggregate (Overall Pool) |",
            "|---|---|---|",
            f"| **Precision** | {p_macro} | {p_micro} |",
            f"| **Recall** | {r_macro} | {r_micro} |",
            f"| **F1 Score** | {f1_macro} | {f1_micro} |",
            f"| **False Positive Rate (FPR)** | {self.metrics.mean_fpr:.4f} | {fpr_micro:.4f} |",
            f"| **Lag MAE (s)** | {self.metrics.mean_lag_mae_s:.3f}s | - |",
            f"| **Lag RMSE (s)** | {self.metrics.mean_lag_rmse_s:.3f}s | - |",
            f"| **Missing Delay Rate** | {self.metrics.overall_missing_lag_rate * 100:.1f}% ({self.metrics.total_eligible_lags - self.metrics.total_finite_lags}/{self.metrics.total_eligible_lags}) | - |",
            "",
            "### Confusion Counts Summary",
            f"- **True Positives (TP):** {self.metrics.overall_tp}",
            f"- **False Positives (FP):** {self.metrics.overall_fp}",
            f"- **False Negatives (FN):** {self.metrics.overall_fn}",
            f"- **True Negatives (TN):** {self.metrics.overall_tn}",
            f"- **Candidate Edges Filtered Out:** {self.metrics.total_filtered_edges}",
            "",
            "---",
            "",
            "## 2. Per-Scenario Benchmark Breakdown",
            "",
            "| # | Scenario | GT Edges | Predicted Edges | Filtered | TP | FP | FN | TN | Precision | Recall | F1 | FPR | Lag MAE | Runtime |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]

        for i, ev in enumerate(self.evaluations, start=1):
            gt_str = ", ".join(f"{s}->{t}" for s, t in ev.ground_truth_edges) or "none"
            pred_str = ", ".join(f"{s}->{t}" for s, t in ev.predicted_edges) or "none"
            mae_str = f"{ev.lag_mae_s:.2f}s" if not math.isnan(ev.lag_mae_s) else "N/A"
            p_str = f"{ev.precision:.3f}" if ev.precision is not None else "N/A"
            r_str = f"{ev.recall:.3f}" if ev.recall is not None else "N/A"
            f1_str = f"{ev.f1_score:.3f}" if ev.f1_score is not None else "N/A"
            lines.append(
                f"| {i} | **{ev.scenario_name}** | `{gt_str}` | `{pred_str}` | {ev.filtered_edge_count} | "
                f"{ev.tp} | {ev.fp} | {ev.fn} | {ev.tn} | "
                f"{p_str} | {r_str} | {f1_str} | {ev.fpr:.3f} | "
                f"{mae_str} | {ev.execution_time_s:.3f}s |"
            )

        lines.extend([
            "",
            "---",
            "",
            "## 3. Detailed Scenario Diagnostics & Delay Accuracy",
            "",
        ])

        for ev in self.evaluations:
            p_detail = f"{ev.precision:.4f}" if ev.precision is not None else "N/A"
            r_detail = f"{ev.recall:.4f}" if ev.recall is not None else "N/A"
            f1_detail = f"{ev.f1_score:.4f}" if ev.f1_score is not None else "N/A"
            lines.append(f"### {ev.scenario_name} (`{ev.scenario_id}`)")
            lines.append(f"- **Description:** {ev.scenario_name}")
            lines.append(f"- **Confusion Breakdown:** TP={ev.tp}, FP={ev.fp}, FN={ev.fn}, TN={ev.tn} (out of {ev.n_possible_pairs} possible directed pairs)")
            lines.append(f"- **Metrics:** Precision={p_detail}, Recall={r_detail}, F1={f1_detail}, FPR={ev.fpr:.4f}")

            if ev.edge_delay_errors:
                lines.append("- **Delay Errors (Recovered Edges):**")
                for edge_str, err_data in ev.edge_delay_errors.items():
                    lines.append(
                        f"  - `{edge_str}`: Injected={err_data['true_delay_s']:.2f}s, "
                        f"Estimated={err_data['estimated_delay_s']:.2f}s, "
                        f"Error={err_data['error_s']:+.2f}s (Abs={err_data['abs_error_s']:.2f}s)"
                    )
            elif ev.eligible_lag_edges > 0:
                lines.append(f"- **Delay Errors:** All {ev.eligible_lag_edges} eligible edges lacked finite estimates.")
            else:
                lines.append("- **Delay Errors:** N/A (no ground-truth edges recovered).")

            if ev.occcd_summary:
                diag_str = ", ".join(f"{k}: {v}" for k, v in ev.occcd_summary.items())
                lines.append(f"- **OC-CCD Diagnostics:** {diag_str}")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## 4. Scientific Provenance & Methodological Limitations",
            "",
            "1. **Algorithmic Recovery vs. Physical Causality:**",
            "   This benchmark evaluates the software pipeline's mathematical capacity to identify temporal",
            "   precedence patterns and estimate consistent time lags under controlled synthetic conditions.",
            "   Temporal association does **NOT** prove physical causality between interconnected machines.",
            "",
            "2. **Synthetic Data Boundary:**",
            "   All benchmark event records are explicitly generated with `Provenance.SYNTHETIC`.",
            "   These results demonstrate software correctness and algorithmic sensitivity under synthetic conditions;",
            "   they do **NOT** constitute empirical industrial validation of propagation delays or failure propagation.",
            "",
            "3. **Transitive Reduction & Direct vs. Indirect Influence:**",
            "   In multi-stage cascade chains (e.g. A -> B -> C with delays 60s and 90s), pairwise temporal matching",
            "   identifies a temporal precedence between A and C (150s lag) within plausible delay windows.",
            "   Without graphical transitive reduction or conditional independence testing, pairwise matching",
            "   identifies both direct and indirect temporal relationships.",
            "",
            "4. **CRI Interpretation:**",
            "   The Cascade Risk Index (CRI) computed by the pipeline is an evidence-derived graph topology index,",
            "   **NOT** a calibrated failure probability or verified propagation predictor.",
            "",
            "5. **Hardware Prototype Independence:**",
            "   ESP32 hardware ingestion remains separate and is not connected to these benchmark results.",
        ])

        return "\n".join(lines)


def _default_pipeline_factory() -> Stage2Pipeline:
    """Factory creating an isolated Stage2Pipeline instance for benchmark runs."""
    return Stage2Pipeline(
        edge_config=EdgeLifecycleConfig(candidate_threshold=1),
        graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.001),
    )


def run_benchmark(
    scenarios: Optional[List[BenchmarkScenario]] = None,
    pipeline_factory: Optional[Callable[[], Stage2Pipeline]] = None,
    seed: int = 42,
    configuration_name: str = "default",
) -> BenchmarkSuiteResult:
    """Execute the full benchmark suite across all scenarios.

    Parameters
    ----------
    scenarios          : List of BenchmarkScenario instances (defaults to all 7 scenarios).
    pipeline_factory   : Callable returning a fresh Stage2Pipeline instance.
    seed               : Master random seed.
    configuration_name : Label identifying pipeline configuration.

    Returns
    -------
    BenchmarkSuiteResult with individual evaluations and aggregated metrics.
    """
    bench_scenarios = scenarios or generate_all_scenarios(seed=seed)
    make_pipeline = pipeline_factory or _default_pipeline_factory

    evaluations: List[ScenarioEvaluation] = []
    total_start = time.perf_counter()

    for sc in bench_scenarios:
        pipeline = make_pipeline()
        sc_start = time.perf_counter()
        result = pipeline.run(sc.events_by_machine)
        sc_duration = time.perf_counter() - sc_start

        eval_res = evaluate_scenario(
            sc,
            result,
            execution_time_s=sc_duration,
            configuration_name=configuration_name,
        )
        evaluations.append(eval_res)

        p_str = f"{eval_res.precision:.3f}" if eval_res.precision is not None else "N/A"
        r_str = f"{eval_res.recall:.3f}" if eval_res.recall is not None else "N/A"
        f1_str = f"{eval_res.f1_score:.3f}" if eval_res.f1_score is not None else "N/A"
        mae_val = eval_res.lag_mae_s if not math.isnan(eval_res.lag_mae_s) else -1.0
        logger.info(
            "Benchmark [%s]: P=%s, R=%s, F1=%s, MAE=%.2fs in %.3fs",
            sc.scenario_id,
            p_str,
            r_str,
            f1_str,
            mae_val,
            sc_duration,
        )

    total_runtime_s = time.perf_counter() - total_start

    # Macro averages (mean across scenarios where metric is defined)
    n = len(evaluations)
    defined_precs = [e.precision for e in evaluations if e.precision is not None]
    defined_recs = [e.recall for e in evaluations if e.recall is not None]
    defined_f1s = [e.f1_score for e in evaluations if e.f1_score is not None]
    defined_fprs = [e.fpr for e in evaluations if e.fpr is not None]

    mean_precision = float(np.mean(defined_precs)) if defined_precs else None
    mean_recall = float(np.mean(defined_recs)) if defined_recs else None
    mean_f1 = float(np.mean(defined_f1s)) if defined_f1s else None
    mean_fpr = float(np.mean(defined_fprs)) if defined_fprs else 0.0

    # Micro aggregates (pooled counts)
    tot_tp = sum(e.tp for e in evaluations)
    tot_fp = sum(e.fp for e in evaluations)
    tot_fn = sum(e.fn for e in evaluations)
    tot_tn = sum(e.tn for e in evaluations)
    tot_filtered = sum(e.filtered_edge_count for e in evaluations)

    overall_precision = round(tot_tp / (tot_tp + tot_fp), 4) if (tot_tp + tot_fp) > 0 else None
    overall_recall = round(tot_tp / (tot_tp + tot_fn), 4) if (tot_tp + tot_fn) > 0 else None
    if overall_precision is not None and overall_recall is not None and (overall_precision + overall_recall) > 0:
        overall_f1 = round(2.0 * overall_precision * overall_recall / (overall_precision + overall_recall), 4)
    elif overall_precision is not None and overall_recall is not None:
        overall_f1 = 0.0
    else:
        overall_f1 = None

    # Delay metrics across all eligible finite estimates
    finite_maes = [e.lag_mae_s for e in evaluations if not math.isnan(e.lag_mae_s)]
    finite_rmses = [e.lag_rmse_s for e in evaluations if not math.isnan(e.lag_rmse_s)]
    mean_lag_mae_s = float(np.mean(finite_maes)) if finite_maes else float("nan")
    mean_lag_rmse_s = float(np.mean(finite_rmses)) if finite_rmses else float("nan")

    total_eligible_lags = sum(e.eligible_lag_edges for e in evaluations)
    total_finite_lags = sum(e.finite_lag_estimates for e in evaluations)
    overall_missing_lag_rate = (
        (total_eligible_lags - total_finite_lags) / total_eligible_lags
        if total_eligible_lags > 0
        else 0.0
    )

    metrics = BenchmarkMetrics(
        total_scenarios=n,
        mean_precision=round(mean_precision, 4) if mean_precision is not None else None,
        mean_recall=round(mean_recall, 4) if mean_recall is not None else None,
        mean_f1=round(mean_f1, 4) if mean_f1 is not None else None,
        mean_fpr=round(mean_fpr, 4),
        overall_tp=tot_tp,
        overall_fp=tot_fp,
        overall_fn=tot_fn,
        overall_tn=tot_tn,
        overall_precision=overall_precision,
        overall_recall=overall_recall,
        overall_f1=overall_f1,
        mean_lag_mae_s=round(mean_lag_mae_s, 4) if not math.isnan(mean_lag_mae_s) else float("nan"),
        mean_lag_rmse_s=round(mean_lag_rmse_s, 4) if not math.isnan(mean_lag_rmse_s) else float("nan"),
        total_eligible_lags=total_eligible_lags,
        total_finite_lags=total_finite_lags,
        overall_missing_lag_rate=round(overall_missing_lag_rate, 4),
        total_runtime_s=round(total_runtime_s, 4),
        total_filtered_edges=tot_filtered,
        configuration_name=configuration_name,
        n_scenarios_precision_defined=len(defined_precs),
        n_scenarios_precision_undefined=n - len(defined_precs),
        n_scenarios_recall_defined=len(defined_recs),
        n_scenarios_recall_undefined=n - len(defined_recs),
        n_scenarios_f1_defined=len(defined_f1s),
        n_scenarios_f1_undefined=n - len(defined_f1s),
    )

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    return BenchmarkSuiteResult(
        timestamp=now_iso,
        random_seed=seed,
        evaluations=evaluations,
        metrics=metrics,
        configuration_name=configuration_name,
    )


# ---------------------------------------------------------------------------
# Multi-seed robustness helper
# ---------------------------------------------------------------------------

@dataclass
class MultiSeedScenarioStats:
    """Per-scenario statistics across multiple seeds."""
    scenario_id: str
    scenario_name: str
    seeds_run: int
    mean_precision: Optional[float]
    std_precision: Optional[float]
    mean_recall: Optional[float]
    std_recall: Optional[float]
    mean_f1: Optional[float]
    std_f1: Optional[float]
    mean_fpr: float
    std_fpr: float
    mean_lag_mae_s: float
    std_lag_mae_s: float
    missing_delay_rate: float
    worst_precision: Optional[float]
    worst_recall: Optional[float]
    worst_f1: Optional[float]
    worst_fpr: float
    n_seeds_precision_defined: int = 0
    n_seeds_recall_defined: int = 0
    n_seeds_f1_defined: int = 0


@dataclass
class MultiSeedBenchmarkResult:
    """Benchmark robustness results across multiple random seeds."""
    seeds: List[int]
    per_run_results: List[BenchmarkSuiteResult]
    per_scenario_stats: List[MultiSeedScenarioStats]
    deterministic_scenarios: List[str]
    stochastic_scenarios: List[str]

    def to_markdown(self) -> str:
        """Render per-scenario multi-seed robustness as a Markdown table."""
        lines = [
            "## Multi-Seed Robustness Results",
            "",
            f"**Seeds evaluated:** {self.seeds}",
            f"**Deterministic scenarios** (seed-stable): {', '.join(self.deterministic_scenarios)}",
            f"**Stochastic scenarios** (seed-sensitive): {', '.join(self.stochastic_scenarios)}",
            "",
            "| Scenario | Precision mean+/-std | Recall mean+/-std | F1 mean+/-std | FPR mean+/-std | Lag MAE mean+/-std (s) |",
            "|---|---|---|---|---|---|",
        ]
        for st in self.per_scenario_stats:
            mae_str = (
                f"{st.mean_lag_mae_s:.2f}+/-{st.std_lag_mae_s:.2f}"
                if not math.isnan(st.mean_lag_mae_s)
                else "N/A"
            )
            p_str = f"{st.mean_precision:.3f}+/-{st.std_precision:.3f}" if st.mean_precision is not None else "N/A"
            r_str = f"{st.mean_recall:.3f}+/-{st.std_recall:.3f}" if st.mean_recall is not None else "N/A"
            f1_str = f"{st.mean_f1:.3f}+/-{st.std_f1:.3f}" if st.mean_f1 is not None else "N/A"
            lines.append(
                f"| {st.scenario_name} "
                f"| {p_str} "
                f"| {r_str} "
                f"| {f1_str} "
                f"| {st.mean_fpr:.3f}+/-{st.std_fpr:.3f} "
                f"| {mae_str} |"
            )
        lines.append("")
        lines.append("*Note: Deterministic scenarios (chain, branching, ring) have sigma=0.000 because they have no stochastic components.*")
        return "\n".join(lines)


def run_benchmark_multi_seed(
    seeds: List[int],
    pipeline_factory: Optional[Callable[[], Stage2Pipeline]] = None,
    stochastic_scenario_ids: Optional[List[str]] = None,
    configuration_name: str = "default",
) -> MultiSeedBenchmarkResult:
    """Run the benchmark across multiple random seeds and compute per-scenario statistics.

    Parameters
    ----------
    seeds                   : List of master random seeds to evaluate.
    pipeline_factory        : Callable returning a fresh Stage2Pipeline for each run.
    stochastic_scenario_ids : Scenario IDs that use randomness (default: noisy + negative control).
    configuration_name      : Label identifying pipeline configuration.

    Returns
    -------
    MultiSeedBenchmarkResult with per-seed evaluations and per-scenario statistics.

    Notes
    -----
    - Deterministic scenarios (chain, branching, ring, reversed, common cause) have sigma=0
      because their event generation does not use scenario-level randomness.
    - Stochastic scenarios (noisy cascade, negative control) show variation across seeds.
    - This function does NOT modify the production pipeline or tune thresholds.
    """
    if not seeds:
        raise ValueError("seeds list must not be empty.")

    stochastic_ids = set(
        stochastic_scenario_ids
        or ["scenario_4_negative_control", "scenario_7_noisy"]
    )

    deterministic_ids: List[str] = []
    stochastic_id_list: List[str] = []

    per_run_results: List[BenchmarkSuiteResult] = []

    for seed in seeds:
        result = run_benchmark(
            seed=seed,
            pipeline_factory=pipeline_factory,
            configuration_name=configuration_name,
        )
        per_run_results.append(result)
        if not deterministic_ids:
            for ev in result.evaluations:
                if ev.scenario_id in stochastic_ids:
                    stochastic_id_list.append(ev.scenario_id)
                else:
                    deterministic_ids.append(ev.scenario_id)

    # Gather all scenario IDs from first run (order preserved)
    all_scenario_ids = [ev.scenario_id for ev in per_run_results[0].evaluations]

    per_scenario_stats: List[MultiSeedScenarioStats] = []
    for sc_id in all_scenario_ids:
        evs_for_sc = [
            ev
            for run in per_run_results
            for ev in run.evaluations
            if ev.scenario_id == sc_id
        ]
        valid_precs = [e.precision for e in evs_for_sc if e.precision is not None]
        valid_recs = [e.recall for e in evs_for_sc if e.recall is not None]
        valid_f1s = [e.f1_score for e in evs_for_sc if e.f1_score is not None]
        fprs = [e.fpr for e in evs_for_sc]
        finite_maes = [e.lag_mae_s for e in evs_for_sc if not math.isnan(e.lag_mae_s)]

        mean_precision = float(np.mean(valid_precs)) if valid_precs else None
        std_precision = float(np.std(valid_precs, ddof=0)) if valid_precs else None
        worst_precision = float(min(valid_precs)) if valid_precs else None

        mean_recall = float(np.mean(valid_recs)) if valid_recs else None
        std_recall = float(np.std(valid_recs, ddof=0)) if valid_recs else None
        worst_recall = float(min(valid_recs)) if valid_recs else None

        mean_f1 = float(np.mean(valid_f1s)) if valid_f1s else None
        std_f1 = float(np.std(valid_f1s, ddof=0)) if valid_f1s else None
        worst_f1 = float(min(valid_f1s)) if valid_f1s else None

        per_scenario_stats.append(MultiSeedScenarioStats(
            scenario_id=sc_id,
            scenario_name=evs_for_sc[0].scenario_name,
            seeds_run=len(seeds),
            mean_precision=mean_precision,
            std_precision=std_precision,
            mean_recall=mean_recall,
            std_recall=std_recall,
            mean_f1=mean_f1,
            std_f1=std_f1,
            mean_fpr=float(np.mean(fprs)),
            std_fpr=float(np.std(fprs, ddof=0)),
            mean_lag_mae_s=float(np.mean(finite_maes)) if finite_maes else float("nan"),
            std_lag_mae_s=float(np.std(finite_maes, ddof=0)) if finite_maes else float("nan"),
            missing_delay_rate=float(np.mean([e.missing_lag_rate for e in evs_for_sc])),
            worst_precision=worst_precision,
            worst_recall=worst_recall,
            worst_f1=worst_f1,
            worst_fpr=float(max(fprs)),
            n_seeds_precision_defined=len(valid_precs),
            n_seeds_recall_defined=len(valid_recs),
            n_seeds_f1_defined=len(valid_f1s),
        ))

    return MultiSeedBenchmarkResult(
        seeds=list(seeds),
        per_run_results=per_run_results,
        per_scenario_stats=per_scenario_stats,
        deterministic_scenarios=deterministic_ids,
        stochastic_scenarios=stochastic_id_list,
    )

