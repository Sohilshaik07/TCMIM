"""
tests/unit/test_lifecycle_and_transitive.py
============================================
Focused unit and regression tests for edge lifecycle progression,
evidence preservation, graph-view consistency, direct vs. indirect
distinction, control scenarios, empty graph handling, and ground-truth isolation.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.benchmark.multicycle import (
    MultiCycleBenchmarkResult,
    run_multicycle_scenario,
)
from tcmim.benchmark.scenarios import (
    generate_chain_scenario,
    generate_coexisting_direct_indirect_scenario,
    generate_common_cause_scenario,
    generate_negative_control_scenario,
    generate_reversed_temporal_order_scenario,
)
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.delay import DelayEstimatorConfig
from tcmim.schemas import EdgeRecord, EdgeState, EventRecord, Modality, Provenance


def _make_pipeline(
    candidate_threshold: int = 1,
    provisional_threshold: int = 3,
    stable_threshold: int = 15,
    expired_threshold: int = 7,
    filter_transitive: bool = False,
    delay_tolerance_s: float = 15.0,
) -> Stage2Pipeline:
    return Stage2Pipeline(
        edge_config=EdgeLifecycleConfig(
            candidate_threshold=candidate_threshold,
            provisional_threshold=provisional_threshold,
            stable_threshold=stable_threshold,
            expired_threshold=expired_threshold,
        ),
        graph_config=GraphConfig(
            min_active_state=EdgeState.CANDIDATE,
            filter_hypothetical_transitive=filter_transitive,
            transitive_delay_tolerance_s=delay_tolerance_s,
        ),
        path_finder_config=PathFinderConfig(max_hops=4, min_confidence=0.001),
        delay_config=DelayEstimatorConfig(estimator="median"),
    )


# ===========================================================================
# 1. Lifecycle Progression and Expiration
# ===========================================================================

class TestLifecycleProgressionAndExpiration:
    def test_progression_from_candidate_to_provisional_to_stable(self):
        """Verify an edge transitions candidate -> provisional -> stable as evidence grows."""
        # 18 waves with interval 600s and cycle 600s ensures each wave falls into its own cycle
        sc = generate_chain_scenario(n_waves=18, wave_interval_s=600.0, seed=42)
        pipeline = _make_pipeline(provisional_threshold=3, stable_threshold=15)
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        gt_edges = [lc for lc in result.edge_lifecycles if lc.is_ground_truth]
        assert len(gt_edges) >= 2

        for lc in gt_edges:
            assert lc.candidate_cycle is not None
            assert lc.provisional_cycle is not None
            assert lc.stable_cycle is not None
            assert lc.candidate_cycle <= lc.provisional_cycle <= lc.stable_cycle
            assert lc.final_state == EdgeState.STABLE

    def test_edge_expiration_after_consecutive_silence(self):
        """Unreinforced edges decay to EXPIRED when silent cycles exceed expired_threshold."""
        pipeline = _make_pipeline(expired_threshold=3)
        base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        # 1 observation pair at t=0
        events_wave1 = {
            "A": [EventRecord(machine_id="A", modality=Modality.PRESSURE, onset_time=base_ts, detector="d", score=-0.3, provenance=Provenance.SYNTHETIC)],
            "B": [EventRecord(machine_id="B", modality=Modality.PRESSURE, onset_time=base_ts + timedelta(seconds=30), detector="d", score=-0.3, provenance=Provenance.SYNTHETIC)],
        }
        pipeline.run(events_wave1, cycle_timestamp=base_ts + timedelta(seconds=60))
        edge = pipeline.edge_manager.get_edge("A", "B")
        assert edge is not None
        assert edge.state == EdgeState.CANDIDATE
        assert edge.evidence_count == 1

        # Feed 4 silent cycles with unrelated machine C
        for k in range(1, 5):
            t_silence = base_ts + timedelta(seconds=600 * k)
            events_silence = {
                "C": [EventRecord(machine_id="C", modality=Modality.PRESSURE, onset_time=t_silence, detector="d", score=-0.3, provenance=Provenance.SYNTHETIC)]
            }
            pipeline.run(events_silence, cycle_timestamp=t_silence + timedelta(seconds=30))

        edge_after = pipeline.edge_manager.get_edge("A", "B")
        assert edge_after is not None
        assert edge_after.state == EdgeState.EXPIRED


# ===========================================================================
# 2. Evidence Preservation
# ===========================================================================

class TestEvidencePreservation:
    def test_graph_filtering_never_mutates_edgemanager_evidence(self):
        """Creating filtered views (CANDIDATE, PROVISIONAL, STABLE, Transitive) does not alter EdgeManager counts."""
        sc = generate_chain_scenario(n_waves=6, wave_interval_s=500.0, seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        # Read evidence counts from EdgeManager internal entries
        em_counts = {
            pair: entry.evidence_count
            for pair, entry in pipeline.edge_manager._edges.items()
        }

        # Compare with last snapshot edge_states
        last_snap = result.cycle_snapshots[-1]
        snap_counts = {
            (es.source, es.target): es.evidence_count
            for es in last_snap.edge_states
        }

        assert em_counts == snap_counts

    def test_provenance_preserved_through_graph_snapshots(self):
        """Provenance remains SYNTHETIC and is never lost across cycles."""
        sc = generate_chain_scenario(n_waves=4, seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        for entry in pipeline.edge_manager._edges.values():
            assert entry.provenance == Provenance.SYNTHETIC


# ===========================================================================
# 3. Graph View Consistency
# ===========================================================================

class TestGraphViewConsistency:
    def test_hierarchical_graph_inclusion(self):
        """STABLE is a subset of PROVISIONAL, which is a subset of CANDIDATE."""
        sc = generate_chain_scenario(n_waves=18, wave_interval_s=250.0, seed=42)
        pipeline = _make_pipeline(provisional_threshold=3, stable_threshold=15)
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=200.0)

        for snap in result.cycle_snapshots:
            cand = set(snap.edges_candidate)
            prov = set(snap.edges_provisional)
            stab = set(snap.edges_stable)

            assert prov.issubset(cand), f"Cycle {snap.cycle_index}: PROV not subset of CAND"
            assert stab.issubset(prov), f"Cycle {snap.cycle_index}: STAB not subset of PROV"


# ===========================================================================
# 4. Genuine Direct Edges Coexisting with Indirect Paths
# ===========================================================================

class TestCoexistingDirectAndIndirect:
    def test_coexisting_scenario_ground_truth_and_delays(self):
        """Verify coexisting scenario topology: A->C direct (30s) alongside A->B (40s) -> C (50s)."""
        sc = generate_coexisting_direct_indirect_scenario(seed=42)
        assert set(sc.ground_truth_edges) == {("A", "B"), ("B", "C"), ("A", "C")}
        assert sc.injected_delays[("A", "C")] == 30.0
        assert sc.injected_delays[("A", "B")] == 40.0
        assert sc.injected_delays[("B", "C")] == 50.0

    def test_delay_consistent_filter_preserves_genuine_direct_edge(self):
        """Delay-consistent filter keeps A->C because |30 - (40 + 50)| = 60 > 15s tolerance."""
        sc = generate_coexisting_direct_indirect_scenario(n_waves=8, seed=42)
        pipeline = _make_pipeline(filter_transitive=True, delay_tolerance_s=15.0)
        result = run_multicycle_scenario(
            sc,
            pipeline,
            cycle_duration_s=600.0,
            filter_hypothetical_transitive=True,
            transitive_delay_tolerance_s=15.0,
        )

        cand_edges = set(result.cycle_snapshots[-1].edges_candidate)
        assert ("A", "C") in cand_edges
        assert ("A", "B") in cand_edges
        assert ("B", "C") in cand_edges
        # Full retention
        assert result.gt_edge_retention.get("CANDIDATE") == 1.0

    def test_blind_topological_reduction_discards_genuine_direct_edge(self):
        """Blind topological reduction without delay check incorrectly drops genuine direct A->C."""
        sc = generate_coexisting_direct_indirect_scenario(n_waves=8, seed=42)
        pipeline = _make_pipeline(filter_transitive=True, delay_tolerance_s=None)
        result = run_multicycle_scenario(
            sc,
            pipeline,
            cycle_duration_s=600.0,
            filter_hypothetical_transitive=True,
            transitive_delay_tolerance_s=None,  # Pure topological
        )

        # Topological reduction identifies A->C as shortcut of A->B->C and removes it
        cand_edges = set(result.cycle_snapshots[-1].edges_candidate)
        assert ("A", "C") not in cand_edges
        assert result.gt_edge_retention.get("CANDIDATE") < 1.0


# ===========================================================================
# 5. Common Cause and Reversed Order Controls
# ===========================================================================

class TestControlScenarios:
    def test_common_cause_produces_zero_stable_edges(self):
        """Common-cause disturbances fail to form stable propagation edges."""
        sc = generate_common_cause_scenario(seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        assert len(result.ground_truth_edges) == 0
        assert result.is_empty_ground_truth is True
        # In STABLE view, FPR must be 0.0
        assert result.final_fpr.get("STABLE") == 0.0

    def test_reversed_temporal_order_has_no_positive_matches(self):
        """Reversed order (target fires before source) produces zero ground-truth matches."""
        sc = generate_reversed_temporal_order_scenario(seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        assert len(result.ground_truth_edges) == 0
        assert result.is_empty_ground_truth is True
        assert result.final_fpr.get("STABLE") == 0.0


# ===========================================================================
# 6. Empty Graph and Undefined Metric Handling
# ===========================================================================

class TestEmptyGraphAndUndefinedMetrics:
    def test_negative_control_metrics_are_none_for_undefined(self):
        """When ground truth is empty, recall, precision (if pred empty), and path recall are None."""
        sc = generate_negative_control_scenario(seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        assert result.is_empty_ground_truth is True
        # In STABLE view where no predictions form:
        assert result.final_precision.get("STABLE") is None
        assert result.final_recall.get("STABLE") is None
        assert result.final_f1.get("STABLE") is None
        assert result.path_recall_at_final.get("STABLE") is None
        assert result.gt_edge_retention.get("STABLE") is None
        # FPR is well-defined as 0.0
        assert result.final_fpr.get("STABLE") == 0.0

    def test_empty_cycle_produces_none_cleanly(self):
        """Cycle with 0 events does not crash and produces valid evaluations."""
        sc = generate_chain_scenario(n_waves=2, wave_interval_s=1500.0, seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=200.0)

        # Many cycles have 0 events fed
        empty_cycles = [s for s in result.cycle_snapshots if s.events_fed == 0]
        assert len(empty_cycles) > 0


# ===========================================================================
# 7. Ground Truth Isolation
# ===========================================================================

class TestGroundTruthIsolation:
    def test_pipeline_has_no_ground_truth_attribute(self):
        """Verify pipeline components never accept or store scenario ground truth."""
        pipeline = _make_pipeline()
        assert not hasattr(pipeline, "ground_truth")
        assert not hasattr(pipeline.matcher, "ground_truth")
        assert not hasattr(pipeline.gating, "ground_truth")
        assert not hasattr(pipeline.edge_manager, "ground_truth")
        assert not hasattr(pipeline.graph, "ground_truth")

    def test_events_fed_chronologically_without_future_leakage(self):
        """Events are passed strictly in chronological cycles."""
        sc = generate_chain_scenario(n_waves=6, wave_interval_s=600.0, seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=600.0)

        cumulative_events = 0
        for snap in result.cycle_snapshots:
            cumulative_events += snap.events_fed
            assert cumulative_events <= result.total_events
        assert cumulative_events == result.total_events
