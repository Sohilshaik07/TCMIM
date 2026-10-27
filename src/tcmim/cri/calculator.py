"""
TCMIM — Cascade Risk Index calculator (S12, FR-CRI-1, FR-CRI-2).

The CRI quantifies how much upstream propagation evidence points toward
a target machine — i.e., how much "risk" exists that a failure
propagating through the graph will reach that machine.

Formula (FR-CRI-1, deterministic and explainable)
--------------------------------------------------
For each target machine T:

    CRI(T) = clip(Σ_p [ path_confidence(p) ] / normaliser, 0, 1)

Where:
  - p ranges over all paths ending at T in the dynamic graph
  - path_confidence includes edge confidences AND hop-decay
  - normaliser = max(1, number of unique source machines contributing)
    (prevents artificially high CRI from many weak paths)

Properties:
  - CRI ∈ [0, 1]
  - CRI = 0 when no active upstream paths exist
  - CRI increases with more evidence and higher-confidence edges
  - Longer paths contribute less (due to hop-decay in PathFinder)

INTEGRITY NOTE (FR-CRI-2)
--------------------------
CRI is a DETERMINISTIC, EVIDENCE-BASED INDEX.
It is NOT a validated failure predictor.
It MUST NOT be presented as a probability of failure.
Physical validation (M9) is required before making any predictive claim.

Usage
-----
>>> from tcmim.cri.calculator import CRICalculator, CRIConfig
>>> calc = CRICalculator(CRIConfig())
>>> cri_records = calc.compute_all(graph, path_finder)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus
from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.graph.path_finder import PathFinder, PathFinderConfig, PropagationPath
from tcmim.schemas import CRIRecord, EdgeState, Provenance

logger = logging.getLogger(__name__)


@dataclass
class CRIConfig:
    """Configuration for the CRI calculator.

    Attributes
    ----------
    path_finder_config   : PathFinderConfig for the underlying path search.
    normalise_by_sources : If True, divide the raw CRI sum by the number
                           of unique source machines (prevents inflation).
    structural_mask      : Optional PhysicalStructuralMask. Used to identify physical
                           predecessors that are unexcited actuators.
    unexcited_actuators  : Optional set of actuator IDs with zero baseline variance.
    structural_prior_weight : Configurable prior weight W_prior for unexcited edges.
    """
    path_finder_config: PathFinderConfig = None
    normalise_by_sources: bool = True
    structural_mask: Optional[PhysicalStructuralMask] = None
    unexcited_actuators: Optional[Set[str]] = None
    structural_prior_weight: float = 0.5

    def __post_init__(self) -> None:
        if self.path_finder_config is None:
            self.path_finder_config = PathFinderConfig(
                max_hops=3,
                decay_factor=0.8,
                min_confidence=0.01,
                structural_mask=self.structural_mask,
            )
        elif self.structural_mask is not None and self.path_finder_config.structural_mask is None:
            self.path_finder_config.structural_mask = self.structural_mask


class CRICalculator:
    """Compute per-node Cascade Risk Index from the dynamic graph.

    Parameters
    ----------
    config : CRIConfig.
    """

    def __init__(self, config: Optional[CRIConfig] = None) -> None:
        self.config = config or CRIConfig()
        self._finder = PathFinder(self.config.path_finder_config)

    def compute(
        self,
        target: str,
        graph: DynamicGraph,
    ) -> CRIRecord:
        """Compute CRI for one target machine.

        Parameters
        ----------
        target : The machine ID to compute CRI for.
        graph  : Current DynamicGraph.

        Returns
        -------
        CRIRecord with cri ∈ [0, 1] and contribution breakdown.
        """
        paths = self._finder.find_paths_to(graph, target)
        return self._build_cri_record(target, paths, graph)

    def compute_all(
        self,
        graph: DynamicGraph,
    ) -> List[CRIRecord]:
        """Compute CRI for every node in the graph.

        Parameters
        ----------
        graph : Current DynamicGraph.

        Returns
        -------
        List of CRIRecords sorted by cri descending.
        """
        nodes = graph.nodes()
        records: List[CRIRecord] = []
        for node in sorted(nodes):
            paths = self._finder.find_paths_to(graph, node)
            record = self._build_cri_record(node, paths, graph)
            records.append(record)

        records.sort(key=lambda r: r.cri, reverse=True)

        logger.info(
            "CRICalculator: computed CRI for %d nodes. "
            "Top: %s",
            len(records),
            [(r.target_machine, f"{r.cri:.3f}") for r in records[:3]],
        )
        return records

    def _build_cri_record(
        self,
        target: str,
        paths: List[PropagationPath],
        graph: DynamicGraph,
    ) -> CRIRecord:
        now = datetime.now(tz=timezone.utc)
        cfg = self.config

        # Gather unexcited actuator set from config and structural mask
        unexcited_set: Set[str] = set(cfg.unexcited_actuators or set())
        if cfg.structural_mask is not None:
            unexcited_set.update(cfg.structural_mask.unexcited_actuators)

        # Detect unexcited sources in paths
        detected_unexcited: Set[str] = set()
        for path in paths:
            for node in path.nodes:
                if node in unexcited_set:
                    detected_unexcited.add(node)
            for edge in path.edges:
                if edge.is_unexcited_actuator or edge.state == EdgeState.UNEXCITED_PRIOR:
                    detected_unexcited.add(edge.source)

        # Check graph edges connected to target directly
        for edge in graph.active_edges():
            if edge.target == target and (
                edge.source in unexcited_set
                or edge.is_unexcited_actuator
                or edge.state == EdgeState.UNEXCITED_PRIOR
            ):
                detected_unexcited.add(edge.source)

        # Safety check: if no dynamic paths exist, check if structural mask documents
        # permitted physical connections from unexcited actuators to target.
        # This prevents silently returning a zero-risk conclusion when upstream
        # physical connections exist but were unidentifiable from baseline.
        if not paths and cfg.structural_mask is not None:
            for unexcited_act in unexcited_set:
                if cfg.structural_mask.get_status(unexcited_act, target) == StructuralStatus.ALLOWED:
                    detected_unexcited.add(unexcited_act)

        cri_status = "UNCERTAIN_UNEXCITED" if detected_unexcited else "VALIDATED_EMPIRICAL"

        if not paths:
            return CRIRecord(
                timestamp=now,
                target_machine=target,
                cri=0.0,
                contributions={},
                paths_used=[],
                provenance=_graph_provenance(graph),
                cri_status=cri_status,
                unexcited_sources=sorted(detected_unexcited),
            )

        # ---- Sum path confidences grouped by source ---------------------
        source_contributions: Dict[str, float] = {}
        path_descriptions: List[str] = []

        for path in paths:
            src = path.source
            source_contributions[src] = (
                source_contributions.get(src, 0.0) + path.path_confidence
            )
            path_descriptions.append(
                f"{path.description()} "
                f"(conf={path.path_confidence:.3f}, hops={path.n_hops})"
            )

        raw_cri = sum(source_contributions.values())

        if self.config.normalise_by_sources:
            n_sources = max(1, len(source_contributions))
            raw_cri /= n_sources

        cri = float(np.clip(raw_cri, 0.0, 1.0))

        # Normalise contributions to [0, 1] for breakdown readability
        total = sum(source_contributions.values()) or 1.0
        normalised_contributions = {
            src: float(np.clip(v / total, 0.0, 1.0))
            for src, v in sorted(source_contributions.items())
        }

        return CRIRecord(
            timestamp=now,
            target_machine=target,
            cri=cri,
            contributions=normalised_contributions,
            paths_used=path_descriptions[:20],  # cap to 20 for readability
            provenance=_graph_provenance(graph),
            cri_status=cri_status,
            unexcited_sources=sorted(detected_unexcited),
        )


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _graph_provenance(graph: DynamicGraph) -> Provenance:
    """Return the weakest provenance of all active edges in the graph."""
    from tcmim.propagation.matcher import _merge_provenance
    active = graph.active_edges()
    if not active:
        return Provenance.SYNTHETIC
    prov = active[0].provenance
    for er in active[1:]:
        prov = _merge_provenance(prov, er.provenance)
    return prov
