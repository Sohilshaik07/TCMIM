"""
tests/unit/test_swat_a4a5_stage4.py
===================================
TCMIM Stage 4 Unit Tests: Operating-State-Aware Experimental Gating.

Verifies:
1. Verified normal state (MV302 == 1) proceeds to regime-specific delay evaluation [5, 55]s.
2. Unvalidated A6-associated regime (MV302 == 2) is quarantined (QUARANTINED_UNVALIDATED_REGIME).
3. Missing MV302 evidence fails closed.
4. Invalid or unknown MV302 values fail closed.
5. Stale and contradictory state evidence fails closed.
6. No attack label is required by the resolver.
7. An unvalidated regime cannot fall through to the global [0, 600] second delay window.
8. Other relationships retain their existing behavior.
9. Production gating remains disconnected.
10. Plantwide CRI remains disabled.
"""

from __future__ import annotations

import inspect
from pathlib import Path
import pytest

from experiments.stage4_experimental_gating import (
    OperatingRegime,
    OperatingStateResolver,
    RegimeResolutionResult,
    StateAwareExperimentalGatingPipeline,
)
from tcmim.gating.gates import GatingConfig, GatingPipeline
from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus
from tcmim.schemas import PropagationObservation, Provenance

_project_root = Path(__file__).resolve().parent.parent.parent
_reg_stage3_2_path = (
    _project_root / "experiments" / "results" / "swat_a4a5_stage3_2" / "proposed_connectivity_register_stage3_2.csv"
)


def _make_obs(src: str, dst: str, delta_t_s: float = 20.0) -> PropagationObservation:
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


@pytest.fixture
def mask_stage3_2() -> PhysicalStructuralMask:
    assert _reg_stage3_2_path.is_file(), f"Missing Stage 3.2 register at {_reg_stage3_2_path}"
    return PhysicalStructuralMask.load_from_csv(_reg_stage3_2_path)


@pytest.fixture
def exp_pipeline(mask_stage3_2) -> StateAwareExperimentalGatingPipeline:
    cfg = GatingConfig(
        structural_mask=mask_stage3_2,
        allow_unknown=False,
        min_delay_s=0.0,
        max_delay_s=600.0,
        require_positive_dt=True,
    )
    return StateAwareExperimentalGatingPipeline(config=cfg)


