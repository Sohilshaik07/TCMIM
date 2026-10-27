"""
SWaT A4/A5 Physical Graph and Connectivity Register Builder.

Constructs an auditable physical connectivity register and configuration schema
for the SWaT A4/A5 July 2019 dataset to establish a safe structural prior for Stage 2.

Preservation:
- Strictly read-only on all existing source files and prior experiment results.
- Saves all outputs to experiments/results/swat_a4a5_physical_graph_audit/.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("swat_a4a5_physical_graph_audit")


def build_physical_register() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "experiments" / "results" / "swat_a4a5_physical_graph_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Building SWaT A4/A5 Physical Connectivity Register...")
    logger.info("Target directory: %s", out_dir)

    # Define the connectivity register entries
    # Statuses: DOCUMENTED, INFERRED, UNKNOWN, DYNAMICALLY_VALIDATED
    # Evidence confidence: HIGH, MEDIUM, LOW, NONE
    register_entries: List[Dict[str, Any]] = [
        # --- The 5 Audited Candidate Relationships (Task 3) ---
        {
            "edge_id": "EDGE_01",
            "source_component": "P301",
            "destination_component": "DPIT301",
            "source_stage": "P3",
            "destination_stage": "P3",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 6 description); Tag Registry (swat.py)",
            "document_page_or_id": "PDF p. 1 (Attack 6: 'Switch P301 from ON to OFF to halt stage 3 UF process')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "UF feed pump discharge fluid dynamics directly build trans-membrane differential pressure. Direction is forward (P301 -> DPIT301). P&ID drawing missing from package, but process role confirmed by attack intent."
        },
        {
            "edge_id": "EDGE_02",
            "source_component": "FIT501",
            "destination_component": "PIT501",
            "source_stage": "P5",
            "destination_stage": "P5",
            "relationship_type": "measurement",
            "documented_direction": "UNKNOWN",
            "status": "UNKNOWN",
            "supporting_document": "Tag Registry (swat.py); SWaT 2015 Architecture Reference",
            "document_page_or_id": "Tag Registry: PIT501='RO pump suction pressure', FIT501='RO feed flow'",
            "evidence_confidence": "LOW",
            "suitable_as_structural_constraint": "NO",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_NORMAL_STEADY_STATE",
            "physical_mechanism_and_notes": "Direction is physically ambiguous or inverted. PIT501 is pump suction pressure (upstream), while FIT501 is discharge/feed flow (downstream). Flow does not cause suction pressure. High correlation in held-out data was driven by concurrent plant shutdown."
        },
        {
            "edge_id": "EDGE_03",
            "source_component": "FIT501",
            "destination_component": "FIT502",
            "source_stage": "P5",
            "destination_stage": "P5",
            "relationship_type": "mass_balance",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Standard Reverse Osmosis Process Principles; Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: FIT501='RO feed flow', FIT502='RO permeate flow'",
            "evidence_confidence": "MEDIUM",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_NORMAL_STEADY_STATE",
            "physical_mechanism_and_notes": "Conservation of mass across RO membrane separation (Feed = Permeate + Reject). Direction is forward (feed flow supplies permeate stream). Membrane recovery ratio parameters and exact P&ID missing from package."
        },
        {
            "edge_id": "EDGE_04",
            "source_component": "FIT201",
            "destination_component": "LIT301",
            "source_stage": "P2",
            "destination_stage": "P3",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 4 description); Tag Registry (swat.py)",
            "document_page_or_id": "PDF p. 1 (Attack 4: 'Switch MV201 OPEN and P101 ON to overflow tank T301')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "CONDITIONAL",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Stage 2 outflow enters Tank T301. Tank level is the integral of net flow (FIT201 - P301_outflow). Suitable as structural edge only if tank outflow is included in state equation; single-channel correlation without P301 is confounded by integration."
        },
        {
            "edge_id": "EDGE_05",
            "source_component": "MV501",
            "destination_component": "PIT502",
            "source_stage": "P5",
            "destination_stage": "P5",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 5 description); Tag Registry (swat.py)",
            "document_page_or_id": "PDF p. 1 (Attack 5: 'Switch MV501 OPEN to CLOSE to drain water from RO')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            "physical_mechanism_and_notes": "RO reject valve throttling causes hydraulic backpressure surge in RO vessel measured by PIT502. Direction is forward (valve state influences vessel pressure). Zero variance in baseline; unidentifiable without perturbation."
        },

        # --- Additional Primary Physical Connections (Stages 1 through 6) ---
        {
            "edge_id": "EDGE_06",
            "source_component": "MV101",
            "destination_component": "LIT101",
            "source_stage": "P1",
            "destination_stage": "P1",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT Process Architecture; Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: MV101='Raw water inlet motorized valve', LIT101='Raw water tank level'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Inlet valve MV101 modulates municipal raw water inflow into tank T101, directly influencing tank level accumulation."
        },
        {
            "edge_id": "EDGE_07",
            "source_component": "P101",
            "destination_component": "FIT101",
            "source_stage": "P1",
            "destination_stage": "P1",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT Process Architecture; Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P101='Raw water supply pump 1', FIT101='Raw water supply flow'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Pump P101 discharge directly generates raw water flow FIT101 delivered to Stage 2."
        },
        {
            "edge_id": "EDGE_08",
            "source_component": "P101",
            "destination_component": "LIT101",
            "source_stage": "P1",
            "destination_stage": "P1",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT Process Architecture; Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P101 suctions from T101",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Pump P101 draws water from tank T101, reducing level LIT101 during pumping cycles."
        },
        {
            "edge_id": "EDGE_09",
            "source_component": "LIT101",
            "destination_component": "P101",
            "source_stage": "P1",
            "destination_stage": "P1",
            "relationship_type": "electrical_control",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT PLC Control Logic Specifications (External)",
            "document_page_or_id": "PLC1 Control Logic: Low level interlock stops P101",
            "evidence_confidence": "MEDIUM",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "PLC1 control loop: Tank level LIT101 reaching low threshold trips pump P101 to prevent dry running; reaching high threshold enables pump."
        },
        {
            "edge_id": "EDGE_10",
            "source_component": "MV201",
            "destination_component": "FIT201",
            "source_stage": "P2",
            "destination_stage": "P2",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 4 description)",
            "document_page_or_id": "PDF p. 1 (Attack 4: 'Switch MV201 to OPEN to overflow tank T301')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Chemical dosing motorized valve MV201 controls hydraulic passage into Stage 2 pipe and flow transmitter FIT201."
        },
        {
            "edge_id": "EDGE_11",
            "source_component": "P203",
            "destination_component": "AIT202",
            "source_stage": "P2",
            "destination_stage": "P2",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P203='HCl dosing pump 1', AIT202='Chemical dosing pH analyzer'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Hydrochloric acid (HCl) dosing pump P203 injects acid to lower water pH, directly monitored downstream by pH sensor AIT202."
        },
        {
            "edge_id": "EDGE_12",
            "source_component": "P205",
            "destination_component": "AIT203",
            "source_stage": "P2",
            "destination_stage": "P2",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P205='NaHSO3 dosing pump 1', AIT203='Chemical dosing ORP analyzer'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Sodium bisulfite (NaHSO3) dosing pump P205 injects reducing agent, directly altering oxidation-reduction potential monitored by AIT203."
        },
        {
            "edge_id": "EDGE_13",
            "source_component": "LIT301",
            "destination_component": "P301",
            "source_stage": "P3",
            "destination_stage": "P3",
            "relationship_type": "electrical_control",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 2 description)",
            "document_page_or_id": "PDF p. 1 (Attack 2: 'Spoof LIT301 to 1024 to eventually lead to underflow in T301')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "PLC3 control logic: LIT301 level governs P301 operation. Spoofing LIT301 falsely high causes PLC3 to keep pump P301 running, draining tank T301 to underflow."
        },
        {
            "edge_id": "EDGE_14",
            "source_component": "FIT401",
            "destination_component": "UV401",
            "source_stage": "P4",
            "destination_stage": "P4",
            "relationship_type": "electrical_control",
            "documented_direction": "FORWARD",
            "status": "DOCUMENTED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 1 description)",
            "document_page_or_id": "PDF p. 1 (Attack 1: 'Spoof FIT401 to 0.5; Intent: To stop de-chlorination by switching off UV401')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_UV_CONSTANT_IN_BASELINE",
            "physical_mechanism_and_notes": "Explicitly documented control interlock: PLC4 monitors flow transmitter FIT401; if flow drops below threshold (0.8 -> 0.5), PLC4 shuts off UV de-chlorination lamp UV401 to prevent thermal lamp burnout."
        },
        {
            "edge_id": "EDGE_15",
            "source_component": "P401",
            "destination_component": "FIT401",
            "source_stage": "P4",
            "destination_stage": "P4",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P401='RO feed pump 1', FIT401='RO feed flow transmitter'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            "physical_mechanism_and_notes": "RO feed pump P401 discharge generates feed flow FIT401 into Stage 4 de-chlorination and UV unit. P401 ran continuously in baseline."
        },
        {
            "edge_id": "EDGE_16",
            "source_component": "P501",
            "destination_component": "PIT502",
            "source_stage": "P5",
            "destination_stage": "P5",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P501='High-pressure RO pump 1', PIT502='RO pump discharge pressure'",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            "physical_mechanism_and_notes": "High-pressure RO pump P501 discharge builds membrane operating pressure measured by PIT502. P501 ran continuously in baseline."
        },
        {
            "edge_id": "EDGE_17",
            "source_component": "FIT502",
            "destination_component": "LIT601",
            "source_stage": "P5",
            "destination_stage": "P6",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "SWaT Process Architecture; Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: FIT502 permeate delivers clean water to backwash/permeate tank T601",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "IDENTIFIABLE",
            "physical_mechanism_and_notes": "Clean permeate stream from RO membranes flows into backwash and distribution storage tank T601, increasing level LIT601."
        },
        {
            "edge_id": "EDGE_18",
            "source_component": "P601",
            "destination_component": "LIT101",
            "source_stage": "P6",
            "destination_stage": "P1",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "DOCUMENTED",
            "supporting_document": "SWaT data collection_20-07-2019 v2.pdf (p. 1, Attack 3 description)",
            "document_page_or_id": "PDF p. 1 (Attack 3: 'Switch P601 OFF to ON; Intent: To increase water in raw water tank')",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            "physical_mechanism_and_notes": "Explicitly documented physical return pipe: Pump P601 pumps backwash water from Stage 6 back into raw water tank T101 in Stage 1 to recycle water. P601 was strictly OFF (state=1) in baseline."
        },
        {
            "edge_id": "EDGE_19",
            "source_component": "P601",
            "destination_component": "FIT601",
            "source_stage": "P6",
            "destination_stage": "P6",
            "relationship_type": "hydraulic",
            "documented_direction": "FORWARD",
            "status": "INFERRED",
            "supporting_document": "Tag Registry (swat.py)",
            "document_page_or_id": "Tag Registry: P601 suctions to distribution/backwash pipe FIT601",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "YES",
            "dynamically_validated": False,
            "baseline_identifiability": "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            "physical_mechanism_and_notes": "Pump P601 discharge generates distribution flow FIT601. P601 was strictly OFF in baseline."
        },

        # --- Physically Impossible / Unsupported Cross-Stage Connections ---
        {
            "edge_id": "EDGE_20",
            "source_component": "AIT201",
            "destination_component": "FIT501",
            "source_stage": "P2",
            "destination_stage": "P5",
            "relationship_type": "unknown",
            "documented_direction": "UNKNOWN",
            "status": "DISALLOWED",
            "supporting_document": "SWaT Fluid Flow Architecture",
            "document_page_or_id": "P&ID Process Topology (Fluid transit passes through 3 buffer tanks T201, T301, T401)",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "NO_DISALLOWED",
            "dynamically_validated": False,
            "baseline_identifiability": "SPURIOUS_CORRELATION_CONFOUNDED",
            "physical_mechanism_and_notes": "Direct causal edge from Stage 2 conductivity analyzer to Stage 5 RO feed flow is physically impossible. Fluid passes through three intermediate storage tanks (T201, T301, T401) with multi-hour residence times. Statistically correlated due to global plant shutdown, but MUST be masked out in Stage 2."
        },
        {
            "edge_id": "EDGE_21",
            "source_component": "P601",
            "destination_component": "AIT201",
            "source_stage": "P6",
            "destination_stage": "P2",
            "relationship_type": "unknown",
            "documented_direction": "UNKNOWN",
            "status": "DISALLOWED",
            "supporting_document": "SWaT Fluid Flow Architecture",
            "document_page_or_id": "P&ID Process Topology",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "NO_DISALLOWED",
            "dynamically_validated": False,
            "baseline_identifiability": "SPURIOUS_CORRELATION_CONFOUNDED",
            "physical_mechanism_and_notes": "Stage 6 backwash pump has no piping connection to Stage 2 conductivity analyzer. Backwash returns to Tank T101, which then requires pump P101 to deliver to Stage 2. Direct edge is physically impossible and must be masked out."
        },
        {
            "edge_id": "EDGE_22",
            "source_component": "MV501",
            "destination_component": "DPIT301",
            "source_stage": "P5",
            "destination_stage": "P3",
            "relationship_type": "unknown",
            "documented_direction": "UNKNOWN",
            "status": "DISALLOWED",
            "supporting_document": "SWaT Fluid Flow Architecture",
            "document_page_or_id": "P&ID Process Topology",
            "evidence_confidence": "HIGH",
            "suitable_as_structural_constraint": "NO_DISALLOWED",
            "dynamically_validated": False,
            "baseline_identifiability": "SPURIOUS_CORRELATION_CONFOUNDED",
            "physical_mechanism_and_notes": "RO reject valve closure cannot physically cause pressure changes in Stage 3 UF membrane upstream. Hydraulics are isolated by RO feed tank T401 and pump P401. Direct edge is physically impossible and must be masked out."
        },
    ]

    df_reg = pd.DataFrame(register_entries)
    reg_path = out_dir / "physical_connectivity_register.csv"
    df_reg.to_csv(reg_path, index=False)
    logger.info("Saved physical connectivity register with %d edges to: %s", len(df_reg), reg_path)

    # Save audit configuration
    audit_cfg = {
        "audit_name": "SWaT A4/A5 Physical Graph and Connectivity Prior Audit",
        "dataset_file": "SWaT_dataset_Jul 19 v2.xlsx",
        "dataset_sha256": "39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc",
        "inspected_documents": [
            {
                "file_name": "SWaT data collection_20-07-2019 v2.pdf",
                "page_count": 1,
                "contains_pid_diagrams": False,
                "contents_summary": "Plant start/stop schedule and text descriptions/intents of 6 cyber attacks."
            },
            {
                "file_name": "readme.docx",
                "paragraph_count": 25,
                "contains_pid_diagrams": False,
                "contents_summary": "Timezone GMT offset notes and level switch text mapping table for tanks T201-T603."
            },
            {
                "file_name": "SWaT_dataset_Jul 19 v2.xlsx",
                "row_count": 14996,
                "col_count": 77,
                "contains_pid_diagrams": False,
                "contents_summary": "1 Hz raw numerical telemetry spreadsheet."
            }
        ],
        "pid_diagram_status": "MISSING_FROM_SUPPLIED_PACKAGE",
        "missing_evidence_required": [
            "Official iTrust / SUTD SWaT Engineering Piping and Instrumentation Diagrams (P&IDs) for Stages P1 to P6",
            "SWaT Plant Process Description and Control Logic Functional Specifications (documenting PLC interlocks and trip setpoints)",
            "Piping specifications and physical dimensions (pipe diameters, run lengths, nominal velocities, tank cross-sectional areas)"
        ],
        "registered_edges_count": len(register_entries),
        "status_breakdown": {
            "DOCUMENTED": sum(1 for e in register_entries if e["status"] == "DOCUMENTED"),
            "INFERRED": sum(1 for e in register_entries if e["status"] == "INFERRED"),
            "UNKNOWN": sum(1 for e in register_entries if e["status"] == "UNKNOWN"),
            "DISALLOWED": sum(1 for e in register_entries if e["status"] == "DISALLOWED"),
        },
        "audited_candidate_pairs": ["P301->DPIT301", "FIT501->PIT501", "FIT501->FIT502", "FIT201->LIT301", "MV501->PIT502"],
        "unexcited_actuators": ["P601", "MV501", "P102", "P201", "P202", "P204", "P206", "MV301", "MV303", "P302", "P401", "P402", "UV401", "P501", "P502", "P602", "P603"],
        "structural_mask_policy": "Only edges with status DOCUMENTED or INFERRED may be considered by Stage 2 gating; all DISALLOWED edges are masked to zero. Edges involving unexcited actuators are marked UNIDENTIFIABLE_UNEXCITED."
    }

    cfg_path = out_dir / "audit_config.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(audit_cfg, f, indent=2)
    logger.info("Saved audit configuration to: %s", cfg_path)


if __name__ == "__main__":
    build_physical_register()
