"""
TCMIM — Unit tests for PathFinder (M7, S11, FR-MH-1, FR-MH-2).

All fixtures are SYNTHETIC.
"""

import pytest
from datetime import datetime, timezone

from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder, PathFinderConfig, PropagationPath
from tcmim.schemas import EdgeRecord, EdgeState, Modality, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_edge(
    source: str,
    target: str,
    confidence: float = 0.5,
    state: EdgeState = EdgeState.CONFIRMED,
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


def _build_graph(*edges: EdgeRecord) -> DynamicGraph:
    graph = DynamicGraph()
    graph.update(list(edges))
    return graph


class TestPathFinderConfig:
    def test_invalid_max_hops(self):
        with pytest.raises(ValueError, match="max_hops"):
            PathFinderConfig(max_hops=0)

    def test_invalid_decay_factor(self):
        with pytest.raises(ValueError, match="decay_factor"):
            PathFinderConfig(decay_factor=0.0)

    def test_invalid_min_confidence(self):
        with pytest.raises(ValueError, match="min_confidence"):
            PathFinderConfig(min_confidence=-0.1)


class TestPathFinderFindAllPaths:
    def test_direct_edge_found(self):
        """A→B direct edge should be found as a 1-hop path."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        finder = PathFinder(PathFinderConfig(max_hops=3))
        paths = finder.find_all_paths(graph, "A")
        assert len(paths) == 1
        assert paths[0].source == "A"
        assert paths[0].target == "B"
        assert paths[0].n_hops == 1

    def test_two_hop_path_found(self):
        """A→B→C should produce paths A→B and A→B→C."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.7),
        )
        finder = PathFinder(PathFinderConfig(max_hops=3))
        paths = finder.find_all_paths(graph, "A")
        targets = {p.target for p in paths}
        assert "B" in targets
        assert "C" in targets

    def test_max_hops_limits_depth(self):
        """With max_hops=1, only direct edges returned."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.7),
        )
        finder = PathFinder(PathFinderConfig(max_hops=1))
        paths = finder.find_all_paths(graph, "A")
        targets = {p.target for p in paths}
        assert "B" in targets
        assert "C" not in targets  # 2 hops, blocked

    def test_no_cycle_in_paths(self):
        """If there is an implied cycle (A→B, B→A), no circular paths."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.5),
            _make_edge("B", "A", confidence=0.5),
        )
        finder = PathFinder(PathFinderConfig(max_hops=5))
        paths = finder.find_all_paths(graph, "A")
        for p in paths:
            assert len(set(p.nodes)) == len(p.nodes), (
                f"Cycle detected in path: {p.nodes}"
            )

    def test_path_confidence_product_of_edges(self):
        """1-hop path: path_confidence = conf × decay^0 = conf."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.6))
        finder = PathFinder(PathFinderConfig(max_hops=3, decay_factor=1.0))
        paths = finder.find_all_paths(graph, "A")
        assert paths[0].path_confidence == pytest.approx(0.6)

    def test_two_hop_path_confidence_with_decay(self):
        """2-hop path: raw = 0.8×0.7=0.56, decayed = 0.56×0.8^1=0.448."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.7),
        )
        finder = PathFinder(PathFinderConfig(max_hops=3, decay_factor=0.8, min_confidence=0.0))
        paths = finder.find_all_paths(graph, "A")
        two_hop = next(p for p in paths if p.n_hops == 2)
        assert two_hop.raw_confidence == pytest.approx(0.8 * 0.7, rel=1e-5)
        assert two_hop.path_confidence == pytest.approx(0.8 * 0.7 * 0.8, rel=1e-5)

    def test_paths_sorted_by_confidence_descending(self):
        """Highest confidence path must come first."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.9),
            _make_edge("A", "C", confidence=0.3),
        )
        finder = PathFinder(PathFinderConfig(max_hops=3))
        paths = finder.find_all_paths(graph, "A")
        confs = [p.path_confidence for p in paths]
        assert confs == sorted(confs, reverse=True)

    def test_min_confidence_prunes_low_paths(self):
        """Low-confidence paths below min_confidence must be discarded."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.001))
        finder = PathFinder(PathFinderConfig(max_hops=3, min_confidence=0.01))
        paths = finder.find_all_paths(graph, "A")
        assert paths == []

    def test_isolated_source_returns_empty(self):
        """If source has no successors, no paths found."""
        graph = _build_graph(_make_edge("X", "Y", confidence=0.5))
        finder = PathFinder()
        paths = finder.find_all_paths(graph, "Z")  # Z not in graph
        assert paths == []

    def test_path_description_format(self):
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        finder = PathFinder()
        paths = finder.find_all_paths(graph, "A")
        assert "→" in paths[0].description()
        assert "A" in paths[0].description()
        assert "B" in paths[0].description()

    def test_branching_graph_all_branches_found(self):
        """Star topology: A→B, A→C, A→D should give 3 paths."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.7),
            _make_edge("A", "C", confidence=0.6),
            _make_edge("A", "D", confidence=0.5),
        )
        finder = PathFinder(PathFinderConfig(max_hops=1))
        paths = finder.find_all_paths(graph, "A")
        targets = {p.target for p in paths}
        assert targets == {"B", "C", "D"}


class TestPathFinderFindPathsTo:
    def test_finds_incoming_paths(self):
        """find_paths_to(C) in A→B→C should find the A→B→C path."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.7),
        )
        finder = PathFinder(PathFinderConfig(max_hops=3, min_confidence=0.0))
        paths = finder.find_paths_to(graph, "C")
        assert any(p.source == "A" and p.target == "C" for p in paths)

    def test_no_paths_to_root(self):
        """Root node (no predecessors) should have no paths pointing to it."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.8))
        finder = PathFinder()
        paths = finder.find_paths_to(graph, "A")
        assert paths == []

    def test_sorted_by_confidence(self):
        graph = _build_graph(
            _make_edge("X", "Z", confidence=0.3),
            _make_edge("Y", "Z", confidence=0.9),
        )
        finder = PathFinder(PathFinderConfig(max_hops=1))
        paths = finder.find_paths_to(graph, "Z")
        confs = [p.path_confidence for p in paths]
        assert confs == sorted(confs, reverse=True)
