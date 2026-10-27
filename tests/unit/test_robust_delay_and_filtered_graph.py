"""
tests/unit/test_robust_delay_and_filtered_graph.py
==================================================
Unit and regression tests for:
1. Robust delay aggregation (Arithmetic Mean, Median, Trimmed Mean).
2. Backward compatibility with existing delay interfaces.
3. Edge-state confidence-filtered graph views (CANDIDATE, PROVISIONAL, STABLE).
4. Consistency between graph filtering, multi-hop paths, and CRI scores.
5. Preservation of EdgeManager evidence, non-mutation of underlying lifecycle.
6. Non-finite values, NaN/Inf handling, and missing delay handling.
7. Provenance preservation across all estimators.
"""

import math
from datetime import datetime, timezone
import numpy as np
import pytest

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.config import EdgeLifecycleConfig
from tcmim.cri.calculator import CRICalculator
from tcmim.edge.manager import EdgeManager
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder, PathFinderConfig
from tcmim.propagation.delay import (
    DelayEstimator,
    DelayEstimatorConfig,
    DelayEstimatorType,
    aggregate_all_pairs,
    aggregate_delay_stats,
    compute_trimmed_mean,
)
from tcmim.schemas import (
    DelayStatistics,
    EdgeRecord,
    EdgeState,
    EventRecord,
    Modality,
    PropagationObservation,
    Provenance,
)


def _make_obs(
    src: str,
    tgt: str,
    delta: float,
    gate_result: str = "accepted",
    prov: Provenance = Provenance.SYNTHETIC,
) -> PropagationObservation:
    """Helper to create test propagation observations."""
    return PropagationObservation(
        source_event=f"ev_{src}_{delta}",
        target_event=f"ev_{tgt}_{delta}",
        source_machine=src,
        target_machine=tgt,
        delta_t_s=delta,
        gate_result=gate_result,
        reject_reason=None if gate_result == "accepted" else "test_rejected",
        provenance=prov,
    )


# ===========================================================================
# 1. Delay Estimator Algorithms & Edge Cases
# ===========================================================================

