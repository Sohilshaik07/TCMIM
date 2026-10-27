"""
src/tcmim/analysis/orchestrator.py
==================================
Reusable Stage 2 analysis pipeline orchestrator (M8/M9).

Coordinates cross-machine propagation analysis:
1. Validates input event streams and configuration.
2. Builds event index mapping event_id -> EventRecord (required by Gating G5).
3. Matches cross-machine candidate event pairs using EventMatcher.
4. Applies GatingPipeline (G1..G5) to partition into accepted and rejected observations.
5. Runs OCCCDAnalyser on accepted observations with common-cause diagnostics (T1..T4)
   and FR-CC-2 disclaimers.
6. Aggregates accepted observations into DelayStatistics across all active pairs.
7. Updates EdgeManager lifecycle state machine across evaluation cycles.
8. Enriches EdgeRecords with est_delay_s from DelayStatistics (handling absent stats explicitly as float('nan')).
9. Updates DynamicGraph with enriched edge records, incrementing graph snapshot version.
10. Traverses graph using PathFinder to discover all valid multi-hop propagation paths.
11. Computes Cascade Risk Index (CRI) records for all nodes in the graph via CRICalculator.

Preserves provenance, rejected observations for auditability, and all schema invariants.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from tcmim.config import (
    EdgeLifecycleConfig,
    MatchingConfig,
)
from tcmim.cri.calculator import CRICalculator, CRIConfig
from tcmim.edge.manager import EdgeManager
from tcmim.gating.gates import GatingConfig, GatingPipeline
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder, PathFinderConfig, PropagationPath
from tcmim.propagation.delay import DelayEstimator, DelayEstimatorConfig, aggregate_all_pairs
from tcmim.propagation.matcher import EventMatcher
from tcmim.propagation.occ_ccd import OCCCDAnalyser, OCCCDConfig, OCCCDResult
from tcmim.schemas import (
    CRIRecord,
    DelayStatistics,
    EdgeRecord,
    EventRecord,
    HealthSample,
    PropagationGraphState,
    PropagationObservation,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Structured result of executing the Stage 2 propagation pipeline.

    Attributes
    ----------
    matched_observations : All candidate observations from EventMatcher.
    accepted_observations: Observations that passed all gating checks.
    rejected_observations: Observations rejected by gating (with reject_reason audit).
    occcd_results        : OC-CCD analysis results with common-cause diagnostics.
    delay_statistics     : Aggregated delay metrics per machine pair.
    edges                : EdgeRecords updated by EdgeManager and enriched with est_delay_s.
    graph_snapshot       : PropagationGraphState snapshot for this evaluation cycle.
    paths                : All discovered propagation paths from PathFinder.
    cri_records          : Cascade Risk Index records computed for all graph nodes.
    event_index          : Event index mapping event_id -> EventRecord.
    """
    matched_observations: List[PropagationObservation]
    accepted_observations: List[PropagationObservation]
    rejected_observations: List[PropagationObservation]
    occcd_results: List[OCCCDResult]
    delay_statistics: List[DelayStatistics]
    edges: List[EdgeRecord]
    graph_snapshot: PropagationGraphState
    paths: List[PropagationPath]
    cri_records: List[CRIRecord]
    event_index: Dict[str, EventRecord] = field(default_factory=dict)

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_observations)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_observations)

    def get_edge(self, source: str, target: str) -> Optional[EdgeRecord]:
        """Look up an edge by source and target machine IDs."""
        for edge in self.edges:
            if edge.source == source and edge.target == target:
                return edge
        return None

    def get_delay_stats(self, source: str, target: str) -> Optional[DelayStatistics]:
        """Look up delay statistics by source and target machine IDs."""
        for ds in self.delay_statistics:
            if ds.source_machine == source and ds.target_machine == target:
                return ds
        return None


