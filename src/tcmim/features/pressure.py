"""
TCMIM — Pressure and current feature extraction (S2, FR-FE-2).

Statistical and temporal features for pressure and current channels.
These are scalar-valued time-series (not oscillatory), so features
focus on distributional shape and trend rather than spectral content.

Features computed
-----------------
Statistical:
  mean, std, min, max, range, median,
  kurtosis (excess), skewness, iqr (interquartile range),
  percentile_25, percentile_75, percentile_95

Temporal:
  slope      — linear trend over the window (units per second)
  rms        — root mean square (matches FR-FE-2 cross-reference with FR-FE-1)
  zero_crossings — count of sign changes (useful for pressure oscillations)

Requirements coverage: FR-FE-2
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np
from scipy.stats import kurtosis as scipy_kurtosis, skew as scipy_skew

logger = logging.getLogger(__name__)

_EPS = 1e-12


def compute_pressure_features(
    signal: np.ndarray,
    sampling_rate_hz: float = 1.0,
) -> Dict[str, float]:
    """Compute pressure/current features from a 1-D signal array.

    Parameters
    ----------
    signal           : 1-D numpy array of raw values.
    sampling_rate_hz : Sampling frequency in Hz (used for slope computation).

    Returns
    -------
    Dict mapping feature name → float value.
    """
    return _compute_scalar_features(signal, sampling_rate_hz)


# Alias for current channels — same feature set (FR-FE-2)
compute_current_features = compute_pressure_features


def _compute_scalar_features(
    signal: np.ndarray,
    sampling_rate_hz: float,
) -> Dict[str, float]:
    if len(signal) < 2:
        logger.warning(
            "Scalar feature extraction: signal too short (%d samples).",
            len(signal),
        )
        return _nan_features()

    signal = np.asarray(signal, dtype=float)

    mean_val   = float(np.mean(signal))
    std_val    = float(np.std(signal, ddof=1))
    min_val    = float(np.min(signal))
    max_val    = float(np.max(signal))
    range_val  = max_val - min_val
    median_val = float(np.median(signal))
    kurt_val   = float(scipy_kurtosis(signal, fisher=True, bias=False))
    skew_val   = float(scipy_skew(signal, bias=False))
    iqr_val    = float(np.percentile(signal, 75) - np.percentile(signal, 25))
    p25_val    = float(np.percentile(signal, 25))
    p75_val    = float(np.percentile(signal, 75))
    p95_val    = float(np.percentile(signal, 95))
    rms_val    = float(np.sqrt(np.mean(signal ** 2)))

    # Linear slope over the window
    n = len(signal)
    t = np.arange(n) / (sampling_rate_hz + _EPS)
    coeffs = np.polyfit(t, signal, 1)
    slope_val = float(coeffs[0])  # units per second

    # Zero crossings of the mean-centred signal
    centred = signal - mean_val
    zero_crossings = int(((centred[:-1] * centred[1:]) < 0).sum())

    return {
        "mean":            mean_val,
        "std":             std_val,
        "min":             min_val,
        "max":             max_val,
        "range":           range_val,
        "median":          median_val,
        "kurtosis":        kurt_val,
        "skewness":        skew_val,
        "iqr":             iqr_val,
        "percentile_25":   p25_val,
        "percentile_75":   p75_val,
        "percentile_95":   p95_val,
        "rms":             rms_val,
        "slope":           slope_val,
        "zero_crossings":  float(zero_crossings),
    }


def _nan_features() -> Dict[str, float]:
    """Return NaN for all features (degenerate input guard)."""
    keys = [
        "mean", "std", "min", "max", "range", "median",
        "kurtosis", "skewness", "iqr", "percentile_25",
        "percentile_75", "percentile_95", "rms", "slope", "zero_crossings",
    ]
    return {k: float("nan") for k in keys}
