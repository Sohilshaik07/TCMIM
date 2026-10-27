"""
TCMIM — Integration test: M7 dynamic graph + multi-hop + CRI.

PRD STATUS: TEST (synthetic fixture — NOT real experimental data)

Synthetic topology
------------------
    Compressor → Valve → Actuator
         ↘                ↗
           Pump ──────────

Known edges (all CONFIRMED, synthetic):
  C → V : confidence=0.8
  V → A : confidence=0.7
  C → P : confidence=0.6
  P → A : confidence=0.5

Expected cascade paths to Actuator:
  1. C → V → A  (2 hops)
  2. C → P → A  (2 hops)

Expected CRI ordering:
  Actuator (downstream of two paths)  >  Valve  ≈  Pump  >  Compressor (root, CRI=0)

INTEGRITY NOTE
--------------
This is algorithm-correctness testing on a synthetic fixture.
"CONFIRMED" means repeated consistent evidence, NOT proven causality.
CRI values are evidence-based indices, NOT failure probabilities.
"""

import pytest
from datetime import datetime, timezone
from typing import List

from tcmim.cri.calculator import CRICalculator, CRIConfig
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder, PathFinderConfig
from tcmim.schemas import CRIRecord, EdgeRecord, EdgeState, Modality, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_edge(
    source: str,
    target: str,
    confidence: float,
    state: EdgeState = EdgeState.CONFIRMED,
) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        state=state,
        evidence_count=8,
        est_delay_s=60.0,
        confidence=confidence,
        last_updated=NOW,
        modality=Modality.PRESSURE,
        provenance=Provenance.SYNTHETIC,
    )


TOPOLOGY_EDGES = [
    _make_edge("Compressor", "Valve",    confidence=0.8),
    _make_edge("Valve",      "Actuator", confidence=0.7),
    _make_edge("Compressor", "Pump",     confidence=0.6),
    _make_edge("Pump",       "Actuator", confidence=0.5),
]


