"""
TCMIM — Directional consistency and gating (S7, FR-GT-1, FR-GT-2).

The gating pipeline applies a sequence of independent gates to each
PropagationObservation.  A candidate is rejected at the FIRST gate it
fails, and the reject_reason is recorded.

Gates (applied in order)
------------------------
G0 — STRUCTURAL_MASK
     Physical connectivity prior constraint (M-PHY).
     Permits candidate if mask status is 1 (ALLOWED).
     Rejects if mask status is 0 (DISALLOWED).
     Applies allow_unknown policy if mask status is ? (UNKNOWN).

G1 — DELAY_FEASIBILITY
     Δt must be in [min_delay_s, max_delay_s].
     (A quick sanity check — should already be satisfied by the matcher,
     but re-checked here as the gate config may differ.)

G2 — ORDERING
     t_source_onset < t_target_onset, i.e. Δt > 0.
     (The source must fire strictly before the target.)

G3 — DIRECTION_CONSISTENCY
     Over all accepted candidates for this pair so far, the fraction
     with Δt > 0 must meet a minimum threshold.
     Requires a running accumulator (passed in by the caller).

G4 — HEALTH_CONSISTENCY
     The source machine must show health degradation at the source event
     onset.  Requires the HealthSample at the source window.

G5 — RELATIONSHIP_CONSISTENCY
     The source and target events must share the same modality.

Each gate logs its rejection reason.  All rejected observations are
retained (gate_result="rejected") for audit (FR-GT-2).

INTEGRITY NOTE
--------------
Passing all gates means the pair is a plausible candidate — NOT that
propagation has been confirmed.  Confirmation requires OC-CCD (S8)
and the full edge lifecycle (S9).

Usage
-----
>>> from tcmim.gating.gates import GatingPipeline, GatingConfig
>>> gating = GatingPipeline(GatingConfig())
>>> gated = gating.apply(observations, health_map=health_map)
"""

from __future__ import annotations

import logging
from copy import copy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus
from tcmim.schemas import EventRecord, HealthSample, PropagationObservation

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass
class GatingConfig:
    """Configuration for the gating pipeline.

    Attributes
    ----------
    min_delay_s           : Minimum feasible delay (G1).
    max_delay_s           : Maximum feasible delay (G1).
    require_positive_dt   : If True, apply G2 (Δt > 0 required).
    min_direction_consistency : Minimum fraction of positive-Δt observations
                               for G3 to pass (evaluated cumulatively).
    min_direction_n       : Minimum number of observations before G3 is
                            applied; skip G3 if fewer observations exist.
    health_degradation_threshold : G4: source health_score below this
                                   value is considered "degraded".
    require_same_modality : If True, apply G5 (same modality required).
    structural_mask       : Optional PhysicalStructuralMask (G0).
                            If None, G0 is skipped (legacy / benchmark compatibility).
    allow_unknown         : Policy for G0 when candidate edge has status UNKNOWN ('?').
                            False: conservative SWaT mode (rejects unverified edges).
                            True: compatibility mode (permits unverified edges while
                            preserving their unresolved status in audit trail).
    """
    min_delay_s: float = 0.0
    max_delay_s: float = 600.0
    require_positive_dt: bool = True
    min_direction_consistency: float = 0.6
    min_direction_n: int = 3
    health_degradation_threshold: float = 0.7
    require_same_modality: bool = True
    structural_mask: Optional[PhysicalStructuralMask] = None
    allow_unknown: bool = True


# --------------------------------------------------------------------------
# Gate result record
# --------------------------------------------------------------------------

@dataclass
class GateOutcome:
    """Result of one gate check on one observation."""
    gate: str          # gate name
    passed: bool
    reason: str        # human-readable reason for rejection (or "pass")


# --------------------------------------------------------------------------
# Individual gate functions
# --------------------------------------------------------------------------

