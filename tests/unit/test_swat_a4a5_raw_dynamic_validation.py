"""
tests/unit/test_swat_a4a5_raw_dynamic_validation.py
===================================================
Unit tests for Stage 2 Raw Telemetry Dynamic Validation.

Verifies:
- Raw workbook fingerprint and dataset integrity.
- Timestamp ordering, sampling resolution, and cadence statistics.
- Independent episode construction, deduplication, and dependency tracking.
- Startup and shutdown separation.
- Prevention of development/validation event leakage (temporal partitioning).
- Correct units and delay calculation bounds.
- Rejection of non-identifiable / misidentified pathways (P101 -> FIT101).
- Validation metrics and reproducible output generation under fixed configurations.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

_project_root = Path(__file__).resolve().parent.parent.parent
_raw_data_path = (
    _project_root
    / "data"
    / "raw"
    / "SWAT_A4_A5_JULY_2019"
    / "SWaT_dataset_Jul 19 v2.xlsx"
)
_validation_dir = (
    _project_root
    / "experiments"
    / "results"
    / "swat_a4a5_raw_dynamic_validation"
)

EXPECTED_RAW_SHA256 = "39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc"

skip_if_no_raw_workbook = pytest.mark.skipif(
    not _raw_data_path.exists(),
    reason=(
        "Raw SWaT July 2019 workbook not found at data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx — "
        "skipping raw dataset fingerprint verification. To run, place the workbook in data/raw/."
    ),
)


@skip_if_no_raw_workbook
class TestRawDatasetIntegrity:
    """Verify raw dataset presence and SHA-256 fingerprint."""

    def test_raw_dataset_exists(self) -> None:
        assert _raw_data_path.exists(), f"Raw dataset missing at {_raw_data_path}"

    def test_raw_dataset_sha256(self) -> None:
        raw_bytes = _raw_data_path.read_bytes()
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        assert actual_sha == EXPECTED_RAW_SHA256, (
            f"Dataset SHA-256 mismatch! Expected {EXPECTED_RAW_SHA256}, got {actual_sha}"
        )


class TestArtifactsAndCadence:
    """Verify generated dynamic validation artifacts and cadence audit."""

    @pytest.fixture
    def metrics(self) -> Dict[str, Any]:
        json_path = _validation_dir / "episode_validation_metrics.json"
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_all_expected_artifacts_exist(self) -> None:
        expected_files = [
            "physical_response_episodes.csv",
            "response_parameter_estimates.csv",
            "episode_validation_metrics.json",
            "delay_bound_assessment.md",
            "limitations_and_next_steps.md",
            "raw_dynamic_validation_report.md",
            "change_manifest.json",
        ]
        for fname in expected_files:
            fpath = _validation_dir / fname
            assert fpath.exists(), f"Missing artifact {fname} in {_validation_dir}"
            assert fpath.stat().st_size > 0, f"Artifact {fname} is empty"

    def test_response_curves_exist(self) -> None:
        plots_dir = _validation_dir / "response_curves"
        assert plots_dir.exists() and plots_dir.is_dir()
        expected_plots = [
            "p301_dpit301_startup_curves.png",
            "p301_dpit301_shutdown_curves.png",
            "mv201_fit201_opening_curves.png",
            "mv201_fit201_closing_curves.png",
            "p101_fit101_non_responsiveness.png",
            "summary_response_dynamics.png",
        ]
        for pname in expected_plots:
            ppath = plots_dir / pname
            assert ppath.exists(), f"Missing plot {pname} in {plots_dir}"
            assert ppath.stat().st_size > 1000, f"Plot {pname} is too small"

    def test_timestamp_cadence_audit(self, metrics: Dict[str, Any]) -> None:
        cadence = metrics["dataset_metadata"]["cadence_audit"]
        assert cadence["total_records"] == 14996
        assert cadence["median_dt_seconds"] == pytest.approx(1.0, abs=1e-3)
        assert cadence["duplicate_timestamps_count"] == 0
        assert cadence["effective_temporal_resolution_seconds"] == 1.0
        assert cadence["gaps_greater_than_1_5s_count"] == 6


class TestPhysicalResponseEpisodes:
    """Verify episode extraction, deduplication, and leakage prevention."""

    @pytest.fixture
    def episodes(self) -> List[Dict[str, str]]:
        csv_path = _validation_dir / "physical_response_episodes.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_episode_count_and_columns(self, episodes: List[Dict[str, str]]) -> None:
        assert len(episodes) == 37, f"Expected 37 extracted episodes, got {len(episodes)}"
        required_cols = {
            "relationship",
            "episode_id",
            "direction",
            "partition",
            "source_transition_utc",
            "target_response_onset_utc",
            "source_from_state",
            "source_to_state",
            "target_val_before",
            "target_val_after",
            "delay_s",
            "inclusion_status",
        }
        assert required_cols.issubset(episodes[0].keys())

    def test_startup_shutdown_separation(self, episodes: List[Dict[str, str]]) -> None:
        p301_eps = [e for e in episodes if e["relationship"] == "P301 -> DPIT301"]
        directions = {e["direction"] for e in p301_eps}
        assert directions == {"STARTUP", "SHUTDOWN"}
        for e in p301_eps:
            if e["direction"] == "STARTUP":
                assert e["source_from_state"] == "1" and e["source_to_state"] == "2"
            elif e["direction"] == "SHUTDOWN":
                assert e["source_from_state"] == "2" and e["source_to_state"] == "1"

    def test_no_development_validation_leakage(self, episodes: List[Dict[str, str]]) -> None:
        for e in episodes:
            row_idx = int(e["row_index"])
            if e["partition"] == "development":
                assert row_idx < 8400, f"Development episode {e['episode_id']} leaked into held-out partition!"
            elif e["partition"] == "validation":
                assert row_idx >= 8400, f"Validation episode {e['episode_id']} fell into development partition!"

    def test_p101_marked_excluded_misidentified(self, episodes: List[Dict[str, str]]) -> None:
        p101_eps = [e for e in episodes if e["relationship"] == "P101 -> FIT101"]
        assert len(p101_eps) == 12
        for e in p101_eps:
            assert e["inclusion_status"] == "EXCLUDED_MISIDENTIFIED_COUPLING"
            assert "FIT101 is raw intake inflow governed by MV101" in e["inclusion_exclusion_reason"]
            assert e["target_response_onset_utc"].startswith("N/A")


class TestModelFittingAndValidationMetrics:
    """Verify held-out validation metrics and parameter estimates."""

    @pytest.fixture
    def metrics(self) -> Dict[str, Any]:
        json_path = _validation_dir / "episode_validation_metrics.json"
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def parameters(self) -> List[Dict[str, str]]:
        csv_path = _validation_dir / "response_parameter_estimates.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_p301_dpit301_validation_performance(self, metrics: Dict[str, Any]) -> None:
        m = metrics["models"]["P301_to_DPIT301"]
        assert m["status"] == "VALIDATED_STATE_DEPENDENT"
        # Normal startup R2 must be > 0.95
        r2_norm = m["startup_model"]["normal_held_out_validation"]["r_squared"]
        assert r2_norm >= 0.95, f"Expected high R2 for normal P301 startups, got {r2_norm}"
        # Attack A6 failure must be documented with negative R2
        r2_a6 = m["startup_model"]["attack_a6_confounded_validation"]["r_squared"]
        assert r2_a6 < 0.0, f"Expected negative R2 for Attack A6 confounded startup, got {r2_a6}"
        # Shutdown R2 must be > 0.95
        r2_shut = m["shutdown_model"]["held_out_validation"]["r_squared"]
        assert r2_shut >= 0.95, f"Expected high R2 for P301 shutdown decay, got {r2_shut}"

    def test_mv201_fit201_validation_performance(self, metrics: Dict[str, Any]) -> None:
        m = metrics["models"]["MV201_to_FIT201"]
        assert m["status"] == "VALIDATED_FOPDT"
        r2_open = m["opening_model"]["held_out_validation"]["r_squared"]
        assert r2_open >= 0.80, f"Expected R2 >= 0.80 for MV201 opening, got {r2_open}"
        dead_time = m["opening_model"]["fitted_parameters"]["dead_time_td_s"]
        assert 8.0 <= dead_time <= 15.0, f"Expected stroke dead time ~10s, got {dead_time}"

    def test_p101_fit101_diagnosed_not_identifiable(self, metrics: Dict[str, Any]) -> None:
        m = metrics["models"]["P101_to_FIT101"]
        assert m["status"] == "NOT_IDENTIFIABLE_MISIDENTIFIED_PATHWAY"
        assert m["correlation_with_P101"] == pytest.approx(0.0528, abs=1e-3)
        assert m["correlation_with_MV101"] == pytest.approx(0.9259, abs=1e-3)
        assert m["held_out_validation"]["status"] == "INFEASIBLE"

    def test_parameter_estimates_units_and_sample_sizes(
        self, parameters: List[Dict[str, str]]
    ) -> None:
        valid_units = {"seconds", "kPa", "m3/h"}
        for p in parameters:
            assert p["units"] in valid_units
            if p["relationship"] == "P101 -> FIT101":
                assert int(p["effective_sample_size"]) == 0
                assert p["estimate"] == "" or np.isnan(float(p["estimate"]))
            else:
                assert int(p["effective_sample_size"]) >= 3
                assert float(p["estimate"]) >= 0.0