class TestDelayEstimatorAlgorithms:
    """Test arithmetic mean, median, trimmed mean on known hand-calculated numbers."""

    def test_arithmetic_mean_known_observations(self):
        """Hand-calculated: [10, 20, 30, 40, 100] -> mean = 40.0."""
        obs = [_make_obs("A", "B", d) for d in [10.0, 20.0, 30.0, 40.0, 100.0]]
        estimator = DelayEstimator(DelayEstimatorConfig(estimator="mean"))
        stats = estimator.estimate_pair(obs, "A", "B")

        assert stats is not None
        assert stats.n == 5
        assert stats.mean_s == pytest.approx(40.0, rel=1e-5)
        assert stats.estimated_delay_s == pytest.approx(40.0, rel=1e-5)
        assert stats.min_s == 10.0
        assert stats.max_s == 100.0
        assert stats.direction_consistency == 1.0

    def test_median_known_observations_odd_and_even(self):
        """Hand-calculated: odd [10, 20, 30, 40, 100] -> med = 30.0.

        even [10, 20, 30, 40] -> med = 25.0.
        """
        obs_odd = [_make_obs("A", "B", d) for d in [10.0, 20.0, 30.0, 40.0, 100.0]]
        est_med = DelayEstimator(DelayEstimatorConfig(estimator="median"))
        stats_odd = est_med.estimate_pair(obs_odd, "A", "B")
        assert stats_odd is not None
        assert stats_odd.median_s == pytest.approx(30.0, rel=1e-5)
        assert stats_odd.estimated_delay_s == pytest.approx(30.0, rel=1e-5)

        obs_even = [_make_obs("A", "B", d) for d in [10.0, 20.0, 30.0, 40.0]]
        stats_even = est_med.estimate_pair(obs_even, "A", "B")
        assert stats_even is not None
        assert stats_even.median_s == pytest.approx(25.0, rel=1e-5)
        assert stats_even.estimated_delay_s == pytest.approx(25.0, rel=1e-5)

    def test_trimmed_mean_known_observations(self):
        """Hand-calculated: [10, 20, 30, 40, 100], trim_proportion=0.2.

        k = floor(5 * 0.2) = 1. Cuts 10 and 100 -> [20, 30, 40] -> mean = 30.0.
        """
        obs = [_make_obs("A", "B", d) for d in [10.0, 20.0, 30.0, 40.0, 100.0]]
        est_trim = DelayEstimator(DelayEstimatorConfig(estimator="trimmed_mean", trim_proportion=0.2))
        stats = est_trim.estimate_pair(obs, "A", "B")

        assert stats is not None
        assert stats.trimmed_mean_s == pytest.approx(30.0, rel=1e-5)
        assert stats.estimated_delay_s == pytest.approx(30.0, rel=1e-5)
        assert stats.mean_s == pytest.approx(40.0, rel=1e-5)
        assert stats.median_s == pytest.approx(30.0, rel=1e-5)

    def test_trimmed_mean_heavy_outliers(self):
        """Outlier robustness: [60, 60, 60, 60, 600], trim=0.2.

        k = floor(5 * 0.2) = 1. Cuts 60 and 600 -> [60, 60, 60] -> mean = 60.0.
        Mean is 168.0, but trimmed mean is 60.0.
        """
        obs = [_make_obs("A", "B", d) for d in [60.0, 60.0, 60.0, 60.0, 600.0]]
        est_trim = DelayEstimator(DelayEstimatorConfig(estimator="trimmed_mean", trim_proportion=0.2))
        stats = est_trim.estimate_pair(obs, "A", "B")

        assert stats is not None
        assert stats.mean_s == pytest.approx(168.0, rel=1e-5)
        assert stats.trimmed_mean_s == pytest.approx(60.0, rel=1e-5)
        assert stats.estimated_delay_s == pytest.approx(60.0, rel=1e-5)

    def test_all_estimators_auditably_stored(self):
        """All estimators (mean, median, trimmed_mean) must be recorded regardless of choice."""
        obs = [_make_obs("A", "B", d) for d in [50.0, 52.0, 48.0, 51.0, 500.0]]
        est = DelayEstimator(DelayEstimatorConfig(estimator="median"))
        stats = est.estimate_pair(obs, "A", "B")

        assert stats is not None
        assert stats.estimator == "median"
        assert stats.mean_s is not None
        assert stats.median_s is not None
        assert stats.trimmed_mean_s is not None
        assert stats.estimated_delay_s == stats.median_s

    def test_backward_compatibility_default_is_mean(self):
        """Calling aggregate_delay_stats with default config produces arithmetic mean."""
        obs = [_make_obs("A", "B", d) for d in [10.0, 20.0, 30.0]]
        stats = aggregate_delay_stats(obs, "A", "B")

        assert stats is not None
        assert stats.estimator == "mean"
        assert stats.mean_s == pytest.approx(20.0, rel=1e-5)
        assert stats.estimated_delay_s == stats.mean_s

    def test_aggregate_all_pairs_with_estimator(self):
        """aggregate_all_pairs works with DelayEstimatorConfig."""
        obs = [
            _make_obs("A", "B", 10.0),
            _make_obs("A", "B", 100.0),
            _make_obs("B", "C", 50.0),
        ]
        config = DelayEstimatorConfig(estimator="median")
        all_stats = aggregate_all_pairs(obs, config=config)

        assert len(all_stats) == 2
        stats_ab = next(s for s in all_stats if s.source_machine == "A" and s.target_machine == "B")
        assert stats_ab.estimator == "median"
        assert stats_ab.estimated_delay_s == pytest.approx(55.0, rel=1e-5)


# ===========================================================================
# 2. Configuration Validation & Robustness to Malformed Inputs
# ===========================================================================

