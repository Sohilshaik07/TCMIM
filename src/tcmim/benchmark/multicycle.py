"""
src/tcmim/benchmark/multicycle.py
==================================
Chronological multi-cycle benchmark for TCMIM Stage 2.

Feeds events into Stage2Pipeline chronologically across multiple evaluation
cycles, allowing the EdgeLifecycleStateMachine to advance naturally through
NONE -> CANDIDATE -> PROVISIONAL -> STABLE.

Design principles
-----------------
- Events are divided into non-overlapping chronological cycles by wall-clock
  window (``cycle_duration_s`` seconds per cycle).
- Each cycle calls ``pipeline.run()`` with only the events falling within
  that window. State accumulates across cycles via the stateful EdgeManager.
- Ground truth is never passed into the pipeline; only post-prediction
  evaluation uses it.
- Lifecycle transitions are recorded per edge per cycle.
- Three graph views are compared each cycle:
    CANDIDATE  (default baseline)
    PROVISIONAL (>= 3 consistent observations)
    STABLE      (>= 15 consistent observations)

Scientific integrity
--------------------
- This benchmark is algorithmic validation on synthetic data.
- Results demonstrate lifecycle progression behaviour, not physical causality.
- CRI is a structural topology score, not a failure probability.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.benchmark.metrics import evaluate_scenario
from tcmim.benchmark.scenarios import BenchmarkScenario, generate_all_scenarios
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.delay import DelayEstimatorConfig
from tcmim.schemas import EdgeRecord, EdgeState, EventRecord


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CycleEdgeState:
    """Records the lifecycle state of one edge at the end of one cycle."""
    source: str
    target: str
    state: EdgeState
    evidence_count: int
    confidence: float
    est_delay_s: float


@dataclass
class CycleSnapshot:
    """Full state snapshot after one evaluation cycle."""
    cycle_index: int
    cycle_start_s: float
    cycle_end_s: float
    events_fed: int
    edges_candidate: List[Tuple[str, str]]
    edges_provisional: List[Tuple[str, str]]
    edges_stable: List[Tuple[str, str]]
    edge_states: List[CycleEdgeState]


@dataclass
class EdgeLifecycleRecord:
    """Full lifecycle trace for one directed machine pair."""
    source: str
    target: str
    is_ground_truth: bool
    first_seen_cycle: Optional[int] = None
    candidate_cycle: Optional[int] = None
    provisional_cycle: Optional[int] = None
    stable_cycle: Optional[int] = None
    expired_cycle: Optional[int] = None
    termination_status: str = ""
    final_state: Optional[EdgeState] = None
    final_evidence_count: int = 0
    final_confidence: float = 0.0
    final_est_delay_s: float = float("nan")
    evidence_by_cycle: List[int] = field(default_factory=list)
    state_by_cycle: List[Optional[str]] = field(default_factory=list)
    remains_candidate: bool = False
    is_expired: bool = False
    in_candidate_view: bool = False
    in_provisional_view: bool = False
    in_stable_view: bool = False
    in_valid_path: bool = False
    is_false_positive: bool = False
    is_hypothetical_transitive: bool = False


@dataclass
class MultiCycleEvaluation:
    """Evaluation result for one graph-view threshold at one cycle."""
    cycle_index: int
    view_threshold: str              # "CANDIDATE", "PROVISIONAL", or "STABLE"
    gt_edges: List[Tuple[str, str]]
    pred_edges: List[Tuple[str, str]]
    tp: int
    fp: int
    fn: int
    tn: int
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None
    fpr: float = 0.0
    n_possible_pairs: int = 0


@dataclass
class MultiCycleBenchmarkResult:
    """Complete results for a multi-cycle chronological scenario run."""
    scenario_id: str
    scenario_name: str
    n_machines: int
    n_cycles: int
    cycle_duration_s: float
    total_events: int
    ground_truth_edges: List[Tuple[str, str]]
    injected_delays: Dict[Tuple[str, str], float]
    cycle_snapshots: List[CycleSnapshot]
    edge_lifecycles: List[EdgeLifecycleRecord]
    per_cycle_evaluations: Dict[str, List[MultiCycleEvaluation]]   # view -> list per cycle
    final_precision: Dict[str, Optional[float]] = field(default_factory=dict)
    final_recall: Dict[str, Optional[float]] = field(default_factory=dict)
    final_f1: Dict[str, Optional[float]] = field(default_factory=dict)
    final_fpr: Dict[str, float] = field(default_factory=dict)
    path_recall_at_final: Dict[str, Optional[float]] = field(default_factory=dict)
    execution_time_s: float = 0.0
    random_seed: int = 42
    gt_edge_retention: Dict[str, Optional[float]] = field(default_factory=dict)
    false_positive_suppression_rate: Dict[str, Optional[float]] = field(default_factory=dict)
    gt_reached_candidate_count: int = 0
    gt_reached_candidate_prop: Optional[float] = None
    gt_never_reached_candidate_count: int = 0
    gt_never_reached_candidate_prop: Optional[float] = None
    gt_reached_provisional_count: int = 0
    gt_reached_provisional_prop: Optional[float] = None
    gt_never_reached_provisional_count: int = 0
    gt_never_reached_provisional_prop: Optional[float] = None
    gt_reached_stable_count: int = 0
    gt_reached_stable_prop: Optional[float] = None
    gt_never_reached_stable_count: int = 0
    gt_never_reached_stable_prop: Optional[float] = None
    median_cycles_to_candidate: Optional[float] = None
    max_cycles_to_candidate: Optional[int] = None
    median_cycles_to_provisional: Optional[float] = None
    max_cycles_to_provisional: Optional[int] = None
    median_cycles_to_stable: Optional[float] = None
    max_cycles_to_stable: Optional[int] = None
    gt_accumulating_unconfirmed_count: int = 0
    gt_never_observed_count: int = 0
    gt_unconfirmed_at_termination_count: int = 0
    gt_expired_count: int = 0
    is_empty_ground_truth: bool = False
    is_empty_prediction: Dict[str, bool] = field(default_factory=dict)
    transitive_reduction_enabled: bool = False
    n_transitive_edges_filtered: int = 0

    def true_edge_confirmation_cycles(self) -> Dict[str, Optional[int]]:
        """Return the cycle at which each GT edge first reached PROVISIONAL state."""
        result = {}
        for rec in self.edge_lifecycles:
            if rec.is_ground_truth:
                key = f"{rec.source}->{rec.target}"
                result[key] = rec.provisional_cycle
        return result

    def missed_ground_truth_edges(self) -> List[str]:
        """GT edges that never reached CANDIDATE state."""
        return [
            f"{r.source}->{r.target}"
            for r in self.edge_lifecycles
            if r.is_ground_truth and r.candidate_cycle is None
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to JSON-serializable dictionary."""
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "n_machines": self.n_machines,
            "n_cycles": self.n_cycles,
            "cycle_duration_s": self.cycle_duration_s,
            "total_events": self.total_events,
            "ground_truth_edges": [f"{s}->{t}" for s, t in self.ground_truth_edges],
            "injected_delays": dict(self.injected_delays),
            "cycle_snapshots": [
                {
                    "cycle_index": cs.cycle_index,
                    "cycle_start_s": cs.cycle_start_s,
                    "cycle_end_s": cs.cycle_end_s,
                    "events_fed": cs.events_fed,
                    "candidate_edge_count": len(cs.edges_candidate),
                    "provisional_edge_count": len(cs.edges_provisional),
                    "stable_edge_count": len(cs.edges_stable),
                }
                for cs in self.cycle_snapshots
            ],
            "edge_lifecycles": [
                {
                    "edge": f"{el.source}->{el.target}",
                    "is_ground_truth": el.is_ground_truth,
                    "is_false_positive": el.is_false_positive,
                    "is_hypothetical_transitive": el.is_hypothetical_transitive,
                    "first_seen_cycle": el.first_seen_cycle,
                    "candidate_cycle": el.candidate_cycle,
                    "provisional_cycle": el.provisional_cycle,
                    "stable_cycle": el.stable_cycle,
                    "expired_cycle": el.expired_cycle,
                    "termination_status": el.termination_status,
                    "final_state": el.final_state.value if el.final_state else None,
                    "final_evidence_count": el.final_evidence_count,
                    "final_confidence": round(el.final_confidence, 4),
                    "final_est_delay_s": None if math.isnan(el.final_est_delay_s) else round(el.final_est_delay_s, 3),
                    "remains_candidate": el.remains_candidate,
                    "is_expired": el.is_expired,
                    "in_candidate_view": el.in_candidate_view,
                    "in_provisional_view": el.in_provisional_view,
                    "in_stable_view": el.in_stable_view,
                    "in_valid_path": el.in_valid_path,
                }
                for el in self.edge_lifecycles
            ],
            "final_precision": self.final_precision,
            "final_recall": self.final_recall,
            "final_f1": self.final_f1,
            "final_fpr": self.final_fpr,
            "path_recall_at_final": self.path_recall_at_final,
            "gt_edge_retention": self.gt_edge_retention,
            "false_positive_suppression_rate": self.false_positive_suppression_rate,
            "gt_reached_candidate_count": self.gt_reached_candidate_count,
            "gt_reached_candidate_prop": self.gt_reached_candidate_prop,
            "gt_never_reached_candidate_count": self.gt_never_reached_candidate_count,
            "gt_never_reached_candidate_prop": self.gt_never_reached_candidate_prop,
            "gt_reached_provisional_count": self.gt_reached_provisional_count,
            "gt_reached_provisional_prop": self.gt_reached_provisional_prop,
            "gt_never_reached_provisional_count": self.gt_never_reached_provisional_count,
            "gt_never_reached_provisional_prop": self.gt_never_reached_provisional_prop,
            "gt_reached_stable_count": self.gt_reached_stable_count,
            "gt_reached_stable_prop": self.gt_reached_stable_prop,
            "gt_never_reached_stable_count": self.gt_never_reached_stable_count,
            "gt_never_reached_stable_prop": self.gt_never_reached_stable_prop,
            "median_cycles_to_candidate": self.median_cycles_to_candidate,
            "max_cycles_to_candidate": self.max_cycles_to_candidate,
            "median_cycles_to_provisional": self.median_cycles_to_provisional,
            "max_cycles_to_provisional": self.max_cycles_to_provisional,
            "median_cycles_to_stable": self.median_cycles_to_stable,
            "max_cycles_to_stable": self.max_cycles_to_stable,
            "gt_accumulating_unconfirmed_count": self.gt_accumulating_unconfirmed_count,
            "gt_never_observed_count": self.gt_never_observed_count,
            "gt_unconfirmed_at_termination_count": self.gt_unconfirmed_at_termination_count,
            "gt_expired_count": self.gt_expired_count,
            "is_empty_ground_truth": self.is_empty_ground_truth,
            "is_empty_prediction": self.is_empty_prediction,
            "transitive_reduction_enabled": self.transitive_reduction_enabled,
            "n_transitive_edges_filtered": self.n_transitive_edges_filtered,
            "execution_time_s": round(self.execution_time_s, 4),
            "random_seed": self.random_seed,
        }


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def _make_graph_view(
    pipeline: Stage2Pipeline,
    edges: List[EdgeRecord],
    threshold: EdgeState,
    cycle_ts: datetime,
    filter_hypothetical_transitive: bool = False,
    transitive_delay_tolerance_s: Optional[float] = None,
) -> Tuple[List[Tuple[str, str]], int]:
    """Return active (source, target) pairs for a specific edge state threshold.

    This does NOT mutate EdgeManager state. It creates a temporary DynamicGraph
    view over the current edge records filtered to the given threshold and options.
    """
    temp_graph = DynamicGraph(GraphConfig(
        min_active_state=threshold,
        filter_hypothetical_transitive=filter_hypothetical_transitive,
        transitive_delay_tolerance_s=transitive_delay_tolerance_s,
    ))
    temp_graph.update(edges, timestamp=cycle_ts)
    active = [(e.source, e.target) for e in temp_graph.active_edges()]
    return active, len(temp_graph.filtered_edges())


