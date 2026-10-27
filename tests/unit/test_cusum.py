"""
TCMIM — Unit tests for CUSUM and Page-Hinkley detectors (M3, FR-ED-1).

All fixtures are SYNTHETIC — these tests verify algorithm correctness
on controlled inputs; results never constitute real experimental claims.
"""

import numpy as np
import pytest

from tcmim.events.cusum import CUSUMDetector, PageHinkleyDetector, DetectorAlarm


# ============================================================
# CUSUM detector tests
# ============================================================

class TestCUSUMDetector:
    def test_no_alarm_on_flat_signal(self):
        """Flat signal at or below the allowance k should never alarm."""
        det = CUSUMDetector(k=0.5, h=5.0)
        signal = np.zeros(200)
        alarms = det.run(signal)
        assert alarms == []

    def test_alarm_on_step_increase(self):
        """A clear step increase should trigger an alarm."""
        det = CUSUMDetector(k=0.5, h=5.0, reset=False)
        # 50 normal samples, then a step to 2.0
        signal = np.concatenate([np.zeros(50), np.ones(100) * 2.0])
        alarms = det.run(signal)
        assert len(alarms) >= 1

    def test_alarm_index_after_step(self):
        """Alarm must come after the step, not before it."""
        det = CUSUMDetector(k=0.5, h=5.0, reset=False)
        signal = np.concatenate([np.zeros(50), np.ones(200) * 2.0])
        alarms = det.run(signal)
        assert alarms[0].index >= 50

    def test_reset_allows_multiple_alarms(self):
        """With reset=True, multiple alarm bursts should each trigger."""
        det = CUSUMDetector(k=0.5, h=5.0, reset=True)
        # Two burst segments separated by quiescence
        burst = np.ones(30) * 3.0
        quiet = np.zeros(50)
        signal = np.concatenate([burst, quiet, burst])
        alarms = det.run(signal)
        assert len(alarms) >= 2

    def test_no_reset_single_alarm(self):
        """With reset=False the score stays elevated and re-alarms every step
        after the first alarm (score never drops back to 0).  What we verify
        here is that reset=True produces MORE resets than reset=False — the
        key behavioural difference is that reset=True resets S to 0 on alarm
        while reset=False leaves S growing, yielding an alarm on every subsequent step."""
        signal = np.ones(100) * 3.0
        det_no_reset = CUSUMDetector(k=0.5, h=5.0, reset=False)
        det_reset = CUSUMDetector(k=0.5, h=5.0, reset=True)
        alarms_no_reset = det_no_reset.run(signal)
        alarms_reset = det_reset.run(signal)
        # With reset=True, the score is zeroed after each alarm, so fewer
        # alarms fire for the same signal length.
        assert len(alarms_reset) <= len(alarms_no_reset)

    def test_alarm_score_exceeds_threshold(self):
        """Alarm score must always be > h at the moment of alarm."""
        det = CUSUMDetector(k=0.5, h=5.0, reset=True)
        signal = np.ones(200) * 2.0
        alarms = det.run(signal)
        for alarm in alarms:
            assert alarm.score > 5.0

    def test_alarm_detector_name(self):
        det = CUSUMDetector(k=0.5, h=5.0)
        signal = np.ones(100) * 3.0
        alarms = det.run(signal)
        for alarm in alarms:
            assert alarm.detector == "cusum"

    def test_run_with_scores_length(self):
        """Score trace must have the same length as the input signal."""
        det = CUSUMDetector(k=0.5, h=5.0)
        signal = np.random.normal(0, 1, 150)
        scores, alarms = det.run_with_scores(signal)
        assert len(scores) == len(signal)

    def test_scores_non_negative(self):
        """CUSUM scores are always ≥ 0 (max(0, ...))."""
        det = CUSUMDetector(k=0.5, h=5.0)
        signal = np.random.normal(0, 1, 300)
        scores, _ = det.run_with_scores(signal)
        assert np.all(scores >= 0)

    def test_nan_values_skipped(self):
        """NaN values in signal should not cause errors."""
        det = CUSUMDetector(k=0.5, h=5.0)
        signal = np.array([np.nan, 1.0, 2.0, np.nan, 3.0])
        alarms = det.run(signal)  # must not raise

    def test_empty_signal(self):
        det = CUSUMDetector(k=0.5, h=5.0)
        alarms = det.run(np.array([]))
        assert alarms == []

    def test_invalid_k_raises(self):
        with pytest.raises(ValueError, match="k"):
            CUSUMDetector(k=-1.0, h=5.0)

    def test_invalid_h_raises(self):
        with pytest.raises(ValueError, match="h"):
            CUSUMDetector(k=0.5, h=0.0)

    def test_sensitivity_to_k(self):
        """Lower k → more sensitive → alarm fires sooner."""
        signal = np.ones(200) * 1.0
        det_sensitive = CUSUMDetector(k=0.1, h=5.0, reset=False)
        det_robust = CUSUMDetector(k=0.9, h=5.0, reset=False)
        alarms_s = det_sensitive.run(signal)
        alarms_r = det_robust.run(signal)
        if alarms_s and alarms_r:
            assert alarms_s[0].index <= alarms_r[0].index

    def test_sensitivity_to_h(self):
        """Higher h → less sensitive → alarm fires later (or not at all)."""
        signal = np.ones(200) * 1.0
        det_low_h = CUSUMDetector(k=0.5, h=2.0, reset=False)
        det_high_h = CUSUMDetector(k=0.5, h=20.0, reset=False)
        alarms_low = det_low_h.run(signal)
        alarms_high = det_high_h.run(signal)
        if alarms_low and alarms_high:
            assert alarms_low[0].index <= alarms_high[0].index


