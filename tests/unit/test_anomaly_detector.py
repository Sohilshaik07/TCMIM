"""
TCMIM — Unit tests for Stage 1 Anomaly Detector (ML-S1).

Tests cover:
- Chronological splitting and look-ahead prevention.
- Baseline-only fitting (future data isolation).
- Non-constant anomaly score output on suitable data.
- Handling of constant channels, NaNs, and insufficient data.
- Strict provenance enforcement (FR-DA-2).
- Reproducibility with fixed random seed.
- Deterministic CUSUM comparison baseline.
- Daily aggregation accounting for data gaps.
"""

from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np
import pytest

from tcmim.config import CUSUMConfig
from tcmim.ml.anomaly_detector import (
    BaselineSplitInfo,
    IsolationForestAnomalyDetector,
    run_cusum_comparison,
    summarize_anomalies_by_day,
)
from tcmim.schemas import AnomalyRecord, MultimodalFeatureSample, Provenance

BASE_TIME = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)


def make_dummy_samples(
    n: int = 50,
    *,
    step_minutes: int = 5,
    provenance: Provenance = Provenance.SYNTHETIC,
    machine_id: str = "comp_test",
    seed: int = 42,
    constant_feature: bool = False,
    nan_feature: bool = False,
) -> List[MultimodalFeatureSample]:
    """Generate synthetic feature samples for isolated unit testing."""
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(n):
        t_start = BASE_TIME + timedelta(minutes=i * step_minutes)
        t_end = t_start + timedelta(minutes=step_minutes)

        # Varying features (simulate pressure & current)
        p_mean = 5.0 + rng.normal(0, 0.2) + (0.5 if i > 40 else 0.0)
        p_std = 0.3 + rng.uniform(0.01, 0.05)
        c_mean = 10.0 + rng.normal(0, 0.5)

        feats = {
            "pressure": {
                "TP2__mean": float(p_mean),
                "TP2__std": float(p_std),
            },
            "current": {
                "Motor__mean": float(c_mean),
            },
        }

        if constant_feature:
            feats["digital_state"] = {"COMP__mean": 1.0}  # std == 0

        if nan_feature:
            feats["temperature"] = {"T1__mean": np.nan}  # 100% NaN

        samples.append(
            MultimodalFeatureSample(
                machine_id=machine_id,
                window_start=t_start,
                window_end=t_end,
                features=feats,
                provenance=provenance,
            )
        )
    return samples


# ===========================================================================
# 1. Chronological splitting & Temporal ordering
# ===========================================================================

class TestChronologicalSplitting:
    def test_chronological_split_fractions(self):
        samples = make_dummy_samples(n=100)
        det = IsolationForestAnomalyDetector(baseline_frac=0.25, min_baseline_windows=10)
        det.fit(samples)

        assert det.split_info_ is not None
        assert det.split_info_.n_total == 100
        assert det.split_info_.n_baseline == 25
        assert det.split_info_.baseline_frac == 0.25
        assert det.split_info_.baseline_start == samples[0].window_start
        assert det.split_info_.baseline_end == samples[24].window_end
        assert det.split_info_.eval_start == samples[25].window_start
        assert det.split_info_.eval_end == samples[99].window_end

    def test_out_of_order_samples_raise_error(self):
        samples = make_dummy_samples(n=20)
        # Swap two samples to create temporal violation
        samples[5], samples[6] = samples[6], samples[5]

        det = IsolationForestAnomalyDetector(min_baseline_windows=5)
        with pytest.raises(ValueError, match="Temporal violation"):
            det.fit(samples)

    def test_predict_score_rejects_shuffled_eval(self):
        samples = make_dummy_samples(n=30)
        det = IsolationForestAnomalyDetector(baseline_frac=0.4, min_baseline_windows=10)
        det.fit(samples)

        eval_samples = samples[12:].copy()
        eval_samples.reverse()  # Reverse order
        with pytest.raises(ValueError, match="chronological order"):
            det.predict_score(eval_samples)


# ===========================================================================
# 2. Baseline-only fitting (Future Isolation)
# ===========================================================================