class Stage2Pipeline:
    """Reusable end-to-end propagation pipeline orchestrator.

    Integrates EventMatcher, GatingPipeline, OCCCDAnalyser, DelayAggregation,
    EdgeManager, DynamicGraph, PathFinder, and CRICalculator.
    """

    def __init__(
        self,
        *,
        matcher: Optional[EventMatcher] = None,
        gating: Optional[GatingPipeline] = None,
        analyser: Optional[OCCCDAnalyser] = None,
        edge_manager: Optional[EdgeManager] = None,
        graph: Optional[DynamicGraph] = None,
        path_finder: Optional[PathFinder] = None,
        cri_calculator: Optional[CRICalculator] = None,
        matching_config: Optional[MatchingConfig] = None,
        gating_config: Optional[GatingConfig] = None,
        occcd_config: Optional[OCCCDConfig] = None,
        edge_config: Optional[EdgeLifecycleConfig] = None,
        graph_config: Optional[GraphConfig] = None,
        path_finder_config: Optional[PathFinderConfig] = None,
        cri_config: Optional[CRIConfig] = None,
        delay_estimator: Optional[DelayEstimator] = None,
        delay_config: Optional[DelayEstimatorConfig] = None,
    ) -> None:
        if matching_config is not None:
            if matching_config.min_delay_s < 0:
                raise ValueError("min_delay_s must be non-negative")
            if matching_config.min_delay_s >= matching_config.max_delay_s:
                raise ValueError("min_delay_s must be strictly less than max_delay_s")

        self.matcher = matcher or (
            EventMatcher(
                max_delay_s=matching_config.max_delay_s if matching_config else 600.0,
                min_delay_s=matching_config.min_delay_s if matching_config else 1.0,
            )
        )
        self.gating = gating or GatingPipeline(gating_config or GatingConfig())
        self.analyser = analyser or OCCCDAnalyser(occcd_config or OCCCDConfig())
        self.edge_manager = edge_manager or EdgeManager(edge_config or EdgeLifecycleConfig())
        self.graph = graph or DynamicGraph(graph_config or GraphConfig())
        self.path_finder = path_finder or PathFinder(path_finder_config or PathFinderConfig())
        self.cri_calculator = cri_calculator or CRICalculator(cri_config or CRIConfig())
        self.delay_estimator = delay_estimator or DelayEstimator(delay_config or DelayEstimatorConfig())

    def reset(self) -> None:
        """Reset stateful components (EdgeManager and DynamicGraph)."""
        self.edge_manager.reset()
        self.graph = DynamicGraph(self.graph.config)

    def run(
        self,
        events_by_machine: Mapping[str, Sequence[EventRecord]],
        *,
        cycle_timestamp: Optional[datetime] = None,
        health_map: Optional[Dict[str, List[HealthSample]]] = None,
    ) -> PipelineResult:
        """Run the Stage 2 propagation pipeline on machine-keyed event streams.

        Parameters
        ----------
        events_by_machine : Mapping of machine_id -> sequence of EventRecords.
        cycle_timestamp   : Evaluation timestamp (defaults to current UTC time).
        health_map        : Optional machine health sample map for G4 health consistency.

        Returns
        -------
        PipelineResult with all intermediate and terminal outputs.
        """
        now = cycle_timestamp or datetime.now(tz=timezone.utc)

        # 1. Input validation & event index construction
        if not isinstance(events_by_machine, Mapping):
            raise TypeError("events_by_machine must be a mapping of machine_id -> Sequence[EventRecord]")

        event_index: Dict[str, EventRecord] = {}
        validated_events: Dict[str, List[EventRecord]] = {}

        for machine_id, events in events_by_machine.items():
            if not isinstance(machine_id, str):
                raise TypeError(f"machine_id keys must be strings, got {type(machine_id)}")
            if events is None:
                validated_events[machine_id] = []
                continue
            if not isinstance(events, (list, tuple)):
                raise TypeError(f"Events for {machine_id} must be a sequence of EventRecord")

            ev_list: List[EventRecord] = []
            for ev in events:
                if not isinstance(ev, EventRecord):
                    raise TypeError(f"Expected EventRecord in events for {machine_id}, got {type(ev)}")
                event_index[ev.event_id] = ev
                ev_list.append(ev)

            # Keep events ordered by onset_time
            ev_list.sort(key=lambda e: e.onset_time)
            validated_events[machine_id] = ev_list

        # Check for empty streams
        has_events = any(len(evs) > 0 for evs in validated_events.values())

        if not has_events:
            # Graceful execution for empty input
            raw_edges = self.edge_manager.update([], cycle_timestamp=now)
            enriched_edges = [replace(e, est_delay_s=float("nan")) for e in raw_edges]
            snapshot = self.graph.update(enriched_edges, timestamp=now)
            paths: List[PropagationPath] = []
            for node in sorted(self.graph.nodes()):
                paths.extend(self.path_finder.find_all_paths(self.graph, node))
            cri_records = self.cri_calculator.compute_all(self.graph)

            return PipelineResult(
                matched_observations=[],
                accepted_observations=[],
                rejected_observations=[],
                occcd_results=[],
                delay_statistics=[],
                edges=enriched_edges,
                graph_snapshot=snapshot,
                paths=paths,
                cri_records=cri_records,
                event_index=event_index,
            )

        # 2. Event matching
        matched = self.matcher.match_all_pairs(validated_events)

        # 3. Sort matched observations by source onset time so G3 direction gate
        # receives observations in chronological order
        matched.sort(
            key=lambda o: event_index[o.source_event].onset_time
            if o.source_event in event_index
            else datetime.min.replace(tzinfo=timezone.utc)
        )

        # 4. Gating pipeline (G1 Feasibility, G2 Ordering, G3 Direction Consistency,
        # G4 Health Consistency, G5 Modality Match)
        accepted, rejected = self.gating.apply(
            matched,
            health_map=health_map,
            event_index=event_index,
        )

        # 5. OCCCD Analyser (T1 Simultaneity, T2 Onset Bias, T3 Coincidence, T4 Lag Correction)
        occcd_results = [
            self.analyser.analyse(obs, all_observations=accepted)
            for obs in accepted
        ]

        # 6. Delay statistics aggregation using configured estimator (mean, median, trimmed_mean)
        delay_statistics = self.delay_estimator.estimate_all_pairs(accepted)
        delay_map = {
            (ds.source_machine, ds.target_machine): ds
            for ds in delay_statistics
        }

        # 7. Edge manager lifecycle update
        raw_edges = self.edge_manager.update(accepted, cycle_timestamp=now)

        # 8. Delay-statistics enrichment onto EdgeRecords
        # If statistics are present, est_delay_s is set to estimated_delay_s (falling back to mean_s).
        # If absent, est_delay_s is explicitly float('nan'), avoiding misinterpretation as 0.0s.
        enriched_edges: List[EdgeRecord] = []
        for edge in raw_edges:
            pair_key = (edge.source, edge.target)
            if pair_key in delay_map:
                ds = delay_map[pair_key]
                est_delay = ds.estimated_delay_s if ds.estimated_delay_s is not None else ds.mean_s
            else:
                est_delay = float("nan")

            enriched_edges.append(replace(edge, est_delay_s=est_delay))

        # 9. Dynamic graph update
        snapshot = self.graph.update(enriched_edges, timestamp=now)

        # 10. Path finding (all simple paths from every node in active graph)
        paths = []
        for node in sorted(self.graph.nodes()):
            paths.extend(self.path_finder.find_all_paths(self.graph, node))

        # 11. CRI calculation (Cascade Risk Index for all nodes in graph)
        cri_records = self.cri_calculator.compute_all(self.graph)

        return PipelineResult(
            matched_observations=matched,
            accepted_observations=accepted,
            rejected_observations=rejected,
            occcd_results=occcd_results,
            delay_statistics=delay_statistics,
            edges=enriched_edges,
            graph_snapshot=snapshot,
            paths=paths,
            cri_records=cri_records,
            event_index=event_index,
        )
