# TCMIM Stage 3.1: Independent Scientific Verification Audit Report

## Executive Summary

This report presents an independent scientific verification audit of **TCMIM Stage 3: Topology Correction and State-Conditioned Dynamic Modeling** on the SWaT A4/A5 July 2019 dataset.

The audit was conducted strictly as a **read-only scientific evaluation**. No production source code, configuration registers, experimental results, or model parameters were modified. Plantwide CRI evaluation remains strictly disabled.

### Core Audit Verdicts

1. **`P101 -> FIT101` Disallowance: INDEPENDENTLY VERIFIED AND PHYSICALLY GROUNDED**
   - The Stage 3 conclusion that `P101 -> FIT101` is an instrumentation misidentification is verified. Correlation in raw telemetry is $r = 0.0528$; across all 12 transitions of pump `P101`, flow `FIT101` showed zero step response ($\Delta < 0.005\text{ m}^3/\text{h}$). Flow is governed by municipal inlet valve `MV101` ($r = 0.9259$). P&ID flow routing confirms `FIT101` measures inflow into tank T101, whereas `P101` suctions water out of tank T101.
2. **`P101 -> FIT201` Proposed Register Inclusion: DEFECTIVE SCHEMA VULNERABILITY**
   - While `P101` provides the motive force for Stage 2 flow ($r = 0.8845$), the relationship is physically conditional on motorized valve `MV201` being open.
   - **Critical Vulnerability**: The production `PhysicalStructuralMask` and Gate G0 evaluate only component pairs `(source, destination)`. When `EDGE_23` is registered with status `INFERRED`, the mask converts it to `StructuralStatus.ALLOWED`, causing the pipeline to treat `P101 -> FIT201` as **universally permitted across all operating states**—including when `MV201` is closed.
3. **`MV201 -> FIT201` Opening Stroke FOPDT: INDEPENDENTLY VERIFIED**
   - The opening model ($t_d = 12.92\text{ s}, \tau = 3.94\text{ s}, K = 2.36\text{ m}^3/\text{h}$) was fitted strictly on 3 development episodes and evaluated on 3 independent held-out validation episodes, achieving pooled $R^2 = \mathbf{0.8937}$ ($\text{RMSE} = 0.3456\text{ m}^3/\text{h}$).
   - Individual validation episodes achieve $R^2 = 0.9943$ (episode 10066) and $R^2 = 0.9910$ (episode 14247). Episode 11221 exhibits lower $R^2 = 0.6994$ due to an operational delay in pump P101 activation during recovery from Attack A4.
4. **`MV201 -> FIT201` Closing Stroke FOPDT: QUALIFIED (UNSTABLE ON ABNORMAL CYCLES)**
   - The pooled held-out validation metric $R^2 = 0.5434$ was reproduced, but masks an individual failure: in episode 11692, pump P101 shut down 7 seconds before valve travel initiated, causing premature flow decay and yielding an individual episode $R^2 = \mathbf{-1.7373}$.
5. **`P301 -> DPIT301` Normal Startup Two-Stage Model: INDEPENDENTLY VERIFIED**
   - Normal startups with permeate valve closed (`MV302 == 1`, State S2) exhibit extreme repeatability, achieving pooled held-out $R^2 = \mathbf{0.9936}$ ($\text{RMSE} = 0.1877\text{ kPa}$).
   - Per-episode validation metrics: Episode 9419 ($R^2 = 0.9994$), Episode 12124 ($R^2 = 0.9959$), Episode 14024 ($R^2 = 0.9845$).
   - Audit confirms that MV302 opening at $t \approx 32 - 33\text{ s}$ is a deterministic interlock programmed into PLC3 ladder logic.
6. **`P301 -> DPIT301` Attack A6 Model 2 "$R^2 = 0.9961$ Validation": CRITICAL SCIENTIFIC DEFECT (TRAIN-ON-TEST LEAKAGE)**
   - Across all 14,996 records, there is **only one single episode** where `P301` starts with `MV302 == 2` (Attack A6 at row 13,504).
   - In `swat_a4a5_stage3_runner.py`, the FOPDT parameters for State S3 were **fitted directly on row 13,504 and evaluated on the same row 13,504**.
   - The reported $R^2 = 0.9961$ is an **in-sample descriptive reconstruction**, NOT an independent held-out validation. There are zero independent held-out validation episodes for State S3 in the dataset.
   - The overall startup validation score of $R^2 = 0.9963$ is mathematically contaminated by pooling 180 out-of-sample observations with 60 in-sample fitted observations.

