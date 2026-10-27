"""
TCMIM — Multi-hop path finder (S11, FR-MH-1, FR-MH-2).

Discovers all simple (no-cycle) paths from a source machine to all
reachable targets through the dynamic graph.

Path confidence
---------------
For each path, the confidence is the product of edge confidences along it:

    path_confidence = Π confidence(e_i)    for each edge e_i in the path

This is a conservative, multiplicative penalty — each hop reduces the
overall path confidence.

Hop penalty (FR-MH-2)
----------------------
An additional exponential hop-decay is applied:

    decayed_confidence = path_confidence × decay_factor^(hops − 1)

This ensures longer (more speculative) paths receive lower confidence.

INTEGRITY NOTE
--------------
A multi-hop path represents a POSSIBLE cascade route, not a confirmed
cascade.  Paths are returned with their confidence score and the chain
of edges — both are required for any downstream claim.

Usage
-----
>>> from tcmim.graph.path_finder import PathFinder, PathFinderConfig
>>> finder = PathFinder(PathFinderConfig(max_hops=3))
>>> paths = finder.find_all_paths(graph, source="A")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.schemas import EdgeRecord

logger = logging.getLogger(__name__)


@dataclass
class PropagationPath:
    """One multi-hop propagation path from source to target.

    Attributes
    ----------
    nodes          : Ordered list of machine IDs on the path (source first).
    edges          : Ordered list of EdgeRecords on the path.
    path_confidence: Product of edge confidences × hop decay.
    raw_confidence : Product of edge confidences (no hop decay).
    n_hops         : Number of edges (= len(nodes) − 1).
    """
    nodes: List[str]
    edges: List[EdgeRecord]
    path_confidence: float
    raw_confidence: float
    n_hops: int

    @property
    def source(self) -> str:
        return self.nodes[0]

    @property
    def target(self) -> str:
        return self.nodes[-1]

    def description(self) -> str:
        return " → ".join(self.nodes)


@dataclass
class PathFinderConfig:
    """Configuration for the path finder.

    Attributes
    ----------
    max_hops    : Maximum path length in hops (edges).
    decay_factor: Per-hop confidence decay factor in (0, 1].
                  1.0 = no decay; 0.5 = each hop halves the confidence.
    min_confidence: Paths with path_confidence below this are discarded.
    """
    max_hops: int = 3
    decay_factor: float = 0.8
    min_confidence: float = 0.01
    structural_mask: Optional[Any] = None

    def __post_init__(self) -> None:
        if self.max_hops < 1:
            raise ValueError("max_hops must be >= 1.")
        if not (0 < self.decay_factor <= 1.0):
            raise ValueError("decay_factor must be in (0, 1].")
        if not (0 <= self.min_confidence < 1.0):
            raise ValueError("min_confidence must be in [0, 1).")


class PathFinder:
    """Find all simple propagation paths through the dynamic graph.

    Parameters
    ----------
    config : PathFinderConfig.
    """

    def __init__(self, config: Optional[PathFinderConfig] = None) -> None:
        self.config = config or PathFinderConfig()

    def find_all_paths(
        self,
        graph: DynamicGraph,
        source: str,
    ) -> List[PropagationPath]:
        """Find all simple paths starting at *source* in the graph.

        Parameters
        ----------
        graph  : The DynamicGraph to search.
        source : Starting node.

        Returns
        -------
        List of PropagationPath, sorted by path_confidence descending.
        Paths of length 0 (source to itself) are excluded.
        """
        cfg = self.config
        paths: List[PropagationPath] = []

        def _dfs(
            current_node: str,
            visited: set,
            current_nodes: List[str],
            current_edges: List[EdgeRecord],
            running_confidence: float,
        ) -> None:
            for neighbor, edge in graph.successors(current_node):
                if neighbor in visited:
                    continue  # no cycles
                if cfg.structural_mask is not None and cfg.structural_mask.is_prohibited(current_node, neighbor):
                    continue  # prune physically prohibited edges
                if len(current_edges) >= cfg.max_hops:
                    continue  # max hops reached

                new_confidence = running_confidence * edge.confidence
                n_hops = len(current_edges) + 1
                decayed = new_confidence * (cfg.decay_factor ** (n_hops - 1))

                if decayed < cfg.min_confidence:
                    continue  # prune low-confidence branches

                new_nodes = current_nodes + [neighbor]
                new_edges = current_edges + [edge]

                path = PropagationPath(
                    nodes=new_nodes,
                    edges=new_edges,
                    path_confidence=decayed,
                    raw_confidence=new_confidence,
                    n_hops=n_hops,
                )
                paths.append(path)

                # Continue DFS from this neighbor
                _dfs(
                    neighbor,
                    visited | {neighbor},
                    new_nodes,
                    new_edges,
                    new_confidence,
                )

        _dfs(
            current_node=source,
            visited={source},
            current_nodes=[source],
            current_edges=[],
            running_confidence=1.0,
        )

        paths.sort(key=lambda p: p.path_confidence, reverse=True)

        logger.debug(
            "PathFinder: %d paths from '%s' (max_hops=%d).",
            len(paths), source, cfg.max_hops,
        )
        return paths

    def find_paths_to(
        self,
        graph: DynamicGraph,
        target: str,
    ) -> List[PropagationPath]:
        """Find all paths in the graph that end at *target*.

        Parameters
        ----------
        graph  : The DynamicGraph to search.
        target : Destination node.

        Returns
        -------
        List of PropagationPath, sorted by path_confidence descending.
        """
        all_paths: List[PropagationPath] = []
        for source in graph.nodes():
            if source == target:
                continue
            for path in self.find_all_paths(graph, source):
                if path.target == target:
                    all_paths.append(path)

        all_paths.sort(key=lambda p: p.path_confidence, reverse=True)

        logger.debug(
            "PathFinder.find_paths_to '%s': %d paths.",
            target, len(all_paths),
        )
        return all_paths