def _evaluate_view(
    cycle_index: int,
    view_name: str,
    pred_set: set,
    gt_set: set,
    all_pairs: set,
) -> MultiCycleEvaluation:
    n_all = len(all_pairs)
    tp_set = gt_set & pred_set
    fp_set = pred_set - gt_set
    fn_set = gt_set - pred_set
    tn_set = (all_pairs - gt_set) - pred_set

    tp = len(tp_set)
    fp = len(fp_set)
    fn = len(fn_set)
    tn = len(tn_set)

    if tp + fp > 0:
        precision = round(tp / (tp + fp), 4)
    else:
        # Precision is undefined if no positive predictions are made
        precision = None

    if tp + fn > 0:
        recall = round(tp / (tp + fn), 4)
    else:
        # Recall is undefined if ground truth has zero positive edges (e.g. negative control)
        recall = None

    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    elif precision is not None and recall is not None:
        f1 = 0.0
    else:
        f1 = None

    n_neg = fp + tn
    fpr = round(fp / n_neg, 4) if n_neg > 0 else 0.0

    return MultiCycleEvaluation(
        cycle_index=cycle_index,
        view_threshold=view_name,
        gt_edges=sorted(gt_set),
        pred_edges=sorted(pred_set),
        tp=tp, fp=fp, fn=fn, tn=tn,
        precision=precision,
        recall=recall,
        f1=f1,
        fpr=fpr,
        n_possible_pairs=n_all,
    )


