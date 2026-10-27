"""
TCMIM — Unit tests for feature extractors (M2, FR-FE-1..5).

All tests use SYNTHETIC fixtures (programmatically generated signals).
These results are never presented as real experimental data.
"""

import numpy as np
import pytest

from tcmim.features.vibration import compute_vibration_features
from tcmim.features.pressure import compute_pressure_features
from tcmim.features.temperature import compute_temperature_features
from tcmim.features.flow_pulse import compute_flow_pulse_features
from tcmim.features.digital import compute_digital_features


# ============================================================
# FR-FE-1 — Vibration features
# ============================================================

class TestVibrationFeatures:
    def setup_method(self):
        np.random.seed(42)
        self.sine = np.sin(2 * np.pi * 10 * np.linspace(0, 1, 1000))
        self.noise = np.random.normal(0, 1, 500)
        self.impulse = np.zeros(100)
        self.impulse[50] = 10.0   # single spike → high crest factor

    def test_rms_of_sine(self):
        feats = compute_vibration_features(self.sine, sampling_rate_hz=1000.0)
        # RMS of sin(x) = 1/sqrt(2) ≈ 0.707
        assert feats["rms"] == pytest.approx(1.0 / np.sqrt(2), rel=0.01)

    def test_all_keys_present(self):
        feats = compute_vibration_features(self.noise, sampling_rate_hz=1.0)
        expected_keys = {
            "rms", "std", "kurtosis", "skewness", "peak", "peak_to_peak",
            "crest_factor", "shape_factor", "spectral_centroid",
            "spectral_energy", "dominant_freq",
        }
        assert set(feats.keys()) == expected_keys

    def test_crest_factor_high_for_impulse(self):
        feats = compute_vibration_features(self.impulse, sampling_rate_hz=1.0)
        # Impulsive signal should have crest factor >> 1
        assert feats["crest_factor"] > 5.0

    def test_kurtosis_gaussian_approx_zero(self):
        """Large Gaussian sample → excess kurtosis ≈ 0."""
        np.random.seed(0)
        signal = np.random.normal(0, 1, 5000)
        feats = compute_vibration_features(signal, sampling_rate_hz=1.0)
        assert abs(feats["kurtosis"]) < 0.5

    def test_short_signal_returns_nan(self):
        feats = compute_vibration_features(np.array([1.0]), sampling_rate_hz=1.0)
        assert np.isnan(feats["rms"])

    def test_spectral_energy_positive(self):
        feats = compute_vibration_features(self.noise, sampling_rate_hz=1.0)
        assert feats["spectral_energy"] > 0

    def test_dominant_freq_sine(self):
        """Dominant frequency of a 10 Hz sine should be ~10 Hz."""
        feats = compute_vibration_features(self.sine, sampling_rate_hz=1000.0)
        assert feats["dominant_freq"] == pytest.approx(10.0, abs=2.0)

    def test_std_constant_signal_zero(self):
        """Constant signal should have std ≈ 0."""
        signal = np.ones(100) * 3.0
        feats = compute_vibration_features(signal, sampling_rate_hz=1.0)
        assert feats["std"] == pytest.approx(0.0, abs=1e-10)

    def test_peak_to_peak(self):
        signal = np.array([0.0, -2.0, 3.0, 1.0])
        feats = compute_vibration_features(signal, sampling_rate_hz=1.0)
        assert feats["peak_to_peak"] == pytest.approx(5.0)


# ============================================================
# FR-FE-2 — Pressure / current features
# ============================================================

