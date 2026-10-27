"""
src/tcmim/benchmark/metrics.py
==============================
Evaluation metrics and ground-truth comparison utilities for TCMIM Stage 2 benchmarks.

Metrics implemented:
- Edge Precision, Recall, F1 Score
- False Positive Rate (FPR)
- Lag Estimation Mean Absolute Error (MAE) and Root Mean Square Error (RMSE)
- Missing-delay estimation rate
- Ground-truth directed-edge confusion breakdown (TP, FP, FN, TN)
- OC-CCD common-cause diagnostics summary

Conventions:
- All possible directed edges in scenario is V x V \\ {(v, v) for v in V}.
- True Negatives (TN) is strictly counted over this finite domain.
- Lag MAE and RMSE are computed exclusively over correctly recovered edges (TP)
  with finite estimated delays. Missing/NaN delays are never treated as 0.0.
- Zero denominators are handled explicitly and documented.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from tcmim.analysis.orchestrator import PipelineResult
from tcmim.benchmark.scenarios import BenchmarkScenario


@dataclass
class ScenarioEvaluation:
    """Detailed evaluation result for one benchmark scenario.

    Attributes
    ----------
    scenario_id            : Short scenario identifier.
    scenario_name          : Human-readable scenario name.
    ground_truth_edges     : Expected directed propagation edges.
    predicted_edges        : Recovered active directed edges from pipeline.
    true_positives         : Correctly identified edges (TP).
    false_positives        : Inadvertently predicted non-edges (FP).
    false_negatives        : Missed ground-truth edges (FN).
    true_negatives         : Correctly omitted non-edges (TN).
    n_possible_pairs       : Total directed non-self pairs in scenario.
    tp                     : Count of TP.
    fp                     : Count of FP.
    fn                     : Count of FN.
    tn                     : Count of TN.
    precision              : TP / (TP + FP) with zero-denominator convention.
    recall                 : TP / (TP + FN) with zero-denominator convention.
    f1_score               : Harmonic mean of precision and recall.
    fpr                    : FP / (FP + TN) false positive rate.
    eligible_lag_edges     : Recovered ground-truth edges with defined true delay.
    finite_lag_estimates   : Eligible edges with finite estimated delay.
    missing_lag_estimates  : Eligible edges with NaN or absent delay estimate.
    missing_lag_rate       : Fraction of eligible edges lacking finite delay.
    lag_mae_s              : Mean absolute delay error on finite estimates (s).
    lag_rmse_s             : Root mean square delay error on finite estimates (s).
    edge_delay_errors      : Detailed map of (src, tgt) -> {true_s, est_s, error_s}.
    occcd_summary          : Count of OC-CCD diagnostic labels across accepted observations.
    execution_time_s       : Pipeline execution wall-clock time in seconds.
    random_seed            : Scenario random seed.
    """
    scenario_id: str
    scenario_name: str
    ground_truth_edges: List[Tuple[str, str]]
    predicted_edges: List[Tuple[str, str]]
    true_positives: List[Tuple[str, str]]
    false_positives: List[Tuple[str, str]]
    false_negatives: List[Tuple[str, str]]
    true_negatives: List[Tuple[str, str]]
    n_possible_pairs: int
    tp: int
    fp: int
    fn: int
    tn: int
    precision: Optional[float]
    recall: Optional[float]
    f1_score: Optional[float]
    fpr: float
    eligible_lag_edges: int
    finite_lag_estimates: int
    missing_lag_estimates: int
    missing_lag_rate: float
    lag_mae_s: float
    lag_rmse_s: float
    edge_delay_errors: Dict[str, Dict[str, float]]
    occcd_summary: Dict[str, int]
    execution_time_s: float
    random_seed: int
    filtered_edge_count: int = 0
    configuration_name: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize evaluation result to dictionary."""
        data = asdict(self)
        # Convert tuples in edge lists to readable "A->B" strings
        data["ground_truth_edges"] = [f"{s}->{t}" for s, t in self.ground_truth_edges]
        data["predicted_edges"] = [f"{s}->{t}" for s, t in self.predicted_edges]
        data["true_positives"] = [f"{s}->{t}" for s, t in self.true_positives]
        data["false_positives"] = [f"{s}->{t}" for s, t in self.false_positives]
        data["false_negatives"] = [f"{s}->{t}" for s, t in self.false_negatives]
        data["true_negatives"] = [f"{s}->{t}" for s, t in self.true_negatives]
        return data


@dataclass
class BenchmarkMetrics:
    """Aggregate benchmark metrics across all evaluated scenarios."""
    total_scenarios: int
    mean_precision: Optional[float]
    mean_recall: Optional[float]
    mean_f1: Optional[float]
    mean_fpr: float
    overall_tp: int
    overall_fp: int
    overall_fn: int
    overall_tn: int
    overall_precision: Optional[float]
    overall_recall: Optional[float]
    overall_f1: Optional[float]
    mean_lag_mae_s: float
    mean_lag_rmse_s: float
    total_eligible_lags: int
    total_finite_lags: int
    overall_missing_lag_rate: float
    total_runtime_s: float
    total_filtered_edges: int = 0
    configuration_name: str = "default"
    n_scenarios_precision_defined: int = 0
    n_scenarios_precision_undefined: int = 0
    n_scenarios_recall_defined: int = 0
    n_scenarios_recall_undefined: int = 0
    n_scenarios_f1_defined: int = 0
    n_scenarios_f1_undefined: int = 0


