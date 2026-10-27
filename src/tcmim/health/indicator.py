"""
TCMIM — Health indicator computation (S3, FR-LH-2).

Converts z-scores (from MachineBaseline) into a normalised health
score in [0.0, 1.0] where 1.0 means perfectly normal.

Health score mapping (to be formally locked at M3 design review)
----------------------------------------------------------------
The mapping chosen here is sigmoid-based on the mean absolute z-score:

    mean_abs_z = mean(|z_i|) over all non-NaN, non-constant features

    health_score = 1 / (1 + mean_abs_z)

Properties:
  - Monotonically decreasing as deviation from baseline grows.
  - health_score = 1.0 when all z_i = 0 (exactly on baseline mean).
  - Approaches 0.0 as z-scores grow without bound.
  - Always in [0, 1] by construction.
  - Does not require a hard threshold — scores are continuous.

This mapping is documented here and in the PRD Section 5.3 per the
requirement that it be "fixed and documented at M3".

Usage
-----
>>> from tcmim.health.indicator import HealthIndicator
>>> indicator = HealthIndicator(baseline)
>>> health_sample = indicator.compute(feature_sample)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np

from tcmim.health.baseline import MachineBaseline
from tcmim.schemas import HealthSample, MultimodalFeatureSample, Provenance

logger = logging.getLogger(__name__)


class HealthIndicator:
    """Compute normalised health scores from features + baseline.

    Parameters
    ----------
    baseline : A fitted MachineBaseline for the target machine.
    """

    def __init__(self, baseline: MachineBaseline) -> None:
        self.baseline = baseline

    def compute(
        self,
        sample: MultimodalFeatureSample,
    ) -> HealthSample:
        """Compute health score for one window.

        Parameters
        ----------
        sample : MultimodalFeatureSample for the window to evaluate.

        Returns
        -------
        HealthSample with health_score in [0, 1] and per-feature z-scores.

        Notes
        -----
        If *all* features in the sample have no baseline match or are
        constant, the health score defaults to 1.0 (no evidence of
        abnormality) and a warning is logged.
        """
        # Flatten all modality features into a single dict
        flat_features = _flatten(sample.features)

        # Compute z-scores via the baseline
        z_scores = self.baseline.z_scores(flat_features)

        # Health score from mean absolute z-score
        health_score = _health_from_z_scores(z_scores)

        return HealthSample(
            machine_id=sample.machine_id,
            window_start=sample.window_start,
            window_end=sample.window_end,
            health_score=health_score,
            z_scores=z_scores,
            provenance=sample.provenance,
            baseline_id=self.baseline.baseline_id,
        )

    def compute_all(
        self,
        samples: List[MultimodalFeatureSample],
    ) -> List[HealthSample]:
        """Compute health scores for a list of feature samples.

        Parameters
        ----------
        samples : List of MultimodalFeatureSamples (one per window).

        Returns
        -------
        List of HealthSamples in the same order.
        """
        results: List[HealthSample] = []
        for s in samples:
            try:
                results.append(self.compute(s))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Health computation failed for window %s: %s",
                    s.window_start, exc,
                )
        logger.info(
            "HealthIndicator: %d/%d windows computed.",
            len(results), len(samples),
        )
        return results


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _flatten(
    features_by_modality: Dict[str, Dict[str, float]],
) -> Dict[str, float]:
    """Flatten {modality: {feat: val}} → {feat: val}."""
    flat: Dict[str, float] = {}
    for mod_feats in features_by_modality.values():
        flat.update(mod_feats)
    return flat


def _health_from_z_scores(z_scores: Dict[str, float]) -> float:
    """Map z-scores to a health score in [0, 1].

    Formula (documented above):
        mean_abs_z = mean(|z_i|)  for non-NaN z-scores
        health     = 1 / (1 + mean_abs_z)

    Returns 1.0 (healthy) if no valid z-scores are available.
    """
    valid_z = [abs(z) for z in z_scores.values() if not np.isnan(z)]
    if not valid_z:
        logger.warning(
            "No valid z-scores available — defaulting health_score to 1.0."
        )
        return 1.0
    mean_abs_z = float(np.mean(valid_z))
    return float(1.0 / (1.0 + mean_abs_z))