class TestPressureFeatures:
    def setup_method(self):
        np.random.seed(1)
        self.ramp = np.linspace(1.0, 5.0, 200)       # steady ramp
        self.flat = np.ones(100) * 3.5                 # constant pressure
        self.noisy = np.random.normal(5.0, 0.5, 300)

    def test_all_keys_present(self):
        feats = compute_pressure_features(self.noisy, sampling_rate_hz=0.1)
        expected = {
            "mean", "std", "min", "max", "range", "median", "kurtosis",
            "skewness", "iqr", "percentile_25", "percentile_75",
            "percentile_95", "rms", "slope", "zero_crossings",
        }
        assert set(feats.keys()) == expected

    def test_mean_of_ramp(self):
        feats = compute_pressure_features(self.ramp)
        assert feats["mean"] == pytest.approx(3.0, rel=0.01)

    def test_slope_positive_ramp(self):
        """Ramp from 1→5 over 200 samples at 1 Hz → slope ≈ (5-1)/199 ≈ 0.02."""
        feats = compute_pressure_features(self.ramp, sampling_rate_hz=1.0)
        assert feats["slope"] > 0

    def test_slope_constant(self):
        feats = compute_pressure_features(self.flat, sampling_rate_hz=1.0)
        assert feats["slope"] == pytest.approx(0.0, abs=1e-8)

    def test_range_of_flat(self):
        feats = compute_pressure_features(self.flat)
        assert feats["range"] == pytest.approx(0.0, abs=1e-10)

    def test_short_signal_nan(self):
        feats = compute_pressure_features(np.array([1.0]))
        assert np.isnan(feats["mean"])

    def test_zero_crossings_oscillating(self):
        """Alternating signal should have many zero crossings."""
        signal = np.array([1.0, -1.0] * 50)
        feats = compute_pressure_features(signal)
        assert feats["zero_crossings"] >= 90


# ============================================================
# FR-FE-3 — Temperature features
# ============================================================

class TestTemperatureFeatures:
    def test_all_keys_present(self):
        signal = np.linspace(20.0, 80.0, 60)
        feats = compute_temperature_features(signal, sampling_rate_hz=1.0)
        assert set(feats.keys()) == {"mean", "std", "min", "max", "slope", "range"}

    def test_slope_warming_trend(self):
        signal = np.linspace(20.0, 80.0, 60)
        feats = compute_temperature_features(signal, sampling_rate_hz=1.0)
        assert feats["slope"] > 0

    def test_slope_cooling_trend(self):
        signal = np.linspace(80.0, 20.0, 60)
        feats = compute_temperature_features(signal, sampling_rate_hz=1.0)
        assert feats["slope"] < 0

    def test_range_correct(self):
        signal = np.linspace(20.0, 80.0, 60)
        feats = compute_temperature_features(signal)
        assert feats["range"] == pytest.approx(60.0, rel=0.01)

    def test_short_signal_nan(self):
        feats = compute_temperature_features(np.array([25.0]))
        assert np.isnan(feats["mean"])


# ============================================================
# FR-FE-4 — Flow-pulse features
# ============================================================

class TestFlowPulseFeatures:
    def test_all_keys_present(self):
        signal = np.ones(100)
        feats = compute_flow_pulse_features(signal, window_duration_s=60.0)
        assert set(feats.keys()) == {"pulse_count", "pulse_rate", "active_ratio"}

    def test_all_ones_signal(self):
        signal = np.ones(100)
        feats = compute_flow_pulse_features(signal, window_duration_s=60.0)
        assert feats["pulse_count"] == pytest.approx(100.0)
        assert feats["active_ratio"] == pytest.approx(1.0)
        assert feats["pulse_rate"] == pytest.approx(100.0 / 60.0)

    def test_half_active(self):
        signal = np.array([1.0, 0.0] * 50)
        feats = compute_flow_pulse_features(signal, window_duration_s=100.0)
        assert feats["active_ratio"] == pytest.approx(0.5)

    def test_zero_signal(self):
        signal = np.zeros(50)
        feats = compute_flow_pulse_features(signal, window_duration_s=60.0)
        assert feats["pulse_count"] == pytest.approx(0.0)
        assert feats["active_ratio"] == pytest.approx(0.0)

    def test_empty_signal_nan(self):
        feats = compute_flow_pulse_features(np.array([]), window_duration_s=60.0)
        assert np.isnan(feats["pulse_count"])

    def test_no_physical_calibration(self):
        """Verify pulse_rate is raw pulses/s — no multiplier applied."""
        signal = np.ones(6)
        feats = compute_flow_pulse_features(signal, window_duration_s=60.0)
        # 6 pulses / 60 s = 0.1 pulses/s (raw, uncalibrated)
        assert feats["pulse_rate"] == pytest.approx(0.1)


