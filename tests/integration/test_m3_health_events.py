"""
TCMIM — Integration test: M3 Health + Event detection on MetroPT-3.

Provenance: PUBLIC_DATASET
Status: EXEC (runs on real data)

INTEGRITY NOTES
---------------
- MetroPT-3 is a single-machine dataset.  No cross-machine claims are made.
- Events detected here are health-degradation onsets on real data.
  They are NOT labelled as causally prior to any failure.
- No ground truth for event correctness exists for MetroPT-3 events;
  this test validates pipeline execution only (not VAL-tier accuracy).
"""

import os
from pathlib import Path

import numpy as np
import pytest

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


@skip_if_no_csv
class TestM3MetroPT3Integration:
    """End-to-end M3 pipeline on MetroPT-3: load → window → features → health → events."""

    @pytest.fixture(scope="class", autouse=False)
    @classmethod
    def pipeline_output(cls, tmp_path_factory):
        """Run the full M0–M3 pipeline on a 5000-row slice of MetroPT-3."""
        from tcmim.data.metropt3 import load_metropt3_dataframe
        from tcmim.data.windower import WindowBuilder
        from tcmim.features.extractor import FeatureExtractor
        from tcmim.health.baseline import MachineBaseline
        from tcmim.health.indicator import HealthIndicator
        from tcmim.events.detector import EventDetector
        from tcmim.config import CUSUMConfig
        from tcmim.schemas import Provenance, Modality

        # --- S0–S1: Load and window ------------------------------------------
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=5000)
        wb = WindowBuilder(window_seconds=300.0, overlap_frac=0.0)
        windows = wb.build(df, "metropt3_compressor", Provenance.PUBLIC_DATASET)

        # --- S2: Feature extraction ------------------------------------------
        extractor = FeatureExtractor(sampling_rate_hz=0.1)
        feature_samples = extractor.extract_all(windows)

        # --- S3: Health baseline + indicator ---------------------------------
        baseline = MachineBaseline.fit(feature_samples, baseline_frac=0.3)
        indicator = HealthIndicator(baseline)
        health_samples = indicator.compute_all(feature_samples)

        # --- S4: Event detection ---------------------------------------------
        cfg = CUSUMConfig(k=0.5, h=5.0)
        detector = EventDetector(cusum_config=cfg)
        events = detector.detect(health_samples, modality=Modality.UNKNOWN)

        return {
            "windows": windows,
            "feature_samples": feature_samples,
            "health_samples": health_samples,
            "events": events,
            "baseline": baseline,
        }

    def test_pipeline_produces_windows(self, pipeline_output):
        assert len(pipeline_output["windows"]) >= 1

    def test_pipeline_produces_features(self, pipeline_output):
        assert len(pipeline_output["feature_samples"]) >= 1

    def test_pipeline_produces_health_samples(self, pipeline_output):
        assert len(pipeline_output["health_samples"]) >= 1

    def test_health_scores_in_range(self, pipeline_output):
        """All health scores must be in [0, 1]."""
        for hs in pipeline_output["health_samples"]:
            assert 0.0 <= hs.health_score <= 1.0, (
                f"Health score {hs.health_score} out of range at {hs.window_start}"
            )

    def test_health_scores_not_all_one(self, pipeline_output):
        """At least some windows should not be perfectly 1.0 (real data varies)."""
        scores = [hs.health_score for hs in pipeline_output["health_samples"]]
        assert any(s < 1.0 for s in scores), "Expected some health variation in real data."

    def test_health_provenance_public_dataset(self, pipeline_output):
        from tcmim.schemas import Provenance
        for hs in pipeline_output["health_samples"]:
            assert hs.provenance == Provenance.PUBLIC_DATASET

    def test_baseline_has_features(self, pipeline_output):
        baseline = pipeline_output["baseline"]
        assert len(baseline.feature_stats) > 0

    def test_events_are_event_records(self, pipeline_output):
        from tcmim.schemas import EventRecord
        for e in pipeline_output["events"]:
            assert isinstance(e, EventRecord)

    def test_events_provenance_public_dataset(self, pipeline_output):
        from tcmim.schemas import Provenance
        for e in pipeline_output["events"]:
            assert e.provenance == Provenance.PUBLIC_DATASET

    def test_event_onset_within_data_range(self, pipeline_output):
        """All event onset times must fall within the data window period."""
        health_samples = pipeline_output["health_samples"]
        if not health_samples:
            pytest.skip("No health samples produced.")
        first_ts = health_samples[0].window_start
        last_ts = health_samples[-1].window_end
        for e in pipeline_output["events"]:
            assert first_ts <= e.onset_time <= last_ts, (
                f"Event onset {e.onset_time} outside data range "
                f"[{first_ts}, {last_ts}]"
            )

    def test_no_synthetic_in_pipeline_output(self, pipeline_output):
        """Provenance guard: no SYNTHETIC data in real-data pipeline output."""
        from tcmim.provenance import assert_not_synthetic
        for hs in pipeline_output["health_samples"]:
            assert_not_synthetic(hs)
        for e in pipeline_output["events"]:
            assert_not_synthetic(e)

    def test_events_logged_count(self, pipeline_output, capsys):
        """Verify events count is logged (not checking specific count)."""
        events = pipeline_output["events"]
        # Just assert we can report the count — no ground truth claim
        print(
            f"[EXEC] MetroPT-3 M3: {len(events)} health-degradation events detected. "
            f"Status: EXEC (no VAL-tier ground truth for MetroPT-3 event correctness)."
        )