def gate_structural_mask(
    obs: PropagationObservation,
    mask: PhysicalStructuralMask,
    allow_unknown: bool = False,
    state_evidence: Optional[Dict[str, Any]] = None,
    max_age_s: Optional[float] = None,
    current_time: Optional[Any] = None,
    require_freshness: bool = False,
) -> GateOutcome:
    """G0 — Physical structural mask constraint (M-PHY).

    Parameters
    ----------
    obs              : Candidate observation to evaluate.
    mask             : PhysicalStructuralMask prior instance.
    allow_unknown    : If False (conservative SWaT mode), reject candidate edges with
                       mask status UNKNOWN ('?').
                       If True (compatibility/audit mode), permit candidate edges with
                       mask status UNKNOWN ('?') to continue to subsequent gates, preserving
                       their unresolved status in the observation audit trail.
                       NOTE: allow_unknown does NOT bypass CONDITIONAL ('C') edges.
    state_evidence   : Optional dictionary of component state evidence (e.g. {'MV201': 2}
                       or {'MV201': {'value': 2, 'timestamp': ...}}). If None, falls back
                       to getattr(obs, 'state_evidence', None).
    max_age_s        : Maximum allowable age in seconds for actuator state freshness.
    current_time     : Current reference timestamp for freshness verification.
    require_freshness: If True, reject if state evidence lacks timestamp.

    Returns
    -------
    GateOutcome with gate="G0_STRUCTURAL_MASK".
    """
    status = mask.get_status(obs.source_machine, obs.target_machine)

    if status == StructuralStatus.ALLOWED:
        return GateOutcome(gate="G0_STRUCTURAL_MASK", passed=True, reason="pass")

    elif status == StructuralStatus.DISALLOWED:
        return GateOutcome(
            gate="G0_STRUCTURAL_MASK",
            passed=False,
            reason=(
                f"Prohibited by physical structural mask (status=0): "
                f"no physical connection {obs.source_machine} -> {obs.target_machine}."
            ),
        )

    elif status == StructuralStatus.CONDITIONAL:
        rec = mask.get_record(obs.source_machine, obs.target_machine)
        pred = rec.condition_predicate if rec is not None else None

        if pred is None:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=False,
                reason=(
                    f"Rejected conditional edge (status=C): {obs.source_machine} -> {obs.target_machine} "
                    f"has missing or malformed operating-state predicate."
                ),
            )

        evidence = state_evidence
        if evidence is None:
            evidence = getattr(obs, "state_evidence", None)

        if evidence is None:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=False,
                reason=(
                    f"Rejected conditional edge (status=C): {obs.source_machine} -> {obs.target_machine} "
                    f"requires condition '{pred.raw_expression}', but state evidence is missing (fail-closed)."
                ),
            )

        satisfied, eval_reason = pred.evaluate(
            evidence,
            max_age_s=max_age_s,
            current_time=current_time,
            require_freshness=require_freshness,
        )

        if satisfied:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=True,
                reason=f"pass: conditional constraint satisfied ({eval_reason})",
            )
        else:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=False,
                reason=(
                    f"Rejected conditional edge (status=C): {obs.source_machine} -> {obs.target_machine} "
                    f"predicate '{pred.raw_expression}' not satisfied ({eval_reason})."
                ),
            )

    else:  # UNKNOWN ('?')
        if allow_unknown:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=True,
                reason=(
                    f"Permitted under policy (status=?): unverified physical connection "
                    f"{obs.source_machine} -> {obs.target_machine}."
                ),
            )
        else:
            return GateOutcome(
                gate="G0_STRUCTURAL_MASK",
                passed=False,
                reason=(
                    f"Rejected under conservative policy (status=?): unverified physical connection "
                    f"{obs.source_machine} -> {obs.target_machine}."
                ),
            )


def gate_delay_feasibility(
    obs: PropagationObservation,
    min_delay_s: float,
    max_delay_s: float,
) -> GateOutcome:
    """G1 — Delay feasibility check."""
    passed = min_delay_s <= obs.delta_t_s <= max_delay_s
    reason = (
        "pass"
        if passed
        else (
            f"Δt={obs.delta_t_s:.2f}s outside feasible window "
            f"[{min_delay_s}, {max_delay_s}]"
        )
    )
    return GateOutcome(gate="G1_DELAY_FEASIBILITY", passed=passed, reason=reason)


def gate_ordering(obs: PropagationObservation) -> GateOutcome:
    """G2 — Ordering: source must fire strictly before target (Δt > 0)."""
    passed = obs.delta_t_s > 0
    reason = (
        "pass"
        if passed
        else f"Δt={obs.delta_t_s:.2f}s ≤ 0: target did not follow source."
    )
    return GateOutcome(gate="G2_ORDERING", passed=passed, reason=reason)


