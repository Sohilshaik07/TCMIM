"""
tests/unit/test_swat_a4a5_stage3.py
===================================
Unit tests for TCMIM Stage 3: Topology Correction and State-Conditioned Dynamic Modeling.

Verifies:
1. Register versioning and provenance:
   - Original register SHA-256 is preserved (08e0ce57...).
   - Proposed register contains 23 rows (22 original updated + EDGE_23).
2. Physical topology audit:
   - P101 -> FIT101 is explicitly DISALLOWED (mask status '0').
   - P101 -> FIT201 is permitted conditionally (mask status '1', conditional on MV201).
   - Unknown pairs return UNKNOWN ('?').
   - G0 deterministic behavior.
3. MV201 -> FIT201 dynamic formalization:
   - Separate opening vs closing parameter sets.
   - Opening dead time (~12.9s) is distinct from closing dead time (~3.7s).
   - Held-out opening R2 >= 0.85, closing R2 >= 0.50.
4. P301 -> DPIT301 state conditioning:
   - Normal startup (State S2) achieves R2 >= 0.99 on held-out data.
   - Single-input SISO reproduces negative R2 on Attack A6 (-1.8922).
   - State-conditioned MISO resolves Attack A6 with R2 >= 0.99.
5. Experimental model interface safety:
   - No silent defaulting to validated states.
   - FIT501 -> FIT502 quarantined, P205 -> AIT203 unresolved.
   - Plantwide CRI evaluation remains disabled.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import pytest
import numpy as np

_project_root = Path(__file__).resolve().parent.parent.parent
_stage3_dir = _project_root / "experiments" / "results" / "swat_a4a5_stage3"
_orig_register_path = _project_root / "experiments" / "results" / "swat_a4a5_physical_graph_audit" / "physical_connectivity_register.csv"
_prop_register_path = _stage3_dir / "proposed_connectivity_register.csv"

from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus


class TestTopologyRegisterAudit:
    """Verifies Part A: Physical Topology Audit and Register Preservation."""

    def test_original_register_preserved_unmodified(self):
        """Original physical register SHA-256 must match established baseline."""
        assert _orig_register_path.is_file(), f"Original register missing at {_orig_register_path}"
        orig_sha = hashlib.sha256(_orig_register_path.read_bytes()).hexdigest()
        expected_sha = "08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3"
        assert orig_sha == expected_sha, (
            f"Original register SHA-256 has been modified! Expected {expected_sha}, got {orig_sha}"
        )

    def test_proposed_register_structure_and_provenance(self):
        """Proposed register must exist, contain 23 valid rows, and preserve columns."""
        assert _prop_register_path.is_file(), f"Proposed register missing at {_prop_register_path}"
        with open(_prop_register_path, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        assert len(reader) == 23, f"Expected 23 rows in proposed register, got {len(reader)}"
        edge_ids = [r["edge_id"] for r in reader]
        assert "EDGE_07" in edge_ids
        assert "EDGE_23" in edge_ids

    def test_p101_to_fit101_disallowed_in_proposed_register(self):
        """P101 -> FIT101 must be explicitly DISALLOWED in the proposed register."""
        mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
        status = mask.get_status("P101", "FIT101")
        assert status == StructuralStatus.DISALLOWED, (
            f"Expected P101 -> FIT101 to be DISALLOWED ('0'), got {status.value}"
        )
        assert mask.is_prohibited("P101", "FIT101")
        assert not mask.is_permitted("P101", "FIT101")

    def test_p101_to_fit201_permitted_conditionally_in_proposed_register(self):
        """P101 -> FIT201 must be recognized as CONDITIONAL ('C'), never unconditional ALLOWED ('1').

        AUDIT REVISION (Stage 3.2):
        The original Stage 3 assertion expected status == ALLOWED ('1') without actuator
        verification. Stage 3.1 audit identified this as an unsafe bypass. The corrected
        invariant requires CONDITIONAL ('C') status, failing closed without state evidence,
        and permitting only when MV201 == 2 is validated.
        """
        mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
        status = mask.get_status("P101", "FIT201")
        assert status == StructuralStatus.CONDITIONAL, (
            f"Expected P101 -> FIT201 to be CONDITIONAL ('C'), got {status.value}"
        )
        assert mask.is_conditional("P101", "FIT201")
        # Must fail closed when state evidence is missing
        assert not mask.is_permitted("P101", "FIT201")
        # Must pass when state evidence confirms MV201 == 2
        assert mask.is_permitted("P101", "FIT201", state_evidence={"MV201": 2})
        # Must fail closed when MV201 is closed
        assert not mask.is_permitted("P101", "FIT201", state_evidence={"MV201": 1})

    def test_unknown_pairs_remain_unknown(self):
        """Unregistered component pairs must remain strictly UNKNOWN ('?')."""
        mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
        assert mask.get_status("P101", "DPIT301") == StructuralStatus.UNKNOWN
        assert mask.get_status("MV101", "FIT501") == StructuralStatus.UNKNOWN

    def test_topology_proposal_csv_validity(self):
        """topology_change_proposal.csv must accurately document EDGE_07 and EDGE_23."""
        proposal_path = _stage3_dir / "topology_change_proposal.csv"
        assert proposal_path.is_file()
        with open(proposal_path, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2
        edge_map = {r["edge_id"]: r for r in rows}
        assert edge_map["EDGE_07"]["proposed_status"] == "DISALLOWED"
        assert edge_map["EDGE_23"]["proposed_status"] == "INFERRED"
        assert edge_map["EDGE_23"]["depends_on_operating_state"].strip().lower() in ("true", "1")


class TestMV201DynamicsFormalization:
    """Verifies Part B: MV201 -> FIT201 Separate Opening vs Closing Dynamics."""

    @pytest.fixture
    def model_comparison(self):
        cmp_path = _stage3_dir / "model_comparison.json"
        assert cmp_path.is_file()
        with open(cmp_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_opening_closing_parameter_separation(self, model_comparison):
        """Opening and closing dynamics must have separate FOPDT parameter sets."""
        mv_data = model_comparison["part_b_mv201_to_fit201"]
        assert mv_data["opening_closing_separation_justified"] is True

        op_params = mv_data["opening_model"]["parameters"]
        cl_params = mv_data["closing_model"]["parameters"]

        # Dead time for opening reflects motor transit (12-14s)
        assert 11.0 <= op_params["td_s"] <= 15.0, f"Unexpected opening td: {op_params['td_s']}"
        # Dead time for closing reflects seating dynamics (3-5s)
        assert 2.0 <= cl_params["td_s"] <= 5.5, f"Unexpected closing td: {cl_params['td_s']}"
        # Dead times must be distinctly separated
        assert abs(op_params["td_s"] - cl_params["td_s"]) > 6.0

    def test_mv201_held_out_validation_metrics(self, model_comparison):
        """Held-out opening validation R2 must exceed 0.85, closing must exceed 0.50."""
        mv_data = model_comparison["part_b_mv201_to_fit201"]
        op_val = mv_data["opening_model"]["held_out_metrics"]
        cl_val = mv_data["closing_model"]["held_out_metrics"]

        assert op_val["r2"] >= 0.85, f"Opening R2 too low: {op_val['r2']}"
        assert op_val["rmse"] <= 0.45, f"Opening RMSE too high: {op_val['rmse']}"
        assert cl_val["r2"] >= 0.50, f"Closing R2 too low: {cl_val['r2']}"

    def test_investigation_delay_range_validity(self, model_comparison):
        """The proposed 5-25s delay investigation range must encompass normal opening."""
        mv_data = model_comparison["part_b_mv201_to_fit201"]
        assert mv_data["opening_model"]["delay_investigation_range_5_to_25s_valid"] is True


class TestP301StateConditionedModeling:
    """Verifies Part C: P301 -> DPIT301 State-Conditioned Modeling and Attack A6 Reconciliation."""

    @pytest.fixture
    def model_comparison(self):
        cmp_path = _stage3_dir / "model_comparison.json"
        assert cmp_path.is_file()
        with open(cmp_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_reproduced_attack_a6_negative_r2(self, model_comparison):
        """Model 1 (SISO) must reproduce the reported negative R2 (-1.8922) on Attack A6."""
        m1 = model_comparison["part_c_p301_to_dpit301"]["model_comparison"]["model_1_siso_unconditioned"]
        r2_atk = m1["attack_a6_val_metrics"]["r2"]
        assert pytest.approx(r2_atk, abs=1e-3) == -1.8922, f"Failed to reproduce Attack A6 R2: {r2_atk}"

    def test_state_conditioned_reconciliation(self, model_comparison):
        """Model 2 (State-Conditioned MISO) must resolve Attack A6 with R2 >= 0.99."""
        m2 = model_comparison["part_c_p301_to_dpit301"]["model_comparison"]["model_2_miso_state_conditioned"]
        r2_atk = m2["attack_a6_val_metrics"]["r2"]
        assert r2_atk >= 0.99, f"State-conditioned Attack A6 R2 did not recover: {r2_atk}"
        assert m2["overall_val_metrics"]["r2"] >= 0.99

    def test_normal_cycle_held_out_reproducibility(self, model_comparison):
        """State S2 normal held-out validation R2 must exceed 0.99."""
        m1 = model_comparison["part_c_p301_to_dpit301"]["model_comparison"]["model_1_siso_unconditioned"]
        assert m1["normal_val_metrics"]["r2"] >= 0.99
        assert m1["normal_val_metrics"]["rmse"] <= 0.25

    def test_delay_range_5_to_55s_conditional(self, model_comparison):
        """The 5-55s delay bound must be strictly conditional on State S2."""
        p3_data = model_comparison["part_c_p301_to_dpit301"]
        assert p3_data["normal_cycle_range_5_to_55s_conditional"] is True


class TestExperimentalModelInterfaceSafety:
    """Verifies Section 6: Experimental Model Interface and Integration Safety."""

    @pytest.fixture
    def interface_data(self):
        iface_path = _stage3_dir / "experimental_model_interface.json"
        assert iface_path.is_file()
        with open(iface_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_safety_contract_flags(self, interface_data):
        """Plantwide CRI and unvalidated defaults must be explicitly disabled."""
        contract = interface_data["safety_contract"]
        assert contract["allow_unvalidated_defaults"] is False
        assert contract["production_gating_connected"] is False
        assert contract["plantwide_cri_enabled"] is False

    def test_quarantined_and_unresolved_edges(self, interface_data):
        """FIT501 -> FIT502 must be QUARANTINED; P205 -> AIT203 must be UNRESOLVED."""
        rel = interface_data["relationships"]
        assert rel["FIT501_to_FIT502"]["status"] == "QUARANTINED"
        assert rel["FIT501_to_FIT502"]["eligible_for_experimental_dynamic_gating"] is False

        assert rel["P205_to_AIT203"]["status"] == "UNRESOLVED"
        assert rel["P205_to_AIT203"]["eligible_for_experimental_dynamic_gating"] is False

        assert rel["P101_to_FIT101"]["status"] == "DISALLOWED"
        assert rel["P101_to_FIT101"]["eligible_for_experimental_dynamic_gating"] is False
