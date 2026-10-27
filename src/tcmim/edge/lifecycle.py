"""
TCMIM — Edge lifecycle state machine (S9, FR-EL-1, FR-EL-2).

Implements the deterministic 8-state lifecycle for propagation edges:

    NONE → CANDIDATE → PROVISIONAL → CONFIRMED →
    STRENGTHENING → STABLE → WEAKENING → EXPIRED

Transition rules
----------------
UPWARD (more evidence):
  NONE → CANDIDATE       : evidence_count >= candidate_threshold
  CANDIDATE → PROVISIONAL: evidence_count >= provisional_threshold
  PROVISIONAL → CONFIRMED: evidence_count >= confirmed_threshold
                           AND direction_consistency >= min_direction_consistency
  CONFIRMED → STRENGTHENING: evidence_count >= strengthening_threshold
  STRENGTHENING → STABLE : evidence_count >= stable_threshold

DOWNWARD (absence of evidence):
  Any active state → WEAKENING  : consecutive_silence >= weakening_threshold
  WEAKENING → EXPIRED           : consecutive_silence >= expired_threshold
  EXPIRED → NONE (implicit reset when new evidence arrives)

Key constraints (FR-EL-2)
--------------------------
- One observation NEVER creates a CONFIRMED or higher edge.
- direction_consistency gate is enforced before CONFIRMED.
- Transitions are logged for auditability.

Usage
-----
>>> from tcmim.edge.lifecycle import EdgeLifecycleStateMachine, LifecycleConfig
>>> lc = EdgeLifecycleConfig()
>>> sm = EdgeLifecycleStateMachine(lc)
>>> new_state = sm.transition(current_state, evidence_count,
...                            direction_consistency, consecutive_silence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from tcmim.config import EdgeLifecycleConfig
from tcmim.schemas import EdgeRecord, EdgeState, Modality, Provenance

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Transition log entry
# --------------------------------------------------------------------------

@dataclass
class TransitionEvent:
    """Record of one state transition.

    Attributes
    ----------
    edge_key          : "{source}→{target}" identifier.
    from_state        : State before transition.
    to_state          : State after transition.
    evidence_count    : Evidence count at time of transition.
    direction_consistency : Direction consistency at transition.
    consecutive_silence   : Silence count at transition.
    timestamp         : UTC time of transition.
    reason            : Human-readable reason.
    """
    edge_key: str
    from_state: EdgeState
    to_state: EdgeState
    evidence_count: int
    direction_consistency: float
    consecutive_silence: int
    timestamp: datetime
    reason: str


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------

class EdgeLifecycleStateMachine:
    """Deterministic edge lifecycle state machine (FR-EL-1).

    Parameters
    ----------
    config : EdgeLifecycleConfig with all transition thresholds.
    """

    def __init__(self, config: Optional[EdgeLifecycleConfig] = None) -> None:
        self.config = config or EdgeLifecycleConfig()

    def transition(
        self,
        current_state: EdgeState,
        evidence_count: int,
        direction_consistency: float,
        consecutive_silence: int,
        edge_key: str = "?→?",
    ) -> Tuple[EdgeState, Optional[TransitionEvent]]:
        """Compute the next state given the current evidence.

        Parameters
        ----------
        current_state         : Current EdgeState.
        evidence_count        : Total accepted observations for this edge.
        direction_consistency : Fraction of observations with Δt > 0.
        consecutive_silence   : Number of evaluation periods with no new
                                accepted observations.
        edge_key              : Human-readable edge identifier for logging.

        Returns
        -------
        (next_state, transition_event_or_None)
        If no transition occurred, returns (current_state, None).
        """
        cfg = self.config

        # ---- Downward transitions (silence wins over upward) ----
        if consecutive_silence >= cfg.expired_threshold and current_state not in (
            EdgeState.NONE, EdgeState.EXPIRED, EdgeState.UNEXCITED_PRIOR
        ):
            return self._make_transition(
                current_state, EdgeState.EXPIRED,
                evidence_count, direction_consistency, consecutive_silence,
                edge_key,
                reason=f"Silence ≥ expired_threshold ({cfg.expired_threshold})",
            )

        if consecutive_silence >= cfg.weakening_threshold and current_state in (
            EdgeState.STABLE, EdgeState.STRENGTHENING,
            EdgeState.CONFIRMED, EdgeState.PROVISIONAL, EdgeState.CANDIDATE,
        ):
            return self._make_transition(
                current_state, EdgeState.WEAKENING,
                evidence_count, direction_consistency, consecutive_silence,
                edge_key,
                reason=f"Silence ≥ weakening_threshold ({cfg.weakening_threshold})",
            )

        # ---- Upward transitions ----
        if current_state == EdgeState.NONE:
            if evidence_count >= cfg.candidate_threshold:
                return self._make_transition(
                    current_state, EdgeState.CANDIDATE,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=f"evidence_count={evidence_count} ≥ candidate_threshold={cfg.candidate_threshold}",
                )

        elif current_state == EdgeState.UNEXCITED_PRIOR:
            # An unexcited prior transitions to CANDIDATE once fresh dynamic excitation arrives
            if consecutive_silence == 0 and evidence_count >= cfg.candidate_threshold:
                return self._make_transition(
                    current_state, EdgeState.CANDIDATE,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=(
                        f"Dynamic excitation observed: transitioned from UNEXCITED_PRIOR to CANDIDATE "
                        f"(evidence_count={evidence_count} ≥ candidate_threshold={cfg.candidate_threshold})"
                    ),
                )

        elif current_state == EdgeState.EXPIRED:
            # An EXPIRED edge cannot restart merely because historical evidence_count
            # remains high. Fresh evidence in the current cycle is strictly required
            # (consecutive_silence == 0).
            if consecutive_silence == 0 and evidence_count >= cfg.candidate_threshold:
                return self._make_transition(
                    current_state, EdgeState.CANDIDATE,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=(
                        f"Restarted from EXPIRED: fresh evidence arrived "
                        f"(evidence_count={evidence_count} ≥ candidate_threshold={cfg.candidate_threshold})"
                    ),
                )

        elif current_state == EdgeState.CANDIDATE:
            if evidence_count >= cfg.provisional_threshold:
                return self._make_transition(
                    current_state, EdgeState.PROVISIONAL,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=f"evidence_count={evidence_count} ≥ provisional_threshold={cfg.provisional_threshold}",
                )

        elif current_state == EdgeState.PROVISIONAL:
            if (
                evidence_count >= cfg.confirmed_threshold
                and direction_consistency >= cfg.min_direction_consistency
            ):
                return self._make_transition(
                    current_state, EdgeState.CONFIRMED,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=(
                        f"evidence_count={evidence_count} ≥ confirmed_threshold={cfg.confirmed_threshold} "
                        f"AND direction_consistency={direction_consistency:.2f} ≥ {cfg.min_direction_consistency}"
                    ),
                )

        elif current_state == EdgeState.CONFIRMED:
            if evidence_count >= cfg.strengthening_threshold:
                return self._make_transition(
                    current_state, EdgeState.STRENGTHENING,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=f"evidence_count={evidence_count} ≥ strengthening_threshold={cfg.strengthening_threshold}",
                )

        elif current_state == EdgeState.STRENGTHENING:
            if evidence_count >= cfg.stable_threshold:
                return self._make_transition(
                    current_state, EdgeState.STABLE,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason=f"evidence_count={evidence_count} ≥ stable_threshold={cfg.stable_threshold}",
                )

        elif current_state == EdgeState.WEAKENING:
            # Can recover if new evidence arrives
            if consecutive_silence == 0 and evidence_count >= cfg.provisional_threshold:
                return self._make_transition(
                    current_state, EdgeState.PROVISIONAL,
                    evidence_count, direction_consistency, consecutive_silence,
                    edge_key,
                    reason="Recovered from WEAKENING: new evidence arrived.",
                )

        # No transition
        return current_state, None

    @staticmethod
    def _make_transition(
        from_state: EdgeState,
        to_state: EdgeState,
        evidence_count: int,
        direction_consistency: float,
        consecutive_silence: int,
        edge_key: str,
        reason: str,
    ) -> Tuple[EdgeState, TransitionEvent]:
        event = TransitionEvent(
            edge_key=edge_key,
            from_state=from_state,
            to_state=to_state,
            evidence_count=evidence_count,
            direction_consistency=direction_consistency,
            consecutive_silence=consecutive_silence,
            timestamp=datetime.now(tz=timezone.utc),
            reason=reason,
        )
        logger.info(
            "EdgeLifecycle [%s]: %s → %s (n=%d, dir=%.2f, sil=%d) — %s",
            edge_key, from_state.value, to_state.value,
            evidence_count, direction_consistency, consecutive_silence, reason,
        )
        return to_state, event
