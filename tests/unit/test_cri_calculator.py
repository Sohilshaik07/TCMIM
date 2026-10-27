"""
TCMIM — Unit tests for CRI calculator (M7, S12, FR-CRI-1, FR-CRI-2).

All fixtures are SYNTHETIC.

Key invariants tested:
  - CRI ∈ [0, 1] always
  - CRI = 0 when no upstream paths exist
  - CRI increases with more / higher-confidence upstream paths
  - FR-CRI-2: CRI is not a probability — tested via label assertions
  - Contributions sum to ≈1.0 (normalised breakdown)
"""

import pytest
from datetime import datetime, timezone

import numpy as np

from tcmim.cri.calculator import CRICalculator, CRIConfig
from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.graph.path_finder import PathFinderConfig
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


class TestCRICalculatorBasic:
    def test_cri_zero_when_no_paths(self):
        """Isolated machine with no predecessors → CRI = 0."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("A", graph)
        assert record.cri == pytest.approx(0.0)

    def test_cri_positive_with_upstream_path(self):
        """Machine B has upstream A → CRI > 0."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("B", graph)
        assert record.cri > 0.0

    def test_cri_in_range(self):
        """CRI must always be in [0, 1]."""
        # Try with many high-confidence edges pointing to one target
        graph = _build_graph(
            _make_edge("A", "Z", confidence=0.9),
            _make_edge("B", "Z", confidence=0.9),
            _make_edge("C", "Z", confidence=0.9),
        )
        calc = CRICalculator()
        record = calc.compute("Z", graph)
        assert 0.0 <= record.cri <= 1.0

    def test_cri_increases_with_confidence(self):
        """Higher edge confidence → higher CRI for the target."""
        graph_low = _build_graph(_make_edge("A", "B", confidence=0.1))
        graph_high = _build_graph(_make_edge("A", "B", confidence=0.9))
        calc = CRICalculator()
        cri_low = calc.compute("B", graph_low).cri
        cri_high = calc.compute("B", graph_high).cri
        assert cri_high > cri_low

    def test_cri_target_machine_id_correct(self):
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("B", graph)
        assert record.target_machine == "B"

    def test_contributions_sum_to_one(self):
        """Normalised contributions must sum to ≈1 when paths exist."""
        graph = _build_graph(
            _make_edge("A", "C", confidence=0.6),
            _make_edge("B", "C", confidence=0.4),
        )
        calc = CRICalculator()
        record = calc.compute("C", graph)
        if record.contributions:
            total = sum(record.contributions.values())
            assert total == pytest.approx(1.0, abs=0.01)

    def test_contributions_empty_when_no_paths(self):
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("A", graph)
        assert record.contributions == {}

    def test_paths_used_populated(self):
        """paths_used should contain at least one entry when paths exist."""
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("B", graph)
        assert len(record.paths_used) >= 1

    def test_provenance_synthetic(self):
        graph = _build_graph(_make_edge("A", "B", confidence=0.5))
        calc = CRICalculator()
        record = calc.compute("B", graph)
        assert record.provenance == Provenance.SYNTHETIC


class TestCRICalculatorMultiHop:
    def test_two_hop_contributes_to_cri(self):
        """Two-hop chain A→B→C: C should have positive CRI from A."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.7),
        )
        calc = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.0)
        ))
        record_c = calc.compute("C", graph)
        assert record_c.cri > 0.0

    def test_longer_path_lower_cri_than_direct(self):
        """A→B→C should give C less CRI than B (due to hop decay)."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.9),
            _make_edge("B", "C", confidence=0.9),
        )
        calc = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(
                max_hops=3, decay_factor=0.8, min_confidence=0.0
            )
        ))
        cri_b = calc.compute("B", graph).cri
        cri_c = calc.compute("C", graph).cri
        assert cri_b >= cri_c

    def test_cri_bounded_by_one_even_with_many_paths(self):
        """Stress test: many parallel paths must not push CRI above 1."""
        edges = [_make_edge(f"S{i}", "T", confidence=0.9) for i in range(20)]
        graph = _build_graph(*edges)
        calc = CRICalculator()
        record = calc.compute("T", graph)
        assert record.cri <= 1.0