def run_multicycle_scenario(
    scenario: BenchmarkScenario,
    pipeline: Stage2Pipeline,
    cycle_duration_s: float = 600.0,
    views: Optional[List[EdgeState]] = None,
    filter_hypothetical_transitive: bool = False,
    transitive_delay_tolerance_s: Optional[float] = None,
) -> MultiCycleBenchmarkResult:
    """Run one scenario chronologically across multiple evaluation cycles.

    Parameters
    ----------
    scenario                       : BenchmarkScenario with events and ground truth.
    pipeline                       : A fresh Stage2Pipeline instance (stateful across cycles).
    cycle_duration_s               : Duration of each evaluation window in seconds.
    views                          : List of EdgeState thresholds for graph-view comparison.
                                     Defaults to [CANDIDATE, PROVISIONAL, STABLE].
    filter_hypothetical_transitive : If True, excludes edges identified as hypothetical
                                     transitive shortcuts from active views.
    transitive_delay_tolerance_s   : Delay tolerance for matching direct edge delay to
                                     indirect path sum.

    Returns
    -------
    MultiCycleBenchmarkResult with per-cycle snapshots, edge lifecycle traces,
    and evaluation metrics across all specified graph views.

    Notes
    -----
    - Ground truth is never passed into the pipeline.
    - Events are assigned to cycles by their onset_time relative to the
      earliest event in the scenario (i.e. cycle_start = 0s).
    - The pipeline is called once per cycle with only the events in that window.
    - State (EdgeManager evidence) accumulates across cycles.
    """
    start_time = time.perf_counter()

    if views is None:
        views = [EdgeState.CANDIDATE, EdgeState.PROVISIONAL, EdgeState.STABLE]

    pipeline.reset()

    gt_set = set(scenario.ground_truth_edges)
    all_pairs = set(scenario.possible_directed_edges)

    # Find temporal extent from events
    all_events: List[EventRecord] = [
        ev
        for evs in scenario.events_by_machine.values()
        for ev in evs
    ]
    if not all_events:
        raise ValueError(f"Scenario '{scenario.scenario_id}' has no events.")

    t0 = min(ev.onset_time for ev in all_events)
    t_end = max(ev.onset_time for ev in all_events)
    total_span_s = (t_end - t0).total_seconds()

    n_cycles = max(1, math.ceil(total_span_s / cycle_duration_s))

    # Build per-cycle event bins
    cycle_bins: List[Dict[str, List[EventRecord]]] = [
        {m: [] for m in scenario.machines}
        for _ in range(n_cycles)
    ]
    for machine_id, evs in scenario.events_by_machine.items():
        for ev in evs:
            offset_s = (ev.onset_time - t0).total_seconds()
            cycle_idx = min(int(offset_s / cycle_duration_s), n_cycles - 1)
            cycle_bins[cycle_idx][machine_id].append(ev)

    # Track lifecycle records
    lifecycle_map: Dict[Tuple[str, str], EdgeLifecycleRecord] = {}
    for pair in all_pairs:
        src, tgt = pair
        lifecycle_map[pair] = EdgeLifecycleRecord(
            source=src,
            target=tgt,
            is_ground_truth=pair in gt_set,
        )

    cycle_snapshots: List[CycleSnapshot] = []
    per_cycle_evals: Dict[str, List[MultiCycleEvaluation]] = {
        v.value: [] for v in views
    }

    last_edges: List[EdgeRecord] = []

    for ci in range(n_cycles):
        cycle_start_s = ci * cycle_duration_s
        cycle_end_s = (ci + 1) * cycle_duration_s
        cycle_ts = t0 + timedelta(seconds=cycle_end_s)

        events_this_cycle = cycle_bins[ci]
        n_events = sum(len(evs) for evs in events_this_cycle.values())

        result = pipeline.run(
            events_by_machine=events_this_cycle,
            cycle_timestamp=cycle_ts,
        )

        last_edges = result.edges

        # Record lifecycle transitions from edges
        for edge in result.edges:
            pair = (edge.source, edge.target)
            if pair not in lifecycle_map:
                lifecycle_map[pair] = EdgeLifecycleRecord(
                    source=edge.source,
                    target=edge.target,
                    is_ground_truth=pair in gt_set,
                )
            rec = lifecycle_map[pair]

            if rec.first_seen_cycle is None:
                rec.first_seen_cycle = ci

            if edge.state == EdgeState.CANDIDATE and rec.candidate_cycle is None:
                rec.candidate_cycle = ci
            elif edge.state == EdgeState.PROVISIONAL and rec.provisional_cycle is None:
                rec.provisional_cycle = ci
                if rec.candidate_cycle is None:
                    rec.candidate_cycle = ci  # transitioned directly
            elif edge.state == EdgeState.STABLE and rec.stable_cycle is None:
                rec.stable_cycle = ci
                if rec.provisional_cycle is None:
                    rec.provisional_cycle = ci
                if rec.candidate_cycle is None:
                    rec.candidate_cycle = ci

            rec.final_state = edge.state
            rec.final_evidence_count = edge.evidence_count
            rec.final_confidence = edge.confidence
            rec.final_est_delay_s = edge.est_delay_s

        # Record cycle-by-cycle evidence counts and states
        current_edges_by_pair = {(e.source, e.target): e for e in last_edges}
        for pair, rec in lifecycle_map.items():
            e_curr = current_edges_by_pair.get(pair)
            if e_curr is not None:
                rec.evidence_by_cycle.append(e_curr.evidence_count)
                rec.state_by_cycle.append(e_curr.state.value)
            else:
                rec.evidence_by_cycle.append(0)
                rec.state_by_cycle.append(None)

        # Record cycle snapshot: edge states from all three views
        cand_pairs, _ = _make_graph_view(
            pipeline, last_edges, EdgeState.CANDIDATE, cycle_ts,
            filter_hypothetical_transitive, transitive_delay_tolerance_s,
        )
        prov_pairs, _ = _make_graph_view(
            pipeline, last_edges, EdgeState.PROVISIONAL, cycle_ts,
            filter_hypothetical_transitive, transitive_delay_tolerance_s,
        )
        stab_pairs, _ = _make_graph_view(
            pipeline, last_edges, EdgeState.STABLE, cycle_ts,
            filter_hypothetical_transitive, transitive_delay_tolerance_s,
        )

        edge_state_records = [
            CycleEdgeState(
                source=e.source,
                target=e.target,
                state=e.state,
                evidence_count=e.evidence_count,
                confidence=e.confidence,
                est_delay_s=e.est_delay_s,
            )
            for e in last_edges
        ]

        cycle_snapshots.append(CycleSnapshot(
            cycle_index=ci,
            cycle_start_s=cycle_start_s,
            cycle_end_s=cycle_end_s,
            events_fed=n_events,
            edges_candidate=cand_pairs,
            edges_provisional=prov_pairs,
            edges_stable=stab_pairs,
            edge_states=edge_state_records,
        ))

        # Evaluate each view
        for view_state in views:
            if view_state == EdgeState.CANDIDATE:
                view_pred = set(cand_pairs)
            elif view_state == EdgeState.PROVISIONAL:
                view_pred = set(prov_pairs)
            else:
                view_pred = set(stab_pairs)

            ev_result = _evaluate_view(
                ci, view_state.value, view_pred, gt_set, all_pairs
            )
            per_cycle_evals[view_state.value].append(ev_result)

    # Final metrics per view
    final_evals = {
        v: per_cycle_evals[v][-1] if per_cycle_evals[v] else None
        for v in per_cycle_evals
    }

    final_precision = {v: (e.precision if e else None) for v, e in final_evals.items()}
    final_recall = {v: (e.recall if e else None) for v, e in final_evals.items()}
    final_f1 = {v: (e.f1 if e else None) for v, e in final_evals.items()}
    final_fpr = {v: (e.fpr if e else 0.0) for v, e in final_evals.items()}

    # Path recall at final cycle: are all GT edges reachable via directed paths?
    # When ground truth is empty, path recall is undefined (None).
    path_recall: Dict[str, Optional[float]] = {}
    for view_state in views:
        key = view_state.value
        if final_evals[key]:
            pred_set = set(final_evals[key].pred_edges)
            recovered_gt = len(gt_set & pred_set)
            path_recall[key] = round(recovered_gt / len(gt_set), 4) if gt_set else None
        else:
            path_recall[key] = None if not gt_set else 0.0

    # Discover simple paths in final active graph
    final_paths = []
    for node in sorted(pipeline.graph.nodes()):
        final_paths.extend(pipeline.path_finder.find_all_paths(pipeline.graph, node))
    active_path_edges = {
        (e.source, e.target) for p in final_paths for e in p.edges
    }

    # Transitive shortcut detection on final active graph
    transitive_edge_records = pipeline.graph.identify_transitive_edges(transitive_delay_tolerance_s)
    transitive_keys = {(er.source, er.target) for er in transitive_edge_records}

    cand_set = set(cand_pairs)
    prov_set = set(prov_pairs)
    stab_set = set(stab_pairs)

    for pair, rec in lifecycle_map.items():
        rec.remains_candidate = (rec.final_state == EdgeState.CANDIDATE)
        rec.is_expired = (rec.final_state == EdgeState.EXPIRED or "EXPIRED" in rec.state_by_cycle)
        if rec.is_expired and rec.expired_cycle is None and "EXPIRED" in rec.state_by_cycle:
            rec.expired_cycle = rec.state_by_cycle.index("EXPIRED")
        rec.in_candidate_view = pair in cand_set
        rec.in_provisional_view = pair in prov_set
        rec.in_stable_view = pair in stab_set
        rec.in_valid_path = pair in active_path_edges
        rec.is_false_positive = (not rec.is_ground_truth and pair in cand_set)
        rec.is_hypothetical_transitive = pair in transitive_keys

        # Classify termination status
        if rec.stable_cycle is not None and rec.final_state == EdgeState.STABLE:
            rec.termination_status = "STABLE"
        elif rec.provisional_cycle is not None and rec.final_state in (
            EdgeState.PROVISIONAL, EdgeState.CONFIRMED, EdgeState.STRENGTHENING
        ):
            rec.termination_status = "PROVISIONAL"
        elif rec.is_expired or rec.final_state == EdgeState.EXPIRED:
            rec.termination_status = "EXPIRED"
        elif rec.candidate_cycle is not None and rec.final_evidence_count > 0:
            rec.termination_status = "ACCUMULATING_UNCONFIRMED"
        else:
            rec.termination_status = "NEVER_OBSERVED"

    # Part 2 Lifecycle and Graph-View Metrics
    n_gt = len(gt_set)
    is_empty_gt = (n_gt == 0)

    gt_edge_retention: Dict[str, Optional[float]] = {}
    if n_gt > 0:
        gt_edge_retention["CANDIDATE"] = round(len(gt_set & cand_set) / n_gt, 4)
        gt_edge_retention["PROVISIONAL"] = round(len(gt_set & prov_set) / n_gt, 4)
        gt_edge_retention["STABLE"] = round(len(gt_set & stab_set) / n_gt, 4)
    else:
        # Documented convention: retention is undefined when ground truth is empty
        gt_edge_retention["CANDIDATE"] = None
        gt_edge_retention["PROVISIONAL"] = None
        gt_edge_retention["STABLE"] = None

    fp_cand = len(cand_set - gt_set)
    fp_prov = len(prov_set - gt_set)
    fp_stab = len(stab_set - gt_set)

    false_positive_suppression_rate: Dict[str, Optional[float]] = {}
    if fp_cand > 0:
        false_positive_suppression_rate["PROVISIONAL"] = round((fp_cand - fp_prov) / fp_cand, 4)
        false_positive_suppression_rate["STABLE"] = round((fp_cand - fp_stab) / fp_cand, 4)
    else:
        false_positive_suppression_rate["PROVISIONAL"] = 1.0 if not is_empty_gt else None
        false_positive_suppression_rate["STABLE"] = 1.0 if not is_empty_gt else None

    gt_recs = [r for r in lifecycle_map.values() if r.is_ground_truth]
    cand_cycles = [r.candidate_cycle for r in gt_recs if r.candidate_cycle is not None]
    prov_cycles = [r.provisional_cycle for r in gt_recs if r.provisional_cycle is not None]
    stab_cycles = [r.stable_cycle for r in gt_recs if r.stable_cycle is not None]

    gt_reached_candidate_count = len(cand_cycles)
    gt_reached_candidate_prop = round(gt_reached_candidate_count / n_gt, 4) if n_gt > 0 else None
    gt_never_reached_candidate_count = n_gt - gt_reached_candidate_count
    gt_never_reached_candidate_prop = round(gt_never_reached_candidate_count / n_gt, 4) if n_gt > 0 else None

    gt_reached_prov_count = len(prov_cycles)
    gt_reached_prov_prop = round(gt_reached_prov_count / n_gt, 4) if n_gt > 0 else None
    gt_never_reached_provisional_count = n_gt - gt_reached_prov_count
    gt_never_reached_provisional_prop = round(gt_never_reached_provisional_count / n_gt, 4) if n_gt > 0 else None

    gt_reached_stab_count = len(stab_cycles)
    gt_reached_stab_prop = round(gt_reached_stab_count / n_gt, 4) if n_gt > 0 else None
    gt_never_reached_stable_count = n_gt - gt_reached_stab_count
    gt_never_reached_stable_prop = round(gt_never_reached_stable_count / n_gt, 4) if n_gt > 0 else None

    median_cycles_to_candidate = float(np.median(cand_cycles)) if cand_cycles else None
    max_cycles_to_candidate = int(max(cand_cycles)) if cand_cycles else None
    median_cycles_to_provisional = float(np.median(prov_cycles)) if prov_cycles else None
    max_cycles_to_provisional = int(max(prov_cycles)) if prov_cycles else None
    median_cycles_to_stable = float(np.median(stab_cycles)) if stab_cycles else None
    max_cycles_to_stable = int(max(stab_cycles)) if stab_cycles else None

    gt_accumulating_unconfirmed_count = len([r for r in gt_recs if r.termination_status == "ACCUMULATING_UNCONFIRMED"])
    gt_never_observed_count = len([r for r in gt_recs if r.termination_status == "NEVER_OBSERVED"])
    gt_unconfirmed_count = len([r for r in gt_recs if r.provisional_cycle is None])
    gt_expired_count = len([r for r in gt_recs if r.is_expired])

    is_empty_pred = {
        "CANDIDATE": len(cand_pairs) == 0,
        "PROVISIONAL": len(prov_pairs) == 0,
        "STABLE": len(stab_pairs) == 0,
    }

    n_trans_filtered = len(transitive_keys) if filter_hypothetical_transitive else 0

    elapsed = time.perf_counter() - start_time

    return MultiCycleBenchmarkResult(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        n_machines=len(scenario.machines),
        n_cycles=n_cycles,
        cycle_duration_s=cycle_duration_s,
        total_events=len(all_events),
        ground_truth_edges=sorted(gt_set),
        injected_delays={
            f"{s}->{t}": d
            for (s, t), d in scenario.injected_delays.items()
        },
        cycle_snapshots=cycle_snapshots,
        edge_lifecycles=sorted(lifecycle_map.values(), key=lambda r: (r.source, r.target)),
        per_cycle_evaluations=per_cycle_evals,
        final_precision=final_precision,
        final_recall=final_recall,
        final_f1=final_f1,
        final_fpr=final_fpr,
        path_recall_at_final=path_recall,
        gt_edge_retention=gt_edge_retention,
        false_positive_suppression_rate=false_positive_suppression_rate,
        gt_reached_candidate_count=gt_reached_candidate_count,
        gt_reached_candidate_prop=gt_reached_candidate_prop,
        gt_never_reached_candidate_count=gt_never_reached_candidate_count,
        gt_never_reached_candidate_prop=gt_never_reached_candidate_prop,
        gt_reached_provisional_count=gt_reached_prov_count,
        gt_reached_provisional_prop=gt_reached_prov_prop,
        gt_never_reached_provisional_count=gt_never_reached_provisional_count,
        gt_never_reached_provisional_prop=gt_never_reached_provisional_prop,
        gt_reached_stable_count=gt_reached_stab_count,
        gt_reached_stable_prop=gt_reached_stab_prop,
        gt_never_reached_stable_count=gt_never_reached_stable_count,
        gt_never_reached_stable_prop=gt_never_reached_stable_prop,
        median_cycles_to_candidate=median_cycles_to_candidate,
        max_cycles_to_candidate=max_cycles_to_candidate,
        median_cycles_to_provisional=median_cycles_to_provisional,
        max_cycles_to_provisional=max_cycles_to_provisional,
        median_cycles_to_stable=median_cycles_to_stable,
        max_cycles_to_stable=max_cycles_to_stable,
        gt_accumulating_unconfirmed_count=gt_accumulating_unconfirmed_count,
        gt_never_observed_count=gt_never_observed_count,
        gt_unconfirmed_at_termination_count=gt_unconfirmed_count,
        gt_expired_count=gt_expired_count,
        is_empty_ground_truth=is_empty_gt,
        is_empty_prediction=is_empty_pred,
        transitive_reduction_enabled=filter_hypothetical_transitive,
        n_transitive_edges_filtered=n_trans_filtered,
        execution_time_s=round(elapsed, 4),
        random_seed=scenario.random_seed,
    )


