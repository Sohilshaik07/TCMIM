"""
tests/unit/test_stage2_pipeline.py
===================================
End-to-end integration tests for the TCMIM Stage 2 analysis pipeline.

All fixtures are explicitly marked Provenance.SYNTHETIC.
These tests verify SOFTWARE CORRECTNESS of the integrated pipeline.
They do NOT constitute empirical validation of propagation delays,
cascade risk predictions, or physical causality between machines.

Components under test (real implementations, no mocks):
  EventMatcher -> GatingPipeline -> OCCCDAnalyser -> aggregate_delay_stats
  -> EdgeManager -> DynamicGraph -> PathFinder -> CRICalculator

Coverage (14 scenarios):
  1.  Two independently identified machines, feasible delay
  2.  Source event preceding target — accepted by gating
  3.  Reverse ordering (target before source) — rejected by G2
  4.  Events outside permitted delay window — not matched
  5.  Simultaneous events — near-zero delta, T1-flagged by OC-CCD
  6.  Repeated consistent-direction observations — edge lifecycle advances
  7.  Inconsistent / alternating direction — G3 direction-consistency gate fires
  8.  Multiple machines with coincident events — multi-pair OC-CCD T3 check
  9.  Edge lifecycle progression and expiry (silence cycles)
  10. Graph snapshot and pathfinding
  11. CRI calculation and boundary cases
  12. Provenance preservation from input to output
  13. Empty streams, missing observations
  14. Deterministic results across repeated executions
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import pytest

from tcmim.cri.calculator import CRICalculator, CRIConfig
from tcmim.edge.manager import EdgeManager
from tcmim.gating.gates import GatingConfig, GatingPipeline
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder, PathFinderConfig
from tcmim.propagation.delay import aggregate_all_pairs, aggregate_delay_stats
from tcmim.propagation.matcher import EventMatcher
from tcmim.propagation.occ_ccd import OCCCDAnalyser, OCCCDConfig, OCCCDLabel
from tcmim.schemas import (
    EdgeRecord, EdgeState, EventRecord, Modality,
    PropagationObservation, Provenance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2021, 3, 1, 8, 0, 0, tzinfo=timezone.utc)


def _ev(
    machine_id: str,
    onset_offset_s: float,
    modality: Modality = Modality.PRESSURE,
    provenance: Provenance = Provenance.SYNTHETIC,
    detector: str = "isolation_forest",
    score: float = -0.20,
) -> EventRecord:
    return EventRecord(
        machine_id=machine_id,
        modality=modality,
        onset_time=_BASE_TS + timedelta(seconds=onset_offset_s),
        detector=detector,
        score=score,
        provenance=provenance,
    )


def _obs(
    src: str, tgt: str,
    delta_t_s: float,
    gate_result: str = "accepted",
    provenance: Provenance = Provenance.SYNTHETIC,
) -> PropagationObservation:
    return PropagationObservation(
        source_event=f"{src}_s_{delta_t_s}",
        target_event=f"{tgt}_t_{delta_t_s}",
        source_machine=src,
        target_machine=tgt,
        delta_t_s=delta_t_s,
        gate_result=gate_result,
        reject_reason=None if gate_result == "accepted" else "test",
        provenance=provenance,
    )


def _edge(
    src: str, tgt: str,
    state: EdgeState = EdgeState.CONFIRMED,
    confidence: float = 0.45,
    provenance: Provenance = Provenance.SYNTHETIC,
) -> EdgeRecord:
    return EdgeRecord(
        source=src, target=tgt, state=state,
        evidence_count=10, est_delay_s=120.0, confidence=confidence,
        last_updated=datetime.now(tz=timezone.utc),
        modality=Modality.PRESSURE, provenance=provenance,
    )


def _default_matcher(
    max_delay_s: float = 600.0, min_delay_s: float = 1.0
) -> EventMatcher:
    return EventMatcher(max_delay_s=max_delay_s, min_delay_s=min_delay_s)


def _default_gating(
    require_same_modality: bool = True,
    min_direction_n: int = 3,
) -> GatingPipeline:
    cfg = GatingConfig(
        min_delay_s=1.0, max_delay_s=600.0,
        require_positive_dt=True,
        require_same_modality=require_same_modality,
        min_direction_n=min_direction_n,
    )
    return GatingPipeline(cfg)


def _run_full_pipeline(
    events_by_machine: Dict[str, List[EventRecord]],
    matcher: Optional[EventMatcher] = None,
    gating: Optional[GatingPipeline] = None,
    n_edge_cycles: int = 1,
) -> Tuple:
    """Wire all Stage 2 components and return every output stage."""
    matcher = matcher or _default_matcher()
    gating = gating or _default_gating()
    event_index = {ev.event_id: ev for evs in events_by_machine.values() for ev in evs}

    observations = matcher.match_all_pairs(events_by_machine)
    accepted, rejected = gating.apply(observations, event_index=event_index)

    analyser = OCCCDAnalyser(OCCCDConfig(simultaneity_threshold_s=30.0))
    occ_results = [analyser.analyse(obs, accepted) for obs in accepted]

    delay_stats = aggregate_all_pairs(accepted)

    edge_mgr = EdgeManager()
    edges: List[EdgeRecord] = []
    for _ in range(n_edge_cycles):
        edges = edge_mgr.update(accepted)

    graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.CANDIDATE))
    snapshot = graph.update(edges)

    cri_calc = CRICalculator(CRIConfig())
    cri_records = cri_calc.compute_all(graph)

    return observations, accepted, rejected, occ_results, delay_stats, edges, snapshot, cri_records


# ---------------------------------------------------------------------------
# 1. Two independently identified machines, feasible delay
# ---------------------------------------------------------------------------

class TestFeasibleDelay:
    def test_match_produces_observation_with_correct_delta(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 120)]
        obs = _default_matcher().match(src, tgt, "A", "B")
        assert len(obs) == 1
        assert obs[0].delta_t_s == pytest.approx(120.0)
        assert obs[0].source_machine == "A"
        assert obs[0].target_machine == "B"

    def test_gating_accepts_feasible_pair(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 120)]
        obs = _default_matcher().match(src, tgt, "A", "B")
        event_index = {ev.event_id: ev for ev in src + tgt}
        accepted, rejected = _default_gating().apply(obs, event_index=event_index)
        assert len(accepted) == 1
        assert len(rejected) == 0
        assert accepted[0].gate_result == "accepted"

    def test_delay_statistic_computed_from_accepted(self):
        src = [_ev("A", 0), _ev("A", 1000)]
        tgt = [_ev("B", 120), _ev("B", 1120)]
        obs = _default_matcher().match(src, tgt, "A", "B")
        event_index = {ev.event_id: ev for ev in src + tgt}
        accepted, _ = _default_gating().apply(obs, event_index=event_index)
        stats = aggregate_delay_stats(accepted, "A", "B")
        assert stats is not None
        assert stats.n >= 1
        assert stats.mean_s > 0
        assert stats.direction_consistency == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. Source strictly precedes target — accepted
# ---------------------------------------------------------------------------

class TestPositiveDeltaAccepted:
    def test_positive_delta_passes_g2(self):
        src = [_ev("M1", 0)]
        tgt = [_ev("M2", 60)]
        obs = _default_matcher().match(src, tgt, "M1", "M2")
        event_index = {ev.event_id: ev for ev in src + tgt}
        accepted, rejected = _default_gating().apply(obs, event_index=event_index)
        assert len(accepted) == 1
        assert accepted[0].delta_t_s > 0


# ---------------------------------------------------------------------------
# 3. Reverse ordering — rejected by G2
# ---------------------------------------------------------------------------

class TestReverseOrdering:
    def test_target_before_source_not_matched_with_min_delay(self):
        src = [_ev("A", 200)]
        tgt = [_ev("B", 0)]
        # delta = t_tgt - t_src = -200s < min_delay_s=1.0 => not in window
        obs = _default_matcher(max_delay_s=600, min_delay_s=1.0).match(src, tgt, "A", "B")
        assert obs == []

    def test_gate_ordering_rejects_negative_delta(self):
        from tcmim.gating.gates import gate_ordering
        o = _obs("A", "B", -50.0)
        assert not gate_ordering(o).passed

    def test_gate_ordering_rejects_zero_delta(self):
        from tcmim.gating.gates import gate_ordering
        o = _obs("A", "B", 0.0)
        assert not gate_ordering(o).passed


# ---------------------------------------------------------------------------
# 4. Events outside the permitted delay window — not matched
# ---------------------------------------------------------------------------

class TestOutsideDelayWindow:
    def test_delay_too_large_not_matched(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 7200)]  # 2 hours > max_delay_s=600
        obs = _default_matcher(max_delay_s=600, min_delay_s=1.0).match(src, tgt, "A", "B")
        assert obs == []

    def test_delay_below_minimum_not_matched(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 0)]  # simultaneous => delta=0 < min_delay_s=1.0
        obs = _default_matcher(max_delay_s=600, min_delay_s=1.0).match(src, tgt, "A", "B")
        assert obs == []

    def test_gate_g1_rejects_out_of_range_delta(self):
        from tcmim.gating.gates import gate_delay_feasibility
        o = _obs("A", "B", 9999.0)
        assert not gate_delay_feasibility(o, min_delay_s=1.0, max_delay_s=600.0).passed


# ---------------------------------------------------------------------------
# 5. Near-simultaneous events — T1-flagged by OC-CCD
# ---------------------------------------------------------------------------

class TestSimultaneousEvents:
    def test_near_simultaneous_flagged_t1(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 5)]
        obs = EventMatcher(max_delay_s=600.0, min_delay_s=0.0).match(src, tgt, "A", "B")
        result = OCCCDAnalyser(OCCCDConfig(simultaneity_threshold_s=30.0)).analyse(obs[0], obs)
        assert result.checks["T1_SIMULTANEITY"] is True
        assert result.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE

    def test_large_delay_not_flagged_t1(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 300)]
        obs = EventMatcher(max_delay_s=600.0, min_delay_s=0.0).match(src, tgt, "A", "B")
        result = OCCCDAnalyser(OCCCDConfig(simultaneity_threshold_s=30.0)).analyse(obs[0], obs)
        assert result.checks["T1_SIMULTANEITY"] is False

    def test_every_occ_result_carries_fr_cc2_disclaimer(self):
        src = [_ev("A", 0)]
        tgt = [_ev("B", 60)]
        obs = EventMatcher(max_delay_s=600.0, min_delay_s=0.0).match(src, tgt, "A", "B")
        result = OCCCDAnalyser().analyse(obs[0], obs)
        assert "FR-CC-2" in result.note
        assert "Physical validation" in result.note


# ---------------------------------------------------------------------------
# 6. Repeated consistent observations — edge lifecycle advances
# ---------------------------------------------------------------------------

class TestEdgeLifecycleProgression:
    def _make_accepted(self, n: int, delta_t_s: float = 120.0) -> List[PropagationObservation]:
        return [_obs("A", "B", delta_t_s) for _ in range(n)]

    def test_first_observation_creates_edge(self):
        mgr = EdgeManager()
        edges = mgr.update(self._make_accepted(1))
        assert len(edges) == 1

    def test_many_consistent_observations_advance_beyond_candidate(self):
        mgr = EdgeManager()
        for _ in range(5):
            edges = mgr.update(self._make_accepted(3))
        ab = next(e for e in edges if e.source == "A" and e.target == "B")
        advanced = {EdgeState.PROVISIONAL, EdgeState.CONFIRMED, EdgeState.STRENGTHENING, EdgeState.STABLE}
        assert ab.state in advanced

    def test_confidence_positive_after_consistent_evidence(self):
        mgr = EdgeManager()
        edges = mgr.update(self._make_accepted(5))
        ab = next(e for e in edges if e.source == "A" and e.target == "B")
        assert ab.confidence > 0.0


# ---------------------------------------------------------------------------
# 7. Inconsistent / alternating direction — G3 direction-consistency gate fires
# ---------------------------------------------------------------------------

class TestDirectionConsistencyGate:
    def test_g3_skipped_when_history_too_small(self):
        from tcmim.gating.gates import gate_direction_consistency
        result = gate_direction_consistency(_obs("A", "B", 120.0), [], min_consistency=0.6, min_n=3)
        assert result.passed

    def test_g3_passes_with_consistent_history(self):
        from tcmim.gating.gates import gate_direction_consistency
        prior = [_obs("A", "B", d) for d in [50.0, 60.0, 70.0]]
        result = gate_direction_consistency(_obs("A", "B", 100.0), prior, min_consistency=0.6, min_n=3)
        assert result.passed

    def test_g3_rejects_with_mostly_negative_history(self):
        from tcmim.gating.gates import gate_direction_consistency
        # 4 negatives, 1 positive => consistency = 0.2 < 0.6
        prior = [_obs("A", "B", d) for d in [100.0, -80.0, -90.0, -70.0, -60.0]]
        result = gate_direction_consistency(_obs("A", "B", 50.0), prior, min_consistency=0.6, min_n=3)
        assert not result.passed


# ---------------------------------------------------------------------------
# 8. Multiple machines coincident — OC-CCD T3 multi-pair coincidence
# ---------------------------------------------------------------------------

class TestMultiPairCoincidence:
    def test_t3_flagged_when_many_pairs_coincide(self):
        all_obs = [
            _obs("A", "B", 5.0),
            _obs("A", "C", 5.0),
            _obs("B", "C", 5.0),
        ]
        analyser = OCCCDAnalyser(OCCCDConfig(
            coincidence_pair_threshold=2,
            coincidence_window_s=60.0,
            simultaneity_threshold_s=100.0,
        ))
        results = [analyser.analyse(o, all_obs) for o in all_obs]
        assert any(r.checks.get("T3_MULTI_PAIR_COINCIDENCE", False) for r in results)

    def test_t3_not_flagged_for_single_pair(self):
        single = [_obs("A", "B", 5.0)]
        result = OCCCDAnalyser(OCCCDConfig(coincidence_pair_threshold=2)).analyse(single[0], single)
        assert not result.checks.get("T3_MULTI_PAIR_COINCIDENCE", False)


# ---------------------------------------------------------------------------
# 9. Edge lifecycle progression and expiry on silence
# ---------------------------------------------------------------------------

class TestEdgeExpiryOnSilence:
    def _initial_obs(self, n: int = 5) -> List[PropagationObservation]:
        return [_obs("A", "B", 60.0) for _ in range(n)]

    def test_silence_increments_consecutive_silence_counter(self):
        mgr = EdgeManager()
        mgr.update(self._initial_obs(5))
        for _ in range(10):
            mgr.update([])
        entry = mgr.get_edge("A", "B")
        assert entry is not None
        assert entry.consecutive_silence >= 10

    def test_edge_degrades_after_many_silent_cycles(self):
        from tcmim.config import EdgeLifecycleConfig
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=3,
            confirmed_threshold=6, strengthening_threshold=10, stable_threshold=15,
            weakening_threshold=2, expired_threshold=5,
            min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)
        for _ in range(4):
            mgr.update(self._initial_obs(1))
        # 2 cycles of silence -> WEAKENING
        mgr.update([])
        records = mgr.update([])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state == EdgeState.WEAKENING

        # Silence reaching expired_threshold (total 5 cycles of silence) -> EXPIRED
        mgr.update([])
        mgr.update([])
        records = mgr.update([])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state == EdgeState.EXPIRED


# ---------------------------------------------------------------------------
# 10. Graph snapshot and pathfinding
# ---------------------------------------------------------------------------

class TestGraphSnapshotAndPaths:
    def _build_graph(self) -> DynamicGraph:
        edges = [
            _edge("A", "B", state=EdgeState.CONFIRMED, confidence=0.45),
            _edge("B", "C", state=EdgeState.CONFIRMED, confidence=0.40),
        ]
        g = DynamicGraph(GraphConfig(min_active_state=EdgeState.CANDIDATE))
        g.update(edges)
        return g

    def test_snapshot_nodes_and_edges(self):
        snap = self._build_graph().snapshot()
        assert snap is not None
        assert set(snap.nodes) == {"A", "B", "C"}
        assert len(snap.edges) == 2

    def test_version_increments_on_update(self):
        g = self._build_graph()
        v = g.version
        g.update([])
        assert g.version == v + 1

    def test_path_finder_discovers_two_hop_path(self):
        g = self._build_graph()
        finder = PathFinder(PathFinderConfig(max_hops=3, min_confidence=0.001))
        paths = finder.find_all_paths(g, "A")
        assert "C" in {p.target for p in paths}

    def test_path_confidence_decreases_with_hops(self):
        g = self._build_graph()
        finder = PathFinder(PathFinderConfig(max_hops=3, decay_factor=0.8, min_confidence=0.001))
        paths = finder.find_all_paths(g, "A")
        one_hop = [p for p in paths if p.n_hops == 1]
        two_hop = [p for p in paths if p.n_hops == 2]
        if one_hop and two_hop:
            assert max(p.path_confidence for p in two_hop) <= max(p.path_confidence for p in one_hop)

    def test_find_paths_to_target(self):
        g = self._build_graph()
        finder = PathFinder(PathFinderConfig(max_hops=3, min_confidence=0.001))
        paths = finder.find_paths_to(g, "C")
        assert len(paths) >= 1
        assert all(p.target == "C" for p in paths)


# ---------------------------------------------------------------------------
# 11. CRI calculation and boundary cases
# ---------------------------------------------------------------------------

class TestCRICalculation:
    def _build_graph(self, confidence: float = 0.45) -> DynamicGraph:
        g = DynamicGraph()
        g.update([_edge("A", "B", confidence=confidence)])
        return g

    def test_cri_zero_for_source_node(self):
        record = CRICalculator().compute("A", self._build_graph())
        assert record.cri == pytest.approx(0.0)

    def test_cri_positive_for_downstream_node(self):
        record = CRICalculator().compute("B", self._build_graph(confidence=0.5))
        assert record.cri > 0.0

    def test_all_cri_records_in_bounds(self):
        for r in CRICalculator().compute_all(self._build_graph()):
            assert 0.0 <= r.cri <= 1.0

    def test_cri_empty_graph_returns_empty_list(self):
        g = DynamicGraph()
        g.update([])
        assert CRICalculator().compute_all(g) == []

    def test_cri_provenance_synthetic_for_synthetic_graph(self):
        for r in CRICalculator().compute_all(self._build_graph()):
            if r.cri > 0:
                assert r.provenance == Provenance.SYNTHETIC


# ---------------------------------------------------------------------------
# 12. Provenance preservation input -> output
# ---------------------------------------------------------------------------

class TestProvenancePreservation:
    def test_synthetic_provenance_propagates_through_matcher(self):
        src = [_ev("A", 0, provenance=Provenance.SYNTHETIC)]
        tgt = [_ev("B", 120, provenance=Provenance.SYNTHETIC)]
        obs = EventMatcher(max_delay_s=600.0, min_delay_s=1.0).match(src, tgt, "A", "B")
        assert all(o.provenance == Provenance.SYNTHETIC for o in obs)

    def test_weakest_provenance_wins_in_merge(self):
        src = [_ev("A", 0, provenance=Provenance.HARDWARE)]
        tgt = [_ev("B", 120, provenance=Provenance.SYNTHETIC)]
        obs = EventMatcher(max_delay_s=600.0, min_delay_s=0.0).match(src, tgt, "A", "B")
        assert obs[0].provenance == Provenance.SYNTHETIC

    def test_synthetic_edge_provenance_in_edge_manager(self):
        mgr = EdgeManager()
        edges = mgr.update([_obs("A", "B", 60.0, provenance=Provenance.SYNTHETIC)])
        assert all(e.provenance == Provenance.SYNTHETIC for e in edges)

    def test_provenance_flows_through_full_pipeline(self):
        events = {
            "A": [_ev("A", 0), _ev("A", 1000)],
            "B": [_ev("B", 120), _ev("B", 1120)],
        }
        _, _, _, _, _, edges, snapshot, cri_records = _run_full_pipeline(events)
        for e in edges:
            assert e.provenance == Provenance.SYNTHETIC
        for r in cri_records:
            assert r.provenance in (Provenance.SYNTHETIC, Provenance.PUBLIC_DATASET)


# ---------------------------------------------------------------------------
# 13. Empty streams and missing observations
# ---------------------------------------------------------------------------

class TestEmptyAndMissingStreams:
    def test_matcher_empty_source_returns_empty(self):
        obs = EventMatcher(max_delay_s=600.0).match([], [_ev("B", 120)], "A", "B")
        assert obs == []

    def test_matcher_empty_target_returns_empty(self):
        obs = EventMatcher(max_delay_s=600.0).match([_ev("A", 0)], [], "A", "B")
        assert obs == []

    def test_gating_empty_input_returns_empty_lists(self):
        accepted, rejected = GatingPipeline().apply([])
        assert accepted == [] and rejected == []

    def test_delay_stats_no_accepted_returns_none(self):
        rejected = [_obs("A", "B", 60.0, gate_result="rejected")]
        assert aggregate_delay_stats(rejected, "A", "B") is None

    def test_edge_manager_empty_update_returns_empty(self):
        assert EdgeManager().update([]) == []

    def test_dynamic_graph_empty_update_no_active_edges(self):
        g = DynamicGraph()
        g.update([])
        assert g.active_edges() == []
        assert g.nodes() == set()

    def test_cri_empty_graph_empty_list(self):
        g = DynamicGraph()
        g.update([])
        assert CRICalculator().compute_all(g) == []

    def test_path_finder_empty_graph_returns_empty(self):
        g = DynamicGraph()
        g.update([])
        assert PathFinder().find_all_paths(g, "A") == []


# ---------------------------------------------------------------------------
# 14. Deterministic results across repeated executions
# ---------------------------------------------------------------------------

class TestDeterminism:
    def _events(self) -> Dict[str, List[EventRecord]]:
        return {
            "A": [_ev("A", 0), _ev("A", 1000), _ev("A", 2000)],
            "B": [_ev("B", 120), _ev("B", 1120), _ev("B", 2120)],
        }

    def test_matcher_deterministic(self):
        matcher = _default_matcher()
        events = self._events()
        obs1 = matcher.match_all_pairs(events)
        obs2 = matcher.match_all_pairs(events)
        assert [(o.source_machine, o.target_machine, o.delta_t_s) for o in obs1] == \
               [(o.source_machine, o.target_machine, o.delta_t_s) for o in obs2]

    def test_gating_deterministic(self):
        events = self._events()
        matcher = _default_matcher()
        event_index = {ev.event_id: ev for evs in events.values() for ev in evs}
        obs = matcher.match_all_pairs(events)
        acc1, rej1 = _default_gating().apply(obs, event_index=event_index)
        acc2, rej2 = _default_gating().apply(obs, event_index=event_index)
        assert len(acc1) == len(acc2)
        assert len(rej1) == len(rej2)

    def test_cri_deterministic_for_same_graph(self):
        g = DynamicGraph()
        g.update([_edge("A", "B", confidence=0.45)])
        calc = CRICalculator()
        r1 = [(r.target_machine, r.cri) for r in calc.compute_all(g)]
        r2 = [(r.target_machine, r.cri) for r in calc.compute_all(g)]
        assert r1 == r2


# ---------------------------------------------------------------------------
# Integrated pipeline smoke test
# ---------------------------------------------------------------------------

class TestIntegratedPipelineSmokeTest:
    """Full end-to-end pipeline smoke test.
    Verifies components wire together without errors and produce structurally
    valid outputs. NOT a claim of empirical validation.
    """

    def test_full_pipeline_runs_without_error(self):
        events = {
            "A": [_ev("A", 0), _ev("A", 1000), _ev("A", 2000)],
            "B": [_ev("B", 120), _ev("B", 1120), _ev("B", 2120)],
        }
        obs, acc, rej, occ, delay_stats, edges, snap, cri = _run_full_pipeline(events)
        for item in (obs, acc, rej, occ, delay_stats, edges, cri):
            assert isinstance(item, list)
        assert snap is not None

    def test_consistent_120s_delay_produces_accepted_observations(self):
        events = {
            "A": [_ev("A", 0), _ev("A", 1000), _ev("A", 2000)],
            "B": [_ev("B", 120), _ev("B", 1120), _ev("B", 2120)],
        }
        _, acc, _, _, _, _, _, _ = _run_full_pipeline(events)
        assert len(acc) >= 1

    def test_snapshot_provenance_synthetic(self):
        events = {"A": [_ev("A", 0)], "B": [_ev("B", 120)]}
        _, acc, _, _, _, edges, snap, _ = _run_full_pipeline(events)
        if snap and snap.edges:
            assert snap.provenance == Provenance.SYNTHETIC

    def test_all_cri_records_in_bounds(self):
        events = {
            "A": [_ev("A", 0), _ev("A", 1000)],
            "B": [_ev("B", 120), _ev("B", 1120)],
        }
        _, _, _, _, _, _, _, cri_records = _run_full_pipeline(events)
        for r in cri_records:
            assert 0.0 <= r.cri <= 1.0