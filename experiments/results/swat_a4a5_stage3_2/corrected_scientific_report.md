# TCMIM Stage 3.2: Corrected Scientific Evaluation Report

## Project Context
**Project**: Temporal Cross-Machine Influence Modeling and Cascade Risk Estimation for Early Failure Propagation in Interconnected Industrial Machines (TCMIM).  
**Dataset**: Secure Water Treatment (SWaT) A4/A5 Raw Telemetry (July 2019, SHA-256: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`).  
**Milestone**: Stage 3.2 — Implementation of Safe Conditional Structural Connectivity and Corrected Scientific Evaluation Reporting following the completed Stage 3.1 Independent Verification Audit.

---

## 1. Executive Summary

Following the completion of the Stage 3.1 independent scientific verification audit ([experiments/results/swat_a4a5_stage3_1_audit/](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_stage3_1_audit/)), this milestone enacts the required technical and scientific corrections:

1. **Topology & Structural Mask**: Replaced the unsafe unconditional mapping of inferred candidate edges with an explicit quaternary structural status (`ALLOWED`, `DISALLOWED`, `CONDITIONAL`, `UNKNOWN`). For transfer edge `P101 -> FIT201`, Gate G0 now strictly evaluates operating predicate `MV201 == 2` against authenticated actuator telemetry, failing closed if evidence is missing, closed, invalid, stale, or unknown.
2. **Evaluation Metric Qualification**: Disqualified the reported headline startup score ($R^2 = 0.9963$) as contaminated. Officially reclassified Attack A6 Model 2 ($R^2 = 0.9961$) as an **`IN-SAMPLE DESCRIPTIVE FIT`** because the dataset contains only a single observed episode ($N=1$) of State S3, meaning out-of-sample validation is **`NOT AVAILABLE`**.
3. **Closing Stroke Dynamics**: Transparently reported the failure of the simple closing FOPDT model on episode `MV201_CLOSE_11692` ($R^2 = -1.7376$), explaining that premature pump `P101` de-energization changes the observed flow trajectory.
4. **Safety & Plant Protection**: Production gating remains disconnected (`production_gating_connected: false`), production delay bounds $[0, 600]\text{ s}$ remain intact, and plantwide CRI remains strictly disabled.

---

## 2. Physical Topology and Structural Gate Reconciliation

### 2.1 Refutation and Disallowance of `P101 -> FIT101`
- **Empirical Evidence**: Across the entire 14,996-row continuous telemetry record, correlation $\text{corr}(\text{P101}, \text{FIT101}) = 0.0528$. During 12 pump starts, zero transitions produced flow response in `FIT101`. Conversely, flow `FIT101` is governed strictly by municipal inlet valve `MV101` ($r = 0.9259$, mean flow $4.382\text{ m}^3/\text{h}$ when open).
- **Physical Ground Truth**: Flow meter `FIT101` measures raw water entering Tank `T101`. Pump `P101` draws suction *from* Tank `T101` and discharges into Stage 2 pipe. A direct hydraulic edge `P101 -> FIT101` is physically impossible.
- **Classification**: **`DISALLOWED`** (`StructuralStatus.DISALLOWED`, `'0'`). Permanently prohibited in [proposed_connectivity_register_stage3_2.csv](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_stage3_2/proposed_connectivity_register_stage3_2.csv).

### 2.2 Safe Conditional Representation of `P101 -> FIT201`
- **Physical Mechanism**: Pump `P101` provides motive hydraulic head into Stage 2. However, flow `FIT201` passes through motorized valve `MV201`.
- **Condition**: Hydraulic transfer occurs **if and only if** `MV201 == 2` (OPEN). When `MV201 == 1` (CLOSED), flow is physically blocked ($0.000\text{ m}^3/\text{h}$).
- **Classification**: **`CONDITIONALLY SUPPORTED`** (`StructuralStatus.CONDITIONAL`, `'C'`).
- **Gating Invariant**: In Gate G0, candidate edge `P101 -> FIT201` may pass to subsequent delay gates if and only if actuator evidence confirms `MV201 == 2`. If evidence is missing, invalid, or `MV201 == 1`, G0 rejects the edge conservatively.
- **Scientific Qualification**: Empirical dynamic correlation ($r = 0.9870$) provides dynamic support under operating condition `MV201 == 2`, but does not constitute independent causal proof across all plant operating modes.

---

## 3. Dynamic Modeling Reconciliation

### 3.1 P301 → DPIT301 (Differential Pressure Across UF Membrane)

| Model & Evaluation Regime | Episode ID / Partition | Evaluation Type | Reported $R^2$ | Verified $R^2$ | Reported RMSE | Verified RMSE | Audit Status & Qualification |
|---|---|---|---|---|---|---|---|
| **State S2 Normal Startup** | `P301_START_9419` | Held-Out Validation | 0.9936 (pooled) | **0.9994** | 0.1877 (pooled) | 0.0570 kPa | **INDEPENDENTLY VALIDATED**. Genuinely held-out normal cycle. |
| **State S2 Normal Startup** | `P301_START_12124` | Held-Out Validation | 0.9936 (pooled) | **0.9959** | 0.1877 (pooled) | 0.1533 kPa | **INDEPENDENTLY VALIDATED**. Genuinely held-out normal cycle. |
| **State S2 Normal Startup** | `P301_START_14024` | Held-Out Validation | 0.9936 (pooled) | **0.9845** | 0.1877 (pooled) | 0.2810 kPa | **INDEPENDENTLY VALIDATED**. Genuinely held-out normal cycle. |
| **State S2 Normal Startup (Pooled)** | `POOLED_VAL_NORMAL_3_EPS` | Held-Out Validation | 0.9936 | **0.9936** | 0.1877 | 0.1877 kPa | **INDEPENDENTLY VALIDATED**. Verified pooled normal held-out score across 180s. |
| **State S3 Attack A6 (SISO)** | `P301_START_13504` | Cross-Regime Failure | -1.8922 | **-1.8922** | 4.6258 | 4.6258 kPa | **DISALLOWED**. Single-input model fails ($SS_{\text{res}} = 1283.86 > SS_{\text{tot}} = 443.91$). |
| **State S3 Attack A6 (MISO)** | `P301_START_13504` | In-Sample Reconstruction | 0.9961 | **0.9961** | 0.2458 | 0.1701 kPa | **IN-SAMPLE DESCRIPTIVE FIT**. Train-on-test leakage ($N=1$ episode). Out-of-sample validation **NOT AVAILABLE**. |
| **Headline Combined Startup** | `HEADLINE_COMBINED` | Contaminated Concatenation | 0.9963 | **0.9963** | 0.1835 | 0.1835 kPa | **DISQUALIFIED**. Combines 180s held-out normal with 60s in-sample Attack A6 observations. |
| **State S5 Shutdown (Pooled)** | `POOLED_VAL_SHUTDOWN_3_EPS` | Held-Out Validation | 0.9644 | **0.9644** | 0.5238 | 0.5238 kPa | **INDEPENDENTLY VALIDATED**. Verified across 3 independent shutdown cycles. |

#### Scientific Findings:
1. **Normal Startup Validity**: Under standard operations (`MV302 == 1` CLOSED at pump start), the two-stage model (dead-head pressurization to $6.1\text{ kPa}$ followed by permeate valve opening to $11.2\text{ kPa}$) is **independently validated** with out-of-sample $R^2 = 0.9936$ and $\text{RMSE} = 0.1877\text{ kPa}$.
2. **Attack A6 In-Sample Fit**: Because the SWaT July 2019 dataset contains only a single startup episode where `MV302 == 2` at $t=0$ (Attack 6, row 13,504), fitting FOPDT parameters ($K=11.2\text{ kPa}$, $\tau=4.0\text{ s}$, $t_d=1.0\text{ s}$) on row 13,504 and evaluating on row 13,504 is a circular in-sample fit. Its $R^2 = 0.9961$ must not be reported as held-out validation. Independent validation remains **`NOT AVAILABLE`** until multi-run dataset pooling is conducted.
3. **Disqualification of Headline Metric**: Reporting $R^2 = 0.9963$ as the headline startup validation score is scientifically invalid because it masks in-sample evaluation within pooled held-out metrics.

---

### 3.2 MV201 → FIT201 (Stage 2 Chemical Dosing Flow Response)

| Model & Evaluation Regime | Episode ID / Partition | Evaluation Type | Reported $R^2$ | Verified $R^2$ | Reported RMSE | Verified RMSE | Audit Status & Qualification |
|---|---|---|---|---|---|---|---|
| **Opening Stroke** | `MV201_OPEN_10066` | Held-Out Validation | 0.8937 (pooled) | **0.9943** | 0.3456 (pooled) | 0.0791 $\text{m}^3/\text{h}$ | **INDEPENDENTLY VALIDATED**. Normal opening cycle. |
| **Opening Stroke** | `MV201_OPEN_11221` | Held-Out Validation | 0.8937 (pooled) | **0.6994** | 0.3456 (pooled) | 0.5851 $\text{m}^3/\text{h}$ | **CONDITIONALLY SUPPORTED**. Pump P101 activation delayed by 6s, reducing fit. |
| **Opening Stroke** | `MV201_OPEN_14247` | Held-Out Validation | 0.8937 (pooled) | **0.9910** | 0.3456 (pooled) | 0.0980 $\text{m}^3/\text{h}$ | **INDEPENDENTLY VALIDATED**. Normal opening cycle. |
| **Opening Stroke (Pooled)** | `POOLED_VAL_OPEN_3_EPS` | Held-Out Validation | 0.8937 | **0.8937** | 0.3456 | 0.3456 $\text{m}^3/\text{h}$ | **INDEPENDENTLY VALIDATED**. Verified across 135s of opening cycles. |
| **Closing Stroke** | `MV201_CLOSE_11047` | Held-Out Validation | 0.5434 (pooled) | **0.9909** | 0.4611 (pooled) | 0.0799 $\text{m}^3/\text{h}$ | **INDEPENDENTLY VALIDATED**. Normal closing cycle with concurrent pump operation. |
| **Closing Stroke** | `MV201_CLOSE_11692` | Held-Out Validation | 0.5434 (pooled) | **-1.7376** | 0.4611 (pooled) | 0.6472 $\text{m}^3/\text{h}$ | **CONDITIONALLY SUPPORTED**. Severe episode failure ($SS_{\text{res}} = 12.56 > SS_{\text{tot}} = 4.59$). |
| **Closing Stroke (Pooled)** | `POOLED_VAL_CLOSE_2_EPS` | Held-Out Validation | 0.5434 | **0.5434** | 0.4611 | 0.4611 $\text{m}^3/\text{h}$ | **CONDITIONALLY SUPPORTED**. Pooled metric masks individual failure on episode 11692. |

#### Scientific Findings:
1. **Actuator Stroke Asymmetry**: Opening dynamics ($t_d \approx 12.92\text{ s}$, settling $20-22\text{ s}$) reflect motor stroke transit before flow initiation. Closing dynamics ($t_d \approx 3.74\text{ s}$, settling $11-12\text{ s}$) reflect rapid valve seating.
2. **Closing Failure Episode 11692**: In episode 11,692, pump `P101` shut down 7 seconds *before* motorized valve `MV201` closure initiated. Loss of upstream pressure caused flow to decay prematurely, producing an individual episode $R^2 = \mathbf{-1.7376}$. The pooled metric ($R^2 = 0.5434$) masked this failure. The simple SISO closing model does not reliably represent cycles with asynchronous pump shutdown.

---

## 4. Quarantined and Unresolved Relationships

1. **`P205 -> AIT203` (Sodium Bisulfite Dosing Pump to ORP Analyzer)**:
   - Baseline variance is zero ($\sigma = 0.0$ across baseline).
   - Relationship is unidentifiable in single-run baseline telemetry.
   - Status: **`UNRESOLVED`**. Quarantined from dynamic gating.
2. **`FIT501 -> FIT502` (RO Feed Flow to Permeate Flow)**:
   - Represents static mass balance across reverse osmosis membrane separation ($\text{FIT502} \approx 0.78 \cdot \text{FIT501}$).
   - High correlation is driven by steady-state ratio, not propagation delay dynamics.
   - Status: **`UNRESOLVED / QUARANTINED`**. Quarantined from delay gating.

---

## 5. Authoritative Relationship Decisions

| Relationship | Structural Status | Validation Classification | Permitted Integration Scope | Prerequisites Before Stage 4 Production Gating |
|---|---|---|---|---|
| **`MV201 -> FIT201`** | `ALLOWED` | `CONDITIONALLY SUPPORTED` | Shadow Mode Experimental Gating Only | Separate stroke models ($5-25\text{ s}$ open, $1-15\text{ s}$ close); monitor P101 motor status. |
| **`P301 -> DPIT301`** | `ALLOWED` | `CONDITIONALLY SUPPORTED` | Shadow Mode (Restricted to State S2) | State S2 ($5-55\text{ s}$) validated. State S3 requires multi-run dataset pooling. |
| **`P101 -> FIT101`** | `DISALLOWED` | `DISALLOWED` | Prohibited from Structural Graph | Instrumentation misidentification corrected. Direct edge refuted. |
| **`P101 -> FIT201`** | `CONDITIONAL` | `CONDITIONALLY SUPPORTED` | Shadow Mode with Actuator Gate | Requires authenticated state evidence `MV201 == 2`. Fails closed if missing/closed. |
| **`P205 -> AIT203`** | `ALLOWED` | `UNRESOLVED` | Quarantined from Gating | Zero baseline variance. Requires multi-run operational pooling. |
| **`FIT501 -> FIT502`** | `ALLOWED` | `UNRESOLVED` | Quarantined from Dynamic Gating | Static membrane mass balance. Quarantined from dynamic delay gating. |

---

## 6. Safety and Production Status

In strict accordance with project safety guidelines:
1. **Production Gating**: Remains completely disconnected (`production_gating_connected = False`). Default production delay bounds $[0, 600]\text{ s}$ are unchanged.
2. **Plantwide CRI**: Remains completely disabled (`plantwide_cri_enabled = False`).
3. **Shadow Mode Evaluation**: Permitted for experimental observation logging, guaranteeing zero modification of production decisions.
