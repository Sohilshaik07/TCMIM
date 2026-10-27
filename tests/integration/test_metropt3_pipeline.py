"""
TCMIM — Integration test: MetroPT-3 load + validate + window + features.

This is an EXEC-tier test — it runs on the real MetroPT-3 CSV.
It is skipped automatically if the CSV file is not found (e.g. in CI
without the large dataset).

Status: TEST (runs on real data → will be EXEC once confirmed on full file)
Provenance: PUBLIC_DATASET
"""

import os
from pathlib import Path

import pandas as pd
import pytest

# Path to the real MetroPT-3 CSV (relative to the project root or absolute)
_CSV_CANDIDATES = [
    Path(__file__).parent.parent.parent.parent / "MetroPT3(AirCompressor).csv",
    Path("data/raw/MetroPT3(AirCompressor).csv"),
]

METROPT3_CSV = next((p for p in _CSV_CANDIDATES if p.exists()), None)

skip_if_no_csv = pytest.mark.skipif(
    METROPT3_CSV is None,
    reason="MetroPT-3 CSV not found — skipping real-data integration test."
)


@skip_if_no_csv
class TestMetroPT3LoadIntegration:
    """Integration tests for the MetroPT-3 ingestion pipeline."""

    def test_dataframe_loads(self):
        """Load first 1000 rows into a DataFrame; verify shape and index."""
        from tcmim.data.metropt3 import load_metropt3_dataframe, SENSOR_COLUMNS
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=1000)
        assert len(df) == 1000
        assert df.index.name == "timestamp"
        for col in SENSOR_COLUMNS:
            assert col in df.columns, f"Expected column '{col}' missing."

    def test_dataframe_index_is_datetimeindex(self):
        from tcmim.data.metropt3 import load_metropt3_dataframe
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=100)
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_dataframe_index_timezone_aware(self):
        from tcmim.data.metropt3 import load_metropt3_dataframe
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=100)
        assert df.index.tz is not None

    def test_dataframe_index_monotonic(self):
        from tcmim.data.metropt3 import load_metropt3_dataframe
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=5000)
        assert df.index.is_monotonic_increasing

    def test_sensor_samples_provenance(self):
        """All loaded SensorSamples must carry PUBLIC_DATASET provenance."""
        from tcmim.data.metropt3 import load_metropt3
        from tcmim.schemas import Provenance
        samples = load_metropt3(METROPT3_CSV, max_rows=100, columns=["TP2"])
        for s in samples:
            assert s.provenance == Provenance.PUBLIC_DATASET, (
                f"Expected PUBLIC_DATASET, got {s.provenance}"
            )

    def test_sensor_samples_machine_id(self):
        from tcmim.data.metropt3 import load_metropt3, MACHINE_ID
        samples = load_metropt3(METROPT3_CSV, max_rows=50, columns=["Motor_current"])
        for s in samples:
            assert s.machine_id == MACHINE_ID

    def test_validation_passes_on_small_slice(self):
        from tcmim.data.metropt3 import load_metropt3_dataframe, PHYSICAL_RANGES
        from tcmim.data.validator import validate_dataframe
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=1000)
        report = validate_dataframe(df, physical_ranges=PHYSICAL_RANGES)
        # Timestamp ordering must be clean
        assert report.out_of_order_count == 0

    def test_windowing_produces_windows(self):
        """Windowing a 1000-row slice should produce at least 1 window."""
        from tcmim.data.metropt3 import load_metropt3_dataframe
        from tcmim.data.windower import WindowBuilder
        from tcmim.schemas import Provenance
        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=1000)
        wb = WindowBuilder(window_seconds=300.0, overlap_frac=0.0)
        windows = wb.build(df, "metropt3_compressor", Provenance.PUBLIC_DATASET)
        assert len(windows) >= 1

    def test_feature_extraction_on_real_window(self):
        """End-to-end: load → window → extract features; no NaN in output."""
        from tcmim.data.metropt3 import load_metropt3_dataframe
        from tcmim.data.windower import WindowBuilder
        from tcmim.features.extractor import FeatureExtractor
        from tcmim.schemas import Provenance
        import numpy as np

        df = load_metropt3_dataframe(METROPT3_CSV, max_rows=500)
        wb = WindowBuilder(window_seconds=300.0, overlap_frac=0.0)
        windows = wb.build(df, "metropt3_compressor", Provenance.PUBLIC_DATASET)
        extractor = FeatureExtractor(sampling_rate_hz=0.1)  # ~10-s sample rate
        feature_samples = extractor.extract_all(windows)

        assert len(feature_samples) > 0
        # Check no all-NaN modality dict
        for fs in feature_samples:
            for mod_key, feat_dict in fs.features.items():
                vals = list(feat_dict.values())
                non_nan = [v for v in vals if not np.isnan(v)]
                assert len(non_nan) > 0, (
                    f"All features NaN for modality '{mod_key}' "
                    f"in window {fs.window_start}"
                )

    def test_no_synthetic_in_real_output(self):
        """Provenance guard: assert no sample is SYNTHETIC in a real pipeline."""
        from tcmim.data.metropt3 import load_metropt3
        from tcmim.provenance import filter_real, assert_not_synthetic
        from tcmim.schemas import Provenance

        samples = load_metropt3(METROPT3_CSV, max_rows=200, columns=["TP2", "COMP"])
        real_samples = filter_real(samples)
        # All samples from MetroPT-3 should already be real
        assert len(real_samples) == len(samples)
        for s in real_samples:
            assert_not_synthetic(s)   # must not raise
