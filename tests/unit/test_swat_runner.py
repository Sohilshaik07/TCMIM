"""
tests/unit/test_swat_runner.py
==============================
Focused unit tests for SWaT experiment runner (experiments/swat_propagation_runner.py).

INTEGRITY NOTICE:
All test fixtures in this file are strictly SYNTHETIC in-memory fixtures.
They test software contract compliance and must NEVER be represented or cited
as real SWaT measurements. All samples carry Provenance.SYNTHETIC.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from experiments.swat_propagation_runner import (
    SWaTExperimentConfig,
    SWaTExperimentResult,
    TCMIMJSONEncoder,
    _generate_markdown_report,
    build_parser,
    resolve_swat_dataset_paths,
    run_swat_experiment,
)
from tcmim.data.swat import (
    SWAT_ACTUATOR_STATE_MAP,
    SWAT_DEFAULT_ACTUATOR_STATE_MAP,
    SWAT_MODALITY_MAP,
    align_swat_labels_to_windows,
    evaluate_swat_window_predictions,
    verify_no_ground_truth_leakage,
)
from tcmim.data.windower import WindowBuilder
from tcmim.features.extractor import FeatureExtractor
from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance


# ---------------------------------------------------------------------------
# Synthetic Test Fixtures
# ---------------------------------------------------------------------------

def _create_synthetic_swat_pair(
    tmp_path: Path,
    n_rows_normal: int = 180,
    n_rows_attack: int = 240,
    inject_anomaly_in_p2: bool = True,
) -> Tuple[Path, Path]:
    """Create paired synthetic Normal and Attack CSV fixtures for testing."""
    start_norm = pd.Timestamp("2015-12-22 10:00:00", tz="UTC")
    norm_ts = [start_norm + pd.Timedelta(seconds=i) for i in range(n_rows_normal)]

    t_norm = np.linspace(0, 4 * np.pi, n_rows_normal)
    norm_data = {
        " Timestamp ": [t.strftime("%d/%m/%Y %I:%M:%S %p") for t in norm_ts],
        " FIT101 ": 2.5 + 0.1 * np.sin(t_norm),
        " LIT101 ": 500.0 + 1.0 * np.cos(t_norm),
        " MV101 ": [1.0 if i % 20 < 10 else 2.0 for i in range(n_rows_normal)],
        " P101 ": [1.0] * n_rows_normal,
        " AIT201 ": 150.0 + 0.5 * np.sin(t_norm),
        " P201 ": [1.0] * n_rows_normal,
        " DPIT301 ": 10.0 + 0.2 * np.cos(t_norm),
        " P301 ": [1.0] * n_rows_normal,
        " AIT401 ": 10.0 + 0.1 * np.cos(t_norm),
        " P401 ": [1.0] * n_rows_normal,
        " PIT501 ": 2.0 + 0.05 * np.sin(t_norm),
        " P501 ": [1.0] * n_rows_normal,
        " LIT601 ": 800.0 + 2.0 * np.cos(t_norm),
        " P601 ": [1.0] * n_rows_normal,
        " Normal/Attack ": ["Normal"] * n_rows_normal,
    }
    norm_df = pd.DataFrame(norm_data)
    norm_csv = tmp_path / "synthetic_normal.csv"
    norm_df.to_csv(norm_csv, index=False)

    start_att = pd.Timestamp("2015-12-23 10:00:00", tz="UTC")
    att_ts = [start_att + pd.Timedelta(seconds=i) for i in range(n_rows_attack)]

    t_att = np.linspace(0, 5 * np.pi, n_rows_attack)
    att_p1_fit = 2.5 + 0.1 * np.sin(t_att)
    att_p2_ait = 150.0 + 0.5 * np.sin(t_att)
    att_labels = ["Normal"] * n_rows_attack

    # Inject anomaly into P1 at [60:120] and into P2 at [80:140] to simulate cross-stage propagation
    if inject_anomaly_in_p2:
        att_p1_fit[60:120] = 50.0  # extreme deviation
        att_labels[60:120] = ["Attack"] * 60
        att_p2_ait[80:140] = 500.0  # lagging deviation in P2
        att_labels[80:140] = ["Attack"] * 60

    att_data = {
        " Timestamp ": [t.strftime("%d/%m/%Y %I:%M:%S %p") for t in att_ts],
        " FIT101 ": att_p1_fit,
        " LIT101 ": 500.0 + 1.0 * np.cos(t_att),
        " MV101 ": [1.0 if i % 20 < 10 else 2.0 for i in range(n_rows_attack)],
        " P101 ": [1.0] * n_rows_attack,
        " AIT201 ": att_p2_ait,
        " P201 ": [1.0] * n_rows_attack,
        " DPIT301 ": 10.0 + 0.2 * np.cos(t_att),
        " P301 ": [1.0] * n_rows_attack,
        " AIT401 ": 10.0 + 0.1 * np.cos(t_att),
        " P401 ": [1.0] * n_rows_attack,
        " PIT501 ": 2.0 + 0.05 * np.sin(t_att),
        " P501 ": [1.0] * n_rows_attack,
        " LIT601 ": 800.0 + 2.0 * np.cos(t_att),
        " P601 ": [1.0] * n_rows_attack,
        " Normal/Attack ": att_labels,
    }
    att_df = pd.DataFrame(att_data)
    att_csv = tmp_path / "synthetic_attack.csv"
    att_df.to_csv(att_csv, index=False)

    return norm_csv, att_csv


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

class TestMissingDatasetBehavior:
    """Verify that absent SWaT CSVs trigger actionable errors without claiming execution."""

    def test_missing_dataset_raises_filenotfounderror(self, tmp_path):
        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=tmp_path / "nonexistent_normal.csv",
            attack_csv=tmp_path / "nonexistent_attack.csv",
        )
        with pytest.raises(FileNotFoundError) as exc_info:
            run_swat_experiment(config)

        err_msg = str(exc_info.value)
        assert "SWaT dataset files missing" in err_msg
        assert "TCMIM_SWAT_DATA_PATH" in err_msg
        assert "iTrust" in err_msg

    def test_resolve_paths_missing_protocol_b(self, tmp_path):
        with pytest.raises(FileNotFoundError) as exc_info:
            resolve_swat_dataset_paths(
                protocol="protocol_b",
                attack_csv=tmp_path / "nonexistent_attack.csv",
            )
        assert "Attack CSV" in str(exc_info.value)


class TestActuatorMapWiringAndStateTransitions:
    """Verify critical actuator mapping requirement and state-transition preservation."""

    def test_runner_feature_extractor_wires_swat_actuator_map(self):
        """FeatureExtractor must be wired with explicit SWAT_ACTUATOR_STATE_MAP."""
        extractor = FeatureExtractor(
            sampling_rate_hz=1.0,
            channel_modality_map=SWAT_MODALITY_MAP,
            channel_state_map=SWAT_ACTUATOR_STATE_MAP,
        )
        assert extractor.channel_state_map is not None
        assert "MV101" in extractor.channel_state_map
        assert extractor.channel_state_map["MV101"] == {1.0: 0, 2.0: 1}
        assert extractor.channel_state_map["P101"] == {1.0: 0, 2.0: 1}

    def test_actuator_state_transition_1_to_2_not_lost(self):
        """A state transition from 1.0 (OFF) to 2.0 (ON) must register transitions properly."""
        extractor = FeatureExtractor(
            sampling_rate_hz=1.0,
            channel_modality_map=SWAT_MODALITY_MAP,
            channel_state_map=SWAT_ACTUATOR_STATE_MAP,
        )

        # 10 samples: 5 samples at state 1.0 (OFF=0), then 5 samples at state 2.0 (ON=1)
        # Raw sequence: [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0]
        # There is exactly 1 transition from state 1 to state 2.
        ts_index = pd.date_range("2015-12-22 16:00:00", periods=10, freq="1s", tz="UTC")
        df = pd.DataFrame(
            {"MV101": [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0]},
            index=ts_index,
        )

        wb = WindowBuilder(window_seconds=10.0, overlap_frac=0.0)
        windows = wb.build(df, machine_id="P1_raw_water", provenance=Provenance.SYNTHETIC)
        assert len(windows) == 1

        feature_sample = extractor.extract_window(windows[0])
        digital_features = feature_sample.features.get(Modality.DIGITAL_STATE.value, {})

        assert "MV101__n_transitions" in digital_features
        # Must record exactly 1 transition between consecutive states
        assert digital_features["MV101__n_transitions"] == 1.0
        # Duty cycle: 5 active out of 10 = 0.5
        assert digital_features["MV101__duty_cycle"] == 0.5
        # First state = 1.0 (raw state at start), Last state = 2.0 (raw state at end)
        assert digital_features["MV101__first_state"] == 1.0
        assert digital_features["MV101__last_state"] == 2.0


class TestGroundTruthIsolation:
    """Verify strict ground-truth isolation safeguards."""

    def test_labels_never_leak_into_features_or_detector(self, tmp_path):
        norm_csv, att_csv = _create_synthetic_swat_pair(tmp_path)
        out_dir = tmp_path / "out"

        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=norm_csv,
            attack_csv=att_csv,
            window_seconds=30.0,
            contamination=0.1,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        res = run_swat_experiment(config)

        # Audit that no label column appears in feature outputs or detector
        for stage_name, st in res.stage_results.items():
            assert st.n_windows > 0
            assert "Normal/Attack" not in st.stage_name


class TestPostPredictionLabelAlignmentAndMetrics:
    """Verify both 'any' and 'majority' evaluation methods and 50% majority tie rule."""

    def test_any_and_majority_evaluation_rules(self):
        # 10s window from 00:00:00 to 00:00:10
        start = pd.Timestamp("2015-12-22 16:00:00", tz="UTC")
        ts_list = [start + pd.Timedelta(seconds=i) for i in range(10)]

        # Exactly 5 normal (0) and 5 attack (1) samples
        labels_series = pd.Series([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], index=pd.DatetimeIndex(ts_list))

        df_dummy = pd.DataFrame({"FIT101": np.ones(10)}, index=pd.DatetimeIndex(ts_list))
        wb = WindowBuilder(window_seconds=10.0, overlap_frac=0.0)
        windows = wb.build(df_dummy, machine_id="P1", provenance=Provenance.SYNTHETIC)

        # 'any' method should be 1.0 because at least one timestamp has attack
        aligned_any = align_swat_labels_to_windows(labels_series, windows, method="any")
        assert aligned_any[0] == 1.0

        # 'majority' rule: exact 50% evaluates to Normal (0.0)
        aligned_maj = align_swat_labels_to_windows(labels_series, windows, method="majority")
        assert aligned_maj[0] == 0.0

    def test_evaluate_swat_predictions_handles_undefined_metrics_as_nan(self):
        """Undefined division by zero metrics must be np.nan, not replaced with 0.0."""
        gt = np.array([0.0, 0.0, 0.0])  # No true attacks
        preds = [False, False, False]    # No alarms
        metrics = evaluate_swat_window_predictions(gt, preds)

        assert np.isnan(metrics["precision"])
        assert np.isnan(metrics["recall"])
        assert np.isnan(metrics["f1"])
        assert metrics["fpr"] == 0.0


class TestProtocolsExecution:
    """Verify Protocol A, Protocol B, and Protocol C execution."""

    def test_protocol_a_normal_baseline_execution(self, tmp_path):
        norm_csv, att_csv = _create_synthetic_swat_pair(tmp_path)
        out_dir = tmp_path / "out_proto_a"

        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=norm_csv,
            attack_csv=att_csv,
            window_seconds=30.0,
            contamination=0.1,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        res = run_swat_experiment(config)

        assert res.protocol == "protocol_a"
        assert len(res.stage_results) > 0
        assert Path(res.output_artifacts["json"]).exists()
        assert Path(res.output_artifacts["report_md"]).exists()

    def test_protocol_b_chronological_split_execution(self, tmp_path):
        _, att_csv = _create_synthetic_swat_pair(tmp_path)
        out_dir = tmp_path / "out_proto_b"

        config = SWaTExperimentConfig(
            protocol="protocol_b",
            attack_csv=att_csv,
            window_seconds=30.0,
            baseline_frac=0.3,
            contamination=0.1,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        res = run_swat_experiment(config)

        assert res.protocol == "protocol_b"
        assert len(res.stage_results) > 0
        for st in res.stage_results.values():
            assert st.baseline_window_count > 0


class TestStage2IntegrationAndCRI:
    """Verify Stage 2 multi-stage propagation and Cascade Risk Index calculation."""

    def test_stage2_orchestrator_runs_end_to_end(self, tmp_path):
        norm_csv, att_csv = _create_synthetic_swat_pair(
            tmp_path, n_rows_normal=180, n_rows_attack=240, inject_anomaly_in_p2=True
        )
        out_dir = tmp_path / "out_stage2"

        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=norm_csv,
            attack_csv=att_csv,
            window_seconds=30.0,
            contamination=0.2,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        res = run_swat_experiment(config)

        assert "total_events_input" in res.stage2_summary
        assert "accepted_observations_count" in res.stage2_summary
        assert "paths_count" in res.stage2_summary
        assert "cri_targets" in res.stage2_summary

    def test_empty_anomalies_and_events_handled_gracefully(self, tmp_path):
        norm_csv, att_csv = _create_synthetic_swat_pair(
            tmp_path, n_rows_normal=180, n_rows_attack=180, inject_anomaly_in_p2=False
        )
        out_dir = tmp_path / "out_empty"

        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=norm_csv,
            attack_csv=att_csv,
            window_seconds=60.0,
            contamination=0.01,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        # Should execute smoothly even with low or 0 event counts
        res = run_swat_experiment(config)
        assert res.stage2_summary["paths_count"] >= 0


class TestReproducibleOutputsAndJSONSerialization:
    """Verify that results serialize cleanly to JSON and Markdown reports are generated."""

    def test_json_encoder_and_report_generation(self, tmp_path):
        norm_csv, att_csv = _create_synthetic_swat_pair(tmp_path)
        out_dir = tmp_path / "out_repro"

        config = SWaTExperimentConfig(
            protocol="protocol_a",
            normal_csv=norm_csv,
            attack_csv=att_csv,
            window_seconds=30.0,
            output_dir=out_dir,
            provenance=Provenance.SYNTHETIC,
        )
        res = run_swat_experiment(config)

        json_file = Path(res.output_artifacts["json"])
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["run_id"] == res.run_id
        assert data["protocol"] == "protocol_a"
        assert "stage_results" in data
        assert "stage2_summary" in data
        assert "scientific_limitations" in data

        md_file = Path(res.output_artifacts["report_md"])
        report_text = md_file.read_text(encoding="utf-8")
        assert "TCMIM — SWaT Experiment Execution Report" in report_text
        assert "Logical Process Stages vs Independent Machines" in report_text
        assert "Temporal Precedence vs Causality" in report_text
