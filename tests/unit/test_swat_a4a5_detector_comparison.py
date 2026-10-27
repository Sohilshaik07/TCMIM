"""Unit tests for SWaT A4/A5 Stage 1 Detector Comparison improvements.

Validates:
1. CUSUM partition initialization (starts at zero for each partition).
2. Boundary isolation: no state carries from pre-baseline buffer into baseline.
3. Boundary isolation: no state carries from baseline into held-out evaluation.
4. Operational false-alarm clustering: consecutive FP windows form one incident.
5. Normal / non-FP windows break false-alarm clusters and allow new incidents.
6. Positive-labelled (attack) windows break false-alarm clusters.
7. Empty partitions and zero-false-alarm sequences handled safely.
8. Standard confusion matrix invariance: clustered metrics do not alter TP, FP, TN, FN.
"""

from __future__ import annotations

import numpy as np
import pytest

from tcmim.data.swat_a4a5 import (
    count_clustered_false_alarms,
    compute_clustered_false_alarm_metrics,
)
from tcmim.events.cusum import CUSUMDetector


# ==============================================================================
# 1. CUSUM Partition Initialization and Boundary Isolation Tests
# ==============================================================================

class TestCUSUMPartitionInitialization:
    def test_cusum_starts_at_zero_for_each_partition(self):
        """Verify that a fresh CUSUMDetector instance starts strictly with S_0 = 0."""
        det = CUSUMDetector(k=0.5, h=5.0, reset=True)
        x = np.array([1.0, 1.2, 0.8])
        scores, alarms = det.run_with_scores(x)

        # First score should be max(0, 0 + x[0] - k) = 1.0 - 0.5 = 0.5
        assert scores[0] == pytest.approx(0.5)

    def test_no_state_carryover_buffer_to_baseline(self):
        """Verify no state carries from pre-baseline buffer into baseline when reset."""
        # Simulated pre-baseline buffer that accumulates positive S below threshold
        buffer_x = np.array([1.5, 1.5])  # S accumulates to 1.0 + 1.0 = 2.0 (< h=5.0)
        # Simulated baseline with nominal values below allowance k=0.5
        baseline_x = np.array([0.4, 0.4, 0.4])

        k = 0.5
        h = 5.0

        # Scenario A: Continuous run across boundary (carries S=2.0 into baseline)
        continuous_det = CUSUMDetector(k=k, h=h, reset=True)
        continuous_scores, _ = continuous_det.run_with_scores(np.concatenate([buffer_x, baseline_x]))
        s_entering_baseline_continuous = continuous_scores[len(buffer_x)]  # max(0, 2.0 + 0.4 - 0.5) = 1.9

        # Scenario B: Explicit partition reset (starts fresh S_0 = 0)
        baseline_det = CUSUMDetector(k=k, h=h, reset=True)
        baseline_scores, _ = baseline_det.run_with_scores(baseline_x)
        s_entering_baseline_clean = baseline_scores[0]  # max(0, 0.0 + 0.4 - 0.5) = 0.0

        # In continuous run, state at index len(buffer_x) is contaminated by buffer
        assert s_entering_baseline_continuous == pytest.approx(1.9)
        assert s_entering_baseline_clean == pytest.approx(0.0)
        assert s_entering_baseline_continuous > s_entering_baseline_clean


    def test_no_state_carryover_baseline_to_heldout(self):
        """Verify no state carries from baseline into held-out evaluation when reset."""
        baseline_x = np.array([0.5, 0.6, 0.7, 0.8, 0.9])  # Drift at end of baseline
        heldout_x = np.array([0.3, 0.4, 0.5])

        k = 0.5
        h = 5.0

        # Isolated held-out detector
        heldout_det = CUSUMDetector(k=k, h=h, reset=True)
        heldout_scores, _ = heldout_det.run_with_scores(heldout_x)

        expected_heldout_s0 = max(0.0, 0.0 + heldout_x[0] - k)
        assert heldout_scores[0] == pytest.approx(expected_heldout_s0)


# ==============================================================================
# 2. Clustered False-Alarm Metric Tests
# ==============================================================================

