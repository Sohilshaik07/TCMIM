"""
TCMIM — Temperature feature extraction (S2, FR-FE-3).

Temperature signals change slowly; features emphasise trend and spread.

Features computed
-----------------
  mean, std, min, max, slope (°C/s), range

Requirements coverage: FR-FE-3 (P1)
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)
_EPS = 1e-12


def compute_temperature_features(
    signal: np.ndarray,
    sampling_rate_hz: float = 1.0,
) -> Dict[str, float]:
    """Compute temperature features.

    Parameters
    ----------
    signal           : 1-D numpy array of temperature values.
    sampling_rate_hz : Sampling frequency in Hz.

    Returns
    -------
    Dict of feature name → float.
    """
    if len(signal) < 2:
        logger.warning(
            "Temperature feature extraction: signal too short (%d).", len(signal)
        )
        return {k: float("nan") for k in ("mean", "std", "min", "max", "slope", "range")}

    signal = np.asarray(signal, dtype=float)
    n = len(signal)
    t = np.arange(n) / (sampling_rate_hz + _EPS)
    coeffs = np.polyfit(t, signal, 1)

    return {
        "mean":  float(np.mean(signal)),
        "std":   float(np.std(signal, ddof=1)),
        "min":   float(np.min(signal)),
        "max":   float(np.max(signal)),
        "slope": float(coeffs[0]),
        "range": float(np.max(signal) - np.min(signal)),
    }