---

## 1. Artifact and Data Provenance Audit

The raw dataset and historical results were audited for file integrity and cryptographic immutability:

- **Raw Dataset**: `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx`
  - SHA-256: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc` (Verified unchanged).
  - Row count: 14,996 rows, spanning 04:30:00 to 08:39:59 UTC (4.165 hours).
  - Nominal sampling rate: 1.0 Hz (median $\Delta t = 1.000\text{ s}$).
  - Timestamp continuity: Exactly 6 gaps $>1.5\text{ s}$ (max $5.45\text{ s}$ at row 2245), zero duplicate timestamps.
- **Original Physical Register**: `experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv`
  - SHA-256: `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3` (Verified unchanged).
- **Historical Milestone Integrity**: Directories `swat_a4a5_g0_evaluation/`, `swat_a4a5_dynamic_evidence_readiness/`, and `swat_a4a5_raw_dynamic_validation/` were audited and confirmed preserved without modification.

---

## 2. Event Partitioning and Temporal Leakage Audit

A complete audit of all 49 physical actuator transitions (13 for P301, 24 for MV201, 12 for P101) was conducted to verify sample independence and partition boundaries:

1. **Development vs. Validation Boundary (Row 8,400 / 06:50:00 UTC)**:
   - Rows 0 to 8,399 define the baseline development partition.
   - Rows 8,400 to 14,995 define the held-out validation partition (encompassing cyber-attacks A1 to A6).
   - Zero physical response windows crossed the row 8,400 boundary.
2. **Episode Overlap Analysis**:
   - Consecutive normal pumping cycles are separated by hundreds or thousands of seconds of steady operation (median interval between P301 startups is 1,302.5 seconds; median interval between MV201 openings is 2,692 seconds).
   - Within the 60-second evaluation windows, no normal episode overlaps with another normal episode.
   - In raw telemetry, motorized valve transitions exhibit two digital edges per stroke ($1 \to 0$ travel start, $0 \to 2$ travel complete). Stage 3 correctly filtered these completion edges, ensuring each stroke was counted exactly once.
3. **Leakage Finding**:
   - Temporal event leakage between development and validation was zero for normal episodes.
   - However, **parameter leakage occurred on Attack A6**, where the validation episode was ingested into the optimization objective function.

---

## 3. Detailed Audit of Model Evaluations

### 3.1 P301 -> DPIT301 Normal Startup Modeling (State S2)

Under normal operating conditions (`MV302 == 1` at pump start), the dynamic response is governed by a two-stage physical sequence:
- **Phase 1 (Dead-Head Pressurization)**: From $t = 0$ to $t \approx 32\text{ s}$, pump P301 builds fluid pressure against closed permeate valve MV302. Pressure rises rapidly and plateaus at $6.08 \pm 0.08\text{ kPa}$.
- **Phase 2 (Permeate Flow Establishment)**: At $t = 32 - 33\text{ s}$, PLC3 ladder logic commands MV302 to open ($1 \to 0 \to 2$, taking 7–8s). As the valve clears, fluid permeates the ultrafiltration membranes, and differential pressure rises to steady-state operating pressure ($12.55 \pm 0.15\text{ kPa}$).

#### Per-Episode Held-Out Performance Reconciliation

The Stage 3 empirical profile derived from the 3 development episodes (indices 1364, 4050, 6720) was evaluated against each validation episode independently:

| Episode Identifier | Row Index | Timestamp (UTC) | $R^2$ Score | RMSE (kPa) | MAE (kPa) | Max Error (kPa) | Verification Status |
|---|---|---|---|---|---|---|---|
| `P301_START_9419` | 9,419 | 2019-07-20 07:07:03 | **0.9994** | 0.0570 | 0.0409 | 0.1697 | **VERIFIED HELD-OUT** |
| `P301_START_12124` | 12,124 | 2019-07-20 07:52:08 | **0.9959** | 0.1533 | 0.1237 | 0.4567 | **VERIFIED HELD-OUT** |
| `P301_START_14024` | 14,024 | 2019-07-20 08:23:48 | **0.9845** | 0.2810 | 0.2344 | 0.5698 | **VERIFIED HELD-OUT** |
| **Pooled Validation (N=180)** | — | — | **0.9936** | **0.1877** | **0.1330** | 0.5698 | **VERIFIED POOLED** |

The normal startup model demonstrates extraordinary out-of-sample reproducibility across all individual episodes.

---

### 3.2 P301 -> DPIT301 Attack A6 Reconciliation and Train-on-Test Audit

Under cyber-attack A6 (row 13,504), the attacker cycled pump `P301` while permeate valve `MV302` was already fully open (`MV302 == 2`).

#### Model 1 (Single-Input Normal) Failure Reproduction
- When the normal two-stage profile was applied to Attack A6:
  $$\text{SS}_{\text{tot}} = \sum_{t=0}^{59} (y_t - \bar{y})^2 = 443.91\text{ kPa}^2$$
  $$\text{SS}_{\text{res}} = \sum_{t=0}^{59} (y_t - \hat{y}_{\text{normal}})^2 = 1283.86\text{ kPa}^2$$
  $$R^2 = 1 - \frac{1283.86}{443.91} = \mathbf{-1.8922} \quad (\text{RMSE} = \mathbf{4.6258\text{ kPa}})$$
- This failure is verified down to the fourth decimal place.

#### Model 2 (State-Conditioned MISO) Audit
The Stage 3 report claims Model 2 achieved held-out validation $R^2 = 0.9961$ on Attack A6.
The audit inspected the fitting code in `experiments/swat_a4a5_stage3_runner.py` (lines 340–348):

```python
    s3_val_y = s3_episodes[0]["y"][:60]
    s3_t = np.arange(len(s3_val_y))
    popt_s3, _ = curve_fit(fopdt_step, s3_t, s3_val_y, p0=[1.5, 10.7, 4.0, 1.0], ...)
    s3_val_pred_miso = fopdt_step(s3_t, *popt_s3)
    m2_s3_val_metrics = compute_metrics(s3_val_y, s3_val_pred_miso)
