"""
TCMIM — Unit tests for SWaT Integration Readiness and Contract Verification.

SCIENTIFIC INTEGRITY & TEST DESIGN
----------------------------------
1. Synthetic Fixtures: All unit tests here operate on explicitly constructed
   synthetic test fixtures carrying Provenance.SYNTHETIC.
2. Ground-Truth Isolation: Validates that ground-truth labels are strictly
   excluded from model features, windowing, feature extraction, detector fitting,
   and event conversion.
3. Multi-Stage Logical Identity: Validates that P1-P6 process stages map to
   logical machine entities without asserting physical causality.
4. Modality Dispatch: Verifies that actuators (DIGITAL_STATE), pressure sensors
   (PRESSURE), and general sensors (UNKNOWN) produce their respective expected
   features without NaN or silent fallback failures.
5. Post-Prediction Evaluation: Verifies that label-based evaluation functions
   only evaluate predictions post-hoc and handle undefined metrics gracefully.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from tcmim.data.swat import (
    LABEL_COLUMN_CANDIDATES,
    SWAT_ACTUATOR_STATE_MAP,
    SWAT_MODALITY_MAP,
    SWaTProcessStage,
    align_swat_labels_to_windows,
    binarize_swat_labels,
    evaluate_swat_window_predictions,
    get_swat_actuator_state_mapping,
    load_swat_dataframe,
    normalize_swat_actuator_signal,
    partition_swat_by_stage,
    verify_no_ground_truth_leakage,
)
from tcmim.data.windower import WindowBuilder, WindowedData
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import IsolationForestAnomalyDetector
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance


# ---------------------------------------------------------------------------
# Synthetic Test Fixtures (Explicitly SYNTHETIC Provenance)
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_multistage_csv(tmp_path: Path) -> Path:
    """Create a synthetic 120-second SWaT CSV covering stages P1, P2, and P3."""
    csv_file = tmp_path / "synthetic_swat_multistage.csv"
    base_time = datetime(2015, 12, 22, 16, 0, 0, tzinfo=timezone.utc)
    n_rows = 120

    records = []
    for i in range(n_rows):
        ts = base_time + timedelta(seconds=i)
        ts_str = ts.strftime("%d/%m/%Y %I:%M:%S %p")
        # Injected attack between second 60 and 90
        label = "Attack" if 60 <= i < 90 else "Normal"

        records.append({
            "Timestamp": ts_str,
            # Stage 1: P1
            "FIT101": 2.5 + 0.1 * np.sin(i / 10.0),
            "LIT101": 500.0 + (i * 0.5),
            "MV101": 1.0 if i < 60 else 0.0,
            "P101": 1.0,
            # Stage 2: P2
            "AIT201": 250.0 + 5.0 * np.cos(i / 10.0),
            "FIT201": 2.4 + 0.05 * np.sin(i / 5.0),
            "P201": 1.0 if i % 20 < 10 else 0.0,
            # Stage 3: P3
            "DPIT301": 19.5 + 0.2 * np.random.RandomState(i).randn(),
            "FIT301": 2.3 + 0.02 * np.cos(i / 8.0),
            "MV301": 1.0,
            # Ground truth label
            "Normal/Attack": label,
        })

    pd.DataFrame(records).to_csv(csv_file, index=False)
    return csv_file


# ---------------------------------------------------------------------------
# Test Suite: Ground-Truth Isolation Contract
# ---------------------------------------------------------------------------

class TestGroundTruthIsolationContract:
    """Verify strict ground-truth isolation across all pipeline boundaries."""

    def test_labels_excluded_from_dataframe_and_leakage_verifier(
        self, synthetic_multistage_csv: Path
    ):
        """Feature DataFrame must not contain any label candidates."""
        features_df, labels = load_swat_dataframe(synthetic_multistage_csv)
        assert labels is not None
        assert len(labels) == len(features_df)

        for cand in LABEL_COLUMN_CANDIDATES:
            assert cand not in [c.lower() for c in features_df.columns]

        # Audit helper must pass
        assert verify_no_ground_truth_leakage(df=features_df)

    def test_leakage_verifier_raises_on_injected_label_column(self):
        """verify_no_ground_truth_leakage must raise ValueError if label column present."""
        df = pd.DataFrame({
            "FIT101": [1.0, 2.0],
            "Normal/Attack": ["Normal", "Attack"],
        })
        with pytest.raises(ValueError, match="Ground-truth leakage detected in DataFrame columns"):
            verify_no_ground_truth_leakage(df=df)

    def test_windows_and_features_contain_zero_ground_truth_labels(
        self, synthetic_multistage_csv: Path
    ):
        """WindowedData and MultimodalFeatureSample must never receive labels."""
        features_df, _ = load_swat_dataframe(synthetic_multistage_csv)
        stage_dfs = partition_swat_by_stage(features_df)
        p1_df = stage_dfs["P1_raw_water"]

        wb = WindowBuilder(window_seconds=30.0, overlap_frac=0.0)
        windows = wb.build(p1_df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)
        assert len(windows) > 0

        for w in windows:
            assert verify_no_ground_truth_leakage(df=w.data)

        extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
        samples = extractor.extract_all(windows)
        assert len(samples) == len(windows)

        # Audit samples
        assert verify_no_ground_truth_leakage(samples=samples)

    def test_detector_feature_names_contain_zero_labels(
        self, synthetic_multistage_csv: Path
    ):
        """Fitted IsolationForest must never contain label names among selected features."""
        features_df, _ = load_swat_dataframe(synthetic_multistage_csv)
        p1_df = partition_swat_by_stage(features_df)["P1_raw_water"]

        wb = WindowBuilder(window_seconds=20.0, overlap_frac=0.0)
        windows = wb.build(p1_df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)
        extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
        samples = extractor.extract_all(windows)

        detector = IsolationForestAnomalyDetector(
            baseline_frac=0.5,
            min_baseline_windows=2,
            random_state=42,
        )
        detector.fit(samples)

        assert verify_no_ground_truth_leakage(detector=detector)
        for cand in LABEL_COLUMN_CANDIDATES:
            for feat in detector.feature_names_:
                assert cand not in feat.lower()

    @pytest.mark.parametrize("suspicious_col", [
        "is_attack",
        "isattack",
        "is attack",
        "target",
        "ground_truth",
        "ground truth",
        "anomaly",
        "fault",
    ])
    def test_leakage_verifier_detects_numeric_binary_targets_under_suspicious_names(
        self, suspicious_col: str
    ):
        """Numeric binary targets ([0, 1]) must not evade detection by passing as numbers."""
        df = pd.DataFrame({
            "FIT101": [2.5, 2.6],
            suspicious_col: [0, 1],  # Pure numeric integers
        })
        with pytest.raises(ValueError, match="Ground-truth leakage detected in DataFrame columns"):
            verify_no_ground_truth_leakage(df=df)

    def test_loader_isolates_numeric_binary_targets_without_leaking_to_features(
        self, tmp_path: Path
    ):
        """Verify load_swat_dataframe isolates numeric binary targets (e.g. is_attack) from features."""
        csv_path = tmp_path / "numeric_target_test.csv"
        df_raw = pd.DataFrame({
            "Timestamp": ["22/12/2015 4:00:00 PM", "22/12/2015 4:00:01 PM"],
            "FIT101": [2.5, 2.6],
            "is_attack": [0, 1],  # Numeric integer labels
        })
        df_raw.to_csv(csv_path, index=False)

        features_df, labels = load_swat_dataframe(csv_path)
        assert labels is not None
        assert list(labels) == ["0", "1"] or list(labels) == [0, 1]
        assert "is_attack" not in features_df.columns
        assert verify_no_ground_truth_leakage(df=features_df)

    def test_verify_no_ground_truth_leakage_validates_records(self):
        """Audit of AnomalyRecords verifies detector and machine_id do not leak labels."""
        now = datetime(2015, 12, 22, 16, 0, 0, tzinfo=timezone.utc)
        clean_rec = AnomalyRecord(
            timestamp=now,
            machine_id="P1_raw_water",
            anomaly_score=-0.1,
            is_anomaly=True,
            detector="isolation_forest",
            provenance=Provenance.SYNTHETIC,
        )
        assert verify_no_ground_truth_leakage(records=[clean_rec]) is True

        # Injected oracle detector name
        leaked_det_rec = AnomalyRecord(
            timestamp=now,
            machine_id="P1_raw_water",
            anomaly_score=-0.1,
            is_anomaly=True,
            detector="attack_oracle_detector",
            provenance=Provenance.SYNTHETIC,
        )
        with pytest.raises(ValueError, match="Ground-truth leakage detected in AnomalyRecord.detector"):
            verify_no_ground_truth_leakage(records=[leaked_det_rec])

        # Injected machine_id
        leaked_mid_rec = AnomalyRecord(
            timestamp=now,
            machine_id="stage_target_groundtruth",
            anomaly_score=-0.1,
            is_anomaly=True,
            detector="isolation_forest",
            provenance=Provenance.SYNTHETIC,
        )
        with pytest.raises(ValueError, match="Ground-truth leakage detected in AnomalyRecord.machine_id"):
            verify_no_ground_truth_leakage(records=[leaked_mid_rec])


# ---------------------------------------------------------------------------
# Test Suite: Multi-Stage Integration and Modality Handling
# ---------------------------------------------------------------------------

class TestSWaTMultiStageIntegration:
    """Validate end-to-end integration across P1-P6 logical stages."""

    def test_partitioning_into_verified_logical_stages(
        self, synthetic_multistage_csv: Path
    ):
        """Partitioning separates stages into distinct DataFrames without column conflation."""
        features_df, _ = load_swat_dataframe(synthetic_multistage_csv)
        stage_dfs = partition_swat_by_stage(features_df)

        assert "P1_raw_water" in stage_dfs
        assert "P2_chemical_dosing" in stage_dfs
        assert "P3_ultrafiltration" in stage_dfs

        assert set(stage_dfs["P1_raw_water"].columns) == {"FIT101", "LIT101", "MV101", "P101"}
        assert set(stage_dfs["P2_chemical_dosing"].columns) == {"AIT201", "FIT201", "P201"}
        assert set(stage_dfs["P3_ultrafiltration"].columns) == {"DPIT301", "FIT301", "MV301"}

    def test_modality_dispatch_in_feature_extractor(
        self, synthetic_multistage_csv: Path
    ):
        """Verify that UNKNOWN, DIGITAL_STATE, and PRESSURE modalities extract proper features."""
        features_df, _ = load_swat_dataframe(synthetic_multistage_csv)
        stage_dfs = partition_swat_by_stage(features_df)
        p3_df = stage_dfs["P3_ultrafiltration"]  # has DPIT301 (PRESSURE), FIT301 (UNKNOWN), MV301 (DIGITAL_STATE)

        wb = WindowBuilder(window_seconds=30.0, overlap_frac=0.0)
        windows = wb.build(p3_df, machine_id="P3_ultrafiltration", provenance=Provenance.SYNTHETIC)
        extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
        samples = extractor.extract_all(windows)
        assert len(samples) > 0

        first_sample = samples[0]
        feats = first_sample.features

        # 1. Modality.PRESSURE (DPIT301)
        assert Modality.PRESSURE.value in feats
        dpit_feats = feats[Modality.PRESSURE.value]
        assert "DPIT301__mean" in dpit_feats
        assert "DPIT301__std" in dpit_feats
        assert "DPIT301__skewness" in dpit_feats
        assert np.isfinite(dpit_feats["DPIT301__mean"])

        # 2. Modality.UNKNOWN (FIT301)
        assert Modality.UNKNOWN.value in feats
        fit_feats = feats[Modality.UNKNOWN.value]
        assert "FIT301__mean" in fit_feats
        assert "FIT301__std" in fit_feats
        assert np.isfinite(fit_feats["FIT301__mean"])
        assert np.isfinite(fit_feats["FIT301__std"])

        # 3. Modality.DIGITAL_STATE (MV301)
        assert Modality.DIGITAL_STATE.value in feats
        mv_feats = feats[Modality.DIGITAL_STATE.value]
        assert "MV301__duty_cycle" in mv_feats
        assert "MV301__n_transitions" in mv_feats
        assert "MV301__mode_state" in mv_feats

    def test_stage_pipeline_to_event_adapter(
        self, synthetic_multistage_csv: Path
    ):
        """Full pipeline: Stage DF -> Windows -> Features -> Detector -> Events."""
        features_df, _ = load_swat_dataframe(synthetic_multistage_csv)
        stage_dfs = partition_swat_by_stage(features_df)

        events_by_stage: Dict[str, List[EventRecord]] = {}

        for stage_name, stage_df in stage_dfs.items():
            wb = WindowBuilder(window_seconds=20.0, overlap_frac=0.0)
            windows = wb.build(stage_df, machine_id=stage_name, provenance=Provenance.SYNTHETIC)
            extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
            samples = extractor.extract_all(windows)

            detector = IsolationForestAnomalyDetector(
                baseline_frac=0.5,
                min_baseline_windows=2,
                contamination=0.1,
                random_state=42,
            )
            records, _ = detector.fit_and_score(samples)

            adapter = AnomalyToEventAdapter(
                EventAdapterConfig(
                    min_burst_windows=1,
                    max_gap_s=30.0,
                    score_aggregation="peak",
                )
            )
            events = adapter.adapt(records, machine_id=stage_name)
            events_by_stage[stage_name] = events

            # Verify integrity on each event
            for ev in events:
                assert ev.machine_id == stage_name
                assert ev.provenance == Provenance.SYNTHETIC
                assert ev.window_count >= 1
                assert np.isfinite(ev.score)
                assert ev.detector == "isolation_forest"

        assert len(events_by_stage) == 3

    def test_swat_actuator_state_mapping_applied_in_feature_extractor(self):
        """Verify SWAT_ACTUATOR_STATE_MAP correctly maps {1: 0, 2: 1} in FeatureExtractor."""
        # 10 samples of MV101 alternating between 1.0 (Closed/Off) and 2.0 (Open/On)
        # [1, 1, 2, 2, 1, 2, 1, 2, 1, 1]
        raw_vals = [1.0, 1.0, 2.0, 2.0, 1.0, 2.0, 1.0, 2.0, 1.0, 1.0]
        ts_index = pd.date_range("2015-12-22 16:00:00", periods=10, freq="1s", tz="UTC")
        df = pd.DataFrame({"MV101": raw_vals}, index=ts_index)

        wb = WindowBuilder(window_seconds=10.0, overlap_frac=0.0)
        windows = wb.build(df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)
        assert len(windows) == 1

        extractor = FeatureExtractor(
            sampling_rate_hz=1.0,
            channel_modality_map={"MV101": Modality.DIGITAL_STATE},
            channel_state_map=SWAT_ACTUATOR_STATE_MAP,
        )
        samples = extractor.extract_all(windows)
        feats = samples[0].features[Modality.DIGITAL_STATE.value]

        # 6 transitions: (1->1, 1->2, 2->2, 2->1, 1->2, 2->1, 1->2, 2->1, 1->1) -> 6 transitions
        assert feats["MV101__n_transitions"] == pytest.approx(6.0)
        # 4 ON states (2.0) out of 10 total -> duty_cycle = 4/10 = 0.4
        assert feats["MV101__duty_cycle"] == pytest.approx(0.4)
        assert feats["MV101__mode_state"] == pytest.approx(0.0)
        assert feats["MV101__first_state"] == pytest.approx(1.0)
        assert feats["MV101__last_state"] == pytest.approx(1.0)

    def test_normalize_swat_actuator_signal_helper(self):
        """Test normalize_swat_actuator_signal helper and policy for state 0/unmapped."""
        orig = np.array([1.0, 2.0, 0.0, 3.0, 2.0])
        orig_copy = orig.copy()

        norm = normalize_swat_actuator_signal(orig, tag="MV101")
        # 1 -> 0.0 (Closed/Off), 2 -> 1.0 (Open/On), 0 -> np.nan, 3 -> np.nan
        assert norm[0] == 0.0
        assert norm[1] == 1.0
        assert np.isnan(norm[2])
        assert np.isnan(norm[3])
        assert norm[4] == 1.0

        # Input array must be preserved unmodified
        np.testing.assert_array_equal(orig, orig_copy)


# ---------------------------------------------------------------------------
# Test Suite: Post-Prediction Evaluation and Metrics
# ---------------------------------------------------------------------------

class TestPostPredictionEvaluation:
    """Validate window label alignment and evaluation metrics."""

    def test_align_swat_labels_to_windows_any(
        self, synthetic_multistage_csv: Path
    ):
        """Test 'any' alignment: window is 1 if any attack timestamp in interval."""
        features_df, labels = load_swat_dataframe(synthetic_multistage_csv)
        p1_df = partition_swat_by_stage(features_df)["P1_raw_water"]

        # 120s total, 30s non-overlapping windows -> 4 windows:
        # Window 0: [0, 30s) -> Normal -> 0.0
        # Window 1: [30, 60s) -> Normal -> 0.0
        # Window 2: [60, 90s) -> Attack -> 1.0
        # Window 3: [90, 120s) -> Normal -> 0.0
        wb = WindowBuilder(window_seconds=30.0, overlap_frac=0.0)
        windows = wb.build(p1_df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)
        assert len(windows) == 4

        aligned_gt = align_swat_labels_to_windows(labels, windows, method="any")
        assert len(aligned_gt) == 4
        assert aligned_gt[0] == 0.0
        assert aligned_gt[1] == 0.0
        assert aligned_gt[2] == 1.0
        assert aligned_gt[3] == 0.0

    def test_align_swat_labels_to_windows_majority(
        self, synthetic_multistage_csv: Path
    ):
        """Test 'majority' alignment: window is 1 only if >50% attack timestamps."""
        features_df, labels = load_swat_dataframe(synthetic_multistage_csv)
        p1_df = partition_swat_by_stage(features_df)["P1_raw_water"]

        wb = WindowBuilder(window_seconds=30.0, overlap_frac=0.0)
        windows = wb.build(p1_df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)

        aligned_gt = align_swat_labels_to_windows(labels, windows, method="majority")
        assert aligned_gt[2] == 1.0
        assert aligned_gt[0] == 0.0

    def test_evaluate_swat_window_predictions_metrics(self):
        """Test confusion matrix, precision, recall, F1, and FPR."""
        # 4 windows: GT = [0, 0, 1, 0]
        y_true = np.array([0.0, 0.0, 1.0, 0.0])
        # Prediction: flags window 1 (FP) and window 2 (TP) -> [0, 1, 1, 0]
        preds = [False, True, True, False]

        eval_res = evaluate_swat_window_predictions(y_true, preds)
        assert eval_res["tp"] == 1
        assert eval_res["fp"] == 1
        assert eval_res["tn"] == 2
        assert eval_res["fn"] == 0
        assert eval_res["precision"] == 0.5   # 1 / (1 + 1)
        assert eval_res["recall"] == 1.0      # 1 / (1 + 0)
        assert np.isclose(eval_res["f1"], 2.0 * (0.5 * 1.0) / (0.5 + 1.0))
        assert np.isclose(eval_res["fpr"], 1.0 / 3.0)  # FP / (FP + TN)

    def test_evaluate_swat_predictions_undefined_metric_handling(self):
        """Handle zero true positives and zero alarms without division by zero crash."""
        y_true = np.array([0.0, 0.0, 0.0])
        preds = [False, False, False]

        eval_res = evaluate_swat_window_predictions(y_true, preds)
        assert eval_res["tp"] == 0
        assert eval_res["fp"] == 0
        assert eval_res["tn"] == 3
        assert eval_res["fn"] == 0
        assert np.isnan(eval_res["precision"])
        assert np.isnan(eval_res["recall"])
        assert np.isnan(eval_res["f1"])
        assert eval_res["fpr"] == 0.0
