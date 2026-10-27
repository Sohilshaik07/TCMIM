"""
TCMIM — Unit tests for data validation and windower (M1).

All tests use synthetic DataFrames — labelled as SYNTHETIC fixtures.
"""

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta

from tcmim.data.validator import validate_dataframe, validate_samples, filter_range_violations
from tcmim.data.windower import WindowBuilder, WindowedData
from tcmim.schemas import Provenance, SensorSample, Modality


def make_datetime_index(n: int, freq_s: float = 10.0) -> pd.DatetimeIndex:
    start = pd.Timestamp("2020-02-01", tz="UTC")
    return pd.date_range(start, periods=n, freq=f"{freq_s}s")


def make_df(n: int = 100, freq_s: float = 10.0) -> pd.DataFrame:
    idx = make_datetime_index(n, freq_s)
    return pd.DataFrame({"TP2": np.random.normal(5, 0.5, n)}, index=idx)


# ============================================================
# Validator — DataFrame interface
# ============================================================

class TestValidateDataframe:
    def test_clean_df_passes(self):
        df = make_df(100)
        report = validate_dataframe(df)
        assert report.passed is True
        assert report.out_of_order_count == 0
        assert report.nan_count == 0

    def test_nan_detected(self):
        df = make_df(50)
        df.iloc[10, 0] = np.nan
        report = validate_dataframe(df)
        assert report.nan_count >= 1

    def test_range_violation_detected(self):
        df = make_df(50)
        df.iloc[5, 0] = 999.0   # way out of range
        report = validate_dataframe(df, physical_ranges={"TP2": (-1.0, 15.0)})
        assert report.range_violation_count >= 1

    def test_out_of_order_detected(self):
        df = make_df(10)
        # Manually scramble the index
        idx_list = list(df.index)
        idx_list[3], idx_list[4] = idx_list[4], idx_list[3]
        df.index = pd.DatetimeIndex(idx_list)
        report = validate_dataframe(df)
        assert report.out_of_order_count >= 1

    def test_empty_df(self):
        df = pd.DataFrame()
        report = validate_dataframe(df)
        assert report.total_checked == 0


# ============================================================
# Validator — SensorSample interface
# ============================================================

class TestValidateSamples:
    def _make_samples(self, n: int) -> list:
        start = datetime(2020, 2, 1, tzinfo=timezone.utc)
        return [
            SensorSample(
                machine_id="m1",
                channel="TP2",
                modality=Modality.PRESSURE,
                timestamp=start + timedelta(seconds=i * 10),
                value=5.0,
                provenance=Provenance.SYNTHETIC,
                source_id="test",
            )
            for i in range(n)
        ]

    def test_clean_samples_pass(self):
        samples = self._make_samples(20)
        report = validate_samples(samples)
        assert report.passed is True
        assert report.out_of_order_count == 0

    def test_empty_samples(self):
        report = validate_samples([])
        assert report.total_checked == 0

    def test_range_filter(self):
        samples = self._make_samples(10)
        # Inject an out-of-range value
        bad = SensorSample(
            machine_id="m1",
            channel="TP2",
            modality=Modality.PRESSURE,
            timestamp=datetime(2020, 2, 1, 0, 5, tzinfo=timezone.utc),
            value=999.0,
            provenance=Provenance.SYNTHETIC,
            source_id="test",
        )
        samples.append(bad)
        clean, removed = filter_range_violations(
            samples, {"TP2": (-1.0, 15.0)}
        )
        assert removed == 1
        assert len(clean) == 10


# ============================================================
# WindowBuilder
# ============================================================

class TestWindowBuilder:
    def test_basic_windowing(self):
        df = make_df(360, freq_s=10.0)  # 3600 seconds of data
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        # 3600s / 60s = 60 non-overlapping windows
        assert len(windows) == 60

    def test_overlapping_windows(self):
        df = make_df(360, freq_s=10.0)   # 3600 s
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.5)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        # Step = 30s; starts: 0, 30, 60, ..., 3540 → 119 windows approx
        assert len(windows) > 60

    def test_window_provenance_propagated(self):
        df = make_df(50)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "m1", Provenance.PUBLIC_DATASET)
        for w in windows:
            assert w.provenance == Provenance.PUBLIC_DATASET

    def test_window_machine_id(self):
        df = make_df(50)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "my_machine", Provenance.SYNTHETIC)
        for w in windows:
            assert w.machine_id == "my_machine"

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame()
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        assert windows == []

    def test_window_end_after_start(self):
        df = make_df(50)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        for w in windows:
            assert w.window_end > w.window_start

    def test_invalid_window_seconds(self):
        with pytest.raises(ValueError, match="window_seconds"):
            WindowBuilder(window_seconds=-10.0)

    def test_invalid_overlap_frac(self):
        with pytest.raises(ValueError, match="overlap_frac"):
            WindowBuilder(window_seconds=60.0, overlap_frac=1.0)

    def test_min_samples_filter(self):
        """Windows with fewer than min_samples rows should be excluded."""
        # 3 rows total with a 60s window that fits all — min_samples=5 → excluded
        df = make_df(3, freq_s=10.0)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0, min_samples=5)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        assert len(windows) == 0

    def test_window_indices_sequential(self):
        df = make_df(180, freq_s=10.0)
        wb = WindowBuilder(window_seconds=60.0, overlap_frac=0.0)
        windows = wb.build(df, "m1", Provenance.SYNTHETIC)
        for i, w in enumerate(windows):
            assert w.window_index == i
