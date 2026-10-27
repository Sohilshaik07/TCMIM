"""
experiments/stage4_experimental_gating.py
=========================================
TCMIM Stage 4: Operating-State-Aware Experimental Gating Layer.

Resolves the architectural gap identified in the Stage 3.3 audit:
- Physical edge P301 -> DPIT301 is ALLOWED at structural Gate G0.
- Dynamic validity is bifurcated:
    * State S2 (MV302 == 1, closed): Independently validated (R2 = 0.9936),
      delay window [5.0, 55.0]s.
    * State S3 (MV302 == 2, open / A6-associated): In-sample descriptive fit
      (N=1, R2 = 0.9961), lacks independent out-of-sample validation.
- This module introduces:
    1. OperatingRegime (Enum)
    2. RegimeResolutionResult (Dataclass)
    3. OperatingStateResolver: Deterministic, fail-closed regime identification
       inspecting only physical actuator telemetry (NO attack labels).
    4. StateAwareExperimentalGatingPipeline: Enforces regime-specific delay
       eligibility prior to delay feasibility check. Quarantines unvalidated
       regimes (State S3) and fails closed on unknown or invalid states.
       Unrelated relationships retain standard gating behavior.

SAFETY AND ISOLATION CONTRACT:
- Implemented ONLY in the experimental evaluation layer.
- Zero production code integration (src/tcmim/ remains clean and unmodified).
- Plantwide CRI remains completely disabled.
"""

from __future__ import annotations

import logging
from copy import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from tcmim.gating.gates import (
    GateOutcome,
    GatingConfig,
    GatingPipeline,
    gate_delay_feasibility,
    gate_direction_consistency,
    gate_health_consistency,
    gate_ordering,
    gate_relationship_consistency,
    gate_structural_mask,
)
from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus
from tcmim.schemas import EventRecord, HealthSample, PropagationObservation

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Operating Regime Definitions
# --------------------------------------------------------------------------

class OperatingRegime(str, Enum):
    """Authoritative operating regimes for state-dependent dynamic relationships."""
    STATE_S2_NORMAL = "STATE_S2_NORMAL"
    STATE_S3_UNVALIDATED = "STATE_S3_UNVALIDATED"
    UNKNOWN_REGIME = "UNKNOWN_REGIME"


@dataclass(frozen=True)
class RegimeResolutionResult:
    """Detailed result of operating regime resolution."""
    regime: OperatingRegime
    is_validated: bool
    delay_bounds: Optional[Tuple[float, float]]
    reason: str
    actuator: Optional[str] = None
    actuator_value: Optional[Any] = None
    quality: str = "GOOD"
    is_stale: bool = False


# --------------------------------------------------------------------------
# Operating State Resolver
# --------------------------------------------------------------------------