def gate_direction_consistency(
    obs: PropagationObservation,
    prior_accepted: List[PropagationObservation],
    min_consistency: float,
    min_n: int,
) -> GateOutcome:
    """G3 — Direction consistency: sufficient fraction of Δt > 0 in history.

    Parameters
    ----------
    obs            : Current observation being evaluated.
    prior_accepted : Previously accepted observations for the same pair.
    min_consistency: Minimum fraction of Δt>0 required.
    min_n          : Minimum history size before this gate applies.
    """
    pair_history = [
        o for o in prior_accepted
        if o.source_machine == obs.source_machine
        and o.target_machine == obs.target_machine
    ]

    if len(pair_history) < min_n:
        # Not enough history — gate passes by default
        return GateOutcome(
            gate="G3_DIRECTION_CONSISTENCY",
            passed=True,
            reason=f"skip: history size {len(pair_history)} < min_n={min_n}",
        )

    consistency = float(
        np.mean([o.delta_t_s > 0 for o in pair_history])
    )
    passed = consistency >= min_consistency
    reason = (
        "pass"
        if passed
        else (
            f"direction_consistency={consistency:.2f} < "
            f"threshold={min_consistency} "
            f"(n={len(pair_history)})"
        )
    )
    return GateOutcome(gate="G3_DIRECTION_CONSISTENCY", passed=passed, reason=reason)


def gate_health_consistency(
    obs: PropagationObservation,
    health_map: Dict[str, List[HealthSample]],
    degradation_threshold: float,
) -> GateOutcome:
    """G4 — Health consistency: source machine must be degraded at source onset.

    Parameters
    ----------
    obs                   : Observation to check.
    health_map            : Dict machine_id → list of HealthSample (sorted by time).
    degradation_threshold : health_score below this → machine considered degraded.
    """
    if obs.source_machine not in health_map:
        # No health data for source — gate skipped (cannot reject without data)
        return GateOutcome(
            gate="G4_HEALTH_CONSISTENCY",
            passed=True,
            reason="skip: no health data for source machine.",
        )

    source_health_samples = health_map[obs.source_machine]
    if not source_health_samples:
        return GateOutcome(
            gate="G4_HEALTH_CONSISTENCY",
            passed=True,
            reason="skip: empty health sample list for source machine.",
        )

    # Use the most recently available health sample for the source machine.
    # A more precise implementation (M5 design review) would look up the
    # health sample whose window covers the source event onset_time.
    # For now, we use the last available sample (conservative approach).
    latest_hs = source_health_samples[-1]
    passed = latest_hs.health_score < degradation_threshold
    reason = (
        "pass"
        if passed
        else (
            f"source health_score={latest_hs.health_score:.3f} ≥ "
            f"threshold={degradation_threshold} — source appears healthy."
        )
    )
    return GateOutcome(gate="G4_HEALTH_CONSISTENCY", passed=passed, reason=reason)


def gate_relationship_consistency(
    obs: PropagationObservation,
    source_event: Optional[EventRecord],
    target_event: Optional[EventRecord],
) -> GateOutcome:
    """G5 — Relationship consistency: same modality required.

    Parameters
    ----------
    obs          : The observation to gate.
    source_event : Full EventRecord for the source event (or None).
    target_event : Full EventRecord for the target event (or None).
    """
    if source_event is None or target_event is None:
        return GateOutcome(
            gate="G5_RELATIONSHIP_CONSISTENCY",
            passed=True,
            reason="skip: event record(s) not available for modality check.",
        )

    passed = source_event.modality == target_event.modality
    reason = (
        "pass"
        if passed
        else (
            f"modality mismatch: source={source_event.modality.value}, "
            f"target={target_event.modality.value}"
        )
    )
    return GateOutcome(gate="G5_RELATIONSHIP_CONSISTENCY", passed=passed, reason=reason)


# --------------------------------------------------------------------------
# Gating pipeline
# --------------------------------------------------------------------------

