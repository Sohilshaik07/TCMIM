"""
TCMIM — OC-CCD: Onset Correction and Common-Cause Discrimination (S8).

FR-CC-1: Discriminate shared disturbances from possible propagation.
FR-CC-2: OC-CCD output is LABELLED EVIDENCE, never proof.

Four discrimination checks
--------------------------
T1 — SIMULTANEITY
     If |Δt_corrected| < simultaneity_threshold_s, the two events
     occurred near-simultaneously.  This is consistent with a shared
     disturbance triggering both machines at once.
     Result: COMMON_CAUSE_CANDIDATE

T2 — ONSET_BIAS
     If the mean Δt across all observations for this pair is
     systematically very close to zero (within bias_threshold_s),
     this may indicate both machines share a common driver.
     Result: COMMON_CAUSE_CANDIDATE (weak)

T3 — MULTI_PAIR_COINCIDENCE
     If the same time interval sees events on many machine pairs
     simultaneously (more than coincidence_pair_threshold pairs),
     this is consistent with a plant-wide disturbance.
     Result: COMMON_CAUSE_CANDIDATE (strong)

T4 — ONSET_CORRECTION
     CUSUM and similar detectors have inherent lag: the alarm fires
     after the change, not at the change.  The corrected Δt subtracts
     estimated detector lags from both source and target onset times.
     A very small corrected Δt is more consistent with simultaneous
     response to a shared disturbance.

OUTPUT LABELS (FR-CC-2)
-----------------------
    PROPAGATION_CANDIDATE  — passes all checks; consistent with propagation
    COMMON_CAUSE_CANDIDATE — failed at least one check; consistent with
                              shared disturbance
    AMBIGUOUS              — inconclusive evidence

INTEGRITY NOTE
--------------
None of these labels constitute proof.  "PROPAGATION_CANDIDATE" means
the observation is not explained by common-cause checks — it does NOT
confirm propagation.  Physical validation (M9) is required for that.

Usage
-----
>>> from tcmim.propagation.occ_ccd import OCCCDAnalyser, OCCCDConfig
>>> analyser = OCCCDAnalyser(OCCCDConfig())
>>> result = analyser.analyse(observation, all_observations)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np

from tcmim.schemas import PropagationObservation

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Output labels
# --------------------------------------------------------------------------

class OCCCDLabel(str):
    """String constants for OC-CCD evidence labels."""
    PROPAGATION_CANDIDATE  = "PROPAGATION_CANDIDATE"
    COMMON_CAUSE_CANDIDATE = "COMMON_CAUSE_CANDIDATE"
    AMBIGUOUS              = "AMBIGUOUS"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass
class OCCCDConfig:
    """Configuration for OC-CCD checks.

    Attributes
    ----------
    simultaneity_threshold_s   : T1 — |Δt| below this → simultaneity flag (s).
    bias_threshold_s           : T2 — |mean Δt| below this → onset bias flag (s).
    coincidence_pair_threshold : T3 — more than this many pairs flagging in the
                                 same window → multi-pair coincidence flag.
    coincidence_window_s       : T3 — time window for counting co-occurring pairs (s).
    detector_lag_s             : T4 — estimated CUSUM detection lag in seconds.
                                 Subtracted from both onset times for correction.
    min_observations_for_bias  : Minimum observations before T2 is applied.
    """
    simultaneity_threshold_s: float = 30.0
    bias_threshold_s: float = 15.0
    coincidence_pair_threshold: int = 2
    coincidence_window_s: float = 60.0
    detector_lag_s: float = 0.0
    min_observations_for_bias: int = 5


# --------------------------------------------------------------------------
# Per-observation result
# --------------------------------------------------------------------------

@dataclass
class OCCCDResult:
    """OC-CCD analysis result for one PropagationObservation.

    Attributes
    ----------
    obs_id             : ID of the PropagationObservation analysed.
    label              : Evidence label (PROPAGATION_CANDIDATE /
                         COMMON_CAUSE_CANDIDATE / AMBIGUOUS).
    corrected_delta_t_s: Δt after onset-lag correction (T4).
    checks             : Dict of check name → bool (True = flagged).
    reasons            : Human-readable explanation for each flag.
    note               : Overall evidence note (always includes the
                         FR-CC-2 disclaimer).
    """
    obs_id: str
    label: str
    corrected_delta_t_s: float
    checks: Dict[str, bool]    # True = flagged as common-cause indicator
    reasons: List[str]
    note: str

    # FR-CC-2 disclaimer is appended to every note
    _DISCLAIMER: str = (
        " [FR-CC-2: This label is EVIDENCE, not proof. "
        "Physical validation required for any propagation claim.]"
    )

    def __post_init__(self) -> None:
        if not self.note.endswith(self._DISCLAIMER):
            self.note += self._DISCLAIMER


# --------------------------------------------------------------------------
# Analyser
# --------------------------------------------------------------------------

class OCCCDAnalyser:
    """Apply OC-CCD checks to a PropagationObservation.

    Parameters
    ----------
    config : OCCCDConfig with all check thresholds.
    """

    def __init__(self, config: Optional[OCCCDConfig] = None) -> None:
        self.config = config or OCCCDConfig()

    def analyse(
        self,
        obs: PropagationObservation,
        all_observations: Optional[List[PropagationObservation]] = None,
    ) -> OCCCDResult:
        """Run all four OC-CCD checks on one observation.

        Parameters
        ----------
        obs              : The PropagationObservation to analyse.
        all_observations : All observations in the current batch (for T2, T3).
                           If None, T2 and T3 are skipped.

        Returns
        -------
        OCCCDResult with a label and evidence breakdown.
        """
        cfg = self.config
        checks: Dict[str, bool] = {}
        reasons: List[str] = []

        # T4 — Onset correction (applied first, before checks)
        corrected_dt = obs.delta_t_s - cfg.detector_lag_s
        if cfg.detector_lag_s != 0.0:
            reasons.append(
                f"T4_ONSET_CORRECTION: corrected Δt = "
                f"{corrected_dt:.2f}s (raw={obs.delta_t_s:.2f}s, "
                f"lag={cfg.detector_lag_s:.2f}s)"
            )

        # T1 — Simultaneity
        t1_flagged = abs(corrected_dt) < cfg.simultaneity_threshold_s
        checks["T1_SIMULTANEITY"] = t1_flagged
        if t1_flagged:
            reasons.append(
                f"T1_SIMULTANEITY: |corrected Δt|={abs(corrected_dt):.2f}s < "
                f"threshold={cfg.simultaneity_threshold_s}s — "
                "consistent with simultaneous response to shared disturbance."
            )

        # T2 — Onset bias (requires prior observations for same pair)
        t2_flagged = False
        if all_observations is not None:
            pair_obs = [
                o for o in all_observations
                if o.source_machine == obs.source_machine
                and o.target_machine == obs.target_machine
                and o.gate_result == "accepted"
            ]
            if len(pair_obs) >= cfg.min_observations_for_bias:
                mean_dt = float(np.mean([o.delta_t_s for o in pair_obs]))
                t2_flagged = abs(mean_dt) < cfg.bias_threshold_s
                checks["T2_ONSET_BIAS"] = t2_flagged
                if t2_flagged:
                    reasons.append(
                        f"T2_ONSET_BIAS: mean Δt={mean_dt:.2f}s for pair "
                        f"{obs.source_machine}→{obs.target_machine} is within "
                        f"bias threshold {cfg.bias_threshold_s}s — "
                        "may indicate simultaneous response to shared driver."
                    )
            else:
                checks["T2_ONSET_BIAS"] = False
        else:
            checks["T2_ONSET_BIAS"] = False

        # T3 — Multi-pair coincidence
        t3_flagged = False
        if all_observations is not None:
            # Count distinct pairs with accepted observations near the same time
            # (within coincidence_window_s of this observation's delta_t)
            coinciding_pairs = set()
            for o in all_observations:
                if (
                    o.obs_id != obs.obs_id
                    and o.gate_result == "accepted"
                    and abs(o.delta_t_s - obs.delta_t_s) < cfg.coincidence_window_s
                    and (o.source_machine, o.target_machine)
                    != (obs.source_machine, obs.target_machine)
                ):
                    coinciding_pairs.add((o.source_machine, o.target_machine))

            t3_flagged = len(coinciding_pairs) >= cfg.coincidence_pair_threshold
            checks["T3_MULTI_PAIR_COINCIDENCE"] = t3_flagged
            if t3_flagged:
                reasons.append(
                    f"T3_MULTI_PAIR_COINCIDENCE: {len(coinciding_pairs)} other "
                    "pairs show similar Δt — consistent with plant-wide disturbance."
                )
        else:
            checks["T3_MULTI_PAIR_COINCIDENCE"] = False

        # ---- Determine label ----
        n_flagged = sum(checks.values())
        if n_flagged == 0:
            label = OCCCDLabel.PROPAGATION_CANDIDATE
            note = (
                f"Passes all OC-CCD checks for pair "
                f"{obs.source_machine}→{obs.target_machine}. "
                "Consistent with propagation (not proof)."
            )
        elif t1_flagged or t3_flagged:
            # Strong common-cause indicators
            label = OCCCDLabel.COMMON_CAUSE_CANDIDATE
            note = (
                f"Flagged by {n_flagged} OC-CCD check(s). "
                "Consistent with shared disturbance (not proof of common cause)."
            )
        else:
            label = OCCCDLabel.AMBIGUOUS
            note = (
                f"Weak common-cause indicators ({n_flagged} check(s)). "
                "Evidence is inconclusive."
            )

        result = OCCCDResult(
            obs_id=obs.obs_id,
            label=label,
            corrected_delta_t_s=corrected_dt,
            checks=checks,
            reasons=reasons,
            note=note,
        )

        logger.debug(
            "OC-CCD %s→%s Δt=%.1fs: %s",
            obs.source_machine, obs.target_machine,
            obs.delta_t_s, label,
        )
        return result

    def analyse_all(
        self,
        observations: List[PropagationObservation],
    ) -> List[OCCCDResult]:
        """Apply OC-CCD to every observation in a list.

        Parameters
        ----------
        observations : All PropagationObservations (accepted ones analysed;
                       rejected ones receive AMBIGUOUS with a skip note).

        Returns
        -------
        List of OCCCDResult in the same order as observations.
        """
        results: List[OCCCDResult] = []
        for obs in observations:
            if obs.gate_result != "accepted":
                # Rejected obs — skip OC-CCD, return placeholder
                results.append(
                    OCCCDResult(
                        obs_id=obs.obs_id,
                        label=OCCCDLabel.AMBIGUOUS,
                        corrected_delta_t_s=obs.delta_t_s,
                        checks={},
                        reasons=["Skipped: observation was rejected by gating (S7)."],
                        note="OC-CCD not applied to rejected observations.",
                    )
                )
                continue
            results.append(self.analyse(obs, all_observations=observations))

        n_prop = sum(1 for r in results if r.label == OCCCDLabel.PROPAGATION_CANDIDATE)
        n_cc   = sum(1 for r in results if r.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE)
        n_amb  = sum(1 for r in results if r.label == OCCCDLabel.AMBIGUOUS)
        logger.info(
            "OC-CCD: %d PROPAGATION_CANDIDATE, %d COMMON_CAUSE_CANDIDATE, "
            "%d AMBIGUOUS (of %d total).",
            n_prop, n_cc, n_amb, len(results),
        )
        return results