class OperatingStateResolver:
    """Deterministic, fail-closed operating-state resolver for experimental gating.

    Rules:
    - Identifies physical operating regimes, NOT attacks.
    - Does NOT use attack labels or anomaly ground truth.
    - Does NOT infer causality from correlation alone.
    - Fails closed to UNKNOWN_REGIME on missing, invalid, contradictory, stale,
      or uncharacterized actuator telemetry.
    - Does NOT classify unknown states as normal by default.
    """

    SUPPORTED_RELATIONSHIPS = {
        ("P301", "DPIT301"): "MV302",
    }

    @classmethod
    def resolve_p301_regime(
        cls,
        evidence: Optional[Dict[str, Any]],
        *,
        max_age_s: Optional[float] = 10.0,
        current_time: Optional[Any] = None,
        require_freshness: bool = False,
    ) -> RegimeResolutionResult:
        """Resolve operating regime for P301 -> DPIT301 conditioned on MV302.

        MV302 == 1 (CLOSED):
            State S2 Normal Startup. Independently validated across held-out
            normal episodes (R2 = 0.9936, RMSE = 0.1877 kPa).
            Supported empirical delay window: [5.0, 55.0] s.

        MV302 == 2 (OPEN):
            State S3 Permeate-Open Startup (Attack A6 associated).
            Dynamic model is an in-sample descriptive fit (N=1 episode,
            R2 = 0.9961) lacking independent out-of-sample validation.
            Must be quarantined from delay gating.

        Missing / Invalid / Stale / Sentinels:
            UNKNOWN_REGIME. Fails closed.
        """
        actuator = "MV302"

        if evidence is None or not isinstance(evidence, dict):
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason="MISSING_STATE_EVIDENCE: evidence dict is None or not a dict",
                actuator=actuator,
            )

        if actuator not in evidence:
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason=f"MISSING_ACTUATOR_STATE: actuator '{actuator}' missing from evidence",
                actuator=actuator,
            )

        entry = evidence[actuator]
        raw_val: Any
        timestamp: Optional[Any] = None
        quality: str = "GOOD"
        is_stale: bool = False

        if isinstance(entry, dict):
            raw_val = entry.get("value")
            timestamp = entry.get("timestamp")
            quality = str(entry.get("quality", "GOOD")).strip().upper()
            is_stale = bool(entry.get("is_stale", False))
            if quality in ("BAD", "INVALID", "UNCERTAIN", "CONTRADICTORY"):
                return RegimeResolutionResult(
                    regime=OperatingRegime.UNKNOWN_REGIME,
                    is_validated=False,
                    delay_bounds=None,
                    reason=f"INVALID_QUALITY: actuator '{actuator}' quality flag '{quality}'",
                    actuator=actuator,
                    actuator_value=raw_val,
                    quality=quality,
                    is_stale=is_stale,
                )
            if is_stale:
                return RegimeResolutionResult(
                    regime=OperatingRegime.UNKNOWN_REGIME,
                    is_validated=False,
                    delay_bounds=None,
                    reason=f"STALE_STATE_EVIDENCE: actuator '{actuator}' flagged as stale",
                    actuator=actuator,
                    actuator_value=raw_val,
                    quality=quality,
                    is_stale=True,
                )
        else:
            raw_val = entry

        if raw_val is None:
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason=f"NULL_ACTUATOR_VALUE: actuator '{actuator}' value is None",
                actuator=actuator,
                quality=quality,
            )

        # Check sentinel strings
        if isinstance(raw_val, str):
            clean_s = raw_val.strip().upper()
            if clean_s in ("?", "UNKNOWN", "NAN", "INVALID", "CONTRADICTORY", "STALE", "MISSING", "NONE"):
                return RegimeResolutionResult(
                    regime=OperatingRegime.UNKNOWN_REGIME,
                    is_validated=False,
                    delay_bounds=None,
                    reason=f"INVALID_VALUE: actuator '{actuator}' has sentinel string '{raw_val}'",
                    actuator=actuator,
                    actuator_value=raw_val,
                    quality=quality,
                )

        # Timestamp and freshness validation
        if require_freshness and timestamp is None:
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason=f"MISSING_TIMESTAMP_FOR_FRESHNESS: actuator '{actuator}' lacks required timestamp",
                actuator=actuator,
                actuator_value=raw_val,
                quality=quality,
            )

        if max_age_s is not None and timestamp is not None and current_time is not None:
            try:
                t_cur = current_time.timestamp() if hasattr(current_time, "timestamp") else float(current_time)
                t_rec = timestamp.timestamp() if hasattr(timestamp, "timestamp") else float(timestamp)
                age = t_cur - t_rec
                if age < -1.0:
                    return RegimeResolutionResult(
                        regime=OperatingRegime.UNKNOWN_REGIME,
                        is_validated=False,
                        delay_bounds=None,
                        reason=f"FUTURE_TIMESTAMP: actuator '{actuator}' timestamp in future (age={age:.1f}s)",
                        actuator=actuator,
                        actuator_value=raw_val,
                        quality=quality,
                    )
                if age > max_age_s:
                    return RegimeResolutionResult(
                        regime=OperatingRegime.UNKNOWN_REGIME,
                        is_validated=False,
                        delay_bounds=None,
                        reason=f"STALE_STATE_EVIDENCE: actuator '{actuator}' age {age:.1f}s > max_age_s={max_age_s}s",
                        actuator=actuator,
                        actuator_value=raw_val,
                        quality=quality,
                        is_stale=True,
                    )
            except (ValueError, TypeError) as e:
                return RegimeResolutionResult(
                    regime=OperatingRegime.UNKNOWN_REGIME,
                    is_validated=False,
                    delay_bounds=None,
                    reason=f"TIMESTAMP_COMPARISON_FAILED: {e}",
                    actuator=actuator,
                    actuator_value=raw_val,
                    quality=quality,
                )

        # Value parsing
        parsed_val: int
        try:
            parsed_val = int(float(raw_val))
        except (ValueError, TypeError):
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason=f"NON_NUMERIC_ACTUATOR_VALUE: cannot parse '{raw_val}' as integer",
                actuator=actuator,
                actuator_value=raw_val,
                quality=quality,
            )

        # Regime mapping
        if parsed_val == 1:
            # MV302 == 1 (CLOSED): Normal Startup
            return RegimeResolutionResult(
                regime=OperatingRegime.STATE_S2_NORMAL,
                is_validated=True,
                delay_bounds=(5.0, 55.0),
                reason=(
                    "STATE_S2_NORMAL: MV302==1 (CLOSED). Normal startup regime with independently "
                    "validated dynamic response across held-out episodes. Delay window [5.0, 55.0]s."
                ),
                actuator=actuator,
                actuator_value=parsed_val,
                quality=quality,
                is_stale=False,
            )
        elif parsed_val == 2:
            # MV302 == 2 (OPEN): Permeate Open Startup (Attack A6 associated)
            return RegimeResolutionResult(
                regime=OperatingRegime.STATE_S3_UNVALIDATED,
                is_validated=False,
                delay_bounds=None,
                reason=(
                    "STATE_S3_UNVALIDATED: MV302==2 (OPEN). Permeate open startup regime (A6-associated). "
                    "Dynamic model is an in-sample descriptive fit lacking independent out-of-sample validation. "
                    "Quarantined from delay-based propagation gating."
                ),
                actuator=actuator,
                actuator_value=parsed_val,
                quality=quality,
                is_stale=False,
            )
        else:
            # Other values (e.g. 0 in-transition, negative, or undefined)
            return RegimeResolutionResult(
                regime=OperatingRegime.UNKNOWN_REGIME,
                is_validated=False,
                delay_bounds=None,
                reason=f"UNCHARACTERIZED_ACTUATOR_STATE: MV302 value {parsed_val} is not recognized",
                actuator=actuator,
                actuator_value=parsed_val,
                quality=quality,
                is_stale=False,
            )

    @classmethod
    def resolve(
        cls,
        source_machine: str,
        target_machine: str,
        evidence: Optional[Dict[str, Any]],
        *,
        max_age_s: Optional[float] = 10.0,
        current_time: Optional[Any] = None,
        require_freshness: bool = False,
    ) -> Optional[RegimeResolutionResult]:
        """Dispatch regime resolution for registered state-dependent relationships.

        Returns None if relationship is not state-conditioned in this resolver.
        """
        pair = (source_machine, target_machine)
        if pair == ("P301", "DPIT301"):
            return cls.resolve_p301_regime(
                evidence,
                max_age_s=max_age_s,
                current_time=current_time,
                require_freshness=require_freshness,
            )
        return None