class GatingPipeline:
    """Apply all 5 gates to a list of PropagationObservations.

    Parameters
    ----------
    config : GatingConfig with all gate thresholds.
    """

    def __init__(self, config: Optional[GatingConfig] = None) -> None:
        self.config = config or GatingConfig()

    def apply(
        self,
        observations: List[PropagationObservation],
        *,
        health_map: Optional[Dict[str, List[HealthSample]]] = None,
        event_index: Optional[Dict[str, EventRecord]] = None,
        state_evidence_map: Optional[Dict[str, Dict[str, Any]]] = None,
        state_evidence: Optional[Dict[str, Any]] = None,
        max_age_s: Optional[float] = None,
        current_time: Optional[Any] = None,
        require_freshness: bool = False,
    ) -> Tuple[List[PropagationObservation], List[PropagationObservation]]:
        """Apply all gates to each observation in sequence.

        Parameters
        ----------
        observations       : Candidate PropagationObservations from the matcher.
        health_map         : Dict machine_id → List[HealthSample] (for G4).
                             If None, G4 is skipped for all observations.
        event_index        : Dict event_id → EventRecord (for G5).
                             If None, G5 is skipped.
        state_evidence_map : Dict obs_id or event_id -> Dict of actuator states.
        state_evidence     : Fallback actuator state evidence dict for all observations.
        max_age_s          : Maximum allowable age in seconds for actuator state freshness.
        current_time       : Current reference timestamp for freshness verification.
        require_freshness  : If True, reject if state evidence lacks timestamp.

        Returns
        -------
        (accepted, rejected) — two separate lists.
        Rejected observations have gate_result="rejected" and reject_reason set.

        Notes
        -----
        G3 (direction consistency) uses a running accumulator built from
        the observations accepted SO FAR in the current batch.  Order
        of input therefore matters — pass observations sorted by onset time.
        """
        cfg = self.config
        health_map = health_map or {}
        event_index = event_index or {}

        accepted: List[PropagationObservation] = []
        rejected: List[PropagationObservation] = []

        for obs in observations:
            outcome = self._gate_one(
                obs,
                accepted,
                health_map,
                event_index,
                cfg,
                state_evidence_map=state_evidence_map,
                state_evidence=state_evidence,
                max_age_s=max_age_s,
                current_time=current_time,
                require_freshness=require_freshness,
            )
            mask_val = (
                cfg.structural_mask.get_status(obs.source_machine, obs.target_machine).value
                if cfg.structural_mask is not None
                else getattr(obs, "structural_mask_status", None)
            )
            if outcome is None:
                # All gates passed
                accepted_obs = copy(obs)
                accepted_obs.gate_result = "accepted"
                accepted_obs.reject_reason = None
                accepted_obs.structural_mask_status = mask_val
                accepted.append(accepted_obs)
            else:
                rejected_obs = copy(obs)
                rejected_obs.gate_result = "rejected"
                rejected_obs.reject_reason = outcome.reason
                rejected_obs.structural_mask_status = mask_val
                rejected.append(rejected_obs)
                logger.debug(
                    "REJECTED [%s] %s→%s Δt=%.1fs: %s",
                    outcome.gate,
                    obs.source_machine,
                    obs.target_machine,
                    obs.delta_t_s,
                    outcome.reason,
                )

        logger.info(
            "GatingPipeline: %d accepted, %d rejected (of %d total).",
            len(accepted), len(rejected), len(observations),
        )
        return accepted, rejected

    def _gate_one(
        self,
        obs: PropagationObservation,
        accepted_so_far: List[PropagationObservation],
        health_map: Dict[str, List[HealthSample]],
        event_index: Dict[str, EventRecord],
        cfg: GatingConfig,
        state_evidence_map: Optional[Dict[str, Dict[str, Any]]] = None,
        state_evidence: Optional[Dict[str, Any]] = None,
        max_age_s: Optional[float] = None,
        current_time: Optional[Any] = None,
        require_freshness: bool = False,
    ) -> Optional[GateOutcome]:
        """Run gates in order; return the first failing GateOutcome, or None."""

        # G0 — Structural mask (evaluated FIRST, before delay feasibility)
        if cfg.structural_mask is not None:
            # Resolve evidence for this observation
            obs_evidence = getattr(obs, "state_evidence", None)
            if obs_evidence is None and state_evidence_map is not None:
                obs_evidence = state_evidence_map.get(obs.obs_id) or state_evidence_map.get(obs.source_event)
            if obs_evidence is None:
                obs_evidence = state_evidence

            g0 = gate_structural_mask(
                obs,
                cfg.structural_mask,
                cfg.allow_unknown,
                state_evidence=obs_evidence,
                max_age_s=max_age_s,
                current_time=current_time,
                require_freshness=require_freshness,
            )
            if not g0.passed:
                return g0

        # G1 — Delay feasibility
        g1 = gate_delay_feasibility(obs, cfg.min_delay_s, cfg.max_delay_s)
        if not g1.passed:
            return g1

        # G2 — Ordering
        if cfg.require_positive_dt:
            g2 = gate_ordering(obs)
            if not g2.passed:
                return g2

        # G3 — Direction consistency
        g3 = gate_direction_consistency(
            obs,
            accepted_so_far,
            cfg.min_direction_consistency,
            cfg.min_direction_n,
        )
        if not g3.passed:
            return g3

        # G4 — Health consistency
        g4 = gate_health_consistency(obs, health_map, cfg.health_degradation_threshold)
        if not g4.passed:
            return g4

        # G5 — Relationship consistency
        src_evt = event_index.get(obs.source_event)
        tgt_evt = event_index.get(obs.target_event)
        if cfg.require_same_modality:
            g5 = gate_relationship_consistency(obs, src_evt, tgt_evt)
            if not g5.passed:
                return g5

        return None   # all passed
