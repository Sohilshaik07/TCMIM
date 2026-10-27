"""
TCMIM — Unit tests for DynamicGraph (M7, S10, FR-GR-1).

All fixtures are SYNTHETIC.
"""

import pytest
from datetime import datetime, timezone

from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig, _STATE_ORDER
from tcmim.schemas import (
    EdgeRecord, EdgeState, Modality, PropagationGraphState, Provenance
)

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_edge(
    source: str,
    target: str,
    state: EdgeState = EdgeState.CONFIRMED,
    confidence: float = 0.5,
) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        state=state,
        evidence_count=6,
        est_delay_s=60.0,
        confidence=confidence,
        last_updated=NOW,
        modality=Modality.PRESSURE,
        provenance=Provenance.SYNTHETIC,
    )


class TestDynamicGraphUpdate:
    def test_update_increments_version(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B")])
        assert graph.version == 1
        graph.update([_make_edge("B", "C")])
        assert graph.version == 2

    def test_update_returns_snapshot(self):
        graph = DynamicGraph()
        snapshot = graph.update([_make_edge("A", "B")])
        assert isinstance(snapshot, PropagationGraphState)

    def test_snapshot_version_matches_graph(self):
        graph = DynamicGraph()
        snap = graph.update([_make_edge("A", "B")])
        assert snap.version == graph.version

    def test_snapshot_nodes_correct(self):
        graph = DynamicGraph()
        snap = graph.update([_make_edge("A", "B"), _make_edge("B", "C")])
        assert set(snap.nodes) == {"A", "B", "C"}

    def test_snapshot_edges_filtered_by_min_state(self):
        """Edges below min_active_state must not appear in snapshot."""
        cfg = GraphConfig(min_active_state=EdgeState.CONFIRMED)
        graph = DynamicGraph(cfg)
        edges = [
            _make_edge("A", "B", state=EdgeState.CANDIDATE),    # below threshold
            _make_edge("C", "D", state=EdgeState.CONFIRMED),    # at threshold
        ]
        snap = graph.update(edges)
        assert len(snap.edges) == 1
        assert snap.edges[0].source == "C"

    def test_snapshot_history_retained(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B")])
        graph.update([_make_edge("C", "D")])
        assert len(graph.snapshot_history()) == 2

    def test_empty_update_produces_empty_snapshot(self):
        graph = DynamicGraph()
        snap = graph.update([])
        assert snap.nodes == []
        assert snap.edges == []

    def test_latest_snapshot_accessible(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B")])
        snap = graph.update([_make_edge("C", "D")])
        assert graph.snapshot() is snap

    def test_no_snapshot_before_update(self):
        graph = DynamicGraph()
        assert graph.snapshot() is None


class TestDynamicGraphQueries:
    @pytest.fixture
    def graph_abc(self):
        """Graph: A→B (CONFIRMED, conf=0.5), B→C (STABLE, conf=0.9)."""
        graph = DynamicGraph()
        graph.update([
            _make_edge("A", "B", state=EdgeState.CONFIRMED, confidence=0.5),
            _make_edge("B", "C", state=EdgeState.STABLE, confidence=0.9),
        ])
        return graph

    def test_successors_of_a(self, graph_abc):
        succ = graph_abc.successors("A")
        assert len(succ) == 1
        target, edge = succ[0]
        assert target == "B"

    def test_successors_of_isolated_node(self, graph_abc):
        """C has no successors in A→B→C chain."""
        assert graph_abc.successors("C") == []

    def test_predecessors_of_c(self, graph_abc):
        preds = graph_abc.predecessors("C")
        assert len(preds) == 1
        src, edge = preds[0]
        assert src == "B"

    def test_predecessors_of_root(self, graph_abc):
        """A has no predecessors."""
        assert graph_abc.predecessors("A") == []

    def test_get_edge_returns_record(self, graph_abc):
        er = graph_abc.get_edge("A", "B")
        assert er is not None
        assert er.source == "A"
        assert er.target == "B"

    def test_get_edge_returns_none_for_missing(self, graph_abc):
        assert graph_abc.get_edge("A", "C") is None

    def test_get_edge_returns_none_below_min_state(self):
        cfg = GraphConfig(min_active_state=EdgeState.CONFIRMED)
        graph = DynamicGraph(cfg)
        graph.update([_make_edge("A", "B", state=EdgeState.CANDIDATE)])
        assert graph.get_edge("A", "B") is None

    def test_nodes_returns_all_machines(self, graph_abc):
        assert graph_abc.nodes() == {"A", "B", "C"}

    def test_active_edges_count(self, graph_abc):
        assert len(graph_abc.active_edges()) == 2

    def test_edge_overwritten_on_update(self):
        """Updating with a higher-state edge for the same pair overwrites."""
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B", state=EdgeState.CANDIDATE, confidence=0.1)])
        graph.update([_make_edge("A", "B", state=EdgeState.STABLE, confidence=0.9)])
        er = graph.get_edge("A", "B")
        assert er.state == EdgeState.STABLE

    def test_provenance_weakest_wins_in_snapshot(self):
        graph = DynamicGraph()
        edges = [
            _make_edge("A", "B"),  # SYNTHETIC (default)
        ]
        snap = graph.update(edges)
        assert snap.provenance == Provenance.SYNTHETIC


class TestGraphConfig:
    def test_default_min_state_is_candidate(self):
        cfg = GraphConfig()
        assert cfg.min_active_state == EdgeState.CANDIDATE

    def test_none_and_expired_excluded_by_default(self):
        graph = DynamicGraph()
        edges = [
            _make_edge("A", "B", state=EdgeState.NONE, confidence=0.0),
            _make_edge("C", "D", state=EdgeState.EXPIRED, confidence=0.0),
        ]
        graph.update(edges)
        assert graph.active_edges() == []