class TestOperatingStateResolver:
    """Verifies Task 2: OperatingStateResolver unit behavior."""

    def test_mv302_closed_normal_regime(self):
        """MV302 == 1 resolves to STATE_S2_NORMAL with delay bounds [5.0, 55.0]s."""
        res = OperatingStateResolver.resolve_p301_regime({"MV302": 1})
        assert res.regime == OperatingRegime.STATE_S2_NORMAL
        assert res.is_validated is True
        assert res.delay_bounds == (5.0, 55.0)
        assert "validated" in res.reason.lower()
        assert res.actuator == "MV302"
        assert res.actuator_value == 1

    def test_mv302_open_unvalidated_regime(self):
        """MV302 == 2 resolves to STATE_S3_UNVALIDATED without delay bounds."""
        res = OperatingStateResolver.resolve_p301_regime({"MV302": 2})
        assert res.regime == OperatingRegime.STATE_S3_UNVALIDATED
        assert res.is_validated is False
        assert res.delay_bounds is None
        assert "unvalidated" in res.reason.lower()
        assert res.actuator == "MV302"
        assert res.actuator_value == 2

    def test_missing_evidence_fails_closed(self):
        """Missing or empty evidence resolves to UNKNOWN_REGIME."""
        res_none = OperatingStateResolver.resolve_p301_regime(None)
        assert res_none.regime == OperatingRegime.UNKNOWN_REGIME
        assert res_none.is_validated is False
        assert "missing_state_evidence" in res_none.reason.lower()

        res_empty = OperatingStateResolver.resolve_p301_regime({})
        assert res_empty.regime == OperatingRegime.UNKNOWN_REGIME
        assert "missing_actuator_state" in res_empty.reason.lower()

        res_irrelevant = OperatingStateResolver.resolve_p301_regime({"MV101": 1})
        assert res_irrelevant.regime == OperatingRegime.UNKNOWN_REGIME
        assert "missing_actuator_state" in res_irrelevant.reason.lower()

    def test_invalid_values_fail_closed(self):
        """Sentinels, None, non-numeric strings, and uncharacterized states fail closed."""
        for bad_val in ("?", "UNKNOWN", "NAN", "INVALID", "CONTRADICTORY", None, "BAD_STR", 0, -1, 99):
            res = OperatingStateResolver.resolve_p301_regime({"MV302": bad_val})
            assert res.regime == OperatingRegime.UNKNOWN_REGIME, f"Expected UNKNOWN_REGIME for {bad_val}"
            assert res.is_validated is False
            assert res.delay_bounds is None

    def test_stale_and_contradictory_evidence_fails_closed(self):
        """Stale or contradictory telemetry resolves to UNKNOWN_REGIME."""
        # Flagged as stale
        stale_evidence = {"MV302": {"value": 1, "is_stale": True}}
        res_stale = OperatingStateResolver.resolve_p301_regime(stale_evidence)
        assert res_stale.regime == OperatingRegime.UNKNOWN_REGIME
        assert "stale" in res_stale.reason.lower()

        # Age exceeded
        aged_evidence = {"MV302": {"value": 1, "timestamp": 100.0}}
        res_aged = OperatingStateResolver.resolve_p301_regime(
            aged_evidence,
            max_age_s=5.0,
            current_time=120.0,
        )
        assert res_aged.regime == OperatingRegime.UNKNOWN_REGIME
        assert "stale" in res_aged.reason.lower()

        # Bad quality
        bad_quality_evidence = {"MV302": {"value": 1, "quality": "CONTRADICTORY"}}
        res_qual = OperatingStateResolver.resolve_p301_regime(bad_quality_evidence)
        assert res_qual.regime == OperatingRegime.UNKNOWN_REGIME
        assert "quality" in res_qual.reason.lower()

    def test_future_timestamp_fails_closed(self):
        """Telemetry with future timestamp (age < -1.0s) fails closed."""
        future_evidence = {"MV302": {"value": 1, "timestamp": 150.0}}
        res = OperatingStateResolver.resolve_p301_regime(
            future_evidence,
            current_time=120.0,
        )
        assert res.regime == OperatingRegime.UNKNOWN_REGIME
        assert "future_timestamp" in res.reason.lower()

    def test_no_attack_label_in_resolver_signature(self):
        """Resolver does not accept, require, or inspect attack labels."""
        sig = inspect.signature(OperatingStateResolver.resolve_p301_regime)
        param_names = list(sig.parameters.keys())
        assert "attack" not in param_names
        assert "label" not in param_names
        assert "is_attack" not in param_names