class TestBaselineOnlyFitting:
    def test_future_data_does_not_affect_baseline_fit(self):
        """Fit detector on 50 samples vs fit on 100 samples where first 50 are identical."""
        samples_50 = make_dummy_samples(n=50, seed=123)
        samples_100 = make_dummy_samples(n=100, seed=123)

        det1 = IsolationForestAnomalyDetector(baseline_frac=0.4, min_baseline_windows=10, random_state=42)
        det1.fit(samples_50)  # baseline uses 20 windows

        det2 = IsolationForestAnomalyDetector(baseline_frac=0.2, min_baseline_windows=10, random_state=42)
        det2.fit(samples_100)  # baseline uses first 20 windows (same 20 windows)

        # Baseline medians and selected features must match exactly
        assert det1.feature_names_ == det2.feature_names_
        for feat in det1.feature_names_:
            assert np.isclose(det1.feature_medians_[feat], det2.feature_medians_[feat])

        # Scores on the first 10 windows must be identical
        scores1 = [r.anomaly_score for r in det1.predict_score(samples_50[:10])]
        scores2 = [r.anomaly_score for r in det2.predict_score(samples_100[:10])]
        np.testing.assert_allclose(scores1, scores2)


# ===========================================================================
# 3. Feature sanitisation: Constant channels & NaN exclusion
# ===========================================================================

class TestFeatureSanitisation:
    def test_constant_channels_excluded(self):
        samples = make_dummy_samples(n=30, constant_feature=True)
        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=10)
        det.fit(samples)

        assert "COMP__mean" not in det.feature_names_
        assert "COMP__mean" in det.excluded_features_
        assert "constant_channel" in det.excluded_features_["COMP__mean"]

    def test_high_nan_channels_excluded(self):
        samples = make_dummy_samples(n=30, nan_feature=True)
        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=10)
        det.fit(samples)

        assert "T1__mean" not in det.feature_names_
        assert "T1__mean" in det.excluded_features_

    def test_sparse_nan_imputed_with_baseline_median(self):
        samples = make_dummy_samples(n=30)
        # Introduce a single NaN into eval window
        samples[25].features["pressure"]["TP2__mean"] = np.nan

        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=10)
        det.fit(samples)
        records = det.predict_score([samples[25]])

        assert len(records) == 1
        assert np.isfinite(records[0].anomaly_score)


# ===========================================================================
# 4. Non-constant score output & Schemas
# ===========================================================================

class TestScoringAndOutput:
    def test_non_constant_scores(self):
        samples = make_dummy_samples(n=60, seed=777)
        det = IsolationForestAnomalyDetector(baseline_frac=0.3, min_baseline_windows=10)
        det.fit(samples)
        records = det.predict_score(samples)

        scores = [r.anomaly_score for r in records]
        assert len(scores) == 60
        assert len(set(scores)) > 10, "Expected a varied distribution of continuous anomaly scores."

    def test_anomaly_records_conform_to_schema(self):
        samples = make_dummy_samples(n=25)
        det = IsolationForestAnomalyDetector(baseline_frac=0.4, min_baseline_windows=10)
        records, summary = det.fit_and_score(samples)

        for r in records:
            assert isinstance(r, AnomalyRecord)
            assert isinstance(r.timestamp, datetime)
            assert isinstance(r.anomaly_score, float)
            assert isinstance(r.is_anomaly, bool)
            assert r.detector == "isolation_forest"
            assert r.provenance == Provenance.SYNTHETIC
            assert isinstance(r.record_id, str)
            assert len(r.record_id) > 0


# ===========================================================================
# 5. Invalid and insufficient inputs
# ===========================================================================

class TestInvalidInputs:
    def test_empty_samples_fit_raises(self):
        det = IsolationForestAnomalyDetector()
        with pytest.raises(ValueError, match="empty sample list"):
            det.fit([])

    def test_insufficient_baseline_samples_raises(self):
        samples = make_dummy_samples(n=10)
        det = IsolationForestAnomalyDetector(baseline_frac=0.2, min_baseline_windows=10)
        # 10 * 0.2 = 2 windows < 10 min_baseline_windows
        with pytest.raises(ValueError, match="Insufficient baseline windows"):
            det.fit(samples)

    def test_unfitted_detector_predict_raises(self):
        det = IsolationForestAnomalyDetector()
        samples = make_dummy_samples(n=5)
        with pytest.raises(RuntimeError, match="must be fitted"):
            det.predict_score(samples)

    def test_all_constant_features_raises(self):
        samples = make_dummy_samples(n=20)
        for s in samples:
            s.features = {"mod": {"const_ch": 1.0}}
        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=5)
        with pytest.raises(ValueError, match="No valid features remain"):
            det.fit(samples)