class TestConfigurationAndRobustness:
    """Validation of parameters and robust handling of NaN, Inf, empty data."""

    def test_invalid_estimator_name_raises(self):
        with pytest.raises(ValueError, match="Invalid estimator"):
            DelayEstimatorConfig(estimator="unsupported_estimator")

    def test_invalid_trim_proportion_negative_raises(self):
        with pytest.raises(ValueError, match="0.0 <= trim_proportion < 0.5"):
            DelayEstimatorConfig(estimator="trimmed_mean", trim_proportion=-0.05)

    def test_invalid_trim_proportion_half_or_more_raises(self):
        with pytest.raises(ValueError, match="0.0 <= trim_proportion < 0.5"):
            DelayEstimatorConfig(estimator="trimmed_mean", trim_proportion=0.5)

        with pytest.raises(ValueError, match="0.0 <= trim_proportion < 0.5"):
            DelayEstimatorConfig(estimator="trimmed_mean", trim_proportion=0.75)

    def test_non_numeric_trim_proportion_raises(self):
        with pytest.raises(TypeError, match="must be numeric"):
            DelayEstimatorConfig(trim_proportion="0.2")

    def test_empty_observations_returns_none(self):
        est = DelayEstimator()
        assert est.estimate_pair([], "A", "B") is None

    def test_all_rejected_observations_returns_none(self):
        obs = [_make_obs("A", "B", 10.0, gate_result="rejected")]
        est = DelayEstimator()
        assert est.estimate_pair(obs, "A", "B") is None

    def test_nan_and_inf_handling_filters_explicitly(self):
        """Observations containing NaN or Inf must be filtered; valid subset computed."""
        obs = [
            _make_obs("A", "B", 10.0),
            _make_obs("A", "B", float("nan")),
            _make_obs("A", "B", 20.0),
            _make_obs("A", "B", float("inf")),
            _make_obs("A", "B", 30.0),
        ]
        est = DelayEstimator(DelayEstimatorConfig(estimator="median"))
        stats = est.estimate_pair(obs, "A", "B")

        assert stats is not None
        assert stats.n == 3  # only finite ones counted
        assert stats.median_s == pytest.approx(20.0, rel=1e-5)
        assert stats.mean_s == pytest.approx(20.0, rel=1e-5)

    def test_all_non_finite_observations_returns_none(self):
        """If all observations are NaN or Inf, returns None, never converts to zero."""
        obs = [
            _make_obs("A", "B", float("nan")),
            _make_obs("A", "B", float("inf")),
        ]
        est = DelayEstimator()
        stats = est.estimate_pair(obs, "A", "B")
        assert stats is None

    def test_provenance_preservation(self):
        """Provenance of source observations is strictly preserved."""
        obs_real = [_make_obs("A", "B", 15.0, prov=Provenance.PUBLIC_DATASET)]
        stats_real = DelayEstimator().estimate_pair(obs_real, "A", "B")
        assert stats_real is not None
        assert stats_real.provenance == Provenance.PUBLIC_DATASET

        obs_synth = [_make_obs("A", "B", 15.0, prov=Provenance.SYNTHETIC)]
        stats_synth = DelayEstimator().estimate_pair(obs_synth, "A", "B")
        assert stats_synth is not None
        assert stats_synth.provenance == Provenance.SYNTHETIC


# ===========================================================================
# 3. Confidence-Filtered Graph Views & Integrity
# ===========================================================================

