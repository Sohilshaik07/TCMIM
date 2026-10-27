"""
TCMIM — Cross-machine event matching (S5, FR-EM-1).

For every ordered pair of machines (source, target), this module finds
event pairs whose onset times differ by at most ``max_delay_s`` seconds
and at least ``min_delay_s`` seconds.

INTEGRITY NOTE
--------------
Matching creates CANDIDATE pairs — temporal proximity is NOT causality
(PRD Section 2, rule 1).  Every resulting PropagationObservation has
gate_result = "accepted" / "rejected" set by the gating stage (S7),
not here.  At matching time, gate_result is always set to "pending"
and finalised by the gating module.

The "pending" state exists only during pipeline processing and is never
written to persistent storage or reports.

Usage
-----
>>> from tcmim.propagation.matcher import EventMatcher
>>> matcher = EventMatcher(max_delay_s=600.0, min_delay_s=0.0)
>>> candidates = matcher.match(source_events, target_events,
...                            source_machine="A", target_machine="B")
"""

from __future__ import annotations

import logging
from typing import List, Optional

from tcmim.schemas import EventRecord, PropagationObservation, Provenance

logger = logging.getLogger(__name__)


class EventMatcher:
    """Match events from two machines into candidate propagation pairs.

    For each source event, all target events whose onset time falls
    within [t_source + min_delay_s, t_source + max_delay_s] are paired
    with it.  Multiple target events may be paired with one source event.

    Parameters
    ----------
    max_delay_s : Maximum plausible propagation delay in seconds.
    min_delay_s : Minimum plausible delay (default 0.0).
                  Set > 0 to exclude simultaneous events.
    """

    def __init__(
        self,
        max_delay_s: float = 600.0,
        min_delay_s: float = 0.0,
    ) -> None:
        if max_delay_s <= 0:
            raise ValueError("max_delay_s must be positive.")
        if min_delay_s < 0:
            raise ValueError("min_delay_s must be non-negative.")
        if min_delay_s >= max_delay_s:
            raise ValueError("min_delay_s must be less than max_delay_s.")
        self.max_delay_s = max_delay_s
        self.min_delay_s = min_delay_s

    def match(
        self,
        source_events: List[EventRecord],
        target_events: List[EventRecord],
        source_machine: str,
        target_machine: str,
    ) -> List[PropagationObservation]:
        """Produce candidate PropagationObservations for one ordered pair.

        Parameters
        ----------
        source_events  : Events detected on the (candidate) source machine.
        target_events  : Events detected on the (candidate) target machine.
        source_machine : Logical machine ID of the source.
        target_machine : Logical machine ID of the target.

        Returns
        -------
        List of PropagationObservation with gate_result="accepted"
        (i.e. within the time window — gating stage decides final accept/reject).

        Notes
        -----
        - source_machine != target_machine is not enforced here; callers
          should ensure they pass distinct machines.
        - Both lists should be sorted by onset_time (ascending).
        """
        if not source_events or not target_events:
            return []

        observations: List[PropagationObservation] = []

        for src_evt in source_events:
            t_src = src_evt.onset_time

            for tgt_evt in target_events:
                t_tgt = tgt_evt.onset_time

                delta_t_s = (t_tgt - t_src).total_seconds()

                # Within plausible window: [min_delay, max_delay]
                if self.min_delay_s <= delta_t_s <= self.max_delay_s:
                    obs = PropagationObservation(
                        source_event=src_evt.event_id,
                        target_event=tgt_evt.event_id,
                        source_machine=source_machine,
                        target_machine=target_machine,
                        delta_t_s=delta_t_s,
                        gate_result="accepted",   # provisional — gating may reject
                        reject_reason=None,
                        provenance=_merge_provenance(
                            src_evt.provenance, tgt_evt.provenance
                        ),
                    )
                    observations.append(obs)

        logger.debug(
            "EventMatcher: %s→%s: %d source × %d target events → %d candidates.",
            source_machine,
            target_machine,
            len(source_events),
            len(target_events),
            len(observations),
        )
        return observations

    def match_all_pairs(
        self,
        events_by_machine: dict,
        ordered_pairs: Optional[List[tuple]] = None,
    ) -> List[PropagationObservation]:
        """Match events for multiple ordered machine pairs.

        Parameters
        ----------
        events_by_machine : Dict mapping machine_id → List[EventRecord].
        ordered_pairs     : List of (source_id, target_id) tuples.
                            If None, all ordered permutations are tried.

        Returns
        -------
        Flat list of PropagationObservations across all pairs.
        """
        machine_ids = list(events_by_machine.keys())

        if ordered_pairs is None:
            ordered_pairs = [
                (a, b) for a in machine_ids for b in machine_ids if a != b
            ]

        all_observations: List[PropagationObservation] = []
        for src_id, tgt_id in ordered_pairs:
            src_events = events_by_machine.get(src_id, [])
            tgt_events = events_by_machine.get(tgt_id, [])
            obs = self.match(src_events, tgt_events, src_id, tgt_id)
            all_observations.extend(obs)

        logger.info(
            "EventMatcher.match_all_pairs: %d pairs → %d total candidates.",
            len(ordered_pairs),
            len(all_observations),
        )
        return all_observations


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _merge_provenance(p1: Provenance, p2: Provenance) -> Provenance:
    """Return the 'weakest' provenance of two sources.

    Hierarchy (most → least real): HARDWARE > PUBLIC_DATASET > SYNTHETIC.
    The merged provenance is the least-real of the two, so that a pair
    including a SYNTHETIC event is always labelled SYNTHETIC.
    """
    hierarchy = {
        Provenance.HARDWARE: 2,
        Provenance.PUBLIC_DATASET: 1,
        Provenance.SYNTHETIC: 0,
    }
    if hierarchy[Provenance(p1)] <= hierarchy[Provenance(p2)]:
        return Provenance(p1)
    return Provenance(p2)
