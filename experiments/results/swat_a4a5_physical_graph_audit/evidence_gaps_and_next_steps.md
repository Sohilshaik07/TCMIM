# SWaT A4/A5 Documentary Evidence Gaps, Partial Physical Mask, and Next Steps

**Document Version**: 1.0  
**Audit Date**: 2026-10-26T13:25:20Z  
**Target Repository**: TCMIM (`src/tcmim/`, `experiments/`)  
**Scope**: Systematic audit of documentary evidence available in the SWaT A4/A5 July 2019 dataset package, catalog of missing engineering documents, and justification of the Partial Physical Structural Mask.

---

## 1. Audit of Available Source Documentation

To determine whether an auditable physical connectivity graph can be constructed directly from the provided materials, we inspected every file in `tcmim/data/raw/SWAT_A4_A5_JULY_2019/`:

### A. `SWaT data collection_20-07-2019 v2.pdf`
- **Physical Extent**: Exactly 1 single page (65,482 bytes).
- **Contents**:
  - High-level plant schedule: Start time (12:35 PM GMT+8), Normal run period (12:35 PM to 2:50 PM), Attack period (3:08 PM to 4:16 PM), Plant stop time (4:35 PM).
  - Six brief text entries describing the attack actions and intended cyber-physical outcomes:
    1. FIT401: Spoof 0.8 to 0.5 (Intent: stop de-chlorination by switching off UV401).
    2. LIT301: Spoof 835 to 1024 (Intent: lead to underflow in T301).
    3. P601: Switch OFF to ON (Intent: increase water in raw water tank).
    4. MV201 & P101: Switch MV201 OPEN and P101 ON (Intent: overflow tank T301).
    5. MV501: Switch OPEN to CLOSE (Intent: drain water from RO).
    6. P301: Switch ON to OFF (Intent: halt stage 3 UF process).
- **Audit Assessment**: **Contains ZERO engineering drawings, ZERO piping schematics, and ZERO instrument loop diagrams.** It provides intent descriptions that confirm specific functional connections (e.g., FIT401 interlocked to UV401; P601 discharges to raw water tank T101), but cannot establish a complete plant graph.

### B. `readme.docx`
- **Physical Extent**: 25 paragraphs (15,702 bytes).
- **Contents**:
  - Explanatory note on timestamp timezone conversion (GMT+0 in spreadsheet vs. GMT+8 in PDF).
  - Status mapping table for discrete level switches (`Active` / `Inactive`) on tanks T-201, T-202, T-203, T-401, T-601, T-602, T-603.
- **Audit Assessment**: **Contains ZERO process descriptions or piping topologies.**

### C. `SWaT_dataset_Jul 19 v2.xlsx`
- **Physical Extent**: 14,996 rows, 77 telemetry columns (5,536,097 bytes).
- **Contents**: Numerical time series only.
- **Audit Assessment**: Numerical data alone cannot reveal unexcited connections or distinguish direct causality from shared macro-trends.

---

## 2. Explicit Declaration of Missing Evidence

Because the supplied dataset package contains only operational telemetry and high-level attack descriptions, the physical connectivity of the plant cannot be established purely from local files without risk of fabrication.

The following external engineering documents are **missing from the dataset distribution** and are required for full physical validation:

1. **Official SWaT Engineering Piping and Instrumentation Diagrams (P&IDs)**:
   - Drawing Nos. for Stages P1 through P6 (e.g., SUTD-iTrust Drawing Set SWaT-PID-001 through SWaT-PID-006).
   - Necessary to verify exact piping lines, manual isolation valves, check valve orientations, bypass lines, and instrument sensor tapping locations.
2. **SWaT Process and Instrumentation Control Narrative / Functional Specifications**:
   - Official document detailing PLC control loops (PLC1 through PLC6), PID tuning parameters, automatic pump lead/lag alternations, and safety interlocks (such as tank high/low alarm trip setpoints).
   - Necessary to distinguish electrical control edges from fluid hydraulic edges.
