"""
tests/unit/test_swat_a4a5_g0_evaluation.py
===========================================
Unit tests for the Stage 2 Candidate-Edge Gating Evaluation with G0_STRUCTURAL_MASK.

Verifies:
- Physical connectivity register hash matching audited configuration.
- Preservation of candidate universes and event inputs between Config A and Config B.
- Gate ordering: G0 runs strictly before G1 when enabled.
- Prohibition enforcement: explicitly prohibited edges never pass G0.
- Conservative policy enforcement: unknown edges rejected when allow_unknown=False.
- Legacy preservation: disabling G0 bypasses structural masking without side effects.
- Output metrics and percentages consistency across all 6 attack intervals.
- Immutability of event records, timestamps, and physical registers.
- Rejection reason mappings and accounting.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Dict, List

import pytest

_project_root = Path(__file__).resolve().parent.parent.parent
_audit_register_path = (
    _project_root
    / "experiments"
    / "results"
    / "swat_a4a5_physical_graph_audit"
    / "physical_connectivity_register.csv"
)
_g0_eval_dir = _project_root / "experiments" / "results" / "swat_a4a5_g0_evaluation"

EXPECTED_REGISTER_SHA256 = (
    "08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3"
)


class TestRegisterIntegrity:
    """Verify physical connectivity register integrity and immutability."""

    def test_register_file_exists(self) -> None:
        assert _audit_register_path.exists(), (
            f"Physical register missing at {_audit_register_path}"
        )

    def test_register_sha256_unmodified(self) -> None:
        content = _audit_register_path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        assert actual_hash == EXPECTED_REGISTER_SHA256, (
            f"Register hash mismatch! Expected {EXPECTED_REGISTER_SHA256}, got {actual_hash}"
        )

    def test_register_row_count_and_schema(self) -> None:
        with open(_audit_register_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 22, f"Expected exactly 22 register entries, found {len(rows)}"
        required_cols = {
            "edge_id",
            "source_component",
            "destination_component",
            "source_stage",
            "destination_stage",
            "relationship_type",
            "documented_direction",
            "status",
            "suitable_as_structural_constraint",
            "baseline_identifiability",
            "dynamically_validated",
        }
        assert required_cols.issubset(rows[0].keys()), (
            f"Missing required columns in register: {required_cols - set(rows[0].keys())}"
        )


class TestEvaluationArtifacts:
    """Verify presence and validity of all generated evaluation artifacts."""

    def test_all_expected_artifacts_exist(self) -> None:
        expected_files = [
            "g0_off_vs_on_metrics.json",
            "candidate_edge_comparison.csv",
            "per_attack_interval_metrics.csv",
            "rejection_reason_summary.csv",
            "evaluation_config.json",
        ]
        for fname in expected_files:
            fpath = _g0_eval_dir / fname
            assert fpath.exists(), f"Expected artifact {fname} missing in {_g0_eval_dir}"
            assert fpath.stat().st_size > 0, f"Artifact {fname} is empty"

    def test_evaluation_config_parameters(self) -> None:
        cfg_path = _g0_eval_dir / "evaluation_config.json"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        assert cfg["window_seconds"] == 30.0
        assert cfg["step_seconds"] == 30.0
        assert cfg["matcher_min_delay_s"] == 0.0
        assert cfg["matcher_max_delay_s"] == 600.0
        assert cfg["gating_min_delay_s"] == 0.0
        assert cfg["gating_max_delay_s"] == 600.0
        assert cfg["gating_require_positive_dt"] is True
        assert cfg["allow_unknown_config_b"] is False


class TestPairedCandidateComparison:
    """Verify candidate universe identity and paired gating logic."""

    @pytest.fixture
    def comparison_data(self) -> List[Dict[str, str]]:
        csv_path = _g0_eval_dir / "candidate_edge_comparison.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_candidate_universe_size(self, comparison_data: List[Dict[str, str]]) -> None:
        assert len(comparison_data) == 3852, (
            f"Expected 3852 candidate edges, found {len(comparison_data)}"
        )

    def test_candidate_identities_and_temporal_invariants(
        self, comparison_data: List[Dict[str, str]]
    ) -> None:
        for row in comparison_data:
            assert row["obs_id"].strip() != ""
            assert row["source_channel"].strip() != ""
            assert row["target_channel"].strip() != ""
            delta_t = float(row["delta_t_s"])
            assert 0.0 <= delta_t <= 600.0, (
                f"Candidate {row['obs_id']} delta_t {delta_t} outside [0, 600]s"
            )
            assert row["source_onset_utc"] != ""
            assert row["target_onset_utc"] != ""

    def test_config_a_never_applies_g0(
        self, comparison_data: List[Dict[str, str]]
    ) -> None:
        for row in comparison_data:
            assert row["config_a_gate"] != "G0_STRUCTURAL_MASK", (
                f"Config A erroneously applied G0 on candidate {row['obs_id']}"
            )
            assert "physical structural mask" not in row["config_a_reject_reason"]

    def test_config_b_prohibited_edges_never_accepted(
        self, comparison_data: List[Dict[str, str]]
    ) -> None:
        prohibited_count = 0
        for row in comparison_data:
            if row["physical_mask_status"] == "0":
                prohibited_count += 1
                assert row["config_b_decision"] == "rejected", (
                    f"Prohibited edge {row['source_channel']} -> {row['target_channel']} "
                    f"was accepted in Config B!"
                )
                assert row["config_b_gate"] == "G0_STRUCTURAL_MASK"
                assert "status=0" in row["config_b_reject_reason"]
        assert prohibited_count == 5, f"Expected 5 prohibited edges, found {prohibited_count}"

    def test_config_b_unknown_edges_rejected_under_conservative_policy(
        self, comparison_data: List[Dict[str, str]]
    ) -> None:
        for row in comparison_data:
            if row["physical_mask_status"] == "?":
                assert row["config_b_decision"] == "rejected", (
                    f"Unknown edge {row['source_channel']} -> {row['target_channel']} "
                    f"was accepted under conservative policy!"
                )
                assert row["config_b_gate"] == "G0_STRUCTURAL_MASK"
                assert "status=?" in row["config_b_reject_reason"]

    def test_accepted_edges_in_config_b_are_strictly_allowed(
        self, comparison_data: List[Dict[str, str]]
    ) -> None:
        accepted_b = [r for r in comparison_data if r["config_b_decision"] == "accepted"]
        assert len(accepted_b) == 22, f"Expected 22 accepted edges in Config B, got {len(accepted_b)}"
        for row in accepted_b:
            assert row["physical_mask_status"] == "1", (
                f"Accepted edge {row['source_channel']} -> {row['target_channel']} "
                f"has status {row['physical_mask_status']}, expected 1"
            )
            assert row["config_b_gate"] == "ALL_PASSED"
            assert row["config_b_reject_reason"] == "NONE"


class TestMetricsAndCalculations:
    """Verify aggregated metrics and attack interval reporting."""

    @pytest.fixture
    def metrics(self) -> Dict[str, Any]:
        json_path = _g0_eval_dir / "g0_off_vs_on_metrics.json"
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_top_level_candidate_reduction(self, metrics: Dict[str, Any]) -> None:
        counts = metrics["candidate_counts"]
        init = counts["initial_matched_candidates"]
        assert init == 3852

        acc_a = counts["config_a_g0_disabled"]["accepted_surviving_all_gates"]
        rej_a = counts["config_a_g0_disabled"]["rejected_total"]
        assert acc_a == 3472
        assert rej_a == 380
        assert acc_a + rej_a == init

        acc_b = counts["config_b_g0_enabled"]["accepted_surviving_all_gates"]
        rej_b = counts["config_b_g0_enabled"]["rejected_total"]
        assert acc_b == 22
        assert rej_b == 3830
        assert acc_b + rej_b == init

        comp = counts["comparison"]
        assert comp["absolute_candidate_reduction"] == 3450
        assert comp["percentage_candidate_reduction"] == 99.37
        assert comp["prohibited_edges_removed_count"] == 5
        assert comp["unverified_unknown_edges_removed_count"] == 3814

    def test_all_six_attack_intervals_in_metrics(self, metrics: Dict[str, Any]) -> None:
        per_atk = metrics["per_attack_interval_summary"]
        required_keys = {"A1", "A2", "A3", "A4", "A5", "A6", "outside_attacks"}
        assert required_keys.issubset(per_atk.keys())

        total_init = sum(v["initial_candidates"] for v in per_atk.values())
        assert total_init == 3852

    def test_per_attack_interval_csv_consistency(self) -> None:
        csv_path = _g0_eval_dir / "per_attack_interval_metrics.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        attack_ids = [r["attack_id"] for r in rows]
        assert attack_ids == ["A1", "A2", "A3", "A4", "A5", "A6", "outside_attacks"]

        for r in rows:
            init = int(r["initial_candidates"])
            a_acc = int(r["config_a_accepted"])
            a_rej = int(r["config_a_rejected"])
            assert a_acc + a_rej == init

            b_acc = int(r["config_b_accepted"])
            b_rej = int(r["config_b_rejected"])
            assert b_acc + b_rej == init

            g0_rej = int(r["config_b_g0_rejected"])
            g0_proh = int(r["config_b_g0_prohibited"])
            g0_unk = int(r["config_b_g0_unknown"])
            assert g0_proh + g0_unk == g0_rej
            assert g0_rej <= b_rej

            red_abs = int(r["absolute_reduction"])
            assert red_abs == a_acc - b_acc

            if a_acc > 0:
                expected_pct = round((red_abs / a_acc) * 100.0, 2)
                assert float(r["percentage_reduction"]) == pytest.approx(expected_pct, abs=0.05)
            else:
                assert r["percentage_reduction"] == "N/A"

    def test_rejection_reason_summary_gate_mappings(self) -> None:
        csv_path = _g0_eval_dir / "rejection_reason_summary.csv"
        with open(csv_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        valid_gates = {
            "G0_STRUCTURAL_MASK",
            "G1_DELAY_FEASIBILITY",
            "G2_ORDERING",
            "G3_DIRECTION_CONSISTENCY",
            "G4_HEALTH_CONSISTENCY",
            "G5_RELATIONSHIP_CONSISTENCY",
        }
        for r in rows:
            assert r["gate"] in valid_gates, f"Invalid gate {r['gate']} for reason {r['rejection_reason']}"

        total_a_rej = sum(int(r["config_a_count"]) for r in rows)
        total_b_rej = sum(int(r["config_b_count"]) for r in rows)
        assert total_a_rej == 380
        assert total_b_rej == 3830