# ===========================================================================
# 6. Provenance enforcement (FR-DA-2)
# ===========================================================================

class TestProvenanceEnforcement:
    def test_mixed_provenance_raises(self):
        samples = make_dummy_samples(n=20)
        # Change one sample to PUBLIC_DATASET
        samples[10].provenance = Provenance.PUBLIC_DATASET

        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=5)
        with pytest.raises(ValueError, match="Mixed provenance detected"):
            det.fit(samples)

    def test_score_mismatched_provenance_raises(self):
        samples_synth = make_dummy_samples(n=20, provenance=Provenance.SYNTHETIC)
        det = IsolationForestAnomalyDetector(baseline_frac=0.5, min_baseline_windows=5)
        det.fit(samples_synth)

        samples_pub = make_dummy_samples(n=10, provenance=Provenance.PUBLIC_DATASET)
        with pytest.raises(ValueError, match="Provenance mismatch"):
            det.predict_score(samples_pub)



# ===========================================================================
# 7. Reproducibility
# ===========================================================================

class TestReproducibility:
    def test_fixed_seed_is_reproducible(self):
        samples = make_dummy_samples(n=40)
        det1 = IsolationForestAnomalyDetector(random_state=42, min_baseline_windows=5)
        records1 = det1.fit_and_score(samples)[0]

        det2 = IsolationForestAnomalyDetector(random_state=42, min_baseline_windows=5)
        records2 = det2.fit_and_score(samples)[0]

        scores1 = [r.anomaly_score for r in records1]
        scores2 = [r.anomaly_score for r in records2]
        np.testing.assert_array_equal(scores1, scores2)

    def test_different_seeds_produce_different_scores(self):
        samples = make_dummy_samples(n=40)
        det1 = IsolationForestAnomalyDetector(random_state=42, min_baseline_windows=5)
        records1 = det1.fit_and_score(samples)[0]

        det2 = IsolationForestAnomalyDetector(random_state=999, min_baseline_windows=5)
        records2 = det2.fit_and_score(samples)[0]

        scores1 = [r.anomaly_score for r in records1]
        scores2 = [r.anomaly_score for r in records2]
        assert not np.array_equal(scores1, scores2)


# ===========================================================================
# 8. Deterministic CUSUM comparison baseline
# ===========================================================================

class TestCUSUMComparison:
    def test_cusum_comparison_runs_and_returns_records(self):
        samples = make_dummy_samples(n=50)
        cfg = CUSUMConfig(k=0.2, h=2.0)
        records, summary = run_cusum_comparison(samples, baseline_frac=0.3, cusum_config=cfg)

        assert len(records) == 50
        assert summary["detector"] == "cusum_health"
        assert summary["n_baseline_windows"] == 15
        for r in records:
            assert isinstance(r, AnomalyRecord)
            assert r.detector == "cusum_health"
            assert r.anomaly_score >= 0.0  # S_t statistic is non-negative
            assert isinstance(r.is_anomaly, bool)


# ===========================================================================
# 9. Daily aggregation
# ===========================================================================

class TestDailyAggregation:
    def test_summarize_by_day(self):
        samples = make_dummy_samples(n=50, step_minutes=60)  # across multiple days
        det = IsolationForestAnomalyDetector(min_baseline_windows=5)
        records, _ = det.fit_and_score(samples)

        daily_df = summarize_anomalies_by_day(records)
        assert len(daily_df) > 1
        assert "window_count" in daily_df.columns
        assert "anomaly_count" in daily_df.columns
        assert "anomaly_rate" in daily_df.columns
        assert daily_df["window_count"].sum() == 50