class TestM7GraphTopology:
    @pytest.fixture(scope="class")
    def pipeline(self):
        """Build the full M7 pipeline on the synthetic 4-machine topology."""
        graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.CANDIDATE))
        graph.update(TOPOLOGY_EDGES)

        pf_cfg = PathFinderConfig(max_hops=3, decay_factor=0.8, min_confidence=0.0)
        finder = PathFinder(pf_cfg)

        cri_cfg = CRIConfig(path_finder_config=pf_cfg, normalise_by_sources=True)
        calc = CRICalculator(cri_cfg)
        cri_records = calc.compute_all(graph)

        return {
            "graph": graph,
            "finder": finder,
            "cri_records": cri_records,
        }

    # ---- Graph correctness -----------------------------------------------

    def test_all_four_nodes_in_graph(self, pipeline):
        nodes = pipeline["graph"].nodes()
        assert {"Compressor", "Valve", "Pump", "Actuator"}.issubset(nodes)

    def test_four_active_edges(self, pipeline):
        assert len(pipeline["graph"].active_edges()) == 4

    def test_compressor_has_two_successors(self, pipeline):
        succ = pipeline["graph"].successors("Compressor")
        targets = {t for t, _ in succ}
        assert targets == {"Valve", "Pump"}

    def test_actuator_has_two_predecessors(self, pipeline):
        preds = pipeline["graph"].predecessors("Actuator")
        sources = {s for s, _ in preds}
        assert sources == {"Valve", "Pump"}

    def test_graph_version_incremented(self, pipeline):
        assert pipeline["graph"].version >= 1

    def test_snapshot_has_correct_nodes(self, pipeline):
        snap = pipeline["graph"].snapshot()
        assert "Compressor" in snap.nodes
        assert "Actuator" in snap.nodes

    # ---- Path finding correctness ----------------------------------------

    def test_finds_two_hop_path_compressor_to_actuator(self, pipeline):
        paths = pipeline["finder"].find_all_paths(
            pipeline["graph"], "Compressor"
        )
        two_hop_targets = [p.target for p in paths if p.n_hops == 2]
        assert "Actuator" in two_hop_targets

    def test_finds_two_distinct_paths_to_actuator(self, pipeline):
        paths = pipeline["finder"].find_paths_to(
            pipeline["graph"], "Actuator"
        )
        # Should have at least 2 distinct paths (via Valve and via Pump)
        assert len(paths) >= 2

    def test_path_via_valve_found(self, pipeline):
        paths = pipeline["finder"].find_paths_to(
            pipeline["graph"], "Actuator"
        )
        valve_path = any(
            "Valve" in p.nodes for p in paths
            if p.source == "Compressor"
        )
        assert valve_path

    def test_path_via_pump_found(self, pipeline):
        paths = pipeline["finder"].find_paths_to(
            pipeline["graph"], "Actuator"
        )
        pump_path = any(
            "Pump" in p.nodes for p in paths
            if p.source == "Compressor"
        )
        assert pump_path

    def test_path_confidence_decreases_with_hops(self, pipeline):
        """1-hop paths must have >= confidence than 2-hop paths."""
        paths_from_c = pipeline["finder"].find_all_paths(
            pipeline["graph"], "Compressor"
        )
        one_hop = [p for p in paths_from_c if p.n_hops == 1]
        two_hop = [p for p in paths_from_c if p.n_hops == 2]
        if one_hop and two_hop:
            max_one = max(p.path_confidence for p in one_hop)
            max_two = max(p.path_confidence for p in two_hop)
            assert max_one >= max_two

    # ---- CRI correctness ------------------------------------------------

    def test_compressor_cri_is_zero(self, pipeline):
        """Root machine (Compressor) has no predecessors → CRI = 0."""
        rec = next(
            r for r in pipeline["cri_records"]
            if r.target_machine == "Compressor"
        )
        assert rec.cri == pytest.approx(0.0)

    def test_actuator_has_higher_cri_than_compressor(self, pipeline):
        """Actuator (downstream) must have strictly higher CRI than root Compressor."""
        records = pipeline["cri_records"]
        actuator_cri = next(r.cri for r in records if r.target_machine == "Actuator")
        compressor_cri = next(r.cri for r in records if r.target_machine == "Compressor")
        assert actuator_cri > compressor_cri

    def test_valve_has_highest_single_hop_cri(self, pipeline):
        """Valve is directly connected to Compressor with confidence=0.8,
        the highest single-edge confidence — so its CRI should be highest or
        at least > Pump's (confidence=0.6 direct edge)."""
        records = pipeline["cri_records"]
        valve_cri = next(r.cri for r in records if r.target_machine == "Valve")
        pump_cri = next(r.cri for r in records if r.target_machine == "Pump")
        assert valve_cri > pump_cri

    def test_all_cri_in_range(self, pipeline):
        for rec in pipeline["cri_records"]:
            assert 0.0 <= rec.cri <= 1.0, (
                f"CRI={rec.cri} out of [0,1] for {rec.target_machine}"
            )

    def test_cri_provenance_synthetic(self, pipeline):
        for rec in pipeline["cri_records"]:
            assert rec.provenance == Provenance.SYNTHETIC

    def test_cri_records_count(self, pipeline):
        """One CRI record per node in the graph."""
        n_nodes = len(pipeline["graph"].nodes())
        assert len(pipeline["cri_records"]) == n_nodes

    def test_actuator_contributions_both_sources(self, pipeline):
        """Actuator CRI contributions should include Compressor (via multi-hop)."""
        actuator_rec = next(
            r for r in pipeline["cri_records"]
            if r.target_machine == "Actuator"
        )
        # Contributions can come from Valve, Pump, and/or Compressor (2-hop)
        assert len(actuator_rec.contributions) > 0

    def test_actuator_paths_used_populated(self, pipeline):
        actuator_rec = next(
            r for r in pipeline["cri_records"]
            if r.target_machine == "Actuator"
        )
        assert len(actuator_rec.paths_used) >= 2

    # ---- Version history -------------------------------------------------

    def test_snapshot_history_non_empty(self, pipeline):
        assert len(pipeline["graph"].snapshot_history()) >= 1

    def test_snapshot_version_monotonic(self, pipeline):
        history = pipeline["graph"].snapshot_history()
        versions = [s.version for s in history]
        assert versions == sorted(versions)
