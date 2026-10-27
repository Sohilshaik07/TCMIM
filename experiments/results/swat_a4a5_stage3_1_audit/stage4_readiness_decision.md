# TCMIM Stage 3.1: Stage 4 Readiness Decision and Relationship Categorization

## Executive Summary

This document establishes the official readiness classification for candidate relationships investigated in Stage 3, answers the five mandatory audit questions, and specifies the prerequisite requirements for Stage 4 experimental dynamic gating.

---

## 1. Official Relationship Readiness Matrix

| Relationship | Audit Readiness Classification | Permitted Integration Scope | Prerequisites Before Production Dynamic Gating |
|---|---|---|---|
| **`MV201 -> FIT201`** | **CONDITIONALLY READY** | Experimental Dynamic Gating (Restricted) | Must enforce separate opening ($5-25\text{ s}$) and closing ($1-15\text{ s}$) bounds. Gating must check `P101` motor energization state to prevent false anomalies during delayed pump start. |
| **`P301 -> DPIT301`** | **CONDITIONALLY READY** | Experimental Dynamic Gating (Restricted to State S2) | State S2 (normal startup with `MV302 == 1`) is validated for experimental gating. State S3 (open permeate startup) is **DESCRIPTIVE ONLY** and must NOT be used for dynamic rejection until multi-run dataset pooling provides out-of-sample episodes. |
| **`P101 -> FIT101`** | **REFUTED / DISALLOWED** | Permitted as Disallowance Constraint in Register | Direct hydraulic edge is refuted. Update register to DISALLOWED. Prevents candidate edges from surviving G0. |
| **`P101 -> FIT201`** | **DESCRIPTIVE EVIDENCE ONLY** | Prohibited from Production Structural Register | Empirically supported, but current structural mask lacks state conditionality. Adding as `ALLOWED` creates an unconditional bypass when `MV201` is closed. Retain as `UNKNOWN` / `CONDITIONAL` in register. |
| **`P205 -> AIT203`** | **NOT VERIFIED / UNRESOLVED** | Quarantined from Gating | Zero baseline excitation ($\sigma = 0.0$). Unidentifiable in single-run baseline. Requires operational pooling. |
| **`FIT501 -> FIT502`** | **QUARANTINED** | Quarantined from Dynamic Causal Modeling | Steady-state membrane separation ($\text{FIT502} \approx 0.78 \cdot \text{FIT501}$). Non-causal mass balance. Excluded from dynamic delay gating. |

---

## 2. Answers to the Five Mandatory Audit Questions

### Question 1: Which Stage 3 findings are independently reproducible?
1. **`P101 -> FIT101` Disallowance**: Independently confirmed that $\text{corr}(\text{P101}, \text{FIT101}) = 0.0528$, 0 of 12 transitions respond, and `FIT101` is governed strictly by municipal inlet valve `MV101` ($r = 0.9259$).
2. **`MV201 -> FIT201` Opening FOPDT**: Independently reproduced held-out validation $R^2 = 0.8937$ and $\text{RMSE} = 0.3456\text{ m}^3/\text{h}$ across validation episodes 10066, 11221, and 14247.
3. **`MV201 -> FIT201` Closing FOPDT**: Independently reproduced pooled held-out validation $R^2 = 0.5434$ and $\text{RMSE} = 0.4611\text{ m}^3/\text{h}$ across validation episodes 11047 and 11692.
4. **`P301 -> DPIT301` Normal Startup Two-Stage Model**: Independently reproduced held-out validation $R^2 = 0.9936$ and $\text{RMSE} = 0.1877\text{ kPa}$ across validation episodes 9419, 12124, and 14024.
5. **`P301 -> DPIT301` Attack A6 Single-Input Failure**: Independently reproduced the exact failure metric $R^2 = -1.8922$ ($\text{RMSE} = 4.6258\text{ kPa}$) with residual sum of squares $\text{SS}_{\text{res}} = 1283.86$ exceeding total sum of squares $\text{SS}_{\text{tot}} = 443.91$.
6. **Actuator Stroke Asymmetry**: Independently verified that opening dead time ($12.92\text{ s}$) and closing dead time ($3.74\text{ s}$) reflect distinct mechanical and control-logic phases.
7. **Cadence and Dataset Hash**: Verified 1.0 Hz nominal cadence, 6 timing gaps, and dataset SHA-256 `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`.

