"""
TCMIM — Unit tests for Reporting (M8).
"""

import pytest
from datetime import datetime, timezone

from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.reporting.builder import ReportBuilder
from tcmim.reporting.formatters import ReportFormatter
from tcmim.schemas import CRIRecord, EdgeRecord, EdgeState, Modality, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)

def _make_edge(src, tgt, prov=Provenance.SYNTHETIC):
    return EdgeRecord(
        source=src, target=tgt, state=EdgeState.CONFIRMED,
        evidence_count=5, est_delay_s=10.0, confidence=0.8,
        last_updated=NOW, modality=Modality.PRESSURE,
        provenance=prov
    )

def _make_cri(tgt, prov=Provenance.SYNTHETIC):
    return CRIRecord(
        timestamp=NOW, target_machine=tgt, cri=0.5,
        contributions={"A": 1.0}, paths_used=["A -> B"],
        provenance=prov
    )

class TestReporting:
    def test_builder_synthetic_warning(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B", Provenance.SYNTHETIC)])
        cri = [_make_cri("B", Provenance.SYNTHETIC)]
        
        builder = ReportBuilder()
        report = builder.build_json(graph, cri)
        
        assert report["is_synthetic"] is True
        assert any("SYNTHETIC" in w for w in report["warnings"])
        
    def test_builder_no_synthetic_warning_for_hardware(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B", Provenance.HARDWARE)])
        cri = [_make_cri("B", Provenance.HARDWARE)]
        
        builder = ReportBuilder()
        report = builder.build_json(graph, cri)
        
        assert report["is_synthetic"] is False
        assert not report["warnings"]
        
    def test_formatters(self):
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B")])
        cri = [_make_cri("B")]
        
        builder = ReportBuilder()
        report = builder.build_json(graph, cri)
        
        md = ReportFormatter.to_markdown(report)
        assert "A → B" in md
        assert "0.500" in md
        assert "SYNTHETIC" in md
        assert "FR-CRI-2" in md