class TestClusteredFalseAlarms:
    def test_consecutive_false_positive_windows_form_one_incident(self):
        """Verify consecutive FP windows are grouped into exactly 1 incident."""
        y_true = np.array([0.0, 0.0, 0.0, 0.0])
        y_pred = np.array([1, 1, 1, 1])

        fp_windows, incidents = count_clustered_false_alarms(y_pred, y_true)
        assert fp_windows == 4
        assert incidents == 1

    def test_normal_window_breaks_false_alarm_cluster(self):
        """Verify normal window (TN) breaks a cluster and starts a new incident."""
        # Window 0,1: FP (Incident 1)
        # Window 2: TN (Breaks cluster)
        # Window 3,4: FP (Incident 2)
        y_true = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
        y_pred = np.array([1, 1, 0, 1, 1])

        fp_windows, incidents = count_clustered_false_alarms(y_pred, y_true)
        assert fp_windows == 4
        assert incidents == 2

    def test_positive_labelled_window_breaks_false_alarm_cluster(self):
        """Verify attack-labelled window breaks false-alarm cluster."""
        # Window 0: FP (Incident 1)
        # Window 1: TP (Attack window, breaks false alarm cluster)
        # Window 2: FP (Incident 2)
        y_true = np.array([0.0, 1.0, 0.0])
        y_pred = np.array([1, 1, 1])

        fp_windows, incidents = count_clustered_false_alarms(y_pred, y_true)
        assert fp_windows == 2
        assert incidents == 2

    def test_false_negative_window_breaks_false_alarm_cluster(self):
        """Verify FN window (unflagged attack) breaks false-alarm cluster."""
        # Window 0: FP (Incident 1)
        # Window 1: FN (Attack window, y=1, pred=0, breaks cluster)
        # Window 2: FP (Incident 2)
        y_true = np.array([0.0, 1.0, 0.0])
        y_pred = np.array([1, 0, 1])

        fp_windows, incidents = count_clustered_false_alarms(y_pred, y_true)
        assert fp_windows == 2
        assert incidents == 2

    def test_empty_and_zero_false_alarm_cases_handled_safely(self):
        """Verify empty and all-correct sequences return zero counts safely."""
        # Empty inputs
        fp_w, inc = count_clustered_false_alarms([], [])
        assert fp_w == 0
        assert inc == 0

        # All True Negatives (0 false alarms)
        fp_w, inc = count_clustered_false_alarms([0, 0, 0], [0.0, 0.0, 0.0])
        assert fp_w == 0
        assert inc == 0

        # All True Positives (0 false alarms)
        fp_w, inc = count_clustered_false_alarms([1, 1], [1.0, 1.0])
        assert fp_w == 0
        assert inc == 0

    def test_hourly_rate_calculation(self):
        """Verify hourly false-alarm rates for windows and incidents."""
        y_true = np.array([0.0, 0.0, 0.0, 0.0])
        y_pred = np.array([1, 1, 0, 1])
        # 3 FP windows, 2 incidents
        # Duration: 2.0 hours
        metrics = compute_clustered_false_alarm_metrics(y_pred, y_true, duration_hours=2.0)
        assert metrics["false_positive_windows"] == 3
        assert metrics["clustered_false_alarm_incidents"] == 2
        assert metrics["false_positive_windows_per_hour"] == 1.50
        assert metrics["clustered_false_alarms_per_hour"] == 1.00

    def test_clustered_metrics_do_not_alter_standard_confusion_matrix(self):
        """Verify that clustered false alarm metrics do not alter standard TP/FP/TN/FN."""
        y_true = np.array([0.0, 0.0, 1.0, 1.0, 0.0])
        y_pred = np.array([1, 1, 1, 0, 0])

        tp = int(((y_pred == 1) & (y_true == 1.0)).sum())
        fp = int(((y_pred == 1) & (y_true == 0.0)).sum())
        tn = int(((y_pred == 0) & (y_true == 0.0)).sum())
        fn = int(((y_pred == 0) & (y_true == 1.0)).sum())

        assert tp == 1
        assert fp == 2
        assert tn == 1
        assert fn == 1

        fp_windows, incidents = count_clustered_false_alarms(y_pred, y_true)
        # Clustered FP window count MUST equal standard FP count
        assert fp_windows == fp
        # Consecutive windows 0 and 1 group into 1 incident
        assert incidents == 1
