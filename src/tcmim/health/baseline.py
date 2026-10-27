"""
TCMIM — Baseline builder (S3, FR-LH-1).

A ``MachineBaseline`` is built from a set of "normal" windows
(MultimodalFeatureSamples).  It stores per-feature mean and standard
deviation and is used downstream by the health indicator.

Design decisions (to be locked at M3 design review — Open Decision 2)
----------------------------------------------------------------------
- Baseline windows are the FIRST ``baseline_frac`` fraction of the data
  (chronological order) to avoid look-ahead bias.
- Features with std == 0 (constant channels) are excluded from z-score
  computation to prevent division-by-zero.
- The baseline is frozen (immutable after fitting) to enforce that no
  future data can contaminate it.

Usage
-----
>>> from tcmim.health.baseline import MachineBaseline
>>> baseline = MachineBaseline.fit(feature_samples, baseline_frac=0.2)
>>> baseline.summary()
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from tcmim.schemas import MultimodalFeatureSample, Provenance

logger = logging.getLogger(__name__)

# Minimum number of windows required to build a meaningful baseline
MIN_BASELINE_WINDOWS = 10


@dataclass
class FeatureStats:
    """Mean and std for a single feature, computed over baseline windows.

    Attributes
    ----------
    feature_name : Fully-qualified feature name (e.g. 'TP2__mean').
    mean         : Mean value over baseline windows.
    std          : Standard deviation (ddof=1) over baseline windows.
    n            : Number of baseline windows with a valid value.
    constant     : True if std == 0 (excluded from z-score computation).
    """
    feature_name: str
    mean: float
    std: float
    n: int
    constant: bool = False


@dataclass
class MachineBaseline:
    """Frozen per-machine baseline built from normal windows.

    Attributes
    ----------
    machine_id     : Machine this baseline belongs to.
    baseline_id    : Auto-generated UUID.
    feature_stats  : Dict mapping feature name → FeatureStats.
    n_windows      : Number of windows used to build the baseline.
    window_start   : Earliest window start in the baseline set.
    window_end     : Latest window end in the baseline set.
    provenance     : Provenance class (inherited from input samples).
    fitted         : True once fit() has completed.
    """
    machine_id: str
    baseline_id: str
    feature_stats: Dict[str, FeatureStats]
    n_windows: int
    window_start: datetime
    window_end: datetime
    provenance: Provenance
    fitted: bool = True

    # ------------------------------------------------------------------ #
    # Factory                                                             #
    # ------------------------------------------------------------------ #

    @classmethod
    def fit(
        cls,
        samples: List[MultimodalFeatureSample],
        *,
        baseline_frac: float = 0.2,
        machine_id: Optional[str] = None,
    ) -> "MachineBaseline":
        """Fit a baseline from the first *baseline_frac* of *samples*.

        Parameters
        ----------
        samples       : List of MultimodalFeatureSamples, all from the
                        same machine, in chronological order.
        baseline_frac : Fraction of samples to use as the normal baseline.
                        Must be in (0, 1).
        machine_id    : Override the machine ID (default: inferred from
                        the first sample).

        Returns
        -------
        MachineBaseline (frozen).

        Raises
        ------
        ValueError  : If samples is empty or baseline has < MIN_BASELINE_WINDOWS.
        """
        if not samples:
            raise ValueError("Cannot fit baseline: no samples provided.")

        n_baseline = max(1, int(len(samples) * baseline_frac))
        baseline_samples = samples[:n_baseline]

        if len(baseline_samples) < MIN_BASELINE_WINDOWS:
            logger.warning(
                "Baseline has only %d windows (minimum recommended: %d). "
                "Consider providing more data or reducing baseline_frac.",
                len(baseline_samples),
                MIN_BASELINE_WINDOWS,
            )

        mid = machine_id or samples[0].machine_id
        provenance = samples[0].provenance

        # ---- Collect values per feature across all baseline windows -----
        feature_values: Dict[str, List[float]] = {}
        for s in baseline_samples:
            for mod_feats in s.features.values():
                for feat_name, val in mod_feats.items():
                    if not np.isnan(val):
                        feature_values.setdefault(feat_name, []).append(val)

        # ---- Compute stats per feature -----------------------------------
        feature_stats: Dict[str, FeatureStats] = {}
        n_excluded = 0
        for feat_name, vals in feature_values.items():
            arr = np.array(vals, dtype=float)
            mean = float(np.mean(arr))
            std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
            constant = std < 1e-10
            if constant:
                n_excluded += 1
                logger.debug(
                    "Feature '%s' has std≈0 — excluded from z-score computation.",
                    feat_name,
                )
            feature_stats[feat_name] = FeatureStats(
                feature_name=feat_name,
                mean=mean,
                std=std,
                n=len(arr),
                constant=constant,
            )

        window_starts = [s.window_start for s in baseline_samples]
        window_ends = [s.window_end for s in baseline_samples]

        baseline = cls(
            machine_id=mid,
            baseline_id=str(uuid.uuid4()),
            feature_stats=feature_stats,
            n_windows=len(baseline_samples),
            window_start=min(window_starts),
            window_end=max(window_ends),
            provenance=provenance,
        )

        logger.info(
            "Baseline fitted for '%s': %d windows, %d features "
            "(%d constant/excluded).",
            mid, len(baseline_samples), len(feature_stats), n_excluded,
        )
        return baseline

    # ------------------------------------------------------------------ #
    # Utilities                                                           #
    # ------------------------------------------------------------------ #

    def z_scores(
        self,
        features: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute z-scores for a feature dict against this baseline.

        Parameters
        ----------
        features : Flat dict of feature_name → value (as in FeatureSample
                   or one modality of MultimodalFeatureSample).

        Returns
        -------
        Dict of feature_name → z-score.  Features not in the baseline or
        with constant std are returned as NaN.
        """
        result: Dict[str, float] = {}
        for feat_name, val in features.items():
            stats = self.feature_stats.get(feat_name)
            if stats is None or stats.constant or np.isnan(val):
                result[feat_name] = float("nan")
            else:
                result[feat_name] = (val - stats.mean) / stats.std
        return result

    def summary(self) -> str:
        """Return a human-readable summary of the baseline."""
        valid = sum(1 for s in self.feature_stats.values() if not s.constant)
        excluded = sum(1 for s in self.feature_stats.values() if s.constant)
        return (
            f"MachineBaseline(machine='{self.machine_id}', "
            f"windows={self.n_windows}, "
            f"features={len(self.feature_stats)} "
            f"[{valid} active, {excluded} constant/excluded], "
            f"period={self.window_start} → {self.window_end})"
        )
