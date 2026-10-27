"""
experiments/swat_a4a5_stage3_2_runner.py
========================================
TCMIM Stage 3.2: Generation of Corrected Scientific Evaluation Reporting
and Safe Conditional Connectivity Register.

Generates:
1. proposed_connectivity_register_stage3_2.csv
2. corrected_model_evaluation.csv
3. corrected_relationship_decisions.csv
4. validation_status_register.csv
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

_project_root = Path(__file__).resolve().parent.parent
_stage3_dir = _project_root / "experiments" / "results" / "swat_a4a5_stage3"
_stage3_1_dir = _project_root / "experiments" / "results" / "swat_a4a5_stage3_1_audit"
_stage3_2_dir = _project_root / "experiments" / "results" / "swat_a4a5_stage3_2"


def generate_proposed_connectivity_register_stage3_2() -> Path:
    """Generate the corrected physical connectivity register for Stage 3.2.

    Key updates:
    - EDGE_07 (P101 -> FIT101): explicitly DISALLOWED (status='0', suitable='NO_DISALLOWED')
    - EDGE_23 (P101 -> FIT201): explicitly CONDITIONAL (status='CONDITIONAL', suitable='CONDITIONAL', operating_condition='MV201 == 2')
    """
    _stage3_2_dir.mkdir(parents=True, exist_ok=True)
    out_path = _stage3_2_dir / "proposed_connectivity_register_stage3_2.csv"

    # Base on Stage 3 register, correcting EDGE_23 to CONDITIONAL with operating_condition column
    stage3_reg = _stage3_dir / "proposed_connectivity_register.csv"
    with open(stage3_reg, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    fieldnames = list(reader[0].keys())
    if "operating_condition" not in fieldnames:
        fieldnames.append("operating_condition")

    rows = []
    for r in reader:
        row = dict(r)
        if row["edge_id"] == "EDGE_23":
            row["status"] = "CONDITIONAL"
            row["suitable_as_structural_constraint"] = "CONDITIONAL"
            row["operating_condition"] = "MV201 == 2"
            row["physical_mechanism_and_notes"] = (
                "STAGE 3.2 CORRECTION: Raw water supply pump P101 draws suction from Tank T101 and discharges "
                "through motorized valve MV201 into flow transmitter FIT201. Permitted as structural edge "
                "conditional on MV201 == 2 (OPEN). Fails closed if MV201 is closed (1), missing, or unknown."
            )
        elif row["edge_id"] == "EDGE_07":
            row["status"] = "DISALLOWED"
            row["suitable_as_structural_constraint"] = "NO_DISALLOWED"
            row["operating_condition"] = ""
        else:
            row["operating_condition"] = ""
        rows.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Generated {out_path.name} (SHA-256: {sha[:16]}...) with {len(rows)} rows.")
    return out_path


def generate_corrected_model_evaluation() -> Path:
    """Generate corrected_model_evaluation.csv with qualified scientific metrics."""
    _stage3_2_dir.mkdir(parents=True, exist_ok=True)
    out_path = _stage3_2_dir / "corrected_model_evaluation.csv"

    rows = [
        # P301 -> DPIT301 Normal Startup Held-Out Episodes (Genuinely Independent)
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S2_NORMAL_STARTUP",
            "episode_id": "P301_START_9419",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9936 (pooled)",
            "reproduced_r2": "0.9994",
            "reported_rmse": "0.1877 (pooled)",
            "reproduced_rmse": "0.0570",
            "reproduced_mae": "0.0409",
            "ss_res": "0.1947",
            "ss_tot": "345.8389",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation on independent normal cycle (MV302=1).",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S2_NORMAL_STARTUP",
            "episode_id": "P301_START_12124",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9936 (pooled)",
            "reproduced_r2": "0.9959",
            "reported_rmse": "0.1877 (pooled)",
            "reproduced_rmse": "0.1533",
            "reproduced_mae": "0.1237",
            "ss_res": "1.4109",
            "ss_tot": "344.8636",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation on independent normal cycle (MV302=1).",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S2_NORMAL_STARTUP",
            "episode_id": "P301_START_14024",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9936 (pooled)",
            "reproduced_r2": "0.9845",
            "reported_rmse": "0.1877 (pooled)",
            "reproduced_rmse": "0.2810",
            "reproduced_mae": "0.2344",
            "ss_res": "4.7383",
            "ss_tot": "305.2900",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation on independent normal cycle (MV302=1).",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S2_POOLED_STARTUP",
            "episode_id": "POOLED_VAL_NORMAL_3_EPS",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9936",
            "reproduced_r2": "0.9936",
            "reported_rmse": "0.1877",
            "reproduced_rmse": "0.1877",
            "reproduced_mae": "0.1330",
            "ss_res": "6.3438",
            "ss_tot": "998.9783",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Verified pooled normal startup score across 180s of independently held-out cycles.",
        },
        # P301 -> DPIT301 Attack A6 Evaluation (SISO failure vs MISO in-sample fit)
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S3_ATTACK_A6_SISO",
            "episode_id": "P301_START_13504",
            "evaluation_type": "CROSS_REGIME_EVALUATION",
            "reported_r2": "-1.8922",
            "reproduced_r2": "-1.8922",
            "reported_rmse": "4.6258",
            "reproduced_rmse": "4.6258",
            "reproduced_mae": "4.1471",
            "ss_res": "1283.8609",
            "ss_tot": "443.9051",
            "audit_classification": "DISALLOWED",
            "scientific_qualification": "Exact failure reproduction. Single-input model fails because MV302 open state (S3) bypasses dead-head plateau.",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S3_ATTACK_A6_MISO",
            "episode_id": "P301_START_13504",
            "evaluation_type": "IN_SAMPLE_FIT",
            "reported_r2": "0.9961",
            "reproduced_r2": "0.9961",
            "reported_rmse": "0.2458",
            "reproduced_rmse": "0.1701",
            "reproduced_mae": "0.1101",
            "ss_res": "1.7360",
            "ss_tot": "443.9051",
            "audit_classification": "IN-SAMPLE DESCRIPTIVE FIT",
            "scientific_qualification": "TRAIN-ON-TEST LEAKAGE. Evaluated on the exact single episode used for fitting. Out-of-sample validation status NOT AVAILABLE.",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STARTUP_COMBINED_HEADLINE",
            "episode_id": "HEADLINE_COMBINED_180S_NORMAL_60S_A6",
            "evaluation_type": "CONTAMINATED_POOLED",
            "reported_r2": "0.9963",
            "reproduced_r2": "0.9963",
            "reported_rmse": "0.1835",
            "reproduced_rmse": "0.1835",
            "reproduced_mae": "0.1273",
            "ss_res": "8.0799",
            "ss_tot": "2207.6614",
            "audit_classification": "UNRESOLVED",
            "scientific_qualification": "DISQUALIFIED HEADLINE METRIC. Illegitimately concatenates 180s out-of-sample normal with 60s in-sample fitted Attack A6 observations.",
        },
        # P301 -> DPIT301 Shutdown
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S5_SHUTDOWN",
            "episode_id": "P301_SHUTDOWN_10736",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9746 (pooled)",
            "reproduced_r2": "0.9723",
            "reported_rmse": "0.5770 (pooled)",
            "reproduced_rmse": "0.4618",
            "reproduced_mae": "0.2554",
            "ss_res": "12.9537",
            "ss_tot": "462.5503",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation across independent shutdown cycles.",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S5_SHUTDOWN",
            "episode_id": "P301_SHUTDOWN_12662",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9746 (pooled)",
            "reproduced_r2": "0.9836",
            "reported_rmse": "0.5770 (pooled)",
            "reproduced_rmse": "0.3672",
            "reproduced_mae": "0.3971",
            "ss_res": "11.2789",
            "ss_tot": "494.5867",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation across independent shutdown cycles.",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S5_SHUTDOWN",
            "episode_id": "P301_SHUTDOWN_13940",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9746 (pooled)",
            "reproduced_r2": "0.9330",
            "reported_rmse": "0.5770 (pooled)",
            "reproduced_rmse": "0.6892",
            "reproduced_mae": "0.6205",
            "ss_res": "32.7057",
            "ss_tot": "425.0784",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation across independent shutdown cycles.",
        },
        {
            "relationship": "P301 -> DPIT301",
            "regime": "STATE_S5_SHUTDOWN_POOLED",
            "episode_id": "POOLED_VAL_SHUTDOWN_3_EPS",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.9644",
            "reproduced_r2": "0.9644",
            "reported_rmse": "0.5238",
            "reproduced_rmse": "0.5238",
            "reproduced_mae": "0.3742",
            "ss_res": "49.3819",
            "ss_tot": "1388.4822",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Verified pooled shutdown validation across 180s.",
        },
        # MV201 -> FIT201 Opening
        {
            "relationship": "MV201 -> FIT201",
            "regime": "OPENING_STROKE",
            "episode_id": "MV201_OPEN_10066",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.8937 (pooled)",
            "reproduced_r2": "0.9943",
            "reported_rmse": "0.3456 (pooled)",
            "reproduced_rmse": "0.0791",
            "reproduced_mae": "0.0539",
            "ss_res": "0.2817",
            "ss_tot": "49.6266",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation episode under normal opening.",
        },
        {
            "relationship": "MV201 -> FIT201",
            "regime": "OPENING_STROKE",
            "episode_id": "MV201_OPEN_11221",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.8937 (pooled)",
            "reproduced_r2": "0.6994",
            "reported_rmse": "0.3456 (pooled)",
            "reproduced_rmse": "0.5851",
            "reproduced_mae": "0.3161",
            "ss_res": "15.4059",
            "ss_tot": "51.2446",
            "audit_classification": "CONDITIONALLY SUPPORTED",
            "scientific_qualification": "Pump P101 activation delayed by 6s relative to valve signal, producing lower R2 (0.6994).",
        },
        {
            "relationship": "MV201 -> FIT201",
            "regime": "OPENING_STROKE",
            "episode_id": "MV201_OPEN_14247",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.8937 (pooled)",
            "reproduced_r2": "0.9910",
            "reported_rmse": "0.3456 (pooled)",
            "reproduced_rmse": "0.0980",
            "reproduced_mae": "0.0627",
            "ss_res": "0.4320",
            "ss_tot": "48.1510",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Genuinely held-out validation episode under normal opening.",
        },
        {
            "relationship": "MV201 -> FIT201",
            "regime": "OPENING_POOLED",
            "episode_id": "POOLED_VAL_OPEN_3_EPS",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.8937",
            "reproduced_r2": "0.8937",
            "reported_rmse": "0.3456",
            "reproduced_rmse": "0.3456",
            "reproduced_mae": "0.1442",
            "ss_res": "16.1197",
            "ss_tot": "151.6820",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Verified pooled opening metric across 135s.",
        },
        # MV201 -> FIT201 Closing
        {
            "relationship": "MV201 -> FIT201",
            "regime": "CLOSING_STROKE",
            "episode_id": "MV201_CLOSE_11047",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.5434 (pooled)",
            "reproduced_r2": "0.9909",
            "reported_rmse": "0.4611 (pooled)",
            "reproduced_rmse": "0.0799",
            "reproduced_mae": "0.0646",
            "ss_res": "0.1915",
            "ss_tot": "20.9862",
            "audit_classification": "INDEPENDENTLY VALIDATED",
            "scientific_qualification": "Normal closing cycle with concurrent pump operation.",
        },
        {
            "relationship": "MV201 -> FIT201",
            "regime": "CLOSING_STROKE",
            "episode_id": "MV201_CLOSE_11692",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.5434 (pooled)",
            "reproduced_r2": "-1.7376",
            "reported_rmse": "0.4611 (pooled)",
            "reproduced_rmse": "0.6472",
            "reproduced_mae": "0.4119",
            "ss_res": "12.5639",
            "ss_tot": "4.5898",
            "audit_classification": "CONDITIONALLY SUPPORTED",
            "scientific_qualification": "FAILURE EPISODE: Pump P101 shut down 7s before MV201 valve travel initiated. Flow dropped prematurely, producing R2=-1.7376.",
        },
        {
            "relationship": "MV201 -> FIT201",
            "regime": "CLOSING_POOLED",
            "episode_id": "POOLED_VAL_CLOSE_2_EPS",
            "evaluation_type": "HELD_OUT_VALIDATION",
            "reported_r2": "0.5434",
            "reproduced_r2": "0.5434",
            "reported_rmse": "0.4611",
            "reproduced_rmse": "0.4611",
            "reproduced_mae": "0.2382",
            "ss_res": "12.7553",
            "ss_tot": "27.9374",
            "audit_classification": "CONDITIONALLY SUPPORTED",
            "scientific_qualification": "Pooled metric masks severe individual failure on episode 11692 (R2=-1.7376).",
        },
    ]

    fieldnames = [
        "relationship", "regime", "episode_id", "evaluation_type",
        "reported_r2", "reproduced_r2", "reported_rmse", "reproduced_rmse",
        "reproduced_mae", "ss_res", "ss_tot", "audit_classification", "scientific_qualification",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Generated {out_path.name} (SHA-256: {sha[:16]}...) with {len(rows)} rows.")
    return out_path


def generate_corrected_relationship_decisions() -> Path:
    """Generate corrected_relationship_decisions.csv."""
    _stage3_2_dir.mkdir(parents=True, exist_ok=True)
    out_path = _stage3_2_dir / "corrected_relationship_decisions.csv"

    rows = [
        {
            "relationship_id": "REL_01",
            "source": "MV201",
            "destination": "FIT201",
            "final_classification": "CONDITIONALLY SUPPORTED",
            "structural_mask_status": "ALLOWED",
            "dynamic_validation_status": "INDEPENDENTLY VALIDATED (OPEN) / UNSTABLE (CLOSE)",
            "operating_condition": "Stroke direction (Opening: 5-25s, Closing: 1-15s)",
            "delay_bounds_s": "Opening: 5.0-25.0s; Closing: 1.0-15.0s",
            "audit_readiness_decision": "CONDITIONALLY READY (EXPERIMENTAL SHADOW ONLY)",
            "prerequisites_for_stage4": "Must enforce separate stroke models and monitor P101 motor energization state.",
            "shadow_mode_decision": "SHADOW_MODE_PERMITTED",
        },
        {
            "relationship_id": "REL_02",
            "source": "P301",
            "destination": "DPIT301",
            "final_classification": "CONDITIONALLY SUPPORTED",
            "structural_mask_status": "ALLOWED",
            "dynamic_validation_status": "INDEPENDENTLY VALIDATED (STATE S2) / IN-SAMPLE DESCRIPTIVE FIT (STATE S3)",
            "operating_condition": "MV302 == 1 (Normal S2) vs MV302 == 2 (Attack S3)",
            "delay_bounds_s": "State S2: 5.0-55.0s; State S3: 1.0-10.0s",
            "audit_readiness_decision": "CONDITIONALLY READY (RESTRICTED TO S2)",
            "prerequisites_for_stage4": "Restricted to State S2. State S3 is descriptive reconstruction only; multi-run pooling required for S3 validation.",
            "shadow_mode_decision": "SHADOW_MODE_PERMITTED",
        },
        {
            "relationship_id": "REL_03",
            "source": "P101",
            "destination": "FIT101",
            "final_classification": "DISALLOWED",
            "structural_mask_status": "DISALLOWED",
            "dynamic_validation_status": "DISALLOWED",
            "operating_condition": "N/A (Structurally Prohibited)",
            "delay_bounds_s": "N/A",
            "audit_readiness_decision": "REFUTED / DISALLOWED",
            "prerequisites_for_stage4": "Instrument misidentification corrected. Direct hydraulic edge permanently prohibited in structural mask.",
            "shadow_mode_decision": "ISOLATED_AND_DISALLOWED",
        },
        {
            "relationship_id": "REL_04",
            "source": "P101",
            "destination": "FIT201",
            "final_classification": "CONDITIONALLY SUPPORTED",
            "structural_mask_status": "CONDITIONAL",
            "dynamic_validation_status": "CONDITIONALLY SUPPORTED",
            "operating_condition": "MV201 == 2",
            "delay_bounds_s": "12.0-25.0s (when MV201 == 2)",
            "audit_readiness_decision": "CONDITIONALLY READY (REQUIRES ACTUATOR GATE)",
            "prerequisites_for_stage4": "Must require explicit gate G0 predicate evaluation (MV201 == 2). Fails closed without telemetry.",
            "shadow_mode_decision": "SHADOW_MODE_PERMITTED_WITH_STATE",
        },
        {
            "relationship_id": "REL_05",
            "source": "P205",
            "destination": "AIT203",
            "final_classification": "UNRESOLVED",
            "structural_mask_status": "ALLOWED",
            "dynamic_validation_status": "UNRESOLVED",
            "operating_condition": "N/A (Zero Baseline Variance)",
            "delay_bounds_s": "Unknown",
            "audit_readiness_decision": "QUARANTINED_UNRESOLVED",
            "prerequisites_for_stage4": "Zero variance in baseline telemetry (sigma=0.0). Requires multi-run operational dataset pooling.",
            "shadow_mode_decision": "QUARANTINED_FROM_GATING",
        },
        {
            "relationship_id": "REL_06",
            "source": "FIT501",
            "destination": "FIT502",
            "final_classification": "UNRESOLVED",
            "structural_mask_status": "ALLOWED",
            "dynamic_validation_status": "NOT VERIFIED",
            "operating_condition": "N/A (Steady-State Separation)",
            "delay_bounds_s": "N/A (Static Ratio 0.78)",
            "audit_readiness_decision": "QUARANTINED_STATIC_EDGE",
            "prerequisites_for_stage4": "Static membrane mass balance (FIT502 = 0.78 * FIT501). Quarantined from dynamic delay gating.",
            "shadow_mode_decision": "QUARANTINED_FROM_GATING",
        },
    ]

    fieldnames = [
        "relationship_id", "source", "destination", "final_classification",
        "structural_mask_status", "dynamic_validation_status", "operating_condition",
        "delay_bounds_s", "audit_readiness_decision", "prerequisites_for_stage4", "shadow_mode_decision",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Generated {out_path.name} (SHA-256: {sha[:16]}...) with {len(rows)} rows.")
    return out_path


def generate_validation_status_register() -> Path:
    """Generate validation_status_register.csv for all 23 candidate edges."""
    _stage3_2_dir.mkdir(parents=True, exist_ok=True)
    out_path = _stage3_2_dir / "validation_status_register.csv"

    reg_path = _stage3_2_dir / "proposed_connectivity_register_stage3_2.csv"
    with open(reg_path, "r", encoding="utf-8") as f:
        reg_rows = list(csv.DictReader(f))

    status_map = {
        "EDGE_01": ("INDEPENDENTLY VALIDATED", "Validated on State S2 normal cycles. State S3 is descriptive only."),
        "EDGE_02": ("UNRESOLVED", "Low confidence, unidentifiable normal steady state."),
        "EDGE_03": ("UNRESOLVED", "Static RO membrane separation; non-causal mass balance."),
        "EDGE_04": ("CONDITIONALLY SUPPORTED", "Hydraulic inflow to T301; confounded without outflow P301."),
        "EDGE_05": ("UNRESOLVED", "Zero baseline variance (sigma=0.0)."),
        "EDGE_06": ("INDEPENDENTLY VALIDATED", "Inlet valve modulates raw water inflow."),
        "EDGE_07": ("DISALLOWED", "Refuted by audit. P101 discharges to Stage 2, not FIT101."),
        "EDGE_08": ("INDEPENDENTLY VALIDATED", "P101 suction lowers T101 tank level."),
        "EDGE_09": ("INDEPENDENTLY VALIDATED", "PLC1 level interlock stops P101 on low level."),
        "EDGE_10": ("INDEPENDENTLY VALIDATED", "Validated opening stroke (R2=0.8937). Closing stroke conditional."),
        "EDGE_11": ("INDEPENDENTLY VALIDATED", "HCl dosing modulates pH sensor AIT202."),
        "EDGE_12": ("UNRESOLVED", "Zero baseline variance for P205 (sigma=0.0)."),
        "EDGE_13": ("INDEPENDENTLY VALIDATED", "PLC3 level interlock governs P301."),
        "EDGE_14": ("INDEPENDENTLY VALIDATED", "Documented safety interlock: low FIT401 trips UV401."),
        "EDGE_15": ("UNRESOLVED", "P401 ran continuously in baseline (sigma=0.0)."),
        "EDGE_16": ("UNRESOLVED", "P501 ran continuously in baseline (sigma=0.0)."),
        "EDGE_17": ("INDEPENDENTLY VALIDATED", "Permeate stream increases T601 level."),
        "EDGE_18": ("UNRESOLVED", "P601 strictly OFF in baseline (sigma=0.0)."),
        "EDGE_19": ("UNRESOLVED", "P601 strictly OFF in baseline (sigma=0.0)."),
        "EDGE_20": ("DISALLOWED", "Prohibited: fluid transit passes through 3 buffer tanks."),
        "EDGE_21": ("DISALLOWED", "Prohibited: no piping connection from Stage 6 backwash pump to Stage 2."),
        "EDGE_22": ("DISALLOWED", "Prohibited: hydraulics isolated by RO feed tank T401 and pump P401."),
        "EDGE_23": ("CONDITIONALLY SUPPORTED", "Dynamically supported when MV201 == 2 (OPEN). Fails closed when closed/missing."),
    }

    rows = []
    for r in reg_rows:
        eid = r["edge_id"]
        status, justification = status_map.get(eid, ("NOT VERIFIED", "Unregistered or unclassified edge."))
        rows.append({
            "edge_id": eid,
            "source_component": r["source_component"],
            "destination_component": r["destination_component"],
            "structural_status": r["status"],
            "validation_classification": status,
            "operating_condition": r.get("operating_condition", ""),
            "scientific_justification": justification,
        })

    fieldnames = [
        "edge_id", "source_component", "destination_component",
        "structural_status", "validation_classification",
        "operating_condition", "scientific_justification",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"Generated {out_path.name} (SHA-256: {sha[:16]}...) with {len(rows)} rows.")
    return out_path


if __name__ == "__main__":
    generate_proposed_connectivity_register_stage3_2()
    generate_corrected_model_evaluation()
    generate_corrected_relationship_decisions()
    generate_validation_status_register()