def run_multicycle_benchmark(
    seed: int = 42,
    cycle_duration_s: float = 600.0,
    pipeline_factory: Optional[Callable[[], Stage2Pipeline]] = None,
    scenario_ids: Optional[List[str]] = None,
    filter_hypothetical_transitive: bool = False,
    transitive_delay_tolerance_s: Optional[float] = None,
) -> List[MultiCycleBenchmarkResult]:
    """Run the full benchmark suite in chronological multi-cycle mode.

    Parameters
    ----------
    seed                           : Random seed for scenario generation.
    cycle_duration_s               : Duration of each evaluation window in seconds.
    pipeline_factory               : Callable returning a fresh Stage2Pipeline per scenario.
    scenario_ids                   : Restrict to specific scenario IDs (default: all 7).
    filter_hypothetical_transitive : If True, applies hypothetical transitive shortcut reduction.
    transitive_delay_tolerance_s   : Delay tolerance in seconds for matching direct edge delay
                                     to indirect path delay sum.

    Returns
    -------
    List of MultiCycleBenchmarkResult, one per scenario.
    """
    from tcmim.config import EdgeLifecycleConfig

    if pipeline_factory is None:
        def pipeline_factory() -> Stage2Pipeline:
            return Stage2Pipeline(
                edge_config=EdgeLifecycleConfig(
                    candidate_threshold=1,
                    provisional_threshold=3,
                    stable_threshold=15,
                ),
                graph_config=GraphConfig(
                    min_active_state=EdgeState.CANDIDATE,
                    filter_hypothetical_transitive=filter_hypothetical_transitive,
                    transitive_delay_tolerance_s=transitive_delay_tolerance_s,
                ),
                path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.001),
                delay_config=DelayEstimatorConfig(estimator="mean"),
            )

    scenarios = generate_all_scenarios(seed=seed)
    if scenario_ids:
        scenarios = [s for s in scenarios if s.scenario_id in set(scenario_ids)]

    results = []
    for sc in scenarios:
        pipeline = pipeline_factory()
        mc_result = run_multicycle_scenario(
            scenario=sc,
            pipeline=pipeline,
            cycle_duration_s=cycle_duration_s,
            filter_hypothetical_transitive=filter_hypothetical_transitive,
            transitive_delay_tolerance_s=transitive_delay_tolerance_s,
        )
        results.append(mc_result)

    return results


