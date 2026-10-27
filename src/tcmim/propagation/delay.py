"""
TCMIM — Delay estimation (S6, FR-DL-1, FR-DL-2).

Provides two complementary delay estimates:

1. **Direct Δt** (FR-DL-1)
   ``Δt = t_target_onset − t_source_onset`` in seconds.
   Already computed by the matcher and stored in PropagationObservation.

2. **Cross-correlation lag** (FR-DL-1 — optional)
   Given two aligned time-series signals, finds the lag (in samples)
   that maximises the normalised cross-correlation.  Converts to seconds
   using the sampling rate.  This is an *additional* evidence signal
   — it does NOT override the onset-based Δt.

3. **Aggregated delay statistics** (FR-DL-2)
   Over a set of accepted PropagationObservations for one machine pair,
   computes: n, mean, std, min, max, direction_consistency.

INTEGRITY NOTE
--------------
Cross-correlation measures signal co-movement, NOT causality.
A high correlation lag is consistent with propagation but also
consistent with a shared disturbance (handled by OC-CCD in S8).

Usage
-----
>>> from tcmim.propagation.delay import aggregate_delay_stats
>>> stats = aggregate_delay_stats(accepted_observations,
...                               source_machine="A", target_machine="B")
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

from tcmim.schemas import DelayStatistics, PropagationObservation

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Cross-correlation lag (optional enrichment)
# --------------------------------------------------------------------------

def cross_correlation_lag(
    signal_a: np.ndarray,
    signal_b: np.ndarray,
    sampling_rate_hz: float = 1.0,
    max_lag_samples: Optional[int] = None,
) -> Tuple[float, float]:
    """Estimate the lag between two signals via normalised cross-correlation.

    Parameters
    ----------
    signal_a         : Reference (source) signal.
    signal_b         : Target signal.
    sampling_rate_hz : Sampling rate in Hz (used to convert lag → seconds).
    max_lag_samples  : If given, limit search to ±max_lag_samples.
                       None means full range.

    Returns
    -------
    (lag_seconds, peak_correlation)
        lag_seconds      : Positive means B lags A (B responds after A).
        peak_correlation : Normalised correlation at the peak [-1, 1].

    Notes
    -----
    - Signals are mean-centred before cross-correlation.
    - Returns (nan, nan) if either signal is constant or too short.
    - This estimate is ADVISORY — it supplements onset-based Δt.
    """
    a = np.asarray(signal_a, dtype=float)
    b = np.asarray(signal_b, dtype=float)

    if len(a) < 2 or len(b) < 2:
        logger.warning("cross_correlation_lag: signal(s) too short.")
        return float("nan"), float("nan")

    # Mean-centre
    a = a - np.mean(a)
    b = b - np.mean(b)

    norm_a = np.std(a)
    norm_b = np.std(b)
    if norm_a < 1e-12 or norm_b < 1e-12:
        logger.warning(
            "cross_correlation_lag: constant signal detected — cannot estimate lag."
        )
        return float("nan"), float("nan")

    a /= norm_a
    b /= norm_b

    # Full cross-correlation
    xcorr = np.correlate(b, a, mode="full")
    lags = np.arange(-(len(a) - 1), len(b))   # lag in samples

    # Restrict search range if requested
    if max_lag_samples is not None:
        mask = np.abs(lags) <= max_lag_samples
        xcorr = xcorr[mask]
        lags = lags[mask]

    peak_idx = int(np.argmax(xcorr))
    lag_samples = int(lags[peak_idx])
    peak_corr = float(xcorr[peak_idx]) / len(a)  # normalise by signal length

    lag_seconds = lag_samples / sampling_rate_hz

    logger.debug(
        "cross_correlation_lag: peak=%+.3f at lag=%d samples (%.2f s)",
        peak_corr, lag_samples, lag_seconds,
    )
    return lag_seconds, float(np.clip(peak_corr, -1.0, 1.0))


# --------------------------------------------------------------------------
# Delay statistics aggregation (FR-DL-2) with robust estimator support
# --------------------------------------------------------------------------

from enum import Enum
from dataclasses import dataclass


class DelayEstimatorType(str, Enum):
    """Supported delay aggregation strategies."""
    MEAN = "mean"
    MEDIAN = "median"
    TRIMMED_MEAN = "trimmed_mean"


@dataclass
class DelayEstimatorConfig:
    """Configuration for pairwise delay estimation.

    Attributes
    ----------
    estimator : str or DelayEstimatorType
        Delay estimator strategy:
        - 'mean': Standard arithmetic mean (baseline).
        - 'median': Sample median (robust against heavy-tailed spurious outliers).
        - 'trimmed_mean': Symmetric trimmed mean, discarding extreme delays.
        Default: 'mean'.
    trim_proportion : float
        Fraction of observations to cut from each tail for 'trimmed_mean'.
        Must satisfy 0.0 <= trim_proportion < 0.5. Default: 0.2.
    """
    estimator: str = "mean"
    trim_proportion: float = 0.2

    def __post_init__(self) -> None:
        if isinstance(self.estimator, DelayEstimatorType):
            self.estimator = self.estimator.value
        valid = {"mean", "median", "trimmed_mean"}
        if self.estimator not in valid:
            raise ValueError(
                f"Invalid estimator '{self.estimator}'. Must be one of {valid}."
            )
        if not isinstance(self.trim_proportion, (int, float)):
            raise TypeError("trim_proportion must be numeric.")
        if not (0.0 <= self.trim_proportion < 0.5):
            raise ValueError(
                f"trim_proportion must satisfy 0.0 <= trim_proportion < 0.5, got {self.trim_proportion}."
            )


def compute_trimmed_mean(arr: np.ndarray, proportion: float) -> float:
    """Compute symmetric trimmed mean over a 1D array of finite floats.

    Parameters
    ----------
    arr : 1D numpy array of finite numbers.
    proportion : Fraction to trim from each tail, in [0.0, 0.5).

    Returns
    -------
    float: Mean of elements after trimming floor(N * proportion) items from each end.
    """
    n = len(arr)
    if n == 0:
        return float("nan")
    sorted_arr = np.sort(arr)
    k = int(np.floor(n * proportion))
    if 2 * k >= n:
        k = max(0, (n - 1) // 2)
    trimmed_slice = sorted_arr[k : n - k] if k > 0 else sorted_arr
    return float(np.mean(trimmed_slice))


class DelayEstimator:
    """Computes aggregated delay statistics and central tendency estimates."""

    def __init__(self, config: Optional[DelayEstimatorConfig] = None) -> None:
        self.config = config or DelayEstimatorConfig()

    def estimate_pair(
        self,
        observations: List[PropagationObservation],
        source_machine: str,
        target_machine: str,
    ) -> Optional[DelayStatistics]:
        """Compute aggregated delay statistics for a single directed machine pair."""
        accepted = [
            obs for obs in observations
            if obs.gate_result == "accepted"
            and obs.source_machine == source_machine
            and obs.target_machine == target_machine
        ]

        if not accepted:
            logger.debug(
                "DelayEstimator: no accepted observations for %s->%s.",
                source_machine, target_machine,
            )
            return None

        raw_deltas = np.array([obs.delta_t_s for obs in accepted], dtype=float)
        finite_mask = np.isfinite(raw_deltas)
        deltas = raw_deltas[finite_mask]

        if len(deltas) == 0:
            logger.warning(
                "DelayEstimator: no finite observations for %s->%s.",
                source_machine, target_machine,
            )
            return None

        n = len(deltas)
        mean_s = float(np.mean(deltas))
        std_s = float(np.std(deltas, ddof=1)) if n > 1 else 0.0
        min_s = float(np.min(deltas))
        max_s = float(np.max(deltas))
        median_s = float(np.median(deltas))
        trimmed_mean_s = compute_trimmed_mean(deltas, self.config.trim_proportion)

        if self.config.estimator == "mean":
            chosen_delay = mean_s
        elif self.config.estimator == "median":
            chosen_delay = median_s
        elif self.config.estimator == "trimmed_mean":
            chosen_delay = trimmed_mean_s
        else:
            chosen_delay = mean_s

        direction_consistency = float(np.mean(deltas > 0))
        provenance = accepted[0].provenance

        stats = DelayStatistics(
            source_machine=source_machine,
            target_machine=target_machine,
            n=n,
            mean_s=mean_s,
            std_s=std_s,
            min_s=min_s,
            max_s=max_s,
            direction_consistency=direction_consistency,
            provenance=provenance,
            median_s=median_s,
            trimmed_mean_s=trimmed_mean_s,
            estimator=self.config.estimator,
            estimated_delay_s=chosen_delay,
            trim_proportion=self.config.trim_proportion,
        )

        logger.info(
            "DelayStats %s->%s: n=%d, estimator=%s, est_delay=%.2fs (mean=%.1fs, med=%.1fs, trim=%.1fs), dir_consistency=%.2f",
            source_machine, target_machine,
            n, self.config.estimator, chosen_delay, mean_s, median_s, trimmed_mean_s, direction_consistency,
        )
        return stats

    def estimate_all_pairs(
        self,
        observations: List[PropagationObservation],
    ) -> List[DelayStatistics]:
        """Aggregate delay statistics for all unique machine pairs in observations."""
        pairs = set(
            (obs.source_machine, obs.target_machine)
            for obs in observations
            if obs.gate_result == "accepted"
        )

        stats_list: List[DelayStatistics] = []
        for src, tgt in sorted(pairs):
            stats = self.estimate_pair(observations, src, tgt)
            if stats is not None:
                stats_list.append(stats)

        return stats_list


def aggregate_delay_stats(
    observations: List[PropagationObservation],
    source_machine: str,
    target_machine: str,
    config: Optional[DelayEstimatorConfig] = None,
) -> Optional[DelayStatistics]:
    """Compute aggregated delay statistics from accepted observations."""
    estimator = DelayEstimator(config)
    return estimator.estimate_pair(observations, source_machine, target_machine)


def aggregate_all_pairs(
    observations: List[PropagationObservation],
    config: Optional[DelayEstimatorConfig] = None,
) -> List[DelayStatistics]:
    """Aggregate delay statistics for all unique machine pairs in observations."""
    estimator = DelayEstimator(config)
    return estimator.estimate_all_pairs(observations)
