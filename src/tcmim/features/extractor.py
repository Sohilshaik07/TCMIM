"""
TCMIM — High-level feature extractor (S2).

Dispatches feature computation to the per-modality modules based on
the Modality of each channel in a WindowedData object.
Returns a FeatureSample (single channel) or a MultimodalFeatureSample
(all channels for one window).

Usage
-----
>>> from tcmim.features.extractor import FeatureExtractor
>>> from tcmim.data.windower import WindowedData
>>> extractor = FeatureExtractor(sampling_rate_hz=0.1)  # ~10-s intervals
>>> feature_samples = extractor.extract_all(windowed_data_list)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

from tcmim.data.metropt3 import METROPT3_MODALITY_MAP
from tcmim.data.windower import WindowedData
from tcmim.features.digital import compute_digital_features
from tcmim.features.flow_pulse import compute_flow_pulse_features
from tcmim.features.pressure import compute_pressure_features, compute_current_features
from tcmim.features.temperature import compute_temperature_features
from tcmim.features.vibration import compute_vibration_features
from tcmim.schemas import (
    FeatureSample,
    Modality,
    MultimodalFeatureSample,
)

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Dispatch feature extraction by modality.

    Parameters
    ----------
    sampling_rate_hz : Sampling rate of the input signal in Hz.  Used for
                       spectral and slope features.

                       Default: 0.1 Hz — the nominal rate of the MetroPT-3
                       dataset (~10-second intervals).  Callers using other
                       datasets or hardware streams MUST supply the correct
                       value; the default is intentionally set to the most
                       common TCMIM use-case, not to 1 Hz.

                       Examples:
                         - MetroPT-3 CSV          → 0.1 Hz  (10-s intervals)
                         - 1 kHz vibration sensor  → 1000 Hz
                         - 100 Hz IMU              → 100 Hz

    channel_modality_map : Optional mapping from channel name → Modality.
                           Defaults to the MetroPT-3 map.
    channel_state_map    : Optional mapping from channel name → {raw_state: binary_active_flag}.
                           Used for tag-aware actuator normalization (e.g. SWaT pumps/valves).
    """

    def __init__(
        self,
        sampling_rate_hz: float = 0.1,
        channel_modality_map: Optional[Dict[str, Modality]] = None,
        channel_state_map: Optional[Dict[str, Dict[Union[int, float], int]]] = None,
    ) -> None:
        self.sampling_rate_hz = sampling_rate_hz
        self.channel_modality_map: Dict[str, Modality] = (
            channel_modality_map if channel_modality_map is not None
            else METROPT3_MODALITY_MAP
        )
        self.channel_state_map: Dict[str, Dict[Union[int, float], int]] = (
            channel_state_map if channel_state_map is not None else {}
        )

    def extract_window(
        self,
        window: WindowedData,
    ) -> MultimodalFeatureSample:
        """Extract features for every channel in a single WindowedData.

        Parameters
        ----------
        window : A WindowedData object (S1 output).

        Returns
        -------
        MultimodalFeatureSample with features grouped by modality name.
        """
        features_by_modality: Dict[str, Dict[str, float]] = {}
        window_duration_s = (
            window.window_end - window.window_start
        ).total_seconds()

        for col in window.data.columns:
            modality = self.channel_modality_map.get(col, Modality.UNKNOWN)
            state_mapping = self.channel_state_map.get(col)
            signal = window.data[col].dropna().to_numpy()

            if len(signal) == 0:
                logger.debug("Empty signal for channel '%s' — skipping.", col)
                continue

            col_features = self._compute(
                signal, modality, window_duration_s, state_mapping=state_mapping
            )

            # Prefix each feature name with channel name to avoid clashes
            prefixed = {f"{col}__{k}": v for k, v in col_features.items()}

            mod_key = modality.value
            if mod_key not in features_by_modality:
                features_by_modality[mod_key] = {}
            features_by_modality[mod_key].update(prefixed)

        return MultimodalFeatureSample(
            machine_id=window.machine_id,
            window_start=window.window_start,
            window_end=window.window_end,
            features=features_by_modality,
            provenance=window.provenance,
        )

    def extract_all(
        self,
        windows: List[WindowedData],
    ) -> List[MultimodalFeatureSample]:
        """Extract features for a list of windows.

        Parameters
        ----------
        windows : List of WindowedData objects.

        Returns
        -------
        List of MultimodalFeatureSample in the same order as windows.
        """
        result: List[MultimodalFeatureSample] = []
        for w in windows:
            try:
                fs = self.extract_window(w)
                result.append(fs)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "Feature extraction failed for window %d: %s",
                    w.window_index, exc
                )
        logger.info(
            "FeatureExtractor: %d/%d windows extracted successfully.",
            len(result), len(windows)
        )
        return result

    def _compute(
        self,
        signal: np.ndarray,
        modality: Modality,
        window_duration_s: float,
        state_mapping: Optional[Dict[Union[int, float], int]] = None,
    ) -> Dict[str, float]:
        """Route signal to the correct feature function by modality."""
        if modality == Modality.VIBRATION:
            return compute_vibration_features(signal, self.sampling_rate_hz)
        elif modality == Modality.PRESSURE:
            return compute_pressure_features(signal, self.sampling_rate_hz)
        elif modality == Modality.CURRENT:
            return compute_current_features(signal, self.sampling_rate_hz)
        elif modality == Modality.TEMPERATURE:
            return compute_temperature_features(signal, self.sampling_rate_hz)
        elif modality == Modality.FLOW_PULSE:
            return compute_flow_pulse_features(signal, window_duration_s)
        elif modality == Modality.DIGITAL_STATE:
            return compute_digital_features(signal, state_mapping=state_mapping)
        else:
            # Unknown modality — return basic stats as a fallback.
            # std uses ddof=1 (sample std). When the signal contains only one
            # valid observation, ddof=1 is undefined (zero degrees of freedom)
            # and np.std returns NaN. A single-observation window has no
            # measurable spread by definition; we document this as 0.0 rather
            # than propagating NaN into the feature matrix.
            logger.debug("Unknown modality for signal — using basic stats.")
            n_valid = len(signal)
            std_val = float(np.std(signal, ddof=1)) if n_valid >= 2 else 0.0
            return {
                "mean": float(np.mean(signal)),
                "std":  std_val,
            }
