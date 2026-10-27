"""
TCMIM — Vibration feature extraction (S2, FR-FE-1).

Computes time-domain and frequency-domain features from a 1-D vibration
signal (numpy array).  All functions operate on raw floating-point values
and return a plain dict so they can be composed into FeatureSample objects
by the high-level extractor.

Features implemented
--------------------
Time-domain:
  rms            — Root mean square: sqrt(mean(x²))
  std            — Standard deviation
  kurtosis       — Excess kurtosis (Fisher definition, 0 for Gaussian)
  skewness       — Third standardised moment
  crest_factor   — peak / rms  (measures impulsiveness)
  shape_factor   — rms / mean(|x|)  (dimensionless waveform shape)
  peak           — max(|x|)
  peak_to_peak   — max(x) − min(x)

Frequency-domain (via FFT):
  spectral_centroid — centre of mass of the magnitude spectrum (Hz)
  spectral_energy   — total energy in the magnitude spectrum
  dominant_freq     — frequency bin with maximum magnitude (Hz)

Requirements coverage: FR-FE-1
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np
from scipy.stats import kurtosis as scipy_kurtosis, skew as scipy_skew

logger = logging.getLogger(__name__)

# Small epsilon to prevent division by zero in shape factor / crest factor
_EPS = 1e-12


def compute_vibration_features(
    signal: np.ndarray,
    sampling_rate_hz: float = 1.0,
) -> Dict[str, float]:
    """Compute all vibration features from a 1-D signal array.

    Parameters
    ----------
    signal          : 1-D numpy array of raw vibration values.
    sampling_rate_hz: Sampling frequency in Hz (required for spectral
                      features).  Defaults to 1 Hz (normalised frequency)
                      if not known.

    Returns
    -------
    Dict mapping feature name to float value.
    All values are finite; NaN is returned for degenerate inputs.
    """
    if len(signal) < 2:
        logger.warning(
            "Vibration feature extraction: signal too short (%d samples).",
            len(signal)
        )
        return _nan_features()

    signal = np.asarray(signal, dtype=float)

    # ---- Time-domain features -------------------------------------------
    rms = float(np.sqrt(np.mean(signal ** 2)))
    std = float(np.std(signal, ddof=1))
    kurt = float(scipy_kurtosis(signal, fisher=True, bias=False))
    skew = float(scipy_skew(signal, bias=False))
    peak = float(np.max(np.abs(signal)))
    peak_to_peak = float(np.max(signal) - np.min(signal))
    mean_abs = float(np.mean(np.abs(signal)))
    crest_factor = peak / (rms + _EPS)
    shape_factor = rms / (mean_abs + _EPS)

    # ---- Frequency-domain features (one-sided FFT) ----------------------
    n = len(signal)
    fft_mag = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(n, d=1.0 / sampling_rate_hz)

    spectral_energy = float(np.sum(fft_mag ** 2))
    total_mag = float(np.sum(fft_mag)) + _EPS
    spectral_centroid = float(np.sum(freqs * fft_mag) / total_mag)
    dominant_freq = float(freqs[np.argmax(fft_mag)])

    return {
        "rms":               rms,
        "std":               std,
        "kurtosis":          kurt,
        "skewness":          skew,
        "peak":              peak,
        "peak_to_peak":      peak_to_peak,
        "crest_factor":      crest_factor,
        "shape_factor":      shape_factor,
        "spectral_centroid": spectral_centroid,
        "spectral_energy":   spectral_energy,
        "dominant_freq":     dominant_freq,
    }


def _nan_features() -> Dict[str, float]:
    """Return NaN for all features (degenerate input guard)."""
    return {
        "rms":               float("nan"),
        "std":               float("nan"),
        "kurtosis":          float("nan"),
        "skewness":          float("nan"),
        "peak":              float("nan"),
        "peak_to_peak":      float("nan"),
        "crest_factor":      float("nan"),
        "shape_factor":      float("nan"),
        "spectral_centroid": float("nan"),
        "spectral_energy":   float("nan"),
        "dominant_freq":     float("nan"),
    }