class TestConfidenceFilteredGraph:
    """Verifies CANDIDATE, PROVISIONAL, and STABLE graph views without mutating EdgeManager."""

    def _create_edge_record(self, src: str, tgt: str, state: EdgeState, evidence: int = 1) -> EdgeRecord:
        return EdgeRecord(
            source=src,
            target=tgt,
            state=state,
            evidence_count=evidence,
            est_delay_s=60.0,
            confidence=0.5,
            last_updated=datetime.now(tz=timezone.utc),
            modality=Modality.VIBRATION,
            provenance=Provenance.SYNTHETIC,
        )

    def test_candidate_graph_view_includes_all_active_states(self):
        """CANDIDATE graph view includes CANDIDATE, PROVISIONAL, and STABLE."""
        graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.CANDIDATE))
        records = [
            self._create_edge_record("A", "B", EdgeState.CANDIDATE, 1),
            self._create_edge_record("B", "C", EdgeState.PROVISIONAL, 3),
            self._create_edge_record("C", "D", EdgeState.STABLE, 15),
            self._create_edge_record("D", "E", EdgeState.EXPIRED, 0),
        ]
        snapshot = graph.update(records)

        assert len(graph.active_edges()) == 3
        assert len(graph.filtered_edges()) == 1  # EXPIRED filtered
        assert graph.active_edge_count == 3
        assert graph.filtered_edge_count == 1
        assert snapshot.min_active_state == EdgeState.CANDIDATE
        assert len(snapshot.edges) == 3
        assert len(snapshot.filtered_edges) == 1

    def test_provisional_graph_view_filters_out_candidate(self):
        """PROVISIONAL graph view excludes CANDIDATE edges (< rank 3)."""
        graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.PROVISIONAL))
        records = [
            self._create_edge_record("A", "B", EdgeState.CANDIDATE, 1),
            self._create_edge_record("B", "C", EdgeState.PROVISIONAL, 3),
            self._create_edge_record("C", "D", EdgeState.STABLE, 15),
        ]
        snapshot = graph.update(records)

        active = graph.active_edges()
        filtered = graph.filtered_edges()

        assert len(active) == 2
        active_pairs = {(e.source, e.target) for e in active}
        assert active_pairs == {("B", "C"), ("C", "D")}

        assert len(filtered) == 1
        assert (filtered[0].source, filtered[0].target) == ("A", "B")
        assert filtered[0].state == EdgeState.CANDIDATE

        # Graph queries must not see the CANDIDATE edge
        assert graph.get_edge("A", "B") is None
        assert graph.get_edge("B", "C") is not None
        assert "A" not in graph.nodes()

    def test_stable_graph_view_strictest_filter(self):
        """STABLE graph view excludes CANDIDATE and PROVISIONAL edges."""
        graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.STABLE))
        records = [
            self._create_edge_record("A", "B", EdgeState.CANDIDATE, 1),
            self._create_edge_record("B", "C", EdgeState.PROVISIONAL, 3),
            self._create_edge_record("C", "D", EdgeState.STABLE, 15),
        ]
        snapshot = graph.update(records)

        assert len(graph.active_edges()) == 1
        assert (graph.active_edges()[0].source, graph.active_edges()[0].target) == ("C", "D")
        assert len(graph.filtered_edges()) == 2
        assert graph.nodes() == {"C", "D"}

    def test_edge_manager_evidence_never_mutated_by_graph_view(self):
        """Graph filtering must NOT mutate EdgeManager's underlying evidence or states."""
        edge_manager = EdgeManager(EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=3))
        obs = [_make_obs("A", "B", 60.0)]
        edges = edge_manager.update(obs)

        # In EdgeManager, A->B is CANDIDATE with evidence_count=1
        em_edge = edge_manager.get_edge("A", "B")
        assert em_edge is not None
        assert em_edge.state == EdgeState.CANDIDATE
        assert em_edge.evidence_count == 1

        # Push to a PROVISIONAL graph
        graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.PROVISIONAL))
        graph.update(edges)

        # Graph filtered it out:
        assert graph.active_edge_count == 0
        assert graph.filtered_edge_count == 1

        # But EdgeManager state and evidence count remain completely intact:
        em_edge_after = edge_manager.get_edge("A", "B")
        assert em_edge_after is not None
        assert em_edge_after.state == EdgeState.CANDIDATE
        assert em_edge_after.evidence_count == 1

    def test_consistency_between_graph_filtering_paths_and_cri(self):
        """PathFinder and CRICalculator must consistently respect the graph view filter."""
        # Setup: A -> B (CANDIDATE, 1 obs), B -> C (PROVISIONAL, 3 obs)
        records = [
            self._create_edge_record("A", "B", EdgeState.CANDIDATE, 1),
            self._create_edge_record("B", "C", EdgeState.PROVISIONAL, 3),
        ]

        path_finder = PathFinder(PathFinderConfig(max_hops=3))
        cri_calc = CRICalculator()

        # 1. Under CANDIDATE graph view: A -> B -> C 2-hop path exists
        cand_graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.CANDIDATE))
        cand_graph.update(records)

        cand_paths = path_finder.find_all_paths(cand_graph, "A")
        assert any(len(p.edges) == 2 and p.target == "C" for p in cand_paths)
        cand_cri = {r.target_machine: r.cri for r in cri_calc.compute_all(cand_graph)}
        assert "C" in cand_cri

        # 2. Under PROVISIONAL graph view: A -> B is filtered out
        prov_graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.PROVISIONAL))
        prov_graph.update(records)

        # A is not in the graph, no paths from A can exist:
        prov_paths_from_a = path_finder.find_all_paths(prov_graph, "A")
        assert len(prov_paths_from_a) == 0

        # Only B -> C is active:
        prov_paths_from_b = path_finder.find_all_paths(prov_graph, "B")
        assert len(prov_paths_from_b) == 1
        assert prov_paths_from_b[0].target == "C"

        # CRI for C only reflects the 1-hop path from B:
        prov_cri = {r.target_machine: r.cri for r in cri_calc.compute_all(prov_graph)}
        assert "C" in prov_cri
        assert "A" not in prov_cri  # A has no active edges