def multicycle_results_to_markdown(results: List[MultiCycleBenchmarkResult]) -> str:
    """Generate a comprehensive scientific Markdown report from multi-cycle benchmark results."""
    views = ["CANDIDATE", "PROVISIONAL", "STABLE"]
    lines = [
        "# TCMIM Stage 2 — Chronological Multi-Cycle Benchmark Report",
        "",
        "> **Scientific boundary:** All events are synthetic (`Provenance.SYNTHETIC`).",
        "> This benchmark demonstrates edge lifecycle progression, NOT physical industrial causality.",
        "> CRI is a structural topology score, not a failure probability.",
        "> Empty ground-truth scenarios (e.g. Negative Control) are evaluated by False Positive Count ($FP=0$)",
        "> and False Positive Rate ($FPR=0.0$), NOT by edge retention or positive predictive power.",
        "",
        "---",
        "",
        "## 1. Summary Table: Final-Cycle Metrics by Graph View",
        "",
        "| Scenario | View | P | R | F1 | FPR | Path Recall | GT Retention | FP Suppression | Cycles |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for res in results:
        for view in views:
            p = res.final_precision.get(view)
            r = res.final_recall.get(view)
            f = res.final_f1.get(view)
            fpr = res.final_fpr.get(view, 0.0)
            pr = res.path_recall_at_final.get(view)

            p_str = f"{p:.3f}" if p is not None else "N/A"
            r_str = f"{r:.3f}" if r is not None else "N/A (empty GT)"
            f_str = f"{f:.3f}" if f is not None else "N/A"
            fpr_str = f"{fpr:.3f}"
            pr_str = f"{pr:.3f}" if pr is not None else "N/A (empty GT)"

            ret = res.gt_edge_retention.get(view)
            ret_str = f"{ret:.3f}" if ret is not None else "N/A (empty GT)"

            supp = res.false_positive_suppression_rate.get(view)
            supp_str = f"{supp:.3f}" if supp is not None else "N/A"

            lines.append(
                f"| {res.scenario_name[:32]} | `{view}` | "
                f"{p_str} | {r_str} | {f_str} | {fpr_str} | {pr_str} | {ret_str} | {supp_str} | {res.n_cycles} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 2. Ground-Truth Lifecycle Confirmation & Stability Summary",
        "",
        "Tracking how genuine propagation pathways progress through thresholds: `CANDIDATE` (>= 1 obs), `PROVISIONAL` (>= 3 obs), and `STABLE` (>= 15 obs).",
        "Distinguishes edges still accumulating evidence from edges that expired or were never observed.",
        "",
        "| Scenario | GT Edges | CAND (Prop) | PROV (Prop) | STABLE (Prop) | Never PROV | Never STABLE | Med Cycles (C/P/S) | Accumulating | Never Obs | Expired GT |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for res in results:
        n_gt = len(res.ground_truth_edges)
        cand_p = f"{res.gt_reached_candidate_count} ({res.gt_reached_candidate_prop:.3f})" if res.gt_reached_candidate_prop is not None else "0 (N/A)"
        prov_p = f"{res.gt_reached_provisional_count} ({res.gt_reached_provisional_prop:.3f})" if res.gt_reached_provisional_prop is not None else "0 (N/A)"
        stab_p = f"{res.gt_reached_stable_count} ({res.gt_reached_stable_prop:.3f})" if res.gt_reached_stable_prop is not None else "0 (N/A)"
        never_prov = f"{res.gt_never_reached_provisional_count} ({res.gt_never_reached_provisional_prop:.3f})" if res.gt_never_reached_provisional_prop is not None else "0 (N/A)"
        never_stab = f"{res.gt_never_reached_stable_count} ({res.gt_never_reached_stable_prop:.3f})" if res.gt_never_reached_stable_prop is not None else "0 (N/A)"

        c_med = f"{res.median_cycles_to_candidate:.1f}" if res.median_cycles_to_candidate is not None else "-"
        p_med = f"{res.median_cycles_to_provisional:.1f}" if res.median_cycles_to_provisional is not None else "-"
        s_med = f"{res.median_cycles_to_stable:.1f}" if res.median_cycles_to_stable is not None else "-"
        med_str = f"{c_med} / {p_med} / {s_med}"

        lines.append(
            f"| {res.scenario_id} | {n_gt} | {cand_p} | {prov_p} | {stab_p} | {never_prov} | {never_stab} | {med_str} | {res.gt_accumulating_unconfirmed_count} | {res.gt_never_observed_count} | {res.gt_expired_count} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. Edge Lifecycle & Path Participation Traces",
        "",
        "Full lifecycle history for all observed machine pairs. `GT` = ground truth, `Status` = termination status, `Path?` = contributes to active path, `Trans?` = hypothetical transitive shortcut.",
        "",
        "| Scenario | Edge | GT? | First Seen | CAND | PROV | STABLE | Expired | Status | Final State | Evidence | In Path? | Transitive? |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for res in results:
        for lc in res.edge_lifecycles:
            lines.append(
                f"| {res.scenario_id} | `{lc.source}->{lc.target}` | "
                f"{'**YES**' if lc.is_ground_truth else 'no'} | "
                f"{lc.first_seen_cycle if lc.first_seen_cycle is not None else '-'} | "
                f"{lc.candidate_cycle if lc.candidate_cycle is not None else '-'} | "
                f"{lc.provisional_cycle if lc.provisional_cycle is not None else '-'} | "
                f"{lc.stable_cycle if lc.stable_cycle is not None else '-'} | "
                f"{lc.expired_cycle if lc.expired_cycle is not None else '-'} | "
                f"`{lc.termination_status}` | "
                f"`{lc.final_state.value if lc.final_state else 'NONE'}` | "
                f"{lc.final_evidence_count} | "
                f"{'YES' if lc.in_valid_path else 'no'} | "
                f"{'YES' if lc.is_hypothetical_transitive else 'no'} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 4. Per-Cycle Precision / Recall Progression (CANDIDATE view)",
        "",
        "Shows how precision and recall evolve as evidence accumulates over time windows.",
        "",
        "| Scenario | Cycle | Events | P (CAND) | R (CAND) | F1 (CAND) | P (PROV) | R (PROV) | F1 (PROV) |",
        "|---|---|---|---|---|---|---|---|---|",
    ])

    for res in results:
        cand_evals = res.per_cycle_evaluations.get("CANDIDATE", [])
        prov_evals = res.per_cycle_evaluations.get("PROVISIONAL", [])
        for snap in res.cycle_snapshots:
            ci = snap.cycle_index
            c_ev = cand_evals[ci] if ci < len(cand_evals) else None
            p_ev = prov_evals[ci] if ci < len(prov_evals) else None
            c_p = f"{c_ev.precision:.3f}" if (c_ev and c_ev.precision is not None) else "N/A"
            c_r = f"{c_ev.recall:.3f}" if (c_ev and c_ev.recall is not None) else "N/A"
            c_f1 = f"{c_ev.f1:.3f}" if (c_ev and c_ev.f1 is not None) else "N/A"
            p_p = f"{p_ev.precision:.3f}" if (p_ev and p_ev.precision is not None) else "N/A"
            p_r = f"{p_ev.recall:.3f}" if (p_ev and p_ev.recall is not None) else "N/A"
            p_f1 = f"{p_ev.f1:.3f}" if (p_ev and p_ev.f1 is not None) else "N/A"
            lines.append(
                f"| {res.scenario_id} | {ci} | {snap.events_fed} | "
                f"{c_p} | {c_r} | {c_f1} | {p_p} | {p_r} | {p_f1} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## 5. Methodological & Scientific Notes",
        "",
        "1. **Cold Start vs. Evidence Accumulation:**",
        "   - In Cycle 0, newly formed edges begin at `CANDIDATE` (evidence = 1).",
        "   - Multi-cycle accumulation is required before true edges reach `PROVISIONAL` (>= 3 observations).",
        "2. **Spurious Edge Decay in Independent Streams:**",
        "   - Negative control edges accumulate 1-2 random coincidences and never reach `PROVISIONAL`.",
        "   - As silent cycles accumulate, unreinforced candidate edges decay to `EXPIRED`.",
        "3. **Transitive Shortcuts vs. Direct Connections:**",
        "   - An edge A -> C can be proposed if delta_t = t_C - t_A <= max_delay_s (600s), even when A -> B -> C explains the delay.",
        "   - When delay consistency is evaluated (|tau_AC - (tau_AB + tau_BC)| <= tolerance), transitive shortcuts can be identified.",
        "   - Transitive reduction must remain an exploratory view filter: if genuine direct and indirect connections coexist (e.g. A->C direct cable + A->B->C mechanical cascade), blind topological transitive reduction would discard the genuine direct edge.",
        "4. **Empty Ground-Truth and Empty Prediction Conventions:**",
        "   - Precision is undefined (`None` / `N/A`) when 0 positive edges are predicted.",
        "   - Recall is undefined (`None` / `N/A`) when 0 ground-truth edges exist (e.g. negative control, reversed temporal order, common cause).",
        "   - An empty graph is NOT interpreted as evidence of high recall or precision. In negative-control scenarios, zero predicted edges correctly reflect zero false positives (FPR = 0.0, suppression = 1.0), while precision and recall are documented as undefined (N/A).",
        "   - Path recall is undefined (`None` / `N/A`) when no ground-truth propagation paths exist.",
        "5. **Integrity Boundary:**",
        "   - All benchmark data originates from synthetic fixtures (`Provenance.SYNTHETIC`).",
        "   - These results demonstrate software sensitivity and state-machine transitions, NOT physical industrial causality.",
    ])

    return "\n".join(lines)
