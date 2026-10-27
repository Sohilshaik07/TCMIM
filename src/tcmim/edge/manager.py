"""
TCMIM — Edge manager: processes propagation observations into EdgeRecords (S9).

The EdgeManager maintains a registry of EdgeRecords (one per ordered
machine pair) and updates their states using the EdgeLifecycleStateMachine.

Each update cycle:
1. Collect all newly accepted PropagationObservations for each pair.
2. Compute evidence_count and direction_consistency for each pair.
3. Update consecutive_silence (pairs with no new accepted obs this cycle).
4. Advance the state machine for each active edge.
5. Return all EdgeRecords with updated states and confidence scores.

Confidence score
----------------
Confidence is derived from the edge's current state and evidence density:

    confidence = state_weight × direction_consistency

State weights (fixed):
    NONE/EXPIRED            → 0.0
    CANDIDATE               → 0.1
    PROVISIONAL             → 0.3
    CONFIRMED               → 0.5
    STRENGTHENING           → 0.7
    STABLE                  → 0.9
    WEAKENING               → max(0.0, previous_state_weight − 0.15)

This is a LINEAR, EXPLAINABLE score — not ML-derived.

Usage
-----
>>> from tcmim.edge.manager import EdgeManager
>>> manager = EdgeManager()
>>> edges = manager.update(accepted_observations)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from tcmim.config import EdgeLifecycleConfig
from tcmim.edge.lifecycle import EdgeLifecycleStateMachine, TransitionEvent
from tcmim.schemas import EdgeRecord, EdgeState, Modality, Provenance

logger = logging.getLogger(__name__)


# State-to-weight map (linear confidence weights — FR-EL-2)
_STATE_WEIGHTS: Dict[EdgeState, float] = {
    EdgeState.NONE:          0.0,
    EdgeState.CANDIDATE:     0.1,
    EdgeState.PROVISIONAL:   0.3,
    EdgeState.CONFIRMED:     0.5,
    EdgeState.STRENGTHENING: 0.7,
    EdgeState.STABLE:        0.9,
    EdgeState.WEAKENING:     0.2,
    EdgeState.EXPIRED:       0.0,
}


@dataclass
class _EdgeEntry:
    """Internal mutable state for one machine-pair edge."""
    source_machine: str
    target_machine: str
    state: EdgeState = EdgeState.NONE
    evidence_count: int = 0
    direction_consistency: float = 0.0
    consecutive_silence: int = 0
    confidence: float = 0.0
    provenance: Provenance = Provenance.SYNTHETIC
    last_seen: Optional[datetime] = None
    transition_log: List[TransitionEvent] = field(default_factory=list)
    dominant_modality: Optional[Modality] = None


class EdgeManager:
    """Maintain and update EdgeRecords across evaluation cycles.

    Parameters
    ----------
    config : EdgeLifecycleConfig (thresholds for state transitions).
    """

    def __init__(self, config: Optional[EdgeLifecycleConfig] = None) -> None:
        self._sm = EdgeLifecycleStateMachine(config)
        self._edges: Dict[Tuple[str, str], _EdgeEntry] = {}

    def update(
        self,
        accepted_observations: List,   # List[PropagationObservation]
        cycle_timestamp: Optional[datetime] = None,
    ) -> List[EdgeRecord]:
        """Process one batch of accepted observations.

        Parameters
        ----------
        accepted_observations : New accepted PropagationObservations this cycle.
        cycle_timestamp       : UTC timestamp for this cycle (default: now).

        Returns
        -------
        List of all current EdgeRecords (all pairs seen so far).
        """
        now = cycle_timestamp or datetime.now(tz=timezone.utc)

        # --- Group new observations by machine pair ---
        new_by_pair: Dict[Tuple[str, str], List] = {}
        for obs in accepted_observations:
            if obs.gate_result != "accepted":
                continue
            key = (obs.source_machine, obs.target_machine)
            new_by_pair.setdefault(key, []).append(obs)

        # --- Discover new pairs ---
        for key in new_by_pair:
            if key not in self._edges:
                src, tgt = key
                self._edges[key] = _EdgeEntry(
                    source_machine=src,
                    target_machine=tgt,
                )

        # --- Update each known pair ---
        for key, entry in self._edges.items():
            batch = new_by_pair.get(key, [])

            if not batch:
                # No new observations → increment silence
                entry.consecutive_silence += 1
            else:
                # New evidence: update counts and direction consistency
                entry.evidence_count += len(batch)
                entry.consecutive_silence = 0
                entry.last_seen = now

                all_deltas = [obs.delta_t_s for obs in batch
                              if hasattr(obs, "delta_t_s")]
                if all_deltas:
                    entry.direction_consistency = float(
                        np.mean([d > 0 for d in all_deltas])
                    )
                if batch:
                    entry.provenance = batch[0].provenance
                    # Infer dominant modality from source events if available
                    entry.dominant_modality = None  # resolved at edge level (M7)

            # Advance state machine
            edge_key = f"{entry.source_machine}→{entry.target_machine}"
            new_state, event = self._sm.transition(
                current_state=entry.state,
                evidence_count=entry.evidence_count,
                direction_consistency=entry.direction_consistency,
                consecutive_silence=entry.consecutive_silence,
                edge_key=edge_key,
            )
            if new_state != entry.state:
                entry.state = new_state
                if event:
                    entry.transition_log.append(event)

            # Compute confidence
            entry.confidence = _compute_confidence(
                entry.state, entry.direction_consistency
            )

        # --- Build EdgeRecord list ---
        records: List[EdgeRecord] = []
        for (src, tgt), entry in sorted(self._edges.items()):
            record = EdgeRecord(
                source=src,
                target=tgt,
                state=entry.state,
                evidence_count=entry.evidence_count,
                est_delay_s=0.0,   # enriched by delay module (M5) in full pipeline
                confidence=entry.confidence,
                last_updated=now,
                modality=entry.dominant_modality or Modality.UNKNOWN,
                provenance=entry.provenance,
            )
            records.append(record)

        logger.info(
            "EdgeManager.update: %d pairs, %d with new evidence, "
            "states=%s",
            len(self._edges),
            len(new_by_pair),
            {f"{s}→{t}": e.state.value for (s, t), e in self._edges.items()},
        )
        return records

    def get_edge(self, source: str, target: str) -> Optional[_EdgeEntry]:
        """Return the internal entry for an edge pair (for testing/inspection)."""
        return self._edges.get((source, target))

    def reset(self) -> None:
        """Clear all edge state (for use between experiments)."""
        self._edges.clear()
        logger.info("EdgeManager: all edge state cleared.")


def _compute_confidence(state: EdgeState, direction_consistency: float) -> float:
    """Compute edge confidence in [0, 1] from state weight × direction_consistency."""
    weight = _STATE_WEIGHTS.get(state, 0.0)
    return float(np.clip(weight * direction_consistency, 0.0, 1.0))