---

### Question 2: Which reported validation results need qualification?
1. **Attack A6 Model 2 "$R^2 = 0.9961$ Validation"**:
   - **Qualification**: This is **NOT an independent held-out validation**. There is only one episode of State S3 in the entire dataset (row 13,504). The FOPDT parameters were fitted directly on this episode and evaluated on the same episode. It is an **in-sample descriptive fit**.
2. **Overall Startup Validation "$R^2 = 0.9963$"**:
   - **Qualification**: This pooled metric is contaminated by combining 180 out-of-sample normal observations with 60 in-sample fitted Attack A6 observations.
3. **MV201 Closing Model "$R^2 = 0.5434$ Fit"**:
   - **Qualification**: The pooled metric masks a severe individual episode failure. In episode 11,692, pump P101 shut down 7 seconds before valve closure initiated, causing flow to drop prematurely and producing an individual episode $R^2 = \mathbf{-1.7373}$.
4. **MV201 Opening Range "$5–25\text{ s}$"**:
   - **Qualification**: While valid for opening stroke, it is invalid for closing stroke, which initiates decay in $3–4\text{ s}$ and settles in $11–12\text{ s}$.

---

### Question 3: Is the proposed connectivity register safe to integrate?
**NO, NOT IN ITS CURRENT FORM.**
- Updating `EDGE_07` (`P101 -> FIT101`) to `DISALLOWED` is safe and beneficial.
- However, registering `EDGE_23` (`P101 -> FIT201`) with status `INFERRED` causes `PhysicalStructuralMask` to treat it as **`StructuralStatus.ALLOWED`** (`'1'`) unconditionally.
- Because `gate_structural_mask()` does not accept telemetry context or check valve `MV201` state, `P101 -> FIT201` would be universally allowed across all plant states, including when `MV201` is closed.
- **Remediation**: Keep `EDGE_23` designated as `CONDITIONAL` / `UNKNOWN` in the active structural register until a state-conditioned gate interface is deployed.

---

### Question 4: Can experimental dynamic gating proceed without changing production behavior?
**YES, PROVIDED IT RUNS IN SHADOW / EXPERIMENTAL MODE.**
- The versioned experimental model interface (`experimental_model_interface.json`) enforces `production_gating_connected: false`.
- Experimental dynamic gating can be evaluated in "shadow mode" (logging what edges would be gated without altering candidate edge propagation outputs).
- Production bounds in `GatingConfig` must remain untouched until multi-run pooling and state-conditioned gating are implemented.

---

### Question 5: What exact requirements must be satisfied before a restricted CRI evaluation?
Before plantwide Composite Risk Index (CRI) evaluation can be enabled, even in a restricted prototype capacity, the following five criteria must be strictly satisfied:

1. **State-Conditioned Structural Gate**: Implement and test a telemetry-aware Gate G0 that evaluates actuator conditions (e.g. `MV201 == 2`) before allowing transfer edges.
2. **Multi-Run Dataset Pooling**: Ingest additional SWaT datasets (e.g. 2015 continuous training run) to obtain independent out-of-sample episodes for State S3 (`MV302 == 2` at startup) and `P205 -> AIT203`.
3. **Multi-Input Pump/Valve Model**: Replace SISO valve models with a bilinear or multi-input model $y(t) = f(\text{P101}, \text{MV201})$ that accounts for actuator lead/lag.
4. **Formal Quarantining of Static Edges**: Permanently quarantine `FIT501 -> FIT502` and `AIT201 -> FIT501` from dynamic risk propagation calculations.
5. **Independent Subgraph Isolation**: Validate that CRI calculations are evaluated only on candidate subgraphs where all edges have validated physical bounds, with plantwide aggregation disabled.