# ============================================================
# FR-FE-5 — Digital state features
# ============================================================

class TestDigitalFeatures:
    def test_all_keys_present(self):
        signal = np.array([0.0, 1.0, 1.0, 0.0, 1.0])
        feats = compute_digital_features(signal)
        assert set(feats.keys()) == {
            "mode_state", "duty_cycle", "n_transitions",
            "first_state", "last_state",
        }

    def test_all_ones(self):
        signal = np.ones(100)
        feats = compute_digital_features(signal)
        assert feats["duty_cycle"] == pytest.approx(1.0)
        assert feats["n_transitions"] == pytest.approx(0.0)
        assert feats["mode_state"] == pytest.approx(1.0)

    def test_all_zeros(self):
        signal = np.zeros(100)
        feats = compute_digital_features(signal)
        assert feats["duty_cycle"] == pytest.approx(0.0)
        assert feats["mode_state"] == pytest.approx(0.0)

    def test_transitions_counted(self):
        signal = np.array([0.0, 1.0, 0.0, 1.0, 0.0])
        feats = compute_digital_features(signal)
        assert feats["n_transitions"] == pytest.approx(4.0)

    def test_first_last_state(self):
        signal = np.array([0.0, 1.0, 1.0, 0.0])
        feats = compute_digital_features(signal)
        assert feats["first_state"] == pytest.approx(0.0)
        assert feats["last_state"] == pytest.approx(0.0)

    def test_empty_signal_nan(self):
        feats = compute_digital_features(np.array([]))
        assert np.isnan(feats["duty_cycle"])
        assert np.isnan(feats["mode_state"])
        assert np.isnan(feats["n_transitions"])
        assert np.isnan(feats["first_state"])
        assert np.isnan(feats["last_state"])

    def test_binary_signal_transitions_and_duty(self):
        """Test standard binary signal [0, 0, 1, 1, 0]."""
        signal = np.array([0.0, 0.0, 1.0, 1.0, 0.0])
        feats = compute_digital_features(signal)
        assert feats["n_transitions"] == pytest.approx(2.0)
        assert feats["duty_cycle"] == pytest.approx(2.0 / 5.0)
        assert feats["mode_state"] == pytest.approx(0.0)
        assert feats["first_state"] == pytest.approx(0.0)
        assert feats["last_state"] == pytest.approx(0.0)

    def test_positive_categorical_signal_with_mapping(self):
        """Test positive categorical signal [1, 1, 2, 2, 1] with {1: 0, 2: 1} mapping."""
        signal = np.array([1.0, 1.0, 2.0, 2.0, 1.0])
        mapping = {1.0: 0, 2.0: 1}
        feats = compute_digital_features(signal, state_mapping=mapping)
        # Transitions between 1 and 2 must be counted (1->2, 2->1 = 2 transitions)
        assert feats["n_transitions"] == pytest.approx(2.0)
        # Duty cycle = 2 active (2.0) out of 5 total = 0.4
        assert feats["duty_cycle"] == pytest.approx(0.4)
        assert feats["mode_state"] == pytest.approx(0.0)
        assert feats["first_state"] == pytest.approx(1.0)
        assert feats["last_state"] == pytest.approx(1.0)

    def test_signal_with_state_zero_and_policy(self):
        """Test [0, 1, 2, 1, 0] with {1: 0, 2: 1} mapping under explicit unknown policy."""
        signal = np.array([0.0, 1.0, 2.0, 1.0, 0.0])
        mapping = {1.0: 0, 2.0: 1}
        feats = compute_digital_features(signal, state_mapping=mapping)
        # All 4 level transitions (0->1, 1->2, 2->1, 1->0) must be counted in raw signal
        assert feats["n_transitions"] == pytest.approx(4.0)
        # State 0 is not silently classified as ON or OFF; valid mapped samples = 3 ([1, 2, 1])
        # Active samples = 1 (state 2.0), so duty_cycle = 1/3
        assert feats["duty_cycle"] == pytest.approx(1.0 / 3.0)
        assert feats["mode_state"] == pytest.approx(0.0)
        assert feats["first_state"] == pytest.approx(0.0)
        assert feats["last_state"] == pytest.approx(0.0)

    def test_constant_state_signals(self):
        """Test constant ON and constant OFF signals with mapping."""
        mapping = {1.0: 0, 2.0: 1}
        # Constant ON (state 2)
        feats_on = compute_digital_features(np.array([2.0, 2.0, 2.0, 2.0]), state_mapping=mapping)
        assert feats_on["n_transitions"] == pytest.approx(0.0)
        assert feats_on["duty_cycle"] == pytest.approx(1.0)
        assert feats_on["mode_state"] == pytest.approx(1.0)
        assert feats_on["first_state"] == pytest.approx(2.0)
        assert feats_on["last_state"] == pytest.approx(2.0)

        # Constant OFF (state 1)
        feats_off = compute_digital_features(np.array([1.0, 1.0, 1.0]), state_mapping=mapping)
        assert feats_off["n_transitions"] == pytest.approx(0.0)
        assert feats_off["duty_cycle"] == pytest.approx(0.0)
        assert feats_off["mode_state"] == pytest.approx(0.0)
        assert feats_off["first_state"] == pytest.approx(1.0)
        assert feats_off["last_state"] == pytest.approx(1.0)

    def test_single_sample_input(self):
        """Test single-sample input preserves conventions and valid features."""
        mapping = {1.0: 0, 2.0: 1}
        feats = compute_digital_features(np.array([2.0]), state_mapping=mapping)
        assert feats["n_transitions"] == pytest.approx(0.0)
        assert feats["duty_cycle"] == pytest.approx(1.0)
        assert feats["mode_state"] == pytest.approx(1.0)
        assert feats["first_state"] == pytest.approx(2.0)
        assert feats["last_state"] == pytest.approx(2.0)

    def test_unknown_or_unsupported_actuator_states(self):
        """Signals consisting entirely of unmapped states evaluate to NaN duty_cycle/mode_state."""
        mapping = {1.0: 0, 2.0: 1}
        feats = compute_digital_features(np.array([0.0, 0.0, 0.0]), state_mapping=mapping)
        assert feats["n_transitions"] == pytest.approx(0.0)
        assert np.isnan(feats["duty_cycle"]), "Unmapped state must not be silently forced to 0 or 1"
        assert np.isnan(feats["mode_state"])
        assert feats["first_state"] == pytest.approx(0.0)
        assert feats["last_state"] == pytest.approx(0.0)

    def test_raw_signal_preservation(self):
        """Ensure compute_digital_features does not mutate input array in-place."""
        orig = np.array([1.0, 2.0, 0.0, 1.0])
        orig_copy = orig.copy()
        _ = compute_digital_features(orig, state_mapping={1.0: 0, 2.0: 1})
        np.testing.assert_array_equal(orig, orig_copy)


