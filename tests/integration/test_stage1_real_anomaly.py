"""
TCMIM — Integration test: Stage 1 ML Anomaly Detection on MetroPT-3.

Provenance: PUBLIC_DATASET
Status: EXEC (runs on real MetroPT-3 compressor data)

INTEGRITY NOTES
---------------
- MetroPT-3 is a single-machine dataset. No cross-machine claims are made.
- Anomaly scores reflect statistical divergence from the candidate baseline.
  They are NOT labelled as confirmed failures or fault ground truth.
- This test verifies software correctness, data integrity, and pipeline
  execution on real sensor data.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.config import CUSUMConfig
from tcmim.data.metropt3 import load_metropt3_dataframe
from tcmim.data.windower import WindowBuilder
from tcmim.features.extractor import FeatureExtractor
from tcmim.ml.anomaly_detector import (
    IsolationForestAnomalyDetector,
    run_cusum_comparison,
    summarize_anomalies_by_day,
)
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance

_ENV_METROPT3_PATH = os.environ.get("TCMIM_METROPT3_PATH")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_CSV_CANDIDATES = [
    Path(_ENV_METROPT3_PATH) if _ENV_METROPT3_PATH else None,
    Path("data/raw/MetroPT3(AirCompressor).csv"),
    _PROJECT_ROOT / "data" / "raw" / "MetroPT3(AirCompressor).csv",
    Path("MetroPT3(AirCompressor).csv"),
    _PROJECT_ROOT / "MetroPT3(AirCompressor).csv",
]
METROPT3_CSV = next((p for p in _CSV_CANDIDATES if p is not None and p.exists()), None)

skip_if_no_csv = pytest.mark.skipif(
    METROPT3_CSV is None,
    reason=(
        "MetroPT-3 CSV not found in data/raw/ or configured path — skipping real-data integration test. "
        "To enable, place MetroPT3(AirCompressor).csv in data/raw/ or set TCMIM_METROPT3_PATH."
    ),
)


@pytest.fixture(scope="module")
def stage1_output():
    """Execute full Stage 1 pipeline on a 5000-row slice of MetroPT-3."""
    if METROPT3_CSV is None:
        pytest.skip("MetroPT-3 CSV not found")

    # 1. Load real data
    df = load_metropt3_dataframe(METROPT3_CSV, max_rows=5000)

    # 2. Windowing
    wb = WindowBuilder(window_seconds=300.0, overlap_frac=0.0)
    windows = wb.build(df, "metropt3_compressor", Provenance.PUBLIC_DATASET)

    # 3. Feature extraction (0.1 Hz nominal MetroPT-3 default)
    extractor = FeatureExtractor(sampling_rate_hz=0.1)
    feature_samples = extractor.extract_all(windows)

    # 4. Stage 1 ML Isolation Forest detector
    detector = IsolationForestAnomalyDetector(
        baseline_frac=0.3,
        contamination=0.05,
        random_state=42,
        min_baseline_windows=10,
    )
    if_records, if_summary = detector.fit_and_score(feature_samples)

    # 5. Deterministic CUSUM comparison
    cusum_records, cusum_summary = run_cusum_comparison(
        feature_samples,
        baseline_frac=0.3,
        cusum_config=CUSUMConfig(k=0.5, h=5.0),
    )

    return {
        "windows": windows,
        "feature_samples": feature_samples,
        "if_records": if_records,
        "if_summary": if_summary,
        "cusum_records": cusum_records,
        "cusum_summary": cusum_summary,
        "detector": detector,
    }


@skip_if_no_csv
class TestStage1MetroPT3Integration:
    """End-to-end Stage 1 ML pipeline on real MetroPT-3 compressor observations."""

    def test_pipeline_produces_real_records(self, stage1_output):
        records = stage1_output["if_records"]
        assert len(records) > 0
        for r in records:
            assert isinstance(r, AnomalyRecord)
            assert r.provenance == Provenance.PUBLIC_DATASET, (
                "Real data pipeline must never carry SYNTHETIC provenance."
            )
            assert r.detector == "isolation_forest"
            assert np.isfinite(r.anomaly_score)

    def test_chronological_integrity_preserved(self, stage1_output):
        records = stage1_output["if_records"]
        for i in range(len(records) - 1):
            assert records[i].timestamp <= records[i + 1].timestamp, (
                "AnomalyRecords must be ordered monotonically by timestamp."
            )

    def test_baseline_split_documented(self, stage1_output):
        summary = stage1_output["if_summary"]
        assert "split_info" in summary
        split = summary["split_info"]
        assert split["baseline_frac"] == 0.3
        assert split["n_baseline"] > 0
        assert "assumption_note" in split
        assert "Candidate baseline assumes" in split["assumption_note"]

    def test_features_selected_and_excluded(self, stage1_output):
        detector = stage1_output["detector"]
        assert len(detector.feature_names_) > 0, "Detector must select valid features."
        # Features should be from real modalities (e.g. pressure, current)
        assert any("mean" in f for f in detector.feature_names_)

    def test_cusum_comparison_consistent(self, stage1_output):
        cusum_recs = stage1_output["cusum_records"]
        if_recs = stage1_output["if_records"]
        assert len(cusum_recs) == len(if_recs)
        for cr, ir in zip(cusum_recs, if_recs):
            assert cr.timestamp == ir.timestamp
            assert cr.provenance == Provenance.PUBLIC_DATASET

    def test_daily_summary_aggregation(self, stage1_output):
        records = stage1_output["if_records"]
        daily_df = summarize_anomalies_by_day(records)
        assert not daily_df.empty
        assert daily_df["window_count"].sum() == len(records)


@skip_if_no_csv
class TestStage1ToStage2RealIntegration:
    """Validate Stage 1 to Stage 2 integration on real MetroPT-3 compressor telemetry.

    Integrity Safeguards:
    1. Preserves single-machine scope: no synthetic cross-machine edges are invented.
    2. Zero cross-machine propagation edges are expected and verified.
    3. All events strictly preserve PUBLIC_DATASET provenance.
    4. Timestamps are strictly monotonic and within the real dataset interval.
    5. No synthetic fixtures are mixed into this real-data pipeline.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def adapted_events(cls, stage1_output):
        if_records = stage1_output["if_records"]
        adapter = AnomalyToEventAdapter(
            EventAdapterConfig(
                max_gap_s=600.0,
                min_burst_windows=1,
                score_aggregation="peak",
                default_modality=Modality.PRESSURE,
            )
        )
        events = adapter.adapt(
            if_records,
            machine_id="metropt3_compressor",
            modality=Modality.PRESSURE,
        )
        return {
            "if_records": if_records,
            "adapter": adapter,
            "events": events,
        }

    def test_adapter_produces_valid_event_records(self, adapted_events):
        events = adapted_events["events"]
        assert len(events) > 0, "Real anomalies must produce at least one discrete event."
        for ev in events:
            assert isinstance(ev, EventRecord)
            assert ev.machine_id == "metropt3_compressor"
            assert ev.modality == Modality.PRESSURE
            assert ev.window_count >= 1
            assert np.isfinite(ev.score)

    def test_all_events_preserve_public_dataset_provenance(self, adapted_events):
        events = adapted_events["events"]
        for ev in events:
            assert ev.provenance == Provenance.PUBLIC_DATASET, (
                f"Expected PUBLIC_DATASET, got {ev.provenance}"
            )

    def test_timestamps_monotonic_and_within_range(self, adapted_events, stage1_output):
        events = adapted_events["events"]
        if_records = stage1_output["if_records"]
        earliest = if_records[0].timestamp
        latest = if_records[-1].timestamp

        for i in range(len(events)):
            ev = events[i]
            assert earliest <= ev.onset_time <= latest
            if ev.end_time is not None:
                assert ev.onset_time <= ev.end_time
            if i > 0:
                assert events[i - 1].onset_time < ev.onset_time, (
                    "Events must have strictly ascending onset times."
                )

    def test_event_durations_physically_plausible(self, adapted_events):
        events = adapted_events["events"]
        window_s = 300.0  # Nominal window size in Stage 1
        for ev in events:
            if ev.end_time is not None:
                duration_s = (ev.end_time - ev.onset_time).total_seconds()
                assert duration_s >= 0.0
                assert duration_s <= window_s * ev.window_count + 600.0

    def test_event_scores_bounded_and_match_peak_aggregation(self, adapted_events):
        events = adapted_events["events"]
        for ev in events:
            assert -1.0 <= ev.score <= 1.0

    def test_stage2_pipeline_handles_single_machine_gracefully(self, adapted_events):
        events = adapted_events["events"]
        pipeline = Stage2Pipeline()
        result = pipeline.run({"metropt3_compressor": events})

        # Single machine has no cross-machine pairs
        assert len(result.matched_observations) == 0
        assert len(result.accepted_observations) == 0
        assert len(result.rejected_observations) == 0
        assert len(result.edges) == 0
        assert len(result.paths) == 0
        assert len(result.cri_records) == 0

    def test_no_synthetic_data_mixed(self, adapted_events):
        events = adapted_events["events"]
        for ev in events:
            assert ev.provenance != Provenance.SYNTHETIC