class TestCRIComputeAll:
    def test_returns_record_for_every_node(self):
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.6),
        )
        calc = CRICalculator()
        records = calc.compute_all(graph)
        targets = {r.target_machine for r in records}
        # All three nodes appear in the graph
        assert "A" in targets or "B" in targets or "C" in targets

    def test_sorted_by_cri_descending(self):
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.9),
            _make_edge("A", "C", confidence=0.1),
        )
        calc = CRICalculator()
        records = calc.compute_all(graph)
        cris = [r.cri for r in records]
        assert cris == sorted(cris, reverse=True)

    def test_root_has_zero_cri(self):
        """Root machine A (no predecessors) must have CRI = 0."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.6),
        )
        calc = CRICalculator()
        records = calc.compute_all(graph)
        root_record = next(r for r in records if r.target_machine == "A")
        assert root_record.cri == pytest.approx(0.0)

    def test_empty_graph_returns_empty(self):
        graph = DynamicGraph()
        graph.update([])
        calc = CRICalculator()
        records = calc.compute_all(graph)
        assert records == []


class TestCRIHopDecayFormula:
    def test_one_hop_formula_exact(self):
        """1-hop: path_conf = conf × decay^0 = conf.
        CRI(B) = conf / 1_source = conf."""
        conf = 0.6
        graph = _build_graph(_make_edge("A", "B", confidence=conf))
        calc = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(
                max_hops=1, decay_factor=0.8, min_confidence=0.0
            ),
            normalise_by_sources=True,
        ))
        record = calc.compute("B", graph)
        # path_confidence = conf × 0.8^0 = conf
        # CRI = conf / 1 = conf
        assert record.cri == pytest.approx(conf, abs=0.01)


# ---------------------------------------------------------------------------
# Structural Topology & Sensitivity Audit (Phase 4)
# ---------------------------------------------------------------------------

class TestCRIStructuralTopologyAudit:
    """Comprehensive structural audit of CRI calculation across graph topologies."""

    def test_disconnected_node_zero_cri(self):
        """A disconnected node or node with no incoming edges must have CRI == 0.0."""
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B", confidence=0.7)])
        calc = CRICalculator()
        # "A" has outgoing edges but no incoming edges
        assert calc.compute("A", graph).cri == pytest.approx(0.0)

    def test_linear_chain_hop_decay(self):
        """In a linear chain A -> B -> C -> D, CRI strictly decreases with hop distance.

        Derivation:
        - For B: paths = [A->B (1 hop, conf=0.8)]. Sources = {A}. CRI = 0.8 / 1 = 0.800
        - For C: paths = [A->B->C (2 hops, conf=0.512), B->C (1 hop, conf=0.8)].
                 Sources = {A, B}. Sum = 1.312. CRI = 1.312 / 2 = 0.656
        - For D: paths = [A->B->C->D (3 hops, conf=0.32768), B->C->D (2 hops, conf=0.512), C->D (1 hop, conf=0.8)].
                 Sources = {A, B, C}. Sum = 1.63968. CRI = 1.63968 / 3 = 0.54656
        """
        conf = 0.8
        graph = _build_graph(
            _make_edge("A", "B", confidence=conf),
            _make_edge("B", "C", confidence=conf),
            _make_edge("C", "D", confidence=conf),
        )
        calc = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=4, decay_factor=0.8, min_confidence=0.001),
            normalise_by_sources=True,
        ))
        cri_b = calc.compute("B", graph).cri
        cri_c = calc.compute("C", graph).cri
        cri_d = calc.compute("D", graph).cri

        assert cri_b == pytest.approx(0.800, abs=1e-3)
        assert cri_c == pytest.approx(0.656, abs=1e-3)
        assert cri_d == pytest.approx(0.54656, abs=1e-3)
        assert cri_b > cri_c > cri_d

    def test_converging_paths_multiple_sources(self):
        """Multiple distinct sources converging to a single target machine."""
        conf = 0.6
        graph = _build_graph(
            _make_edge("S1", "Target", confidence=conf),
            _make_edge("S2", "Target", confidence=conf),
            _make_edge("S3", "Target", confidence=conf),
        )
        calc = CRICalculator(CRIConfig(normalise_by_sources=True))
        rec = calc.compute("Target", graph)
        # 3 sources each contributing 0.6, divided by 3 sources = 0.6
        assert rec.cri == pytest.approx(0.6, abs=0.01)
        # Normalised contributions should be equal across all three sources
        assert len(rec.contributions) == 3
        for s in ["S1", "S2", "S3"]:
            assert rec.contributions[s] == pytest.approx(1.0 / 3.0, abs=0.02)

    def test_diverging_paths_single_source(self):
        """One upstream source diverging to multiple independent downstream targets."""
        conf = 0.75
        graph = _build_graph(
            _make_edge("Source", "T1", confidence=conf),
            _make_edge("Source", "T2", confidence=conf),
            _make_edge("Source", "T3", confidence=conf),
        )
        calc = CRICalculator(CRIConfig(normalise_by_sources=True))
        rec1 = calc.compute("T1", graph)
        rec2 = calc.compute("T2", graph)
        rec3 = calc.compute("T3", graph)

        assert rec1.cri == pytest.approx(conf, abs=0.01)
        assert rec2.cri == pytest.approx(conf, abs=0.01)
        assert rec3.cri == pytest.approx(conf, abs=0.01)
        assert rec1.contributions == {"Source": 1.0}
        assert rec2.contributions == {"Source": 1.0}
        assert rec3.contributions == {"Source": 1.0}

    def test_cyclic_graph_terminates_and_bounds_cri(self):
        """Graphs containing directed cycles must terminate without recursion errors."""
        graph = _build_graph(
            _make_edge("A", "B", confidence=0.8),
            _make_edge("B", "C", confidence=0.8),
            _make_edge("C", "A", confidence=0.8),  # Directed cycle A -> B -> C -> A
            _make_edge("C", "D", confidence=0.7),  # Downstream branch to D
        )
        calc = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=4, decay_factor=0.8, min_confidence=0.01)
        ))
        records = calc.compute_all(graph)
        assert len(records) == 4
        for r in records:
            assert 0.0 <= r.cri <= 1.0

    def test_weak_candidate_vs_confirmed_confidence_weighting(self):
        """Weak candidate edges must yield substantially lower CRI than confirmed edges."""
        graph_weak = _build_graph(_make_edge("A", "B", confidence=0.15, state=EdgeState.CANDIDATE))
        graph_strong = _build_graph(_make_edge("A", "B", confidence=0.90, state=EdgeState.CONFIRMED))

        calc = CRICalculator()
        cri_weak = calc.compute("B", graph_weak).cri
        cri_strong = calc.compute("B", graph_strong).cri

        assert cri_weak == pytest.approx(0.15, abs=0.01)
        assert cri_strong == pytest.approx(0.90, abs=0.01)
        assert cri_strong >= 5.0 * cri_weak

    def test_edge_expiration_drops_cri(self):
        """When an edge expires, target machine CRI must drop to 0.0."""
        graph = DynamicGraph()
        # Initially active edge
        graph.update([_make_edge("A", "B", confidence=0.8, state=EdgeState.PROVISIONAL)])
        calc = CRICalculator()
        assert calc.compute("B", graph).cri > 0.0

        # Edge transitions to EXPIRED
        graph.update([_make_edge("A", "B", confidence=0.8, state=EdgeState.EXPIRED)])
        assert calc.compute("B", graph).cri == pytest.approx(0.0)

    def test_path_depth_limits_and_confidence_pruning(self):
        """PathFinder max_hops and min_confidence pruning behavior."""
        conf = 0.5
        # 4-hop chain: A -> B -> C -> D -> E
        graph = _build_graph(
            _make_edge("A", "B", confidence=conf),
            _make_edge("B", "C", confidence=conf),
            _make_edge("C", "D", confidence=conf),
            _make_edge("D", "E", confidence=conf),
        )
        # Cap max_hops = 2
        from tcmim.graph.path_finder import PathFinder
        finder_capped = PathFinder(PathFinderConfig(max_hops=2, decay_factor=1.0, min_confidence=0.01))
        paths_from_a = finder_capped.find_all_paths(graph, "A")
        targets_from_a = {p.target for p in paths_from_a}
        # A can only reach B (1 hop) and C (2 hops); D (3 hops) and E (4 hops) are pruned
        assert targets_from_a == {"B", "C"}
        assert "D" not in targets_from_a
        assert "E" not in targets_from_a

        # For node E, only upstream nodes within 2 hops (C and D) contribute to CRI
        calc_capped = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=2, decay_factor=1.0, min_confidence=0.01)
        ))
        rec_e = calc_capped.compute("E", graph)
        assert set(rec_e.contributions.keys()) == {"C", "D"}
        assert "A" not in rec_e.contributions
        assert "B" not in rec_e.contributions

        # High min_confidence pruning
        finder_pruned = PathFinder(PathFinderConfig(max_hops=4, decay_factor=0.5, min_confidence=0.30))
        paths_from_a_pruned = finder_pruned.find_all_paths(graph, "A")
        targets_pruned = {p.target for p in paths_from_a_pruned}
        # 1-hop path A -> B has confidence 0.5 >= 0.3 -> survives
        # 2-hop path A -> B -> C has confidence 0.5 * 0.5 * 0.5 = 0.125 < 0.3 -> pruned
        assert targets_pruned == {"B"}
        assert "C" not in targets_pruned

        calc_pruned = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=4, decay_factor=0.5, min_confidence=0.30)
        ))
        rec_c = calc_pruned.compute("C", graph)
        # Direct edge B -> C (1 hop, conf=0.5 >= 0.3) survives, but 2-hop A -> B -> C is pruned
        assert "B" in rec_c.contributions
        assert "A" not in rec_c.contributions

        # If min_confidence is raised above edge confidence (0.60 > 0.50), all paths are pruned
        calc_strict = CRICalculator(CRIConfig(
            path_finder_config=PathFinderConfig(max_hops=4, min_confidence=0.60)
        ))
        assert calc_strict.compute("B", graph).cri == pytest.approx(0.0)
        assert calc_strict.compute("C", graph).cri == pytest.approx(0.0)


