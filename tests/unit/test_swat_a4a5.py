"""Unit tests for the dedicated SWaT A4/A5 July 2019 data adapter and pipeline.

Tests cover:
- Multi-row header parsing (3-row composite structure)
- Tag normalization and collision detection
- ISO 8601 timestamps with 'Z' and fractional seconds
- UTC normalization and timezone awareness
- Missing, duplicate, and non-monotonic timestamps
- Irregular cadence and large-gap handling
- Categorical level-switch encoding (Active=1.0, Inactive=0.0)
- Actuator state mappings and P1_STATE semantics preservation
- Attack interval boundaries and timezone alignment (GMT+8 -> UTC)
- Observable vs. unobservable attack coverage
- Prevention of ground-truth label leakage
- Exclusion of gap-spanning windows
- Baseline protocol slicing and empty baseline handling
- Deterministic output and metric calculations
- Missing-file and malformed-workbook errors
"""

from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import openpyxl
import pandas as pd
import pytest

from tcmim.data.swat import SWaTProcessStage, SWaTTagType
from tcmim.data.swat_a4a5 import (
    A4A5Attack,
    A4A5HeaderInfo,
    A4A5_ACTUATOR_STATE_MAP,
    A4A5_EXTENDED_TAG_REGISTRY,
    A4A5_LEVEL_SWITCH_BINARY_MAP,
    A4A5_LEVEL_SWITCH_TAGS,
    A4A5_MODALITY_MAP,
    A4A5_PLC_STATE_TAGS,
    A4A5_STAGE_MAP,
    A4A5_TAG_RENAME_MAP,
    AttackObservability,
    GapAwareWindowBuilder,
    SWAT_A4A5_ATTACK_SCHEDULE,
    SWAT_A4A5_NORMAL_END_UTC,
    SWAT_A4A5_PLANT_START_UTC,
    compute_a4a5_attack_coverage,
    construct_a4a5_window_labels,
    evaluate_a4a5_predictions,
    load_swat_a4a5_dataframe,
    parse_a4a5_composite_header,
    validate_swat_a4a5_telemetry,
)
from tcmim.data.windower import WindowedData
from tcmim.provenance import Provenance
from tcmim.schemas import Modality


# ------------------------------------------------------------------------------
# Helpers to generate mini synthetic Excel workbooks matching A4/A5 3-row layout
# ------------------------------------------------------------------------------

