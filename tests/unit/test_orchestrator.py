"""
tests/unit/test_orchestrator.py
===============================
Unit and integration tests for the Stage2Pipeline orchestrator and PipelineResult.

All test fixtures use explicitly marked Provenance.SYNTHETIC records.
These tests verify software correctness of the orchestrator, including:
- Configuration and input validation
- Empty streams and boundary cases
- Two-machine and multi-machine propagation scenarios
- Gating and G5 event-index construction
- OCCCD diagnostics generation and FR-CC-2 disclaimers
- Delay-statistics enrichment (mean_s vs explicit float('nan'))
- Edge lifecycle integration and provenance propagation
- DynamicGraph snapshot versioning
- Multi-hop pathfinding and CRI calculation
- Deterministic pipeline execution
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest

from tcmim.analysis.orchestrator import PipelineResult, Stage2Pipeline
from tcmim.config import EdgeLifecycleConfig, MatchingConfig
from tcmim.cri.calculator import CRIConfig
from tcmim.gating.gates import GatingConfig
from tcmim.graph.dynamic_graph import GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.occ_ccd import OCCCDConfig, OCCCDLabel
from tcmim.schemas import (
    EdgeState,
    EventRecord,
    Modality,
    Provenance,
)

_BASE_TS = datetime(2021, 3, 1, 8, 0, 0, tzinfo=timezone.utc)


def _make_event(
    machine_id: str,
    offset_s: float,
    modality: Modality = Modality.PRESSURE,
    provenance: Provenance = Provenance.SYNTHETIC,
    score: float = -0.25,
) -> EventRecord:
    return EventRecord(
        machine_id=machine_id,
        modality=modality,
        onset_time=_BASE_TS + timedelta(seconds=offset_s),
        detector="isolation_forest",
        score=score,
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# 1. Configuration & Input Validation
# ---------------------------------------------------------------------------

class TestPipelineValidation:
    def test_invalid_matching_config_negative_delay(self):
        with pytest.raises(ValueError, match="min_delay_s must be non-negative"):
            Stage2Pipeline(matching_config=MatchingConfig(min_delay_s=-5.0, max_delay_s=600.0))

    def test_invalid_matching_config_min_ge_max(self):
        with pytest.raises(ValueError, match="min_delay_s must be strictly less than max_delay_s"):
            Stage2Pipeline(matching_config=MatchingConfig(min_delay_s=600.0, max_delay_s=600.0))

    def test_invalid_input_type_not_mapping(self):
        pipeline = Stage2Pipeline()
        with pytest.raises(TypeError, match="events_by_machine must be a mapping"):
            pipeline.run(["not", "a", "dict"])  # type: ignore

    def test_invalid_input_machine_id_not_string(self):
        pipeline = Stage2Pipeline()
        with pytest.raises(TypeError, match="machine_id keys must be strings"):
            pipeline.run({123: [_make_event("123", 0)]})  # type: ignore

    def test_invalid_input_events_not_sequence(self):
        pipeline = Stage2Pipeline()
        with pytest.raises(TypeError, match="must be a sequence of EventRecord"):
            pipeline.run({"A": "not_a_list"})  # type: ignore

    def test_invalid_input_element_not_event_record(self):
        pipeline = Stage2Pipeline()
        with pytest.raises(TypeError, match="Expected EventRecord"):
            pipeline.run({"A": [_make_event("A", 0), "invalid_record"]})  # type: ignore


# ---------------------------------------------------------------------------
# 2. Empty Streams & Missing Observations
# ---------------------------------------------------------------------------

class TestPipelineEmptyInputs:
    def test_completely_empty_dict(self):
        pipeline = Stage2Pipeline()
        result = pipeline.run({})
        assert isinstance(result, PipelineResult)
        assert result.matched_observations == []
        assert result.accepted_observations == []
        assert result.rejected_observations == []
        assert result.occcd_results == []
        assert result.delay_statistics == []
        assert result.edges == []
        assert result.graph_snapshot.nodes == []
        assert result.paths == []
        assert result.cri_records == []
        assert result.event_index == {}

    def test_machine_streams_with_empty_lists(self):
        pipeline = Stage2Pipeline()
        result = pipeline.run({"A": [], "B": []})
        assert result.accepted_count == 0
        assert result.rejected_count == 0
        assert result.edges == []
        assert result.graph_snapshot.edges == []

    def test_single_machine_stream(self):
        pipeline = Stage2Pipeline()
        # Single machine cannot have cross-machine pairs
        result = pipeline.run({"A": [_make_event("A", 0), _make_event("A", 100)]})
        assert len(result.matched_observations) == 0
        assert len(result.edges) == 0


# ---------------------------------------------------------------------------
# 3. Two-Machine Feasible Propagation
# ---------------------------------------------------------------------------

class TestTwoMachinePropagation:
    def _run_pair(self, dt: float = 120.0) -> PipelineResult:
        pipeline = Stage2Pipeline()
        events = {
            "A": [_make_event("A", 0), _make_event("A", 1000)],
            "B": [_make_event("B", dt), _make_event("B", 1000 + dt)],
        }
        return pipeline.run(events)

    def test_two_machine_produces_accepted_observations(self):
        result = self._run_pair(120.0)
        assert result.accepted_count == 2
        assert result.rejected_count == 0
        assert all(o.source_machine == "A" and o.target_machine == "B" for o in result.accepted_observations)

    def test_delay_statistics_computed(self):
        result = self._run_pair(120.0)
        stats = result.get_delay_stats("A", "B")
        assert stats is not None
        assert stats.n == 2
        assert stats.mean_s == pytest.approx(120.0)
        assert stats.direction_consistency == pytest.approx(1.0)

    def test_edge_enriched_with_mean_delay(self):
        result = self._run_pair(120.0)
        edge = result.get_edge("A", "B")
        assert edge is not None
        assert edge.est_delay_s == pytest.approx(120.0)
        assert not math.isnan(edge.est_delay_s)
        assert edge.state == EdgeState.CANDIDATE
        assert edge.confidence > 0.0

    def test_occcd_results_generated_with_disclaimer(self):
        result = self._run_pair(120.0)
        assert len(result.occcd_results) == 2
        for res in result.occcd_results:
            assert res.label in (OCCCDLabel.PROPAGATION_CANDIDATE, OCCCDLabel.AMBIGUOUS)
            assert "FR-CC-2" in res.note
            assert "Physical validation" in res.note


# ---------------------------------------------------------------------------
# 4. Gating Rejection & Audit Preservation
# ---------------------------------------------------------------------------

class TestGatingAndAuditPreservation:
    def test_reverse_ordering_not_matched_by_matcher(self):
        pipeline = Stage2Pipeline(matching_config=MatchingConfig(min_delay_s=1.0, max_delay_s=600.0))
        # Target fires before source -> delta_t = -60s < min_delay_s
        events = {
            "A": [_make_event("A", 100)],
            "B": [_make_event("B", 40)],
        }
        result = pipeline.run(events)
        # No A -> B candidate matched because delta is negative
        assert not any(o.source_machine == "A" and o.target_machine == "B" for o in result.matched_observations)

    def test_modality_mismatch_rejected_by_g5(self):
        cfg = GatingConfig(require_same_modality=True)
        pipeline = Stage2Pipeline(gating_config=cfg)
        events = {
            "A": [_make_event("A", 0, modality=Modality.PRESSURE)],
            "B": [_make_event("B", 60, modality=Modality.VIBRATION)],
        }
        result = pipeline.run(events)
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        assert "modality mismatch" in result.rejected_observations[0].reject_reason

    def test_same_modality_accepted_by_g5(self):
        cfg = GatingConfig(require_same_modality=True)
        pipeline = Stage2Pipeline(gating_config=cfg)
        events = {
            "A": [_make_event("A", 0, modality=Modality.PRESSURE)],
            "B": [_make_event("B", 60, modality=Modality.PRESSURE)],
        }
        result = pipeline.run(events)
        assert result.accepted_count == 1
        assert result.rejected_count == 0


# ---------------------------------------------------------------------------
# 5. Delay-Statistics Enrichment & Missing Delay Handling
# ---------------------------------------------------------------------------

class TestDelayEnrichmentAndMissingStats:
    def test_missing_delay_statistics_marked_as_nan(self):
        """When an edge exists from previous cycles but receives no new delay stats,
        est_delay_s is float('nan') rather than misleading 0.0s."""
        pipeline = Stage2Pipeline()
        # Cycle 1: establish edge A -> B
        pipeline.run({
            "A": [_make_event("A", 0)],
            "B": [_make_event("B", 85.0)],
        })
        # Cycle 2: silence
        result = pipeline.run({})
        edge = result.get_edge("A", "B")
        assert edge is not None
        assert math.isnan(edge.est_delay_s)
        assert edge.est_delay_s != 0.0

    def test_enriched_delay_matches_aggregate_statistic(self):
        pipeline = Stage2Pipeline()
        deltas = [40.0, 50.0, 60.0]
        events = {
            "A": [_make_event("A", t) for t in [0, 2000, 4000]],
            "B": [_make_event("B", t + d) for t, d in zip([0, 2000, 4000], deltas)],
        }
        result = pipeline.run(events)
        edge = result.get_edge("A", "B")
        stats = result.get_delay_stats("A", "B")
        assert edge is not None and stats is not None
        assert edge.est_delay_s == pytest.approx(50.0)
        assert edge.est_delay_s == stats.mean_s


# ---------------------------------------------------------------------------
# 6. Multi-Machine Cascade & Pathfinding
# ---------------------------------------------------------------------------

class TestMultiMachineCascade:
    def test_linear_cascade_three_machines(self):
        """A -> B -> C cascade with 60s delays."""
        edge_cfg = EdgeLifecycleConfig(candidate_threshold=1)
        graph_cfg = GraphConfig(min_active_state=EdgeState.CANDIDATE)
        path_cfg = PathFinderConfig(max_hops=3, min_confidence=0.001)
        pipeline = Stage2Pipeline(
            edge_config=edge_cfg,
            graph_config=graph_cfg,
            path_finder_config=path_cfg,
        )

        events = {
            "A": [_make_event("A", 0)],
            "B": [_make_event("B", 60)],
            "C": [_make_event("C", 120)],
        }
        result = pipeline.run(events)
        assert set(result.graph_snapshot.nodes) == {"A", "B", "C"}
        assert len(result.edges) >= 2

        # Check that the 2-hop path from A to C exists
        ac_paths = [p for p in result.paths if p.source == "A" and p.target == "C"]
        assert any(p.n_hops == 2 for p in ac_paths)

    def test_cri_records_computed_for_downstream_targets(self):
        edge_cfg = EdgeLifecycleConfig(candidate_threshold=1)
        graph_cfg = GraphConfig(min_active_state=EdgeState.CANDIDATE)
        pipeline = Stage2Pipeline(edge_config=edge_cfg, graph_config=graph_cfg)

        events = {
            "A": [_make_event("A", 0)],
            "B": [_make_event("B", 60)],
        }
        result = pipeline.run(events)
        assert len(result.cri_records) >= 1
        cri_b = next((r for r in result.cri_records if r.target_machine == "B"), None)
        assert cri_b is not None
        assert 0.0 <= cri_b.cri <= 1.0


# ---------------------------------------------------------------------------
# 7. Provenance Preservation
# ---------------------------------------------------------------------------

class TestProvenancePreservation:
    def test_synthetic_provenance_flows_to_all_outputs(self):
        pipeline = Stage2Pipeline()
        events = {
            "A": [_make_event("A", 0, provenance=Provenance.SYNTHETIC)],
            "B": [_make_event("B", 60, provenance=Provenance.SYNTHETIC)],
        }
        result = pipeline.run(events)
        for obs in result.accepted_observations:
            assert obs.provenance == Provenance.SYNTHETIC
        for ds in result.delay_statistics:
            assert ds.provenance == Provenance.SYNTHETIC
        for e in result.edges:
            assert e.provenance == Provenance.SYNTHETIC
        if result.graph_snapshot.edges:
            assert result.graph_snapshot.provenance == Provenance.SYNTHETIC
        for cri in result.cri_records:
            if cri.cri > 0:
                assert cri.provenance == Provenance.SYNTHETIC


# ---------------------------------------------------------------------------
# 8. Deterministic Output & Reset
# ---------------------------------------------------------------------------

class TestDeterminismAndReset:
    def test_deterministic_output(self):
        events = {
            "A": [_make_event("A", 0), _make_event("A", 500)],
            "B": [_make_event("B", 60), _make_event("B", 560)],
        }
        p1 = Stage2Pipeline()
        r1 = p1.run(events)

        p2 = Stage2Pipeline()
        r2 = p2.run(events)

        assert r1.accepted_count == r2.accepted_count
        assert [(e.source, e.target, e.confidence, e.est_delay_s) for e in r1.edges] == \
               [(e.source, e.target, e.confidence, e.est_delay_s) for e in r2.edges]

    def test_reset_clears_pipeline_state(self):
        pipeline = Stage2Pipeline()
        events = {
            "A": [_make_event("A", 0)],
            "B": [_make_event("B", 60)],
        }
        pipeline.run(events)
        assert len(pipeline.graph.nodes()) > 0

        pipeline.reset()
        assert pipeline.graph.nodes() == set()
        empty_res = pipeline.run({})
        assert empty_res.edges == []