# ===========================================================================
# 4. End-to-End Pipeline Integration & Benchmark Determinism
# ===========================================================================

class TestPipelineIntegrationAndDeterminism:
    """Verifies Stage2Pipeline with custom estimator and graph filter."""

    def test_pipeline_with_median_and_provisional_filter(self):
        """Pipeline runs with median delay estimator and provisional-or-higher graph filter."""
        pipeline = Stage2Pipeline(
            delay_config=DelayEstimatorConfig(estimator="median"),
            graph_config=GraphConfig(min_active_state=EdgeState.PROVISIONAL),
        )

        # Generate 4 events on A and 4 on B with ~60s delay
        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        events_a = [
            EventRecord(
                machine_id="A",
                modality=Modality.VIBRATION,
                onset_time=base.replace(minute=i * 5),
                detector="cusum",
                score=5.0,
                provenance=Provenance.SYNTHETIC,
            )
            for i in range(4)
        ]
        events_b = [
            EventRecord(
                machine_id="B",
                modality=Modality.VIBRATION,
                onset_time=base.replace(minute=i * 5 + 1, second=0),
                detector="cusum",
                score=5.0,
                provenance=Provenance.SYNTHETIC,
            )
            for i in range(4)
        ]

        # Cycle 1: Edge transitions NONE -> CANDIDATE (evidence_count=4)
        result1 = pipeline.run({"A": events_a, "B": events_b})
        edge1 = result1.get_edge("A", "B")
        assert edge1 is not None
        assert edge1.state == EdgeState.CANDIDATE
        # Under PROVISIONAL filter, CANDIDATE A->B is filtered out:
        filtered_pairs_1 = {(e.source, e.target) for e in result1.graph_snapshot.filtered_edges}
        assert ("A", "B") in filtered_pairs_1
        assert ("A", "B") not in {(e.source, e.target) for e in result1.graph_snapshot.edges}

        # Cycle 2: Edge transitions CANDIDATE -> PROVISIONAL
        result2 = pipeline.run({"A": events_a, "B": events_b})
        edge2 = result2.get_edge("A", "B")
        assert edge2 is not None
        assert edge2.state == EdgeState.PROVISIONAL
        assert edge2.est_delay_s == pytest.approx(60.0, rel=1e-3)

        # Under PROVISIONAL filter, PROVISIONAL A->B is now active in snapshot:
        active_pairs_2 = {(e.source, e.target) for e in result2.graph_snapshot.edges}
        assert ("A", "B") in active_pairs_2

    def test_pipeline_filters_out_candidate_when_provisional_selected(self):
        """With 1 observation, edge is CANDIDATE and filtered out of graph snapshot."""
        pipeline = Stage2Pipeline(
            graph_config=GraphConfig(min_active_state=EdgeState.PROVISIONAL),
        )

        base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ev_a = [EventRecord("A", Modality.VIBRATION, base, "cusum", 5.0, Provenance.SYNTHETIC)]
        ev_b = [EventRecord("B", Modality.VIBRATION, base.replace(second=50), "cusum", 5.0, Provenance.SYNTHETIC)]

        result = pipeline.run({"A": ev_a, "B": ev_b})

        # EdgeManager produces the CANDIDATE edge
        edge = result.get_edge("A", "B")
        assert edge is not None
        assert edge.state == EdgeState.CANDIDATE

        # Graph snapshot filters it out
        assert len(result.graph_snapshot.edges) == 0
        assert len(result.graph_snapshot.filtered_edges) == 1
        assert (result.graph_snapshot.filtered_edges[0].source, result.graph_snapshot.filtered_edges[0].target) == ("A", "B")
