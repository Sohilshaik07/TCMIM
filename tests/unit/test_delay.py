"""
TCMIM — Unit tests for delay estimation (M5, FR-DL-1, FR-DL-2).

All fixtures are SYNTHETIC.
"""

import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.propagation.delay import (
    cross_correlation_lag,
    aggregate_delay_stats,
    aggregate_all_pairs,
)
from tcmim.schemas import PropagationObservation, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_obs(
    src: str,
    tgt: str,
    delta_t_s: float,
    gate_result: str = "accepted",
) -> PropagationObservation:
    return PropagationObservation(
        source_event="e1",
        target_event="e2",
        source_machine=src,
        target_machine=tgt,
        delta_t_s=delta_t_s,
        gate_result=gate_result,
        reject_reason=None if gate_result == "accepted" else "test",
        provenance=Provenance.SYNTHETIC,
    )


# ============================================================
# Cross-correlation lag
# ============================================================

class TestCrossCorrelationLag:
    def test_perfect_positive_lag(self):
        """Signal B is signal A shifted by 10 samples → lag ≈ +10."""
        a = np.zeros(100)
        a[30] = 1.0
        b = np.zeros(100)
        b[40] = 1.0   # 10 samples later
        lag, corr = cross_correlation_lag(a, b, sampling_rate_hz=1.0)
        assert lag == pytest.approx(10.0, abs=1.0)

    def test_lag_sign_positive_means_b_lags_a(self):
        """Positive lag means B responds after A."""
        a = np.zeros(80)
        a[20] = 1.0
        b = np.zeros(80)
        b[35] = 1.0   # 15 samples after A
        lag, corr = cross_correlation_lag(a, b, sampling_rate_hz=1.0)
        assert lag > 0

    def test_lag_in_seconds(self):
        """Lag should be converted to seconds via sampling_rate_hz."""
        a = np.zeros(100)
        a[30] = 1.0
        b = np.zeros(100)
        b[35] = 1.0   # 5 samples later at 2 Hz → 2.5 s
        lag, _ = cross_correlation_lag(a, b, sampling_rate_hz=2.0)
        assert lag == pytest.approx(2.5, abs=0.6)

    def test_constant_signal_returns_nan(self):
        a = np.ones(50)
        b = np.sin(np.linspace(0, np.pi, 50))
        lag, corr = cross_correlation_lag(a, b, sampling_rate_hz=1.0)
        assert np.isnan(lag)
        assert np.isnan(corr)

    def test_short_signal_returns_nan(self):
        lag, corr = cross_correlation_lag(np.array([1.0]), np.array([1.0]))
        assert np.isnan(lag)

    def test_correlation_clipped_to_minus_one_one(self):
        a = np.random.normal(0, 1, 100)
        b = np.random.normal(0, 1, 100)
        _, corr = cross_correlation_lag(a, b, sampling_rate_hz=1.0)
        assert -1.0 <= corr <= 1.0

    def test_max_lag_samples_restricts_search(self):
        """With max_lag_samples=5, a true lag of 20 should not be found."""
        a = np.zeros(100)
        a[20] = 1.0
        b = np.zeros(100)
        b[40] = 1.0   # true lag = 20
        lag_restricted, _ = cross_correlation_lag(
            a, b, sampling_rate_hz=1.0, max_lag_samples=5
        )
        lag_full, _ = cross_correlation_lag(a, b, sampling_rate_hz=1.0)
        # Full search should find true lag ≈ 20; restricted should not
        assert abs(lag_full - 20.0) < 2.0
        assert abs(lag_restricted) <= 5.0


# ============================================================
# Aggregate delay statistics
# ============================================================

class TestAggregateDelayStats:
    def test_basic_stats(self):
        obs = [
            _make_obs("A", "B", 30.0),
            _make_obs("A", "B", 45.0),
            _make_obs("A", "B", 60.0),
        ]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats is not None
        assert stats.n == 3
        assert stats.mean_s == pytest.approx(45.0)
        assert stats.min_s == pytest.approx(30.0)
        assert stats.max_s == pytest.approx(60.0)

    def test_direction_consistency_all_positive(self):
        obs = [_make_obs("A", "B", 30.0 + i) for i in range(5)]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats.direction_consistency == pytest.approx(1.0)

    def test_direction_consistency_mixed(self):
        """3 positive, 2 negative → consistency = 0.6."""
        obs = [
            _make_obs("A", "B", 30.0),
            _make_obs("A", "B", 45.0),
            _make_obs("A", "B", 60.0),
            _make_obs("A", "B", -10.0),
            _make_obs("A", "B", -5.0),
        ]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats.direction_consistency == pytest.approx(0.6)

    def test_rejected_observations_excluded(self):
        """Rejected observations must not contribute to statistics."""
        obs = [
            _make_obs("A", "B", 30.0, gate_result="accepted"),
            _make_obs("A", "B", 999.0, gate_result="rejected"),  # outlier, rejected
        ]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats.n == 1
        assert stats.mean_s == pytest.approx(30.0)

    def test_no_accepted_returns_none(self):
        obs = [_make_obs("A", "B", 30.0, gate_result="rejected")]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats is None

    def test_empty_list_returns_none(self):
        stats = aggregate_delay_stats([], "A", "B")
        assert stats is None

    def test_single_observation_std_zero(self):
        obs = [_make_obs("A", "B", 50.0)]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats.std_s == pytest.approx(0.0)

    def test_machine_id_filtering(self):
        """Stats should only include obs matching the specified pair."""
        obs = [
            _make_obs("A", "B", 30.0),
            _make_obs("A", "C", 999.0),  # different pair — excluded
            _make_obs("A", "B", 60.0),
        ]
        stats = aggregate_delay_stats(obs, "A", "B")
        assert stats.n == 2

    def test_std_of_multiple_obs(self):
        deltas = [10.0, 20.0, 30.0, 40.0, 50.0]
        obs = [_make_obs("A", "B", d) for d in deltas]
        stats = aggregate_delay_stats(obs, "A", "B")
        expected_std = float(np.std(deltas, ddof=1))
        assert stats.std_s == pytest.approx(expected_std, rel=1e-5)


class TestAggregateAllPairs:
    def test_discovers_both_pairs(self):
        obs = [
            _make_obs("A", "B", 30.0),
            _make_obs("B", "C", 45.0),
        ]
        stats_list = aggregate_all_pairs(obs)
        pairs = {(s.source_machine, s.target_machine) for s in stats_list}
        assert ("A", "B") in pairs
        assert ("B", "C") in pairs

    def test_empty_returns_empty(self):
        assert aggregate_all_pairs([]) == []

    def test_all_rejected_returns_empty(self):
        obs = [_make_obs("A", "B", 30.0, gate_result="rejected")]
        assert aggregate_all_pairs(obs) == []
