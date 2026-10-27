"""
TCMIM — Real-Data Integration Test: SWaT Telemetry Ingestion and Stage 1 Pipeline.

SCIENTIFIC CONTRACT AND DATASET-GATED EXECUTION
-----------------------------------------------
1. Real Data Only: This test is designed to run on the real SWaT (Secure Water
   Treatment) dataset from iTrust (SUTD).
2. Pending Academic Approval Gate: If the dataset file is absent, this test is
   automatically skipped with an explicit explanation. It NEVER fabricates,
   downloads without authorization, or substitutes synthetic data as real.
3. Provenance: Real-data records strictly carry Provenance.PUBLIC_DATASET.
4. Logical Entities: Stages P1-P6 are treated as logical process stages,
   not six independent physical machines.
5. Ground-Truth Isolation: Labels are strictly segregated and used only for
   post-prediction evaluation metrics.

Execution:
  Set TCMIM_SWAT_DATA_PATH to the SWaT CSV path or place the CSV in data/raw/:
  $env:TCMIM_SWAT_DATA_PATH = "C:\\path\\to\\SWaT_Dataset_Attack_v0.csv"
  pytest tests/integration/test_swat_pipeline.py -v
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

from tcmim.data.swat import (
    LABEL_COLUMN_CANDIDATES,
    SWAT_TAG_REGISTRY,
    SWAT_MODALITY_MAP,
    SWaTProcessStage,
    align_swat_labels_to_windows,
    analyze_sampling_continuity,
    evaluate_swat_window_predictions,
    infer_sampling_frequency,
    load_swat_dataframe,
    partition_swat_by_stage,
    verify_no_ground_truth_leakage,
)
from tcmim.data.windower import WindowBuilder
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import IsolationForestAnomalyDetector
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance

# ---------------------------------------------------------------------------
# Dataset Discovery and Gating
# ---------------------------------------------------------------------------

_ENV_SWAT_PATH = os.environ.get("TCMIM_SWAT_DATA_PATH")
_CANDIDATES = [
    Path(_ENV_SWAT_PATH) if _ENV_SWAT_PATH else None,
    Path(__file__).parent.parent.parent / "SWaT_Dataset_Attack_v0.csv",
    Path(__file__).parent.parent.parent / "SWaT_Dataset_Normal_v1.csv",
    Path("data/raw/SWaT_Dataset_Attack_v0.csv"),
    Path("data/raw/SWaT_Dataset_Normal_v1.csv"),
    Path("data/raw/SWaT.csv"),
    Path("SWaT_Dataset_Attack_v0.csv"),
    Path("../SWaT_Dataset_Attack_v0.csv"),
]

SWAT_CSV: Optional[Path] = next((p for p in _CANDIDATES if p is not None and p.exists()), None)

skip_if_no_swat = pytest.mark.skipif(
    SWAT_CSV is None,
    reason=(
        "SWaT dataset CSV not found (checked TCMIM_SWAT_DATA_PATH and standard paths) — "
        "skipping real-data integration test pending academic access approval. "
        "To run once approved, set TCMIM_SWAT_DATA_PATH to the SWaT CSV path."
    ),
)

# Configurable row limit for smoke testing real data without out-of-memory
MAX_SMOKE_ROWS = int(os.environ.get("TCMIM_SWAT_SMOKE_ROWS", "5000"))


@skip_if_no_swat
class TestSWaTRealDataIntegration:
    """Dataset-gated integration test on real SWaT industrial telemetry."""

    @pytest.fixture(scope="class")
    def swat_raw_data(self):
        """Load real SWaT smoke test slice and enforce ground-truth isolation."""
        assert SWAT_CSV is not None and SWAT_CSV.exists()
        features_df, labels = load_swat_dataframe(
            SWAT_CSV,
            max_rows=MAX_SMOKE_ROWS,
            sort_timestamps=True,
        )
        return {"features_df": features_df, "labels": labels}

    def test_real_swat_ingestion_and_timestamp_integrity(self, swat_raw_data):
        """Verify real SWaT loads with monotonic UTC DatetimeIndex and numeric columns."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        assert len(df) > 0, "Real SWaT DataFrame must not be empty."
        assert isinstance(df.index, pd.DatetimeIndex), "Index must be a DatetimeIndex."
        assert df.index.tz is not None, "Index must be UTC timezone-aware."
        assert df.index.is_monotonic_increasing, "Index must be monotonically increasing."

        # Verify all feature columns are numeric
        for col in df.columns:
            assert pd.api.types.is_numeric_dtype(df[col]), (
                f"Column '{col}' must be numeric in feature DataFrame."
            )

    def test_real_swat_continuity_and_sampling_frequency(self, swat_raw_data):
        """Analyze real SWaT timestamp continuity and verify nominal ~1 Hz sampling rate."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        report = analyze_sampling_continuity(df.index)

        assert report.total_timestamps == len(df)
        assert report.median_interval_s > 0, "Median interval must be positive."
        # SWaT is nominal 1.0s (1.0 Hz)
        assert np.isclose(report.median_interval_s, 1.0, atol=0.2), (
            f"Expected SWaT nominal ~1.0s interval, got {report.median_interval_s:.3f}s."
        )

    def test_real_swat_tag_coverage_and_unmapped_reporting(self, swat_raw_data):
        """Verify instrument tag coverage and report any unmapped columns."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        known_tags = set(SWAT_TAG_REGISTRY.keys())
        found_tags = set(df.columns)

        matched_tags = found_tags.intersection(known_tags)
        unmapped = found_tags - known_tags

        assert len(matched_tags) > 0, "Must match at least one verified SWaT instrument tag."
        if unmapped:
            pytest.fail(
                f"Unexpected unmapped columns detected in real SWaT dataset: {unmapped}. "
                "All telemetry channels must be audited."
            )

    def test_real_swat_ground_truth_isolation(self, swat_raw_data):
        """Strict ground-truth isolation: label columns must never be among features."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        labels: Optional[pd.Series] = swat_raw_data["labels"]

        # 1. Labels must be isolated
        assert labels is not None, "Real SWaT dataset should contain a ground-truth label column."
        assert len(labels) == len(df), "Labels length must match features length."

        # 2. No candidate label column in features
        for cand in LABEL_COLUMN_CANDIDATES:
            assert cand not in [c.lower() for c in df.columns]

        # 3. Audit helper verification
        assert verify_no_ground_truth_leakage(df=df)

    def test_real_swat_stage_partitioning(self, swat_raw_data):
        """Verify partitioning into verified logical process stages (P1 to P6)."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        stage_dfs = partition_swat_by_stage(df)

        assert len(stage_dfs) > 0, "Must partition into at least one stage."
        for stage_name, s_df in stage_dfs.items():
            assert len(s_df.columns) > 0
            assert s_df.index.equals(df.index)

    def test_real_swat_stage1_anomaly_detection_pipeline(self, swat_raw_data):
        """End-to-end Stage 1 on real SWaT: windowing, feature extraction, IsolationForest."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        stage_dfs = partition_swat_by_stage(df)

        # Select first available stage (e.g. P1_raw_water)
        stage_name = list(stage_dfs.keys())[0]
        stage_df = stage_dfs[stage_name]

        # 1. Windowing (60s non-overlapping windows)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(stage_df, machine_id=stage_name, provenance=Provenance.PUBLIC_DATASET)
        assert len(windows) > 2, "Must build multiple chronological windows."

        # 2. Feature Extraction
        extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
        samples = extractor.extract_all(windows)
        assert len(samples) == len(windows)
        assert verify_no_ground_truth_leakage(samples=samples)

        for s in samples:
            assert s.provenance == Provenance.PUBLIC_DATASET
            assert s.machine_id == stage_name

        # 3. Isolation Forest Anomaly Detection
        detector = IsolationForestAnomalyDetector(
            baseline_frac=0.3,
            contamination=0.05,
            random_state=42,
            min_baseline_windows=2,
        )
        records, summary = detector.fit_and_score(samples)
        assert len(records) == len(samples)
        assert verify_no_ground_truth_leakage(detector=detector)

        for r in records:
            assert isinstance(r, AnomalyRecord)
            assert r.provenance == Provenance.PUBLIC_DATASET
            assert r.machine_id == stage_name
            assert np.isfinite(r.anomaly_score)

        # 4. Anomaly-to-Event Adaptation
        adapter = AnomalyToEventAdapter(
            EventAdapterConfig(min_burst_windows=1, max_gap_s=120.0, score_aggregation="peak")
        )
        events = adapter.adapt(records, machine_id=stage_name)
        for ev in events:
            assert isinstance(ev, EventRecord)
            assert ev.provenance == Provenance.PUBLIC_DATASET
            assert ev.machine_id == stage_name
            assert ev.window_count >= 1

    def test_real_swat_post_prediction_evaluation(self, swat_raw_data):
        """Verify post-prediction evaluation against isolated real labels."""
        df: pd.DataFrame = swat_raw_data["features_df"]
        labels: Optional[pd.Series] = swat_raw_data["labels"]
        assert labels is not None

        stage_name = list(partition_swat_by_stage(df).keys())[0]
        stage_df = partition_swat_by_stage(df)[stage_name]

        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(stage_df, machine_id=stage_name, provenance=Provenance.PUBLIC_DATASET)

        extractor = FeatureExtractor(sampling_rate_hz=1.0, channel_modality_map=SWAT_MODALITY_MAP)
        samples = extractor.extract_all(windows)

        detector = IsolationForestAnomalyDetector(
            baseline_frac=0.3, contamination=0.05, random_state=42, min_baseline_windows=2
        )
        records, _ = detector.fit_and_score(samples)

        # Align ground truth strictly post-prediction
        aligned_gt = align_swat_labels_to_windows(labels, windows, method="any")
        eval_metrics = evaluate_swat_window_predictions(aligned_gt, records)

        assert "tp" in eval_metrics
        assert "fp" in eval_metrics
        assert "precision" in eval_metrics
        assert "recall" in eval_metrics
        assert "f1" in eval_metrics
        assert eval_metrics["total_windows"] == len(records)