```

**Audit Assessment**:
1. `s3_val_y` is the Attack A6 observation vector ($N=1$ episode).
2. The parameters `popt_s3` were estimated by minimizing squared errors on `s3_val_y`.
3. The metrics `m2_s3_val_metrics` were computed by evaluating `popt_s3` on the identical array `s3_val_y`.
4. There is no other episode of State S3 in the dataset.
5. **Verdict**: This is an **in-sample descriptive curve fit**. Reporting it as held-out validation violates scientific standards.
6. **Overall Score Contamination**: The reported overall startup validation score of $R^2 = 0.9963$ is computed by pooling the 3 out-of-sample normal episodes with this 1 in-sample fitted episode.

---

### 3.3 MV201 -> FIT201 Opening and Closing Stroke Dynamics

#### Opening Stroke Dynamics
- Fitted on Development: $y_0 = 0.0158\text{ m}^3/\text{h}, K = 2.3622\text{ m}^3/\text{h}, \tau = 3.9434\text{ s}, t_d = 12.9185\text{ s}$.
- Validation Episode 10066 (Normal): $R^2 = \mathbf{0.9943}, \text{RMSE} = 0.0791\text{ m}^3/\text{h}$.
- Validation Episode 14247 (Normal): $R^2 = \mathbf{0.9910}, \text{RMSE} = 0.0980\text{ m}^3/\text{h}$.
- Validation Episode 11221 (Post-Attack Recovery): $R^2 = \mathbf{0.6994}, \text{RMSE} = 0.5851\text{ m}^3/\text{h}$.
  - In episode 11221, pump P101 activation was delayed by 6 seconds (energizing 14s after MV201 command instead of the normal 7–8s). Flow remained at zero until the pump started, causing a transient prediction error.
- **Pooled Held-Out Validation**: $R^2 = \mathbf{0.8937}, \text{RMSE} = 0.3456\text{ m}^3/\text{h}$. Verified.

#### Closing Stroke Dynamics
- Fitted on Development: $y_0 = 2.2187\text{ m}^3/\text{h}, K = 2.2717\text{ m}^3/\text{h}, \tau = 4.0711\text{ s}, t_d = 3.7399\text{ s}$.
- Validation Episode 11047 (Normal): $R^2 = \mathbf{0.9909}, \text{RMSE} = 0.0799\text{ m}^3/\text{h}$.
- Validation Episode 11692 (Anomalous Shutdown): $R^2 = \mathbf{-1.7373}, \text{RMSE} = 0.6471\text{ m}^3/\text{h}$.
  - In episode 11692, pump P101 was de-energized 7 seconds *before* valve closure initiated. By the time MV201 began closing, flow was already zero. The model predicted flow to persist for 3.74 seconds of dead time, producing large residuals.
- **Pooled Held-Out Validation**: $R^2 = \mathbf{0.5434}, \text{RMSE} = 0.4611\text{ m}^3/\text{h}$. Verified pooled, but disqualified as universally stable.

---

## 4. Audit of Test Coverage and Scientific Invariants

The 43 automated unit tests were analyzed line-by-line:
1. **Pass Rate**: 43 of 43 tests pass cleanly.
2. **Assertion Quality**:
   - 14 tests verify file and dictionary key existence.
   - 4 tests verify cryptographic hashes.
   - 9 tests re-assert pre-computed numbers from JSON files rather than recalculating them from raw telemetry.
3. **Critical Blindspots**:
   - No test verifies out-of-sample data partitioning for State S3.
   - No test checks that `P101 -> FIT201` is rejected when `MV201` is closed.
   - The test `test_p101_to_fit201_permitted_conditionally_in_proposed_register` explicitly asserts `assert mask.is_permitted("P101", "FIT201")`, validating the unconditioned bypass.
   - No test verifies per-episode minimum performance, allowing negative $R^2$ on episode 11692 to pass unnoticed behind pooled metrics.

---

## 5. Comprehensive Claim vs. Evidence Matrix

| Claim ID | Stage 3 Claim | Reported Metric | Independent Audit Finding | Audit Status |
|---|---|---|---|---|
| **CLM-01** | `P101 -> FIT101` is misidentified and disallowed | $r=0.0528, 0/12$ transitions | Confirmed. FIT101 is municipal inlet; P101 is suction transfer. | **VERIFIED** |
| **CLM-02** | `P101 -> FIT201` conditionally permitted when MV201=2 | Status `INFERRED` | Empirically real, but structural mask treats it as unconditionally allowed. | **DEFECTIVE SCHEMA** |
| **CLM-03** | MV201 opening FOPDT validated | $R^2=0.8937$ | Confirmed out-of-sample across 3 independent cycles. | **VERIFIED** |
| **CLM-04** | MV201 closing FOPDT validated | $R^2=0.5434$ | Pooled match, but episode 11692 fails with $R^2=-1.7373$ due to pump lead time. | **QUALIFIED** |
| **CLM-05** | P301 normal startup model validated | $R^2=0.9936$ | Confirmed out-of-sample across 3 cycles ($R^2 \in [0.9845, 0.9994]$). | **VERIFIED** |
| **CLM-06** | Single-input model fails on Attack A6 | $R^2=-1.8922$ | Confirmed. Caused by open permeate valve sequence bypass. | **VERIFIED** |
| **CLM-07** | State-conditioned model validated on Attack A6 | $R^2=0.9961$ | In-sample fit on $N=1$ episode. Not held-out validation. | **DESCRIPTIVE ONLY** |
| **CLM-08** | Overall P301 startup validation | $R^2=0.9963$ | Contaminated by pooling 180 out-of-sample rows with 60 in-sample rows. | **QUALIFIED** |
| **CLM-09** | 43 unit tests confirm scientific invariants | 43 passed | Tests pass, but fail to catch in-sample leakage and unconditioned bypass. | **PARTIALLY VALID** |

---

## 6. Official Final Decisions

1. **`MV201 -> FIT201`**: **CONDITIONALLY READY FOR EXPERIMENTAL INTEGRATION**
   - Opening model is ready for experimental gating with delay bound $5-25\text{ s}$.
   - Closing model must be restricted to $1-15\text{ s}$ and must account for pump P101 de-energization lead time.
2. **`P301 -> DPIT301`**: **CONDITIONALLY READY FOR EXPERIMENTAL INTEGRATION (RESTRICTED TO STATE S2)**
   - State S2 two-stage normal model is ready for experimental gating with delay bound $5-55\text{ s}$.
   - State S3 model is **DESCRIPTIVE ONLY** and must NOT be used for dynamic rejection until multi-run dataset pooling provides out-of-sample episodes.
3. **`P101 -> FIT101`**: **REFUTED / DISALLOWED**
   - Permitted as a disallowance constraint in the active structural register.
4. **`P101 -> FIT201`**: **DESCRIPTIVE EVIDENCE ONLY**
   - Must NOT be added as `ALLOWED` in the active structural register until Gate G0 supports operating-state evaluation. Retain as `CONDITIONAL` / `UNKNOWN`.
5. **`P205 -> AIT203`**: **NOT VERIFIED / UNRESOLVED**
   - Quarantined pending operational data pooling.
6. **`FIT501 -> FIT502`**: **QUARANTINED**
   - Excluded from dynamic causal modeling (steady-state mass balance separation).

**Plantwide CRI evaluation remains strictly disabled.**