3. **Plant Geometric and Hydrodynamic Metadata**:
   - Pipe nominal diameters ($D$), pipe run lengths between stages ($L$), nominal volumetric flow rates ($Q$), nominal flow velocities ($v = Q/A$), and tank cross-sectional areas ($A_{\text{tank}}$).
   - Necessary to compute true hydrodynamic transport delays ($\tau_{\text{transit}} = L/v$) and calculate differential tank state derivatives ($\frac{dh}{dt}$).

---

## 3. Justification for a Partial Physical Structural Mask

Because official P&ID drawings are missing from the supplied dataset, attempting to construct an exhaustive 77 $\times$ 77 adjacency graph would require guessing unverified connections, violating TCMIM Scientific Preservation Rule 6 (*"Do not invent piping, electrical connections, flow directions, or machine dependencies"*).

Conversely, allowing Stage 2 to operate without any physical constraints would permit unconstrained cross-stage shortcuts driven by sensor drift (`AIT201`), violating Rule 5 (*"Do not infer physical connectivity from correlation alone"*).

**The Solution: An Auditable Partial Physical Structural Mask**:
TCMIM establishes a rigorously audited **Partial Physical Connectivity Register** of 22 critical relationships:
- **2 Explicitly DOCUMENTED Connections**:
  - `EDGE_14` (`FIT401` $\to$ `UV401`): Explicitly confirmed by PDF p. 1 (Attack 1 low-flow interlock).
  - `EDGE_18` (`P601` $\to$ `LIT101`): Explicitly confirmed by PDF p. 1 (Attack 3 backwash recycle line).
- **16 INFERRED Connections (High/Medium Confidence)**:
  - Grounded in verified engineering tag definitions (`swat.py`) and standard water treatment unit operations (e.g., pump `P101` draws from tank `T101` and generates flow `FIT101`; pump `P301` builds membrane differential pressure `DPIT301`).
- **1 UNKNOWN / Rejected Connection**:
  - `EDGE_02` (`FIT501` $\to$ `PIT501`): Rejected because downstream flow does not cause upstream suction pressure.
- **3 Strictly DISALLOWED Non-Physical Connections**:
  - `EDGE_20` (`AIT201` $\to$ `FIT501`): Cross-stage jump shortcut.
  - `EDGE_21` (`P601` $\to$ `AIT201`): Disconnected actuator to chemical sensor.
  - `EDGE_22` (`MV501` $\to$ `DPIT301`): Upstream hydraulic transmission against pump isolation.

All other pairwise connections ($77 \times 76 - 22 = 5,830$ pairs) remain classified as `UNKNOWN` pending acquisition of official P&ID drawings.

---

## 4. Single Recommended Next Research Action

### Action: **Implement the Non-Invasive `G0_STRUCTURAL_MASK` Consistency Gate in Stage 2**

Before executing dynamic DAG inference or calculating Cascade Risk Index (CRI) metrics on the SWaT dataset, execute the following single engineering milestone:

1. **Construct a `PhysicalStructuralMask` Module**:
   - Create `src/tcmim/gating/structural_mask.py` implementing the ternary matrix defined in [`structural_mask_spec.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_physical_graph_audit/structural_mask_spec.md).
   - Ingest [`physical_connectivity_register.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv) as the auditable source of truth.
2. **Add Non-Breaking Gate `G0` to `GatingPipeline`**:
   - Insert `G0_STRUCTURAL_MASK` before `G1_DELAY_FEASIBILITY` in [`src/tcmim/gating/gates.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/gates.py).
   - In default / conservative mode, reject any candidate edge where `status == DISALLOWED`.
3. **Maintain Test Suite Integrity**:
   - Ensure all 757 existing unit tests pass without regression by configuring `allow_unknown=True` for non-SWaT benchmark suites (MetroPT-3, Synthetic fixtures) that lack a physical P&ID mask.