# ============================================================
# FeatureExtractor — sampling-rate contract (BUG-1 regression)
# ============================================================

class TestFeatureExtractorSamplingRate:
    """Verify that FeatureExtractor honours the sampling_rate_hz parameter.

    Regression tests for BUG-1: the default was incorrectly 1.0 Hz.
    The correct MetroPT-3-oriented default is 0.1 Hz.
    Other datasets and hardware streams must supply their own rate.
    Results are SYNTHETIC fixtures — not real experimental data.
    """

    def _make_window(self, n: int = 60, rate_hz: float = 0.1):
        """Return a minimal WindowedData-like object for extractor tests."""
        import pandas as pd
        from datetime import datetime, timezone
        from tcmim.data.windower import WindowedData
        from tcmim.schemas import Provenance

        np.random.seed(7)
        step_s = 1.0 / rate_hz
        idx = pd.date_range(
            start="2020-01-01T00:00:00Z",
            periods=n,
            freq=f"{int(step_s * 1000)}ms",
            tz="UTC",
        )
        df = pd.DataFrame(
            {"Motor_current": np.random.normal(5.0, 0.5, n)},
            index=idx,
        )
        return WindowedData(
            machine_id="test_machine",
            window_start=idx[0].to_pydatetime(),
            window_end=idx[-1].to_pydatetime(),
            data=df,
            provenance=Provenance.SYNTHETIC,
            window_index=0,
        )

    def test_default_sampling_rate_is_0_1_hz(self):
        """Default sampling_rate_hz must be 0.1 (MetroPT-3 nominal)."""
        from tcmim.features.extractor import FeatureExtractor
        extractor = FeatureExtractor()
        assert extractor.sampling_rate_hz == pytest.approx(0.1)

    def test_explicit_sampling_rate_stored(self):
        """Explicitly supplied rate must be stored and used."""
        from tcmim.features.extractor import FeatureExtractor
        extractor = FeatureExtractor(sampling_rate_hz=1000.0)
        assert extractor.sampling_rate_hz == pytest.approx(1000.0)

    def test_different_rates_give_different_slopes(self):
        """slope feature scales with sampling rate — different Hz → different slope."""
        from tcmim.features.extractor import FeatureExtractor

        ramp = np.linspace(0.0, 10.0, 120)
        # 0.1 Hz: 120 samples → 1200 s window → slope ≈ 10/1200
        slope_slow = compute_pressure_features(ramp, sampling_rate_hz=0.1)["slope"]
        # 1.0 Hz: 120 samples → 120 s window → slope ≈ 10/120
        slope_fast = compute_pressure_features(ramp, sampling_rate_hz=1.0)["slope"]
        # Faster sampling rate → steeper slope per second (same physical ramp)
        assert slope_fast > slope_slow

    def test_extractor_uses_stored_rate(self):
        """FeatureExtractor must pass its stored sampling_rate_hz to feature fns."""
        from tcmim.features.extractor import FeatureExtractor

        ramp = np.linspace(0.0, 10.0, 60)
        slope_ref = compute_pressure_features(ramp, sampling_rate_hz=5.0)["slope"]

        extractor = FeatureExtractor(sampling_rate_hz=5.0)
        window = self._make_window(n=60, rate_hz=5.0)
        # Use a ramp window
        import pandas as pd
        from datetime import timezone
        idx = window.data.index
        window.data["Motor_current"] = ramp
        fs = extractor.extract_window(window)
        slope_from_extractor = fs.features["current"]["Motor_current__slope"]
        assert slope_from_extractor == pytest.approx(slope_ref, rel=0.01)

    def test_metropt3_window_uses_correct_default(self):
        """End-to-end: default extractor on a 0.1-Hz window gives valid features."""
        from tcmim.features.extractor import FeatureExtractor
        extractor = FeatureExtractor()  # should default to 0.1 Hz
        window = self._make_window(n=60, rate_hz=0.1)
        fs = extractor.extract_window(window)
        assert len(fs.features) > 0
        # Confirm at least one finite slope value exists
        slope_vals = [
            v for feat_dict in fs.features.values()
            for k, v in feat_dict.items()
            if "slope" in k and not np.isnan(v)
        ]
        assert len(slope_vals) > 0, "Expected at least one finite slope feature."

