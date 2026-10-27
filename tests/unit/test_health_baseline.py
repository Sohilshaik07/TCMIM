"""
TCMIM — Unit tests for health baseline (M3, FR-LH-1).

All fixtures are SYNTHETIC — never used in real-result reports.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import List

import numpy as np
import pytest

from tcmim.health.baseline import MachineBaseline, MIN_BASELINE_WINDOWS
from tcmim.schemas import MultimodalFeatureSample, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_samples(
    n: int,
    feature_vals: dict | None = None,
    noise_std: float = 0.1,
) -> List[MultimodalFeatureSample]:
    """Create n synthetic MultimodalFeatureSamples with controllable features."""
    np.random.seed(42)
    samples = []
    for i in range(n):
        ws = NOW + timedelta(minutes=i)
        we = ws + timedelta(minutes=1)
        if feature_vals is not None:
            feats = {k: float(v) for k, v in feature_vals.items()}
        else:
            feats = {
                "TP2__mean": float(np.random.normal(5.0, noise_std)),
                "TP2__std":  float(np.random.normal(0.5, 0.05)),
            }
        samples.append(
            MultimodalFeatureSample(
                machine_id="test_machine",
                window_start=ws,
                window_end=we,
                features={"pressure": feats},
                provenance=Provenance.SYNTHETIC,
            )
        )
    return samples


class TestMachineBaselineFit:
    def test_basic_fit(self):
        samples = _make_samples(50)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.2)
        assert isinstance(baseline, MachineBaseline)
        assert baseline.fitted is True
        assert baseline.machine_id == "test_machine"

    def test_baseline_id_is_uuid(self):
        samples = _make_samples(50)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.2)
        uuid.UUID(baseline.baseline_id)  # should not raise

    def test_baseline_uses_correct_fraction(self):
        samples = _make_samples(100)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.3)
        assert baseline.n_windows == 30

    def test_empty_samples_raises(self):
        with pytest.raises(ValueError, match="no samples"):
            MachineBaseline.fit([])

    def test_feature_stats_populated(self):
        samples = _make_samples(50)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.5)
        assert "TP2__mean" in baseline.feature_stats
        assert "TP2__std" in baseline.feature_stats

    def test_mean_reasonable(self):
        samples = _make_samples(100, noise_std=0.01)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.5)
        stats = baseline.feature_stats["TP2__mean"]
        assert stats.mean == pytest.approx(5.0, abs=0.1)

    def test_constant_feature_excluded(self):
        """A constant-value feature should be marked constant=True."""
        samples = _make_samples(50, feature_vals={"const_feat": 3.0})
        baseline = MachineBaseline.fit(samples, baseline_frac=0.5)
        assert baseline.feature_stats["const_feat"].constant is True

    def test_provenance_propagated(self):
        samples = _make_samples(50)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.2)
        assert baseline.provenance == Provenance.SYNTHETIC

    def test_window_period_set(self):
        samples = _make_samples(40)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.5)
        assert baseline.window_start <= baseline.window_end

    def test_summary_is_string(self):
        samples = _make_samples(50)
        baseline = MachineBaseline.fit(samples, baseline_frac=0.2)
        s = baseline.summary()
        assert isinstance(s, str)
        assert "test_machine" in s


class TestMachineBaselineZScores:
    def setup_method(self):
        np.random.seed(0)
        # Create a clean baseline: TP2__mean ≈ N(5.0, 0.1)
        self.samples = _make_samples(100, noise_std=0.1)
        self.baseline = MachineBaseline.fit(self.samples, baseline_frac=0.5)

    def test_z_score_on_mean_is_near_zero(self):
        """A value at the baseline mean should have z≈0."""
        feat_mean = self.baseline.feature_stats["TP2__mean"].mean
        z = self.baseline.z_scores({"TP2__mean": feat_mean})
        assert z["TP2__mean"] == pytest.approx(0.0, abs=1e-6)

    def test_z_score_one_std_away(self):
        """A value 1 std above the mean should give z≈1."""
        stats = self.baseline.feature_stats["TP2__mean"]
        val = stats.mean + stats.std
        z = self.baseline.z_scores({"TP2__mean": val})
        assert z["TP2__mean"] == pytest.approx(1.0, abs=1e-6)

    def test_unknown_feature_returns_nan(self):
        z = self.baseline.z_scores({"nonexistent_feat": 99.0})
        assert np.isnan(z["nonexistent_feat"])

    def test_constant_feature_returns_nan(self):
        """Constant features must return NaN for z-score."""
        samples = _make_samples(50, feature_vals={"const_feat": 3.0})
        baseline = MachineBaseline.fit(samples, baseline_frac=0.5)
        z = baseline.z_scores({"const_feat": 3.0})
        assert np.isnan(z["const_feat"])

    def test_nan_input_returns_nan(self):
        z = self.baseline.z_scores({"TP2__mean": float("nan")})
        assert np.isnan(z["TP2__mean"])
