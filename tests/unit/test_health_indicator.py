"""
TCMIM — Unit tests for health indicator (M3, FR-LH-2).

All fixtures are SYNTHETIC.
"""

import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.health.baseline import MachineBaseline
from tcmim.health.indicator import HealthIndicator, _health_from_z_scores, _flatten
from tcmim.schemas import MultimodalFeatureSample, Provenance, HealthSample

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_multimodal_sample(
    feats: dict,
    window_index: int = 0,
    machine_id: str = "m1",
) -> MultimodalFeatureSample:
    ws = NOW + timedelta(minutes=window_index)
    we = ws + timedelta(minutes=1)
    return MultimodalFeatureSample(
        machine_id=machine_id,
        window_start=ws,
        window_end=we,
        features={"pressure": feats},
        provenance=Provenance.SYNTHETIC,
    )


def _make_baseline(n: int = 60) -> MachineBaseline:
    """Build a baseline where TP2__mean ~ N(5, 0.1)."""
    np.random.seed(42)
    samples = [
        _make_multimodal_sample(
            {"TP2__mean": float(np.random.normal(5.0, 0.1))},
            window_index=i,
        )
        for i in range(n)
    ]
    return MachineBaseline.fit(samples, baseline_frac=0.5)


class TestHealthFromZScores:
    def test_zero_z_gives_health_one(self):
        """All z-scores = 0 → health = 1.0."""
        z = {"f1": 0.0, "f2": 0.0}
        assert _health_from_z_scores(z) == pytest.approx(1.0)

    def test_health_decreases_with_z(self):
        """Health decreases as z-scores grow."""
        h_low = _health_from_z_scores({"f1": 1.0})
        h_high = _health_from_z_scores({"f1": 5.0})
        assert h_low > h_high

    def test_health_in_range(self):
        """Health always in [0, 1]."""
        for z_val in [0.0, 1.0, 5.0, 100.0]:
            h = _health_from_z_scores({"f": z_val})
            assert 0.0 <= h <= 1.0

    def test_all_nan_returns_one(self):
        """No valid z-scores → default to 1.0 (no evidence of abnormality)."""
        z = {"f1": float("nan"), "f2": float("nan")}
        assert _health_from_z_scores(z) == pytest.approx(1.0)

    def test_formula_exact(self):
        """Verify formula: health = 1 / (1 + mean_abs_z)."""
        z = {"f1": 2.0, "f2": 4.0}
        expected = 1.0 / (1.0 + 3.0)  # mean_abs_z = 3.0
        assert _health_from_z_scores(z) == pytest.approx(expected)

    def test_negative_z_handled(self):
        """Negative z-scores: abs value is used."""
        z_pos = {"f": 3.0}
        z_neg = {"f": -3.0}
        assert _health_from_z_scores(z_pos) == pytest.approx(
            _health_from_z_scores(z_neg)
        )


class TestFlatten:
    def test_single_modality(self):
        features = {"pressure": {"a": 1.0, "b": 2.0}}
        flat = _flatten(features)
        assert flat == {"a": 1.0, "b": 2.0}

    def test_multi_modality(self):
        features = {
            "pressure": {"a": 1.0},
            "temperature": {"b": 2.0},
        }
        flat = _flatten(features)
        assert "a" in flat and "b" in flat


class TestHealthIndicator:
    def setup_method(self):
        self.baseline = _make_baseline(60)
        self.indicator = HealthIndicator(self.baseline)

    def test_returns_health_sample(self):
        sample = _make_multimodal_sample({"TP2__mean": 5.0})
        hs = self.indicator.compute(sample)
        assert isinstance(hs, HealthSample)

    def test_health_score_in_range(self):
        sample = _make_multimodal_sample({"TP2__mean": 5.0})
        hs = self.indicator.compute(sample)
        assert 0.0 <= hs.health_score <= 1.0

    def test_normal_value_high_health(self):
        """A value on the baseline mean should give health close to 1."""
        mean = self.baseline.feature_stats["TP2__mean"].mean
        sample = _make_multimodal_sample({"TP2__mean": mean})
        hs = self.indicator.compute(sample)
        assert hs.health_score > 0.9

    def test_abnormal_value_lower_health(self):
        """A value far from baseline gives lower health."""
        stats = self.baseline.feature_stats["TP2__mean"]
        normal_val = stats.mean
        abnormal_val = stats.mean + 10 * stats.std
        hs_normal = self.indicator.compute(
            _make_multimodal_sample({"TP2__mean": normal_val})
        )
        hs_abnormal = self.indicator.compute(
            _make_multimodal_sample({"TP2__mean": abnormal_val})
        )
        assert hs_abnormal.health_score < hs_normal.health_score

    def test_provenance_preserved(self):
        sample = _make_multimodal_sample({"TP2__mean": 5.0})
        hs = self.indicator.compute(sample)
        assert hs.provenance == Provenance.SYNTHETIC

    def test_baseline_id_set(self):
        sample = _make_multimodal_sample({"TP2__mean": 5.0})
        hs = self.indicator.compute(sample)
        assert hs.baseline_id == self.baseline.baseline_id

    def test_z_scores_populated(self):
        sample = _make_multimodal_sample({"TP2__mean": 5.0})
        hs = self.indicator.compute(sample)
        assert "TP2__mean" in hs.z_scores

    def test_compute_all_length(self):
        samples = [
            _make_multimodal_sample({"TP2__mean": 5.0 + i * 0.1}, window_index=i)
            for i in range(20)
        ]
        results = self.indicator.compute_all(samples)
        assert len(results) == 20

    def test_compute_all_health_decreases_with_drift(self):
        """Health should trend downward as values drift further from baseline."""
        stats = self.baseline.feature_stats["TP2__mean"]
        samples = [
            _make_multimodal_sample(
                {"TP2__mean": stats.mean + i * 0.5 * stats.std},
                window_index=i,
            )
            for i in range(30)
        ]
        results = self.indicator.compute_all(samples)
        scores = [r.health_score for r in results]
        # Health at end should be lower than at start
        assert scores[-1] < scores[0]