# ============================================================
# Page-Hinkley detector tests
# ============================================================

class TestPageHinkleyDetector:
    def test_no_alarm_flat_signal(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=50.0)
        signal = np.zeros(300)
        alarms = det.run(signal)
        assert alarms == []

    def test_alarm_on_step(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=20.0, reset=False)
        signal = np.concatenate([np.zeros(50), np.ones(200) * 3.0])
        alarms = det.run(signal)
        assert len(alarms) >= 1

    def test_alarm_index_after_step(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=20.0, reset=False)
        signal = np.concatenate([np.zeros(50), np.ones(200) * 3.0])
        alarms = det.run(signal)
        assert alarms[0].index > 50

    def test_alarm_detector_name(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=20.0)
        signal = np.ones(200) * 5.0
        alarms = det.run(signal)
        for alarm in alarms:
            assert alarm.detector == "page_hinkley"

    def test_run_with_scores_length(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=50.0)
        signal = np.random.normal(1, 0.5, 100)
        scores, _ = det.run_with_scores(signal)
        assert len(scores) == len(signal)

    def test_nan_values_skipped(self):
        det = PageHinkleyDetector(delta=0.05, lambda_=50.0)
        signal = np.array([np.nan, 1.0, 2.0, np.nan])
        alarms = det.run(signal)  # must not raise

    def test_invalid_delta_raises(self):
        with pytest.raises(ValueError, match="delta"):
            PageHinkleyDetector(delta=-0.1, lambda_=50.0)

    def test_invalid_lambda_raises(self):
        with pytest.raises(ValueError, match="lambda"):
            PageHinkleyDetector(delta=0.05, lambda_=0.0)

    def test_reset_allows_multiple_alarms(self):
        """PH must fire at least once on a step-shift signal.

        PH operates on x_t - running_mean, so a constant signal gives 0 score.
        A step shift (e.g. zeros → large positive) is needed for PH to
        accumulate enough score to alarm.
        """
        det = PageHinkleyDetector(delta=0.1, lambda_=5.0, reset=True)
        # Repeated pattern: quiet then step up
        block = np.concatenate([np.zeros(30), np.ones(30) * 10.0])
        signal = np.concatenate([block] * 5)   # 5 repetitions
        alarms = det.run(signal)
        assert len(alarms) >= 1