class TestStateAwareExperimentalGating:
    """Verifies Task 3: StateAwareExperimentalGatingPipeline end-to-end behavior."""

    def test_verified_normal_state_proceeds_to_regime_specific_delay(self, exp_pipeline):
        """P301 -> DPIT301 in State S2 passes with Δt in [5, 55]s, rejected if outside."""
        # Nominal case: Δt = 20.0s is inside [5.0, 55.0]s
        obs_pass = _make_obs("P301", "DPIT301", delta_t_s=20.0)
        accepted, rejected = exp_pipeline.apply([obs_pass], state_evidence={"MV302": 1})
        assert len(accepted) == 1
        assert len(rejected) == 0
        assert accepted[0].gate_result == "accepted"

        # Boundary test: Δt = 60.0s is inside global [0, 600]s but outside S2 [5.0, 55.0]s
        obs_fail_high = _make_obs("P301", "DPIT301", delta_t_s=60.0)
        accepted, rejected = exp_pipeline.apply([obs_fail_high], state_evidence={"MV302": 1})
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert rejected[0].gate_result == "rejected"
        assert "outside validated state s2 window" in rejected[0].reject_reason.lower()

        # Lower boundary test: Δt = 3.0s is inside global [0, 600]s but below S2 min delay 5.0s
        obs_fail_low = _make_obs("P301", "DPIT301", delta_t_s=3.0)
        accepted, rejected = exp_pipeline.apply([obs_fail_low], state_evidence={"MV302": 1})
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert rejected[0].gate_result == "rejected"
        assert "outside validated state s2 window" in rejected[0].reject_reason.lower()

    def test_unvalidated_a6_regime_is_quarantined(self, exp_pipeline):
        """P301 -> DPIT301 in State S3 (MV302==2) is quarantined and cannot enter G1."""
        # Even with apparent delay Δt = 4.2s (or Δt = 20.0s), must be quarantined
        obs_s3 = _make_obs("P301", "DPIT301", delta_t_s=4.2)
        accepted, rejected = exp_pipeline.apply([obs_s3], state_evidence={"MV302": 2})
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert rejected[0].gate_result == "rejected"
        assert "quarantined_unvalidated_regime" in rejected[0].reject_reason.lower()
        assert "state s3" in rejected[0].reject_reason.lower()

    def test_unvalidated_regime_cannot_fall_through_to_global_window(self, exp_pipeline):
        """Unvalidated regime cannot pass through global [0, 600]s delay window."""
        obs = _make_obs("P301", "DPIT301", delta_t_s=15.0)  # perfectly plausible under [0, 600]
        # State S3
        accepted_s3, rejected_s3 = exp_pipeline.apply([obs], state_evidence={"MV302": 2})
        assert len(accepted_s3) == 0
        assert "quarantined_unvalidated_regime" in rejected_s3[0].reject_reason.lower()

        # Missing state
        accepted_missing, rejected_missing = exp_pipeline.apply([obs], state_evidence={})
        assert len(accepted_missing) == 0
        assert "unknown_operating_state" in rejected_missing[0].reject_reason.lower()

    def test_missing_and_invalid_evidence_fails_closed(self, exp_pipeline):
        """Missing, null, or invalid MV302 evidence fails closed."""
        obs = _make_obs("P301", "DPIT301", delta_t_s=20.0)

        # None evidence
        _, rejected_none = exp_pipeline.apply([obs], state_evidence=None)
        assert len(rejected_none) == 1
        assert "unknown_operating_state" in rejected_none[0].reject_reason.lower()

        # Invalid sentinel
        _, rejected_sentinel = exp_pipeline.apply([obs], state_evidence={"MV302": "UNKNOWN"})
        assert len(rejected_sentinel) == 1
        assert "unknown_operating_state" in rejected_sentinel[0].reject_reason.lower()

    def test_stale_and_contradictory_evidence_fails_closed_in_pipeline(self, exp_pipeline):
        """Stale or contradictory evidence fails closed in pipeline."""
        obs = _make_obs("P301", "DPIT301", delta_t_s=20.0)

        # Stale evidence
        stale_evidence = {"MV302": {"value": 1, "is_stale": True}}
        _, rejected_stale = exp_pipeline.apply([obs], state_evidence=stale_evidence)
        assert len(rejected_stale) == 1
        assert "unknown_operating_state" in rejected_stale[0].reject_reason.lower()

        # Contradictory evidence
        contra_evidence = {"MV302": {"value": 1, "quality": "CONTRADICTORY"}}
        _, rejected_contra = exp_pipeline.apply([obs], state_evidence=contra_evidence)
        assert len(rejected_contra) == 1
        assert "unknown_operating_state" in rejected_contra[0].reject_reason.lower()

    def test_other_relationships_retain_existing_behavior(self, exp_pipeline):
        """Unrelated relationships (e.g. MV101 -> LIT101) retain standard bounds."""
        # Unconditioned allowed edge: MV101 -> LIT101
        obs_other = _make_obs("MV101", "LIT101", delta_t_s=15.0)
        accepted, rejected = exp_pipeline.apply([obs_other], state_evidence={"MV302": 2})
        assert len(accepted) == 1
        assert len(rejected) == 0

        # Out-of-bounds for standard window: Δt = 650s > 600s
        obs_other_toolate = _make_obs("MV101", "LIT101", delta_t_s=650.0)
        accepted, rejected = exp_pipeline.apply([obs_other_toolate], state_evidence={"MV302": 2})
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert "g1_delay_feasibility" in rejected[0].reject_reason.lower() or "outside feasible window" in rejected[0].reject_reason.lower()

    def test_physical_connectivity_preserved_at_g0(self, mask_stage3_2):
        """Physical connectivity of P301 -> DPIT301 remains ALLOWED in structural mask."""
        status = mask_stage3_2.get_status("P301", "DPIT301")
        assert status == StructuralStatus.ALLOWED
        # Structural mask is_permitted remains True
        assert mask_stage3_2.is_permitted("P301", "DPIT301") is True

    def test_allow_unknown_policy_cannot_bypass_operating_state_gate(self, mask_stage3_2):
        """Setting allow_unknown=True on pipeline cannot bypass S3 quarantine or unknown state."""
        cfg_permissive = GatingConfig(
            structural_mask=mask_stage3_2,
            allow_unknown=True,
            min_delay_s=0.0,
            max_delay_s=600.0,
        )
        permissive_pipeline = StateAwareExperimentalGatingPipeline(config=cfg_permissive)
        obs = _make_obs("P301", "DPIT301", delta_t_s=20.0)

        # S3 with allow_unknown=True must still be quarantined
        _, rej_s3 = permissive_pipeline.apply([obs], state_evidence={"MV302": 2})
        assert len(rej_s3) == 1
        assert "quarantined_unvalidated_regime" in rej_s3[0].reject_reason.lower()

        # Unknown state with allow_unknown=True must still fail closed
        _, rej_unk = permissive_pipeline.apply([obs], state_evidence={})
        assert len(rej_unk) == 1
        assert "unknown_operating_state" in rej_unk[0].reject_reason.lower()

    def test_per_observation_evidence_takes_precedence_in_pipeline(self, exp_pipeline):
        """Observation-level evidence overrides global fallback evidence."""
        # Global fallback says MV302 == 1 (normal S2), but observation says MV302 == 2 (S3)
        obs = _make_obs("P301", "DPIT301", delta_t_s=20.0)
        obs.state_evidence = {"MV302": 2}
        accepted, rejected = exp_pipeline.apply([obs], state_evidence={"MV302": 1})
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert "quarantined_unvalidated_regime" in rejected[0].reject_reason.lower()


class TestProductionAndCRISafety:
    """Verifies isolation invariants: production code unaffected, plantwide CRI disabled."""

    def test_production_gating_disconnected(self):
        """Production src/tcmim/ does not import OperatingStateResolver or stage4_experimental_gating."""
        src_dir = _project_root / "src" / "tcmim"
        for py_file in src_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            content = py_file.read_text(encoding="utf-8", errors="replace")
            assert "stage4_experimental_gating" not in content, f"Leaked import in {py_file.name}"
            assert "OperatingStateResolver" not in content, f"Leaked resolver in {py_file.name}"

    def test_plantwide_cri_remains_disabled(self):
        """Plantwide CRI remains disabled across experimental contracts and configs."""
        import json
        iface_path = _project_root / "experiments" / "results" / "swat_a4a5_stage3" / "experimental_model_interface.json"
        assert iface_path.is_file()
        with open(iface_path, "r", encoding="utf-8") as f:
            iface_data = json.load(f)
        assert iface_data["safety_contract"]["plantwide_cri_enabled"] is False
        assert iface_data["safety_contract"]["production_gating_connected"] is False