# --------------------------------------------------------------------------
# State-Aware Experimental Gating Pipeline
# --------------------------------------------------------------------------

class StateAwareExperimentalGatingPipeline(GatingPipeline):
    """Experimental gating pipeline enforcing operating-state-aware delay eligibility.

    Coordinates:
    - G0_STRUCTURAL_MASK: Evaluated first. Preserves existing physical connectivity
      status (P301 -> DPIT301 remains ALLOWED at G0).
    - EXPERIMENTAL_DYNAMIC_ELIGIBILITY: Evaluated before delay feasibility for
      targeted relationships.
      * STATE_S2_NORMAL: Permitted to proceed to delay feasibility with validated
        regime-specific bounds [5.0, 55.0]s.
      * STATE_S3_UNVALIDATED: Quarantined with QUARANTINED_UNVALIDATED_REGIME.
      * UNKNOWN_REGIME: Rejected/quarantined with UNKNOWN_OPERATING_STATE.
      * Unvalidated/unknown regimes CANNOT fall through to the global [0, 600]s window.
    - G1_DELAY_FEASIBILITY: Evaluated using regime-specific bounds for state-dependent
      edges, and standard [min_delay_s, max_delay_s] for unrelated edges.
    - G2-G5: Standard pipeline checks.
    """

    def __init__(
        self,
        config: Optional[GatingConfig] = None,
        resolver: Optional[OperatingStateResolver] = None,
    ) -> None:
        super().__init__(config or GatingConfig())
        self.resolver = resolver or OperatingStateResolver()

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
        """Run state-aware experimental gating in strict sequence."""

        # Resolve evidence for this observation
        obs_evidence = getattr(obs, "state_evidence", None)
        if obs_evidence is None and state_evidence_map is not None:
            obs_evidence = state_evidence_map.get(obs.obs_id) or state_evidence_map.get(obs.source_event)
        if obs_evidence is None:
            obs_evidence = state_evidence

        # 1. G0 — Structural mask (evaluated FIRST, prior to any delay or state gating)
        if cfg.structural_mask is not None:
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

        # 2. State-Aware Dynamic Eligibility Check (Evaluated before delay evaluation)
        regime_res = self.resolver.resolve(
            obs.source_machine,
            obs.target_machine,
            obs_evidence,
            max_age_s=max_age_s,
            current_time=current_time,
            require_freshness=require_freshness,
        )

        effective_min_delay = cfg.min_delay_s
        effective_max_delay = cfg.max_delay_s

        if regime_res is not None:
            # Targeted state-dependent relationship
            if regime_res.regime == OperatingRegime.STATE_S3_UNVALIDATED:
                return GateOutcome(
                    gate="EXPERIMENTAL_DYNAMIC_ELIGIBILITY",
                    passed=False,
                    reason=(
                        f"QUARANTINED_UNVALIDATED_REGIME: {obs.source_machine} -> {obs.target_machine} "
                        f"operating in State S3 (MV302==2 / A6-associated) which lacks independent "
                        f"out-of-sample dynamic validation. Prohibited from delay gating."
                    ),
                )
            elif regime_res.regime == OperatingRegime.UNKNOWN_REGIME:
                return GateOutcome(
                    gate="EXPERIMENTAL_DYNAMIC_ELIGIBILITY",
                    passed=False,
                    reason=(
                        f"UNKNOWN_OPERATING_STATE: {obs.source_machine} -> {obs.target_machine} "
                        f"operating regime cannot be identified fail-closed ({regime_res.reason})."
                    ),
                )
            elif regime_res.regime == OperatingRegime.STATE_S2_NORMAL:
                # Validated regime: apply validated bounds [5.0, 55.0]s
                if regime_res.delay_bounds is not None:
                    effective_min_delay, effective_max_delay = regime_res.delay_bounds
            else:
                return GateOutcome(
                    gate="EXPERIMENTAL_DYNAMIC_ELIGIBILITY",
                    passed=False,
                    reason=f"UNKNOWN_OPERATING_STATE: unhandled regime {regime_res.regime}",
                )

        # 3. G1 — Delay feasibility (using regime-specific bounds if resolved, otherwise standard)
        g1 = gate_delay_feasibility(obs, effective_min_delay, effective_max_delay)
        if not g1.passed:
            # Clarify in reason if regime-specific bounds were applied
            if regime_res is not None and regime_res.regime == OperatingRegime.STATE_S2_NORMAL:
                return GateOutcome(
                    gate="G1_DELAY_FEASIBILITY",
                    passed=False,
                    reason=(
                        f"Δt={obs.delta_t_s:.2f}s outside validated State S2 window "
                        f"[{effective_min_delay}, {effective_max_delay}]s"
                    ),
                )
            return g1

        # 4. G2 — Ordering
        if cfg.require_positive_dt:
            g2 = gate_ordering(obs)
            if not g2.passed:
                return g2

        # 5. G3 — Direction consistency
        g3 = gate_direction_consistency(
            obs,
            accepted_so_far,
            cfg.min_direction_consistency,
            cfg.min_direction_n,
        )
        if not g3.passed:
            return g3

        # 6. G4 — Health consistency
        g4 = gate_health_consistency(obs, health_map, cfg.health_degradation_threshold)
        if not g4.passed:
            return g4

        # 7. G5 — Relationship consistency
        source_rec = event_index.get(obs.source_event)
        target_rec = event_index.get(obs.target_event)
        if cfg.require_same_modality and (source_rec is not None and target_rec is not None):
            g5 = gate_relationship_consistency(obs, source_rec, target_rec)
            if not g5.passed:
                return g5

        return None