def evaluate_scenario(
    scenario: BenchmarkScenario,
    result: PipelineResult,
    execution_time_s: float = 0.0,
    possible_pairs: Optional[Set[Tuple[str, str]]] = None,
    configuration_name: str = "default",
) -> ScenarioEvaluation:
    """Compare Stage2Pipeline result against ground-truth benchmark scenario.

    Parameters
    ----------
    scenario         : The BenchmarkScenario defining machines and ground truth.
    result           : The PipelineResult output by Stage2Pipeline.run().
    execution_time_s : Wall-clock execution time for this scenario run.
    possible_pairs   : Optional override set of candidate directed pairs.

    Returns
    -------
    ScenarioEvaluation containing all confusion counts, metrics, and delay errors.
    """
    pairs_universe = possible_pairs or set(scenario.possible_directed_edges)
    gt_set = set(scenario.ground_truth_edges)

    # Predicted edges: active edges present in the graph snapshot
    # (edges that passed matching, gating, and achieved active lifecycle state)
    pred_set = set((e.source, e.target) for e in result.graph_snapshot.edges)

    # Confusion sets
    tp_set = gt_set & pred_set
    fp_set = pred_set - gt_set
    fn_set = gt_set - pred_set
    tn_set = (pairs_universe - gt_set) - pred_set

    tp = len(tp_set)
    fp = len(fp_set)
    fn = len(fn_set)
    tn = len(tn_set)

    # 1. Precision: TP / (TP + FP)
    # Undefined (None) if no positive predictions are made (tp + fp == 0)
    if tp + fp > 0:
        precision: Optional[float] = round(tp / (tp + fp), 4)
    else:
        precision = None

    # 2. Recall: TP / (TP + FN)
    # Undefined (None) if ground truth has zero positive edges (tp + fn == 0)
    if tp + fn > 0:
        recall: Optional[float] = round(tp / (tp + fn), 4)
    else:
        recall = None

    # 3. F1 score: harmonic mean of precision and recall
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1_score: Optional[float] = round(2.0 * precision * recall / (precision + recall), 4)
    elif precision is not None and recall is not None:
        f1_score = 0.0
    else:
        f1_score = None

    # 4. False Positive Rate (FPR) = FP / (FP + TN) = FP / N_neg
    n_neg = fp + tn
    if n_neg > 0:
        fpr = round(fp / n_neg, 4)
    else:
        fpr = 0.0

    # 5. Lag metrics over correctly recovered ground truth edges (TP)
    eligible_lag_edges = 0
    finite_lag_estimates = 0
    missing_lag_estimates = 0
    delay_errors: List[float] = []
    edge_delay_errors: Dict[str, Dict[str, float]] = {}

    for src, tgt in sorted(tp_set):
        pair_key = (src, tgt)
        if pair_key in scenario.injected_delays:
            true_delay = scenario.injected_delays[pair_key]
            eligible_lag_edges += 1

            edge_record = result.get_edge(src, tgt)
            est_delay = edge_record.est_delay_s if edge_record else float("nan")

            if est_delay is not None and not math.isnan(est_delay) and math.isfinite(est_delay):
                finite_lag_estimates += 1
                err = est_delay - true_delay
                delay_errors.append(err)
                edge_delay_errors[f"{src}->{tgt}"] = {
                    "true_delay_s": round(true_delay, 3),
                    "estimated_delay_s": round(est_delay, 3),
                    "error_s": round(err, 3),
                    "abs_error_s": round(abs(err), 3),
                }
            else:
                missing_lag_estimates += 1
                edge_delay_errors[f"{src}->{tgt}"] = {
                    "true_delay_s": round(true_delay, 3),
                    "estimated_delay_s": float("nan"),
                    "error_s": float("nan"),
                    "abs_error_s": float("nan"),
                }

    if eligible_lag_edges > 0:
        missing_lag_rate = missing_lag_estimates / eligible_lag_edges
    else:
        missing_lag_rate = 0.0

    if delay_errors:
        lag_mae_s = float(np.mean(np.abs(delay_errors)))
        lag_rmse_s = float(np.sqrt(np.mean(np.array(delay_errors) ** 2)))
    else:
        lag_mae_s = float("nan")
        lag_rmse_s = float("nan")

    # 6. OC-CCD Diagnostics Summary
    occcd_counts: Dict[str, int] = {}
    for res in result.occcd_results:
        occcd_counts[res.label] = occcd_counts.get(res.label, 0) + 1

    filtered_count = len(result.graph_snapshot.filtered_edges) if hasattr(result.graph_snapshot, "filtered_edges") else 0

    return ScenarioEvaluation(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        ground_truth_edges=sorted(gt_set),
        predicted_edges=sorted(pred_set),
        true_positives=sorted(tp_set),
        false_positives=sorted(fp_set),
        false_negatives=sorted(fn_set),
        true_negatives=sorted(tn_set),
        n_possible_pairs=len(pairs_universe),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=round(precision, 4) if precision is not None else None,
        recall=round(recall, 4) if recall is not None else None,
        f1_score=round(f1_score, 4) if f1_score is not None else None,
        fpr=round(fpr, 4),
        eligible_lag_edges=eligible_lag_edges,
        finite_lag_estimates=finite_lag_estimates,
        missing_lag_estimates=missing_lag_estimates,
        missing_lag_rate=round(missing_lag_rate, 4),
        lag_mae_s=round(lag_mae_s, 4) if not math.isnan(lag_mae_s) else float("nan"),
        lag_rmse_s=round(lag_rmse_s, 4) if not math.isnan(lag_rmse_s) else float("nan"),
        edge_delay_errors=edge_delay_errors,
        occcd_summary=occcd_counts,
        execution_time_s=round(execution_time_s, 4),
        random_seed=scenario.random_seed,
        filtered_edge_count=filtered_count,
        configuration_name=configuration_name,
    )
