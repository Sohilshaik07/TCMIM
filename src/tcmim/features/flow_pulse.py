"""
TCMIM — Flow-pulse feature extraction (S2, FR-FE-4).

The MetroPT-3 `Caudal_impulses` column is a raw digital pulse count.
NO physical multiplier or calibration factor is applied here because
no flow-calibration data exists for this sensor (FR-FE-4 / integrity
rule 6: "Never invent physical flow calibration factors").

Features computed
-----------------
  pulse_count  : Total number of pulses (sum of raw values) in the window.
  pulse_rate   : Pulses per second (= pulse_count / window_duration_s).
  active_ratio : Fraction of samples where the pulse signal is > 0.

Requirements coverage: FR-FE-4 (P1)
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np

logger = logging.getLogger(__name__)


def compute_flow_pulse_features(
    signal: np.ndarray,
    window_duration_s: float,
) -> Dict[str, float]:
    """Compute flow-pulse features.

    Parameters
    ----------
    signal            : 1-D array of raw pulse count values (0 or 1 or integer).
    window_duration_s : Duration of the window in seconds.

    Returns
    -------
    Dict of feature name → float.

    Notes
    -----
    pulse_rate is computed as pulse_count / window_duration_s.  No
    physical conversion to volumetric flow is applied.
    """
    if len(signal) < 1:
        return {k: float("nan") for k in ("pulse_count", "pulse_rate", "active_ratio")}

    signal = np.asarray(signal, dtype=float)
    pulse_count = float(np.sum(signal))
    active_ratio = float(np.mean(signal > 0))
    pulse_rate = pulse_count / max(window_duration_s, 1e-12)

    return {
        "pulse_count":  pulse_count,
        "pulse_rate":   pulse_rate,
        "active_ratio": active_ratio,
    }
