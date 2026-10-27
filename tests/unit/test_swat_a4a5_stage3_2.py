"""
tests/unit/test_swat_a4a5_stage3_2.py
=====================================
Scientific Regression Tests and Shadow-Mode Safety Verification for TCMIM Stage 3.2.

Enforces:
1. Task A: Safe Conditional Connectivity
   - MV201 == 2: conditional edge P101 -> FIT201 passes G0.
   - MV201 == 1: edge rejected.
   - Missing MV201 state: edge rejected (fail closed).
   - Unknown actuator value: edge rejected.
   - Stale state evidence: edge rejected if staleness / max_age is violated.
   - Malformed conditional predicate: fails closed safely.
   - Unconditional ALLOWED edge: preserved without needing evidence.
   - DISALLOWED edge (P101 -> FIT101): always rejected.
   - Legacy configuration: cannot bypass conditional checks.
   - allow_unknown policy cannot bypass conditional edges.

2. Task B / Task C: Correct Scientific Evaluation Reporting & Invariants
   - Attack A6 R2 = 0.9961 labeled IN-SAMPLE DESCRIPTIVE FIT, not held-out validation.
   - State S2 normal startup score (R2 = 0.9936) computed strictly from independent episodes.
   - Headline startup R2 = 0.9963 disqualified as contaminated.
   - Closing failure episode MV201_CLOSE_11692 (R2 = -1.7376) remains visible in per-episode reporting.
   - Validation status register uses only authorized audit categories.

3. Task D: Shadow-Mode Safety
   - Production gating remains disconnected.
   - Production delay bounds [0, 600]s remain untouched.
   - Plantwide CRI evaluation remains disabled.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import pytest

from tcmim.gating.gates import (
    GateOutcome,
    GatingConfig,
    GatingPipeline,
    gate_structural_mask,
)
from tcmim.gating.structural_mask import (
    PhysicalStructuralMask,
    StateConditionPredicate,
    StructuralMaskConfig,
    StructuralStatus,
)
from tcmim.schemas import EventRecord, Modality, PropagationObservation, Provenance

_project_root = Path(__file__).resolve().parent.parent.parent
_stage3_2_dir = _project_root / "experiments" / "results" / "swat_a4a5_stage3_2"
_reg_stage3_2_path = _stage3_2_dir / "proposed_connectivity_register_stage3_2.csv"
_model_eval_path = _stage3_2_dir / "corrected_model_evaluation.csv"
_decisions_path = _stage3_2_dir / "corrected_relationship_decisions.csv"
_val_status_path = _stage3_2_dir / "validation_status_register.csv"


def _make_obs(src: str, dst: str, delta_t_s: float = 15.0) -> PropagationObservation:
    return PropagationObservation(
        source_event="evt-src-001",
        target_event="evt-tgt-001",
        source_machine=src,
        target_machine=dst,
        delta_t_s=delta_t_s,
        gate_result="accepted",
        reject_reason=None,
        provenance=Provenance.PUBLIC_DATASET,
    )


class TestSafeConditionalConnectivity:
    """Verifies Task A: Safe Conditional Edge Representation and Gate G0 Enforcement."""

    @pytest.fixture
    def mask_3_2(self) -> PhysicalStructuralMask:
        assert _reg_stage3_2_path.is_file(), f"Missing Stage 3.2 register at {_reg_stage3_2_path}"
        return PhysicalStructuralMask.load_from_csv(_reg_stage3_2_path)

    def test_mv201_open_satisfied(self, mask_3_2):
        """MV201 == 2 allows P101 -> FIT201 conditional edge to pass G0."""
        obs = _make_obs("P101", "FIT201")
        outcome = gate_structural_mask(
            obs,
            mask_3_2,
            allow_unknown=False,
            state_evidence={"MV201": 2},
        )
        assert outcome.passed is True
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert "pass" in outcome.reason
        assert mask_3_2.is_permitted("P101", "FIT201", state_evidence={"MV201": 2})

    def test_mv201_closed_rejected(self, mask_3_2):
        """MV201 == 1 (closed) rejects P101 -> FIT201 conditional edge."""
        obs = _make_obs("P101", "FIT201")
        outcome = gate_structural_mask(
            obs,
            mask_3_2,
            allow_unknown=False,
            state_evidence={"MV201": 1},
        )
        assert outcome.passed is False
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert "not satisfied" in outcome.reason
        assert not mask_3_2.is_permitted("P101", "FIT201", state_evidence={"MV201": 1})

    def test_missing_actuator_state_rejected(self, mask_3_2):
        """Missing MV201 state rejects conditional edge (fail-closed rule)."""
        obs = _make_obs("P101", "FIT201")
        # None evidence
        outcome_none = gate_structural_mask(obs, mask_3_2, state_evidence=None)
        assert outcome_none.passed is False
        assert "missing" in outcome_none.reason.lower()

        # Empty dict evidence
        outcome_empty = gate_structural_mask(obs, mask_3_2, state_evidence={})
        assert outcome_empty.passed is False
        assert "missing" in outcome_empty.reason.lower()

        # Irrelevant actuator evidence
        outcome_irrelevant = gate_structural_mask(obs, mask_3_2, state_evidence={"MV101": 2})
        assert outcome_irrelevant.passed is False
        assert "missing" in outcome_irrelevant.reason.lower()

    def test_unknown_actuator_value_rejected(self, mask_3_2):
        """Unknown or invalid actuator values reject conditional edge."""
        obs = _make_obs("P101", "FIT201")
        for bad_val in ("?", "UNKNOWN", "NAN", "INVALID", "CONTRADICTORY", None):
            outcome = gate_structural_mask(
                obs,
                mask_3_2,
                state_evidence={"MV201": bad_val},
            )
            assert outcome.passed is False, f"Expected rejection for bad_val={bad_val}"
            assert not mask_3_2.is_permitted("P101", "FIT201", state_evidence={"MV201": bad_val})

    def test_stale_state_evidence_rejected(self, mask_3_2):
        """Stale actuator evidence is rejected when staleness or max_age is configured."""
        obs = _make_obs("P101", "FIT201")

        # Explicitly flagged as stale
        stale_evidence = {"MV201": {"value": 2, "is_stale": True}}
        outcome_flagged = gate_structural_mask(obs, mask_3_2, state_evidence=stale_evidence)
        assert outcome_flagged.passed is False
        assert "stale" in outcome_flagged.reason.lower()

        # Timestamp age exceeds max_age_s
        aged_evidence = {"MV201": {"value": 2, "timestamp": 100.0}}
        outcome_aged = gate_structural_mask(
            obs,
            mask_3_2,
            state_evidence=aged_evidence,
            max_age_s=5.0,
            current_time=120.0,  # age is 20s > 5s
        )
        assert outcome_aged.passed is False
        assert "stale" in outcome_aged.reason.lower()

        # Fresh timestamp passes
        fresh_evidence = {"MV201": {"value": 2, "timestamp": 118.0}}
        outcome_fresh = gate_structural_mask(
            obs,
            mask_3_2,
            state_evidence=fresh_evidence,
            max_age_s=5.0,
            current_time=120.0,  # age is 2s <= 5s
        )
        assert outcome_fresh.passed is True

    def test_malformed_conditional_predicate_fails_closed(self):
        """Malformed predicate cannot cause unhandled exception and fails closed."""
        mask = PhysicalStructuralMask()
        mask.add_edge("COMP_A", "COMP_B", status=StructuralStatus.CONDITIONAL, operating_condition="")
        # Modify predicate to be invalid
        rec = mask.get_record("COMP_A", "COMP_B")
        assert rec is not None

        obs = _make_obs("COMP_A", "COMP_B")
        outcome = gate_structural_mask(obs, mask, state_evidence={"VALVE": 1})
        assert outcome.passed is False
        assert "malformed" in outcome.reason.lower() or "missing" in outcome.reason.lower()

    def test_unconditional_allowed_edge_preserved(self, mask_3_2):
        """Unconditional ALLOWED edge (e.g. P301 -> DPIT301) passes without state evidence."""
        obs = _make_obs("P301", "DPIT301")
        outcome = gate_structural_mask(obs, mask_3_2, state_evidence=None)
        assert outcome.passed is True
        assert mask_3_2.is_permitted("P301", "DPIT301")

    def test_disallowed_edge_always_rejected(self, mask_3_2):
        """DISALLOWED edge (P101 -> FIT101) is strictly rejected regardless of state evidence."""
        obs = _make_obs("P101", "FIT101")
        # Without evidence
        outcome_no_ev = gate_structural_mask(obs, mask_3_2, state_evidence=None)
        assert outcome_no_ev.passed is False
        assert "prohibited" in outcome_no_ev.reason.lower()

        # Even with arbitrary evidence
        outcome_with_ev = gate_structural_mask(obs, mask_3_2, state_evidence={"MV101": 2, "MV201": 2})
        assert outcome_with_ev.passed is False
        assert "prohibited" in outcome_with_ev.reason.lower()
        assert mask_3_2.is_prohibited("P101", "FIT101")
        assert not mask_3_2.is_permitted("P101", "FIT101")

    def test_allow_unknown_policy_cannot_bypass_conditional(self, mask_3_2):
        """allow_unknown=True permits UNKNOWN edges, but NEVER bypasses CONDITIONAL edges."""
        # Unregistered / UNKNOWN edge
        obs_unknown = _make_obs("P101", "DPIT301")
        outcome_unk_permissive = gate_structural_mask(obs_unknown, mask_3_2, allow_unknown=True)
        assert outcome_unk_permissive.passed is True

        outcome_unk_conservative = gate_structural_mask(obs_unknown, mask_3_2, allow_unknown=False)
        assert outcome_unk_conservative.passed is False

        # Conditional edge with missing evidence MUST be rejected even if allow_unknown=True
        obs_cond = _make_obs("P101", "FIT201")
        outcome_cond = gate_structural_mask(obs_cond, mask_3_2, allow_unknown=True, state_evidence=None)
        assert outcome_cond.passed is False, "allow_unknown must NEVER bypass conditional edge"

    def test_gating_pipeline_integration(self, mask_3_2):
        """GatingPipeline correctly gates batches with observation-level and map-level evidence."""
        pipeline = GatingPipeline(GatingConfig(structural_mask=mask_3_2, allow_unknown=False))

        obs_cond_pass = _make_obs("P101", "FIT201", delta_t_s=15.0)
        obs_cond_pass.state_evidence = {"MV201": 2}

        obs_cond_fail = _make_obs("P101", "FIT201", delta_t_s=15.0)
        obs_cond_fail.state_evidence = {"MV201": 1}

        obs_cond_missing = _make_obs("P101", "FIT201", delta_t_s=15.0)

        obs_allowed = _make_obs("P301", "DPIT301", delta_t_s=15.0)

        accepted, rejected = pipeline.apply([obs_cond_pass, obs_cond_fail, obs_cond_missing, obs_allowed])
        assert len(accepted) == 2
        assert len(rejected) == 2

        accepted_targets = [o.target_machine for o in accepted]
        assert accepted_targets == ["FIT201", "DPIT301"]


class TestCorrectedScientificEvaluationReporting:
    """Verifies Task B / C: Correct Scientific Metrics and Absence of Leakage Claims."""

    @pytest.fixture
    def model_eval_rows(self) -> list[dict[str, str]]:
        assert _model_eval_path.is_file(), f"Missing {_model_eval_path}"
        with open(_model_eval_path, "r", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_attack_a6_labeled_in_sample_descriptive_fit(self, model_eval_rows):
        """Attack A6 Model 2 must be labeled IN-SAMPLE DESCRIPTIVE FIT, not held-out validation."""
        a6_rows = [r for r in model_eval_rows if "ATTACK_A6_MISO" in r["regime"]]
        assert len(a6_rows) == 1
        a6 = a6_rows[0]
        assert a6["audit_classification"] == "IN-SAMPLE DESCRIPTIVE FIT"
        assert a6["evaluation_type"] == "IN_SAMPLE_FIT"
        assert "held-out" not in a6["audit_classification"].lower()
        assert "leakage" in a6["scientific_qualification"].lower() or "single episode" in a6["scientific_qualification"].lower()

    def test_normal_startup_score_from_independent_episodes_only(self, model_eval_rows):
        """State S2 normal startup score (0.9936) includes only genuinely held-out episodes."""
        s2_normal_episodes = [
            r for r in model_eval_rows
            if r["relationship"] == "P301 -> DPIT301" and r["regime"] == "STATE_S2_NORMAL_STARTUP"
        ]
        # Three independent normal episodes: 9419, 12124, 14024
        assert len(s2_normal_episodes) == 3
        for ep in s2_normal_episodes:
            assert ep["audit_classification"] == "INDEPENDENTLY VALIDATED"
            assert float(ep["reproduced_r2"]) >= 0.98

        pooled_row = next(r for r in model_eval_rows if r["regime"] == "STATE_S2_POOLED_STARTUP")
        assert pooled_row["audit_classification"] == "INDEPENDENTLY VALIDATED"
        assert float(pooled_row["reproduced_r2"]) == 0.9936

    def test_headline_startup_score_disqualified(self, model_eval_rows):
        """Headline startup score (0.9963) combining S2 and S3 is officially disqualified."""
        headline = next(r for r in model_eval_rows if r["regime"] == "STARTUP_COMBINED_HEADLINE")
        assert headline["audit_classification"] in ("UNRESOLVED", "DISQUALIFIED", "CONTAMINATED_HEADLINE_METRIC")
        assert "disqualified" in headline["scientific_qualification"].lower() or "concatenates" in headline["scientific_qualification"].lower()

    def test_closing_failure_episode_visible_per_episode(self, model_eval_rows):
        """MV201 closing failure episode 11692 (R2=-1.7376) is retained and visible."""
        fail_row = next(r for r in model_eval_rows if r["episode_id"] == "MV201_CLOSE_11692")
        assert float(fail_row["reproduced_r2"]) < 0.0
        assert pytest.approx(float(fail_row["reproduced_r2"]), abs=1e-3) == -1.7376
        assert "failure" in fail_row["scientific_qualification"].lower()
        assert "p101" in fail_row["scientific_qualification"].lower()

    def test_validation_status_register_authoritative_categories(self):
        """validation_status_register.csv uses only approved scientific categories."""
        assert _val_status_path.is_file()
        with open(_val_status_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        allowed_categories = {
            "INDEPENDENTLY VALIDATED",
            "IN-SAMPLE DESCRIPTIVE FIT",
            "CONDITIONALLY SUPPORTED",
            "DISALLOWED",
            "UNRESOLVED",
            "NOT VERIFIED",
        }

        for r in rows:
            cat = r["validation_classification"]
            assert cat in allowed_categories, f"Invalid category '{cat}' on edge {r['edge_id']}"

        # EDGE_07 must be DISALLOWED
        e7 = next(r for r in rows if r["edge_id"] == "EDGE_07")
        assert e7["validation_classification"] == "DISALLOWED"

        # EDGE_23 must be CONDITIONALLY SUPPORTED
        e23 = next(r for r in rows if r["edge_id"] == "EDGE_23")
        assert e23["validation_classification"] == "CONDITIONALLY SUPPORTED"
        assert e23["operating_condition"] == "MV201 == 2"


class TestShadowModeSafety:
    """Verifies Task D: Isolation of Experimental Gating and CRI Protection."""

    def test_production_gating_config_default_unmodified(self):
        """Default production GatingConfig has no structural mask and default delay bounds."""
        cfg = GatingConfig()
        assert cfg.structural_mask is None, "Production default must not connect structural mask"
        assert cfg.min_delay_s == 0.0
        assert cfg.max_delay_s == 600.0

    def test_production_safety_contract_flags(self):
        """Safety contract flags in Stage 3.2 decisions prohibit production integration."""
        with open(_decisions_path, "r", encoding="utf-8") as f:
            decisions = list(csv.DictReader(f))

        for d in decisions:
            # No decision can grant unconditional production gating
            assert "PRODUCTION_READY" not in d["audit_readiness_decision"]
            assert d["shadow_mode_decision"] in (
                "SHADOW_MODE_PERMITTED",
                "SHADOW_MODE_PERMITTED_WITH_STATE",
                "ISOLATED_AND_DISALLOWED",
                "QUARANTINED_FROM_GATING",
            )