def create_mini_a4a5_workbook(
    file_path: Path,
    rows_data: List[List[str]],
    tag_names: List[str] = None,
    stage_names: List[str] = None,
    type_names: List[str] = None,
) -> None:
    """Create a minimal openpyxl workbook replicating the A4/A5 3-row header."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MST v2"

    if tag_names is None:
        tag_names = ["GMT +0", "FIT 101", "LIT 101", "MV 101", "P1_STATE", "P101 Status", "LS 201"]
    if stage_names is None:
        stage_names = [None, "P1", None, None, None, None, "P2"]
    if type_names is None:
        type_names = ["timestamp", "value", "value", "value", "value", "value", "value"]

    ws.append(stage_names)
    ws.append(tag_names)
    ws.append(type_names)

    for row in rows_data:
        ws.append(row)

    wb.save(str(file_path))
    wb.close()


# ==============================================================================
# 1. Multi-Row Header Parsing Tests
# ==============================================================================

class TestMultiRowHeaderParsing:
    def test_parse_a4a5_composite_header_success(self):
        raw_header = [
            (None, "P1", None, "P2"),
            ("GMT +0", "FIT 101", "P1_STATE", "LS 201"),
            ("timestamp", "value", "value", "value"),
        ]
        info = parse_a4a5_composite_header(raw_header)
        assert info.timestamp_col == "GMT +0"
        assert info.column_renames["FIT 101"] == "FIT101"
        assert info.column_renames["P1_STATE"] == "P1_STATE"
        assert info.column_renames["LS 201"] == "LS201"
        assert "FIT101" in info.normalized_columns

    def test_parse_too_few_rows_raises(self):
        with pytest.raises(ValueError, match="at least 3 header rows"):
            parse_a4a5_composite_header([("a", "b"), ("c", "d")])

    def test_parse_missing_timestamp_raises(self):
        raw_header = [
            ("P1", "P1"),
            ("FIT 101", "LIT 101"),
            ("value", "value"),
        ]
        with pytest.raises(ValueError, match="timestamp column"):
            parse_a4a5_composite_header(raw_header)

    def test_parse_length_mismatch_raises(self):
        raw_header = [
            ("P1",),
            ("GMT +0", "FIT 101"),
            ("timestamp", "value"),
        ]
        with pytest.raises(ValueError, match="length mismatch"):
            parse_a4a5_composite_header(raw_header)


# ==============================================================================
# 2. Tag Normalization and Collision Detection Tests
# ==============================================================================

class TestTagNormalizationAndCollisions:
    def test_all_78_columns_mapped_uniquely(self):
        assert len(A4A5_TAG_RENAME_MAP) == 78
        normalized_names = list(A4A5_TAG_RENAME_MAP.values())
        assert len(set(normalized_names)) == len(normalized_names), "Collision found in rename map"

    def test_collision_detection_raises_in_header_parser(self):
        # Two tags that would normalize to the same name
        raw_header = [
            (None, "P1", "P1"),
            ("GMT +0", "FIT 101", "FIT101"),
            ("timestamp", "value", "value"),
        ]
        with pytest.raises(ValueError, match="collision detected"):
            parse_a4a5_composite_header(raw_header)

    def test_all_stages_p1_to_p6_represented(self):
        stages = set(A4A5_STAGE_MAP.values())
        for stage in SWaTProcessStage:
            assert stage in stages


# ==============================================================================
# 3. ISO 8601 Timestamps, UTC Normalization, and Validation Tests
# ==============================================================================

class TestTimestampParsingAndUtc:
    def test_iso8601_z_and_fractional_seconds(self, tmp_path):
        wb_path = tmp_path / "test_iso.xlsx"
        rows = [
            ["2019-07-20T04:30:00Z", 1.2, 700.0, 1, 3, 2, "Inactive"],
            ["2019-07-20T04:30:01Z", 1.3, 700.1, 1, 3, 2, "Inactive"],
            ["2019-07-20T04:30:02.004013Z", 1.4, 700.2, 1, 3, 2, "Inactive"],
        ]
        create_mini_a4a5_workbook(wb_path, rows)

        df, meta = load_swat_a4a5_dataframe(wb_path)
        assert len(df) == 3
        assert isinstance(df.index, pd.DatetimeIndex)
        assert str(df.index.tz) == "UTC"
        assert df.index[0] == datetime(2019, 7, 20, 4, 30, 0, tzinfo=timezone.utc)
        assert df.index[2].microsecond == 4013

    def test_duplicate_timestamps_raise(self, tmp_path):
        wb_path = tmp_path / "test_dup.xlsx"
        rows = [
            ["2019-07-20T04:30:00Z", 1.0, 700.0, 1, 3, 2, "Inactive"],
            ["2019-07-20T04:30:00Z", 1.1, 700.1, 1, 3, 2, "Inactive"],
        ]
        create_mini_a4a5_workbook(wb_path, rows)
        with pytest.raises(ValueError, match="duplicate timestamps"):
            load_swat_a4a5_dataframe(wb_path)

    def test_non_monotonic_timestamps_raise(self, tmp_path):
        wb_path = tmp_path / "test_nonmono.xlsx"
        rows = [
            ["2019-07-20T04:30:05Z", 1.0, 700.0, 1, 3, 2, "Inactive"],
            ["2019-07-20T04:30:01Z", 1.1, 700.1, 1, 3, 2, "Inactive"],
        ]
        create_mini_a4a5_workbook(wb_path, rows)
        with pytest.raises(ValueError, match="monotonically increasing"):
            load_swat_a4a5_dataframe(wb_path)


# ==============================================================================
# 4. Irregular Cadence and Telemetry Gap Handling Tests
# ==============================================================================

class TestCadenceAndGapHandling:
    def test_validate_swat_a4a5_telemetry_detects_gaps(self):
        t0 = datetime(2019, 7, 20, 4, 30, 0, tzinfo=timezone.utc)
        times = [
            t0,
            t0 + timedelta(seconds=1),
            t0 + timedelta(seconds=2),
            t0 + timedelta(seconds=15),  # 13s gap > 10s
            t0 + timedelta(seconds=60),  # 45s gap > 30s
            t0 + timedelta(seconds=700), # 640s gap > 600s
        ]
        df = pd.DataFrame({"FIT101": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]}, index=pd.DatetimeIndex(times))
        report = validate_swat_a4a5_telemetry(df)

        assert report.total_rows == 6
        assert report.gap_count_gt_3s == 3
        assert report.gap_count_gt_10s == 3
        assert report.gap_count_gt_30s == 2
        assert report.gap_count_gt_600s == 1
        assert report.max_gap_seconds == 640.0


# ==============================================================================
# 5. Categorical Level-Switch Encoding Tests
# ==============================================================================

class TestLevelSwitchEncoding:
    def test_active_and_inactive_mapping(self, tmp_path):
        wb_path = tmp_path / "test_ls.xlsx"
        rows = [
            ["2019-07-20T04:30:00Z", 1.0, 700.0, 1, 3, 2, "Inactive"],
            ["2019-07-20T04:30:01Z", 1.0, 700.0, 1, 3, 2, "Active"],
        ]
        create_mini_a4a5_workbook(wb_path, rows)

        df, meta = load_swat_a4a5_dataframe(wb_path, encode_level_switches=True)
        assert df["LS201"].iloc[0] == 0.0
        assert df["LS201"].iloc[1] == 1.0

    def test_unknown_level_switch_maps_to_nan(self, tmp_path):
        wb_path = tmp_path / "test_ls_unk.xlsx"
        rows = [
            ["2019-07-20T04:30:00Z", 1.0, 700.0, 1, 3, 2, "UnknownStatus"],
        ]
        create_mini_a4a5_workbook(wb_path, rows)

        df, meta = load_swat_a4a5_dataframe(wb_path, encode_level_switches=True)
        assert np.isnan(df["LS201"].iloc[0])


# ==============================================================================
# 6. Actuator State Mappings and P1_STATE Semantics Preservation Tests
# ==============================================================================

class TestActuatorStateSemantics:
    def test_p1_state_semantics_not_invented(self):
        # Must be empty dict (unmapped / unknown), never assumed {2: 0, 3: 1}
        assert A4A5_ACTUATOR_STATE_MAP["P1_STATE"] == {}

    def test_all_plc_state_registers_unmapped_as_actuators(self):
        for state_tag in A4A5_PLC_STATE_TAGS:
            assert A4A5_ACTUATOR_STATE_MAP[state_tag] == {}

    def test_standard_actuators_have_binary_state_map(self):
        assert A4A5_ACTUATOR_STATE_MAP["P101"] == {1.0: 0, 2.0: 1}
        assert A4A5_ACTUATOR_STATE_MAP["MV101"] == {1.0: 0, 2.0: 1}


# ==============================================================================
# 7. Attack Interval Schedule and Timezone Alignment Tests
# ==============================================================================

class TestAttackScheduleAndTimezone:
    def test_attack_count_and_keys(self):
        assert len(SWAT_A4A5_ATTACK_SCHEDULE) == 6
        assert set(SWAT_A4A5_ATTACK_SCHEDULE.keys()) == {"A1", "A2", "A3", "A4", "A5", "A6"}

    def test_timezone_conversion_gmt8_to_utc(self):
        # A1: 15:08:46 SGT -> 07:08:46 UTC
        a1 = SWAT_A4A5_ATTACK_SCHEDULE["A1"]
        assert a1.start_utc == datetime(2019, 7, 20, 7, 8, 46, tzinfo=timezone.utc)
        assert a1.end_utc == datetime(2019, 7, 20, 7, 10, 31, tzinfo=timezone.utc)
        assert a1.duration_seconds == 105.0

        # A4: 15:38:50 SGT -> 07:38:50 UTC
        a4 = SWAT_A4A5_ATTACK_SCHEDULE["A4"]
        assert a4.start_utc == datetime(2019, 7, 20, 7, 38, 50, tzinfo=timezone.utc)
        assert a4.end_utc == datetime(2019, 7, 20, 7, 46, 20, tzinfo=timezone.utc)
        assert a4.duration_seconds == 450.0

    def test_target_tags_verified(self):
        assert SWAT_A4A5_ATTACK_SCHEDULE["A1"].target_tags == ("FIT401",)
        assert SWAT_A4A5_ATTACK_SCHEDULE["A2"].target_tags == ("LIT301",)
        assert SWAT_A4A5_ATTACK_SCHEDULE["A3"].target_tags == ("P601",)
        assert SWAT_A4A5_ATTACK_SCHEDULE["A4"].target_tags == ("MV201", "P101")
        assert SWAT_A4A5_ATTACK_SCHEDULE["A5"].target_tags == ("MV501",)
        assert SWAT_A4A5_ATTACK_SCHEDULE["A6"].target_tags == ("P301",)


# ==============================================================================
# 8. Observability and Coverage Tests
# ==============================================================================

class TestObservabilityAndCoverage:
    def test_coverage_calculation_observable_and_unobservable(self):
        # Telemetry covering only A3, with zero rows in A1
        t_a3 = datetime(2019, 7, 20, 7, 27, 0, tzinfo=timezone.utc)
        times = [t_a3 + timedelta(seconds=i) for i in range(100)]
        df = pd.DataFrame({"P601": [2.0] * 100}, index=pd.DatetimeIndex(times))

        coverage = compute_a4a5_attack_coverage(df)
        assert coverage["A1"].observability == AttackObservability.UNOBSERVABLE
        assert coverage["A1"].observed_rows == 0
        assert coverage["A3"].observability == AttackObservability.PARTIALLY_OBSERVABLE
        assert coverage["A3"].observed_rows == 100


# ==============================================================================
# 9. Ground-Truth Isolation and Leakage Prevention Tests
# ==============================================================================

class TestGroundTruthIsolation:
    def test_loader_rejects_attack_label_column(self, tmp_path):
        wb_path = tmp_path / "test_leak.xlsx"
        tag_names = ["GMT +0", "FIT 101", "Normal/Attack"]
        stage_names = [None, "P1", None]
        type_names = ["timestamp", "value", "label"]
        rows = [["2019-07-20T04:30:00Z", 1.0, 0]]
        create_mini_a4a5_workbook(wb_path, rows, tag_names, stage_names, type_names)

        with pytest.raises(ValueError, match="Ground-truth leakage detected"):
            load_swat_a4a5_dataframe(wb_path)

    def test_unobservable_attacks_marked_nan_never_normal(self):
        # Window overlapping unobservable attack A1 must be NaN, not 0.0
        ws = datetime(2019, 7, 20, 7, 9, 0, tzinfo=timezone.utc)
        we = datetime(2019, 7, 20, 7, 9, 30, tzinfo=timezone.utc)
        w = WindowedData(
            machine_id="SWAT",
            window_start=ws,
            window_end=we,
            data=pd.DataFrame({"FIT101": [0.5, 0.5]}),
            provenance=Provenance.PUBLIC_DATASET,
            window_index=0,
        )
        labels = construct_a4a5_window_labels(
            [w],
            rule="majority",
            exclude_unobservable=True,
            unobservable_attack_ids={"A1", "A2", "A4"},
        )
        assert np.isnan(labels.iloc[0]), "Unobservable attack period was erroneously labeled as normal!"


# ==============================================================================
# 10. Gap-Aware Window Builder Tests
# ==============================================================================

class TestGapAwareWindowBuilder:
    def test_gap_spanning_window_excluded(self):
        t0 = datetime(2019, 7, 20, 5, 0, 0, tzinfo=timezone.utc)
        times = [
            t0,
            t0 + timedelta(seconds=2),
            t0 + timedelta(seconds=28), # Internal gap of 26s > max_internal_gap_s (15s)
        ]
        df = pd.DataFrame({"FIT101": [1.0, 1.1, 1.2]}, index=pd.DatetimeIndex(times))

        builder = GapAwareWindowBuilder(window_seconds=30.0, step_seconds=30.0, max_internal_gap_s=15.0)
        eligible, manifest = builder.build_and_audit(df)

        assert len(eligible) == 0
        assert len(manifest) >= 1
        assert not manifest["is_eligible"].iloc[0]
        assert "EXCEEDS_GAP_THRESHOLD" in manifest["ineligibility_reason"].iloc[0]

    def test_insufficient_samples_excluded(self):
        t0 = datetime(2019, 7, 20, 5, 0, 0, tzinfo=timezone.utc)
        df = pd.DataFrame({"FIT101": [1.0]}, index=pd.DatetimeIndex([t0]))

        builder = GapAwareWindowBuilder(window_seconds=30.0, step_seconds=30.0, min_samples=2)
        eligible, manifest = builder.build_and_audit(df)

        assert len(eligible) == 0
        assert not manifest["is_eligible"].iloc[0]
        assert "INSUFFICIENT_SAMPLES" in manifest["ineligibility_reason"].iloc[0]

    def test_continuous_window_is_eligible(self):
        t0 = datetime(2019, 7, 20, 5, 0, 0, tzinfo=timezone.utc)
        times = [t0 + timedelta(seconds=i) for i in range(30)]
        df = pd.DataFrame({"FIT101": [1.0] * 30}, index=pd.DatetimeIndex(times))

        builder = GapAwareWindowBuilder(window_seconds=30.0, step_seconds=30.0, min_samples=2, max_internal_gap_s=15.0)
        eligible, manifest = builder.build_and_audit(df)

        assert len(eligible) == 1
        assert bool(manifest["is_eligible"].iloc[0]) is True
        assert eligible[0].window_index == 0

# ==============================================================================
# 11. Baseline Protocols and Metrics Evaluation Tests
# ==============================================================================

class TestBaselineProtocolsAndMetrics:
    def test_empty_baseline_returns_empty_windows(self):
        df_empty = pd.DataFrame({"FIT101": []}, index=pd.DatetimeIndex([]))
        builder = GapAwareWindowBuilder(window_seconds=30.0)
        eligible, manifest = builder.build_and_audit(df_empty)
        assert len(eligible) == 0
        assert len(manifest) == 0

    def test_evaluate_predictions_confusion_matrix_and_metrics(self):
        ws = datetime(2019, 7, 20, 7, 27, 0, tzinfo=timezone.utc)
        we = datetime(2019, 7, 20, 7, 27, 30, tzinfo=timezone.utc)
        w = WindowedData(
            machine_id="SWAT",
            window_start=ws,
            window_end=we,
            data=pd.DataFrame({"P601": [2.0]}),
            provenance=Provenance.PUBLIC_DATASET,
            window_index=0,
        )

        preds = pd.Series({"SWAT_w_000000": 1, "w_1": 0})
        labs = pd.Series({"SWAT_w_000000": 1.0, "w_1": 0.0})

        metrics = evaluate_a4a5_predictions(preds, labs, [w])
        assert metrics.tp == 1
        assert metrics.tn == 1
        assert metrics.fp == 0
        assert metrics.fn == 0
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.f1_score == 1.0

    def test_undefined_metrics_return_none(self):
        # All negative labels with zero positive predictions: precision and recall are undefined
        preds = pd.Series({"w_0": 0, "w_1": 0})
        labs = pd.Series({"w_0": 0.0, "w_1": 0.0})
        metrics = evaluate_a4a5_predictions(preds, labs, [])

        assert metrics.tp == 0
        assert metrics.fp == 0
        assert metrics.fn == 0
        assert metrics.tn == 2
        assert metrics.precision is None
        assert metrics.recall is None
        assert metrics.f1_score is None


# ==============================================================================
# 12. Missing-File and Malformed-Workbook Error Tests
# ==============================================================================

class TestMissingAndMalformedFiles:
    def test_missing_file_raises_filenotfounderror(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_swat_a4a5_dataframe("non_existent_swat_file.xlsx")

    def test_empty_file_raises(self, tmp_path):
        bad_file = tmp_path / "empty.xlsx"
        bad_file.write_bytes(b"not an excel file")
        with pytest.raises(Exception):
            load_swat_a4a5_dataframe(bad_file)
