"""
TCMIM — Reporting builder (M8, FR-REP-1, FR-REP-2).

Produces structured pipeline reports summarising the dynamic graph,
edge states, and Cascade Risk Index (CRI) values.

FR-REP-1: Reports must include full provenance audit trail.
FR-REP-2: Any report containing SYNTHETIC data must clearly watermark
          or flag the report.

Usage
-----
>>> from tcmim.reporting.builder import ReportBuilder
>>> builder = ReportBuilder()
>>> report_dict = builder.build_json(graph, cri_records, run_metadata)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.schemas import CRIRecord, EdgeState, Provenance

logger = logging.getLogger(__name__)


class ReportBuilder:
    """Build structured JSON-serialisable reports from pipeline state."""

    def build_json(
        self,
        graph: DynamicGraph,
        cri_records: List[CRIRecord],
        run_metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Build a full pipeline report dictionary.

        Parameters
        ----------
        graph        : The current DynamicGraph snapshot.
        cri_records  : List of CRIRecords for all nodes.
        run_metadata : Optional dictionary of execution metadata (e.g., config).

        Returns
        -------
        Dictionary suitable for JSON serialization.
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        metadata = run_metadata or {}
        
        # Determine overall provenance
        overall_prov = Provenance.HARDWARE
        has_synthetic = False
        
        # Check active edges
        active_edges = graph.active_edges()
        if not active_edges and not cri_records:
             overall_prov = Provenance.SYNTHETIC
             has_synthetic = True
        else:
             from tcmim.propagation.matcher import _merge_provenance
             # Start with highest, downgrade as needed
             for er in active_edges:
                 overall_prov = _merge_provenance(overall_prov, er.provenance)
                 if er.provenance == Provenance.SYNTHETIC:
                     has_synthetic = True
             for cr in cri_records:
                 overall_prov = _merge_provenance(overall_prov, cr.provenance)
                 if cr.provenance == Provenance.SYNTHETIC:
                     has_synthetic = True

        # FR-REP-2: Synthetic warning
        warnings = []
        if has_synthetic:
            warnings.append(
                "WARNING: This report contains SYNTHETIC provenance data. "
                "It MUST NOT be used for real-world predictive claims."
            )

        # Edges summary
        edges_summary = []
        for er in active_edges:
            edges_summary.append({
                "source": er.source,
                "target": er.target,
                "state": er.state.value,
                "evidence_count": er.evidence_count,
                "confidence": round(er.confidence, 4),
                "provenance": er.provenance.value,
                "last_updated": er.last_updated.isoformat(),
            })
            
        # CRI summary
        cri_summary = []
        for cr in cri_records:
            cri_summary.append({
                "target_machine": cr.target_machine,
                "cri": round(cr.cri, 4),
                "contributions": {k: round(v, 4) for k, v in cr.contributions.items()},
                "paths_used": cr.paths_used,
                "provenance": cr.provenance.value,
            })

        # Node states
        nodes = sorted(graph.nodes())
        node_states = []
        for n in nodes:
            # Find max outgoing state
            max_out = EdgeState.NONE
            for t, e in graph.successors(n):
                if _state_rank(e.state) > _state_rank(max_out):
                    max_out = e.state
            node_states.append({
                "machine_id": n,
                "highest_outgoing_state": max_out.value,
            })

        report = {
            "timestamp": now,
            "overall_provenance": overall_prov.value,
            "is_synthetic": has_synthetic,
            "warnings": warnings,
            "metadata": metadata,
            "graph_version": graph.version,
            "nodes": node_states,
            "edges": edges_summary,
            "cri_records": cri_summary,
            "disclaimer": (
                "FR-CRI-2 / FR-CC-2: Cascade Risk Index and propagation edges "
                "are evidence-based indicators, not confirmed causal links or "
                "probabilities of failure. Physical validation is required."
            )
        }

        logger.info("ReportBuilder: generated report (version=%d, synthetic=%s)", 
                    graph.version, has_synthetic)
        return report

def _state_rank(state: EdgeState) -> int:
    from tcmim.graph.dynamic_graph import _STATE_ORDER
    return _STATE_ORDER.get(state, 0)
