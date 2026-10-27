"""
TCMIM — Dynamic propagation graph (S10, FR-GR-1).

Maintains a versioned, snapshot-based directed graph where:
  - Nodes   = machine IDs
  - Edges   = EdgeRecords with state >= configured minimum (default: CANDIDATE)

Graph updates
-------------
Call ``update(edge_records)`` after each EdgeManager cycle.  The graph
increments its version and stores a new PropagationGraphState snapshot.

Active edges
------------
Only edges with ``state`` at or above ``min_active_state`` contribute to
graph queries.  NONE and EXPIRED edges are excluded by default.

INTEGRITY NOTE
--------------
The graph represents evidence of possible propagation pathways.
Edges in the graph are NOT confirmed causal links.
The graph is labelled accordingly in all exported snapshots.

Usage
-----
>>> from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
>>> graph = DynamicGraph(GraphConfig(min_active_state=EdgeState.PROVISIONAL))
>>> graph.update(edge_records)
>>> snapshot = graph.snapshot()
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from tcmim.schemas import (
    EdgeRecord, EdgeState, Modality, PropagationGraphState, Provenance
)

logger = logging.getLogger(__name__)


# ---- State ordering for filtering ----------------------------------------

_STATE_ORDER: Dict[EdgeState, int] = {
    EdgeState.NONE:          0,
    EdgeState.EXPIRED:       0,
    EdgeState.CANDIDATE:     1,
    EdgeState.WEAKENING:     2,
    EdgeState.PROVISIONAL:   3,
    EdgeState.CONFIRMED:     4,
    EdgeState.STRENGTHENING: 5,
    EdgeState.STABLE:        6,
}


@dataclass
class GraphConfig:
    """Configuration for the dynamic graph.

    Attributes
    ----------
    min_active_state : Minimum EdgeState for an edge to be included in
                       graph queries.  Default: CANDIDATE.
    max_snapshot_history : Number of snapshots to retain in memory.
    filter_hypothetical_transitive : If True, edges identified as hypothetical
                       transitive shortcuts are excluded from active graph queries.
                       Preserves unfiltered underlying EdgeManager evidence.
                       Default: False (baseline).
    transitive_delay_tolerance_s : Tolerance in seconds for matching direct edge
                       delay to indirect path delay sum. If None, purely topological
                       transitivity is evaluated. Default: None.
    """
    min_active_state: EdgeState = EdgeState.CANDIDATE
    max_snapshot_history: int = 100
    filter_hypothetical_transitive: bool = False
    transitive_delay_tolerance_s: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.min_active_state, EdgeState):
            try:
                self.min_active_state = EdgeState(self.min_active_state)
            except Exception as e:
                raise ValueError(
                    f"Invalid min_active_state '{self.min_active_state}'. Must be a valid EdgeState."
                ) from e
        if self.min_active_state not in _STATE_ORDER:
            raise ValueError(
                f"Unknown min_active_state '{self.min_active_state}'."
            )



class DynamicGraph:
    """Versioned directed graph of propagation edges.

    Parameters
    ----------
    config : GraphConfig.
    """

    def __init__(self, config: Optional[GraphConfig] = None) -> None:
        self.config = config or GraphConfig()
        self._version: int = 0
        self._all_edges: Dict[Tuple[str, str], EdgeRecord] = {}
        self._snapshot_history: List[PropagationGraphState] = []

    # ------------------------------------------------------------------ #
    # Mutation                                                            #
    # ------------------------------------------------------------------ #

    def update(
        self,
        edge_records: List[EdgeRecord],
        timestamp: Optional[datetime] = None,
    ) -> PropagationGraphState:
        """Update the graph with a new set of EdgeRecords.

        Parameters
        ----------
        edge_records : All current EdgeRecords from EdgeManager.
        timestamp    : UTC timestamp (default: now).

        Returns
        -------
        The new PropagationGraphState snapshot.
        """
        now = timestamp or datetime.now(tz=timezone.utc)
        self._version += 1

        for er in edge_records:
            self._all_edges[(er.source, er.target)] = er

        snapshot = self._build_snapshot(now)
        self._snapshot_history.append(snapshot)

        # Trim history
        if len(self._snapshot_history) > self.config.max_snapshot_history:
            self._snapshot_history.pop(0)

        logger.info(
            "DynamicGraph v%d: %d nodes, %d active edges.",
            self._version,
            len(snapshot.nodes),
            len(snapshot.edges),
        )
        return snapshot

    # ------------------------------------------------------------------ #
    # Queries                                                             #
    # ------------------------------------------------------------------ #

    def identify_transitive_edges(
        self,
        delay_tolerance_s: Optional[float] = None,
    ) -> List[EdgeRecord]:
        """Identify active edges that have an alternate multi-hop path.

        An edge (u, v) is a hypothetical transitive shortcut if there exists
        an alternate simple directed path from u to v of length >= 2 using
        other active edges.

        If delay_tolerance_s is provided, the edge is only marked if there is
        an alternate path whose cumulative delay sum matches the direct edge delay:
            |est_delay_s(u, v) - sum(est_delay_s(path))| <= delay_tolerance_s.
        If delay_tolerance_s is None, purely topological transitivity is checked.

        Returns
        -------
        List of EdgeRecords identified as hypothetical transitive edges.
        """
        min_rank = _STATE_ORDER.get(self.config.min_active_state, 0)
        active_list = [
            er for er in self._all_edges.values()
            if _STATE_ORDER.get(er.state, 0) >= min_rank
        ]
        active_map: Dict[Tuple[str, str], EdgeRecord] = {
            (er.source, er.target): er for er in active_list
        }

        # Build adjacency for active edges
        adj: Dict[str, List[str]] = {}
        for er in active_list:
            adj.setdefault(er.source, []).append(er.target)

        transitive: List[EdgeRecord] = []

        for er in active_list:
            u, v = er.source, er.target
            paths = _find_alternate_simple_paths(adj, u, v)
            if not paths:
                continue

            if delay_tolerance_s is None:
                transitive.append(er)
            else:
                if er.est_delay_s is None or math.isnan(er.est_delay_s):
                    continue
                direct_delay = er.est_delay_s

                matched_path = False
                for p in paths:
                    path_delay = 0.0
                    valid_path_delays = True
                    for i in range(len(p) - 1):
                        step_edge = active_map.get((p[i], p[i + 1]))
                        if step_edge is None or step_edge.est_delay_s is None or math.isnan(step_edge.est_delay_s):
                            valid_path_delays = False
                            break
                        path_delay += step_edge.est_delay_s
                    if valid_path_delays and abs(direct_delay - path_delay) <= delay_tolerance_s:
                        matched_path = True
                        break
                if matched_path:
                    transitive.append(er)

        return transitive

    def active_edges(self) -> List[EdgeRecord]:
        """Return all edges meeting the min_active_state filter.

        If self.config.filter_hypothetical_transitive is True, edges identified
        as hypothetical transitive shortcuts are excluded from active edges.
        """
        min_rank = _STATE_ORDER.get(self.config.min_active_state, 0)
        candidates = [
            er for er in self._all_edges.values()
            if _STATE_ORDER.get(er.state, 0) >= min_rank
        ]
        if not self.config.filter_hypothetical_transitive:
            return candidates

        transitive_keys = {
            (er.source, er.target)
            for er in self.identify_transitive_edges(self.config.transitive_delay_tolerance_s)
        }
        return [er for er in candidates if (er.source, er.target) not in transitive_keys]

    def transitive_edges(self) -> List[EdgeRecord]:
        """Return edges meeting min_active_state identified as hypothetical transitive shortcuts."""
        return self.identify_transitive_edges(self.config.transitive_delay_tolerance_s)

    def filtered_edges(self) -> List[EdgeRecord]:
        """Return edges passed to the graph that did not meet min_active_state."""
        min_rank = _STATE_ORDER.get(self.config.min_active_state, 0)
        return [
            er for er in self._all_edges.values()
            if _STATE_ORDER.get(er.state, 0) < min_rank
        ]

    def all_edges(self) -> List[EdgeRecord]:
        """Return all edges regardless of lifecycle state filter."""
        return list(self._all_edges.values())

    @property
    def active_edge_count(self) -> int:
        """Count of active edges meeting current graph filter."""
        return len(self.active_edges())

    @property
    def filtered_edge_count(self) -> int:
        """Count of edges excluded by current graph filter."""
        return len(self.filtered_edges())

    def nodes(self) -> Set[str]:
        """Return all machine IDs that appear in any active edge."""
        result: Set[str] = set()
        for er in self.active_edges():
            result.add(er.source)
            result.add(er.target)
        return result

    def successors(self, machine_id: str) -> List[Tuple[str, EdgeRecord]]:
        """Return (target, edge) pairs for all active outgoing edges of a node."""
        return [
            (er.target, er)
            for er in self.active_edges()
            if er.source == machine_id
        ]

    def predecessors(self, machine_id: str) -> List[Tuple[str, EdgeRecord]]:
        """Return (source, edge) pairs for all active incoming edges of a node."""
        return [
            (er.source, er)
            for er in self.active_edges()
            if er.target == machine_id
        ]

    def get_edge(
        self, source: str, target: str
    ) -> Optional[EdgeRecord]:
        """Return the EdgeRecord for (source, target), or None."""
        er = self._all_edges.get((source, target))
        if er is None:
            return None
        min_rank = _STATE_ORDER.get(self.config.min_active_state, 0)
        if _STATE_ORDER.get(er.state, 0) < min_rank:
            return None
        return er

    def snapshot(self) -> Optional[PropagationGraphState]:
        """Return the latest snapshot, or None if no update has been called."""
        return self._snapshot_history[-1] if self._snapshot_history else None

    def snapshot_history(self) -> List[PropagationGraphState]:
        """Return all retained snapshots in chronological order."""
        return list(self._snapshot_history)

    @property
    def version(self) -> int:
        """Current graph version number."""
        return self._version

    # ------------------------------------------------------------------ #
    # Internal                                                            #
    # ------------------------------------------------------------------ #

    def _build_snapshot(self, timestamp: datetime) -> PropagationGraphState:
        active = self.active_edges()
        filtered = self.filtered_edges()
        trans = self.transitive_edges()
        nodes = sorted({n for er in active for n in (er.source, er.target)})

        # Determine overall provenance (weakest of all active edges)
        if not active:
            prov = Provenance.SYNTHETIC
        else:
            from tcmim.propagation.matcher import _merge_provenance
            prov = active[0].provenance
            for er in active[1:]:
                prov = _merge_provenance(prov, er.provenance)

        return PropagationGraphState(
            timestamp=timestamp,
            nodes=nodes,
            edges=active,
            version=self._version,
            provenance=prov,
            min_active_state=self.config.min_active_state,
            filtered_edges=filtered,
            transitive_edges=trans,
        )


def _find_alternate_simple_paths(
    adj: Dict[str, List[str]],
    start: str,
    goal: str,
    max_hops: int = 5,
) -> List[List[str]]:
    """Find all simple paths from start to goal of length >= 2 without direct (start, goal) edge."""
    found: List[List[str]] = []

    def dfs(curr: str, path: List[str]):
        if len(path) > max_hops + 1:
            return
        if curr == goal:
            if len(path) >= 3:
                found.append(list(path))
            return
        for neighbor in adj.get(curr, []):
            if len(path) == 1 and curr == start and neighbor == goal:
                continue
            if neighbor not in path:
                path.append(neighbor)
                dfs(neighbor, path)
                path.pop()

    dfs(start, [start])
    return found
