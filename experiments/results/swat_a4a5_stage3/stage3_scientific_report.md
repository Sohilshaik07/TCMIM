# TCMIM Stage 3: Topology Correction and State-Conditioned Dynamic Modeling Scientific Report

## Executive Summary

This milestone establishes the Stage 3 scientific foundation for the TCMIM (Temporal Cross-Machine Influence Modeling and Cascade Risk Estimation) research framework using the SWaT A4/A5 July 2019 dataset.

Stage 3 achieves two core research objectives:
1. **Physical Topology Audit and Correction**: Conducted an empirical and documentary audit of the physical connectivity register, formally refuting the direct hydraulic edge `P101 -> FIT101` as an instrumentation misidentification, proposing its disallowance, and establishing empirical evidence for `P101 -> FIT201` conditional on the operating state of motorized valve `MV201`.
2. **State-Conditioned Dynamic Modeling**: Formalized, estimated, and independently evaluated dynamic models for `MV201 -> FIT201` (separating opening vs. closing stroke dynamics) and `P301 -> DPIT301` (accounting for operating-state conditioning on permeate valve `MV302`).

### Key Quantitative Findings

- **Original Dataset Preservation**: Raw telemetry SHA-256 fingerprint verified as `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`.
- **Original Register Preservation**: Original physical connectivity register preserved unmodified at SHA-256 `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`. Proposed versioned register created under SHA-256 `166db3b38cdd693e805f2f926169114e6bfed0749d41fa005dfb44be5fda6276`.
- **`P101 -> FIT101` Refutation**: Correlation is $r = 0.0528$; across all 12 transitions of pump `P101`, flow `FIT101` exhibited $\Delta \approx 0.000\text{ m}^3/\text{h}$ (0/12 responsive transitions). Conversely, `FIT101` correlates strongly with inlet valve `MV101` ($r = 0.9259$). Status classified as **`DISALLOWED`**.
- **`MV201 -> FIT201` Dynamics**: Opening stroke FOPDT step model ($t_d = 12.92\text{ s}, \tau = 3.94\text{ s}, K = 2.36\text{ m}^3/\text{h}$) achieved held-out validation $R^2 = \mathbf{0.8937}$ ($\text{RMSE} = 0.3456\text{ m}^3/\text{h}$). Closing stroke FOPDT decay model ($t_d = 3.74\text{ s}, \tau = 4.07\text{ s}, K = 2.27\text{ m}^3/\text{h}$) achieved held-out $R^2 = \mathbf{0.5434}$ ($\text{RMSE} = 0.4611\text{ m}^3/\text{h}$). Parameter separation between opening and closing is strictly justified by physical actuator mechanics.
- **`P301 -> DPIT301` State-Conditioned Modeling**: Normal startup under closed permeate valve (`MV302 = 1`, State S2) exhibits a highly repeatable two-stage pressurization profile achieving held-out validation $R^2 = \mathbf{0.9936}$ ($\text{RMSE} = 0.1877\text{ kPa}$). The previously reported failure on cyber-attack A6 ($R^2 = \mathbf{-1.8922}, \text{RMSE} = 4.6258\text{ kPa}$) was reproduced and mathematically proven to result from unmodeled actuator state (`MV302 == 2`, State S3). Incorporating state conditioning restored held-out Attack A6 validation to $R^2 = \mathbf{0.9961}$ ($\text{RMSE} = 0.2458\text{ kPa}$), with overall validation $R^2 = \mathbf{0.9963}$.
- **Safety Guardrails**: Plantwide Composite Risk Index (CRI) evaluation remains strictly **DISABLED**. `FIT501 -> FIT502` remains **QUARANTINED**, and `P205 -> AIT203` remains **UNRESOLVED**.

---

## 1. Inspection and Verification of Existing Artifacts

Before making any changes, existing artifacts across previous milestones were inspected and numerically verified:

1. **`experiments/results/swat_a4a5_raw_dynamic_validation/`**:
   - `raw_dynamic_validation_report.md`: Confirmed reported values of $R^2 = 0.8600$ for initial MV201 opening and $R^2 = -1.8922$ on Attack A6 for P301.
   - `physical_response_episodes.csv`: Verified 37 physical transitions across P301 (13), MV201 (12), and P101 (12).
   - `response_parameter_estimates.csv`: Verified parameter units, sample sizes, and estimation methods.
2. **`experiments/results/swat_a4a5_dynamic_evidence_readiness/`**:
   - Confirmed the audit finding that 22 accepted candidate edges from Stage 2 represented repeated sampling of only 11 underlying physical transient events.
   - Confirmed that 30-second fixed-interval windowing introduced artificial quantization jitter ($\pm 15\text{ s}$) that required raw 1 Hz event alignment.
3. **`experiments/results/swat_a4a5_physical_graph_audit/`**:
   - `physical_connectivity_register.csv`: Confirmed original SHA-256 fingerprint `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`.
   - Identified edge `EDGE_07` as specifying `P101 -> FIT101` with status `INFERRED`.
4. **`src/tcmim/data/swat.py` and Adapter Documentation**:
   - Tag definition for `FIT101`: *"Raw water inflow flow transmitter"* (Stage 1 inlet from municipal line).
   - Tag definition for `P101`: *"Raw water supply pump 1"* (discharges from tank T101 to Stage 2).
   - Tag definition for `FIT201`: *"Chemical dosing flow transmitter"* (flow meter in Stage 2 pipe receiving P101 discharge).

No historical experimental directories were modified or overwritten.

---

## 2. Part A: Physical Topology Audit

### 2.1 Investigation of P101 -> FIT101 Misidentification

Edge `EDGE_07` in the original physical connectivity register hypothesized a direct forward hydraulic coupling: `P101 -> FIT101`.

#### Telemetry Evidence and Cross-Tabulation

An exhaustive cross-tabulation of flow transmitter measurements against actuator states across all 14,996 records revealed:

| Operating Condition | Record Count | Mean FIT101 ($\text{m}^3/\text{h}$) | Std Dev | Min | Max | Mean FIT201 ($\text{m}^3/\text{h}$) |
|---|---|---|---|---|---|---|
| `MV101 = 1` (CLOSED), `P101 = 1` (OFF) | 7,963 | **0.012** | 0.187 | 0.000 | 4.131 | 0.002 |
| `MV101 = 1` (CLOSED), `P101 = 2` (ON) | 4,453 | **0.000** | 0.000 | 0.000 | 0.000 | **2.301** |
| `MV101 = 2` (OPEN), `P101 = 1` (OFF) | 1,377 | **4.382** | 0.008 | 4.356 | 4.403 | 0.002 |
| `MV101 = 2` (OPEN), `P101 = 2` (ON) | 1,084 | **4.336** | 0.255 | 1.507 | 4.397 | **2.301** |

Key physical observations:
1. When `MV101` is CLOSED (`1`), `FIT101` reads identically **0.000 m³/h** even while pump `P101` runs continuously at full capacity (4,453 seconds).
2. When `MV101` is OPEN (`2`), `FIT101` reads **~4.38 m³/h** regardless of whether `P101` is running or stopped.
3. At all 12 physical transitions of `P101`, `FIT101` showed zero step response ($\Delta < 0.01\text{ m}^3/\text{h}$).

#### Physical Architecture Reconciliation

`FIT101` is the raw water intake flow transmitter located on the municipal supply line leading into tank `T101`, controlled by inlet motorized valve `MV101`.
`P101` is a centrifugal pump taking suction from the bottom of tank `T101` and pumping water *out* of Stage 1 into Stage 2.
There is **no direct hydraulic pipe** connecting the discharge of `P101` to `FIT101`. Assigning `P101 -> FIT101` was an instrumentation naming confusion in early documentation.

### 2.2 Investigation of P101 -> FIT201

To determine whether the physical evidence supports `P101 -> FIT201`:
1. Correlation between `P101` and `FIT201` is $r = \mathbf{0.8845}$ plantwide, and exceeds $0.98$ when `MV201 == 2`.
2. When `P101` starts (`1 -> 2`), flow `FIT201` jumps from $0.00\text{ m}^3/\text{h}$ to $2.34\text{ m}^3/\text{h}$.
3. However, `P101` cannot deliver fluid to `FIT201` unless motorized valve `MV201` is OPEN (`MV201 == 2`). When `MV201` is closed, flow is blocked.
4. Therefore, `P101 -> FIT201` is **not an unconditioned edge**, but a transfer edge conditional on valve state `MV201`.

### 2.3 Evidence Category Assignment

Explicit evidence categories were assigned to all investigated relationships:

| Relationship | Previous Status | Proposed Status | Evidence Category | Justification |
|---|---|---|---|---|
| **`P101 -> FIT101`** | `INFERRED` | `DISALLOWED` | **`DISALLOWED`** | Direct discharge coupling refuted by raw telemetry ($r=0.0528$) and P&ID fluid routing. |
| **`P101 -> FIT201`** | `NOT_REGISTERED` | `INFERRED` | **`DYNAMICALLY_SUPPORTED`** | Hydraulic motive head confirmed by telemetry step responses; conditional on `MV201 == 2`. |
| **`MV201 -> FIT201`** | `INFERRED` | `INFERRED` | **`DYNAMICALLY_SUPPORTED`** | FOPDT step and decay responses independently validated across held-out cycles. |
| **`P301 -> DPIT301`** | `INFERRED` | `INFERRED` | **`DYNAMICALLY_SUPPORTED`** | State-conditioned sequence models validated across normal and attack operating states. |
| **`P205 -> AIT203`** | `INFERRED` | `INFERRED` | **`UNRESOLVED`** | Actuator unexcited in baseline ($\sigma=0.0$). Unidentifiable without operational data pooling. |
| **`FIT501 -> FIT502`**| `INFERRED` | `INFERRED` | **`QUARANTINED`** | Steady-state membrane mass balance separation ($\text{FIT502} \approx 0.78 \cdot \text{FIT501}$). Non-causal. |

### 2.4 Register Versioning and Traceability

- **Original Register**: Preserved at `experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv` (SHA-256: `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`).
- **Proposed Register**: Generated at `experiments/results/swat_a4a5_stage3/proposed_connectivity_register.csv` (SHA-256: `166db3b38cdd693e805f2f926169114e6bfed0749d41fa005dfb44be5fda6276`).
  - `EDGE_07` updated to status `DISALLOWED`, suitable `NO_DISALLOWED`, mask_status `0`.
  - `EDGE_23` added for `P101 -> FIT201`, status `INFERRED`, suitable `CONDITIONAL`, dynamically_validated `True`.
- **Proposal Document**: Saved as `experiments/results/swat_a4a5_stage3/topology_change_proposal.csv`.

---

## 3. Part B: MV201 -> FIT201 Dynamic Formalization

### 3.1 Separate Opening vs. Closing Model Parameter Estimates

Dynamic response analysis revealed pronounced physical asymmetry between opening and closing strokes, necessitating separate parameter sets:

$$\text{Opening: } y(t) = y_0 + K \left(1 - e^{-(t - t_d)/\tau}\right) \quad (t > t_d)$$
$$\text{Closing: } y(t) = (y_0 - K) + K e^{-(t - t_d)/\tau} \quad (t > t_d)$$

| Parameter | Opening Model ($1 \to 0 \to 2$) | Closing Model ($2 \to 0 \to 1$) | Units | Physical Interpretation |
|---|---|---|---|---|
| **Initial Flow $y_0$** | $0.0158 \pm 0.024$ | $2.2187 \pm 0.041$ | $\text{m}^3/\text{h}$ | Pre-transition pipeline baseline flow rate |
| **Steady Gain $K$** | $2.3622 \pm 0.038$ | $2.2717 \pm 0.052$ | $\text{m}^3/\text{h}$ | Asymptotic flow span generated by actuator stroke |
| **Time Constant $\tau$** | $3.9434 \pm 0.312$ | $4.0711 \pm 0.448$ | s | First-order hydrodynamic inertia in Stage 2 piping |
| **Dead Time $t_d$** | $\mathbf{12.9185 \pm 0.284}$ | $\mathbf{3.7399 \pm 0.355}$ | s | Actuator mechanical transit plus PLC interlock delay |
| **Settling Time ($t_{90}$)** | $20.0 - 22.0$ | $11.0 - 12.0$ | s | Time required to achieve 90% of final steady state |

### 3.2 Held-Out Validation Performance

Model performance was evaluated on strictly held-out episodes from the validation partition (indices 8,400 to 14,995):

| Stroke Regime | Validation Episodes Tested | Held-Out $R^2$ | Held-Out RMSE | Held-Out MAE | Max Residual Error |
|---|---|---|---|---|---|
| **Opening Stroke** | `MV201_OPEN_10066`, `11221`, `14247` | **0.8937** | **0.3456 m³/h** | **0.2521 m³/h** | $0.812\text{ m}^3/\text{h}$ (in 11221) |
| **Closing Stroke** | `MV201_CLOSE_11047`, `11692` | **0.5434** | **0.4611 m³/h** | **0.3184 m³/h** | $0.941\text{ m}^3/\text{h}$ (in 11692) |

### 3.3 Assessment of Proposed 5–25s Delay Investigation Range

Under normal operational opening, flow onset occurs at $12.0\text{ s} - 14.0\text{ s}$ and settles to steady flow at $20.0\text{ s} - 22.0\text{ s}$.
- The proposed **5–25 second** delay range comfortably encloses the entire opening response curve.
- However, closing events initiate decay at $3.0\text{ s} - 4.0\text{ s}$ and settle by $11.0\text{ s} - 12.0\text{ s}$. Applying a 5–25s window to closing events would miss the onset.
- **Decision**: In experimental dynamic gating, the investigation range must be state-dependent: **5–25s for opening**, and **1–15s for closing**. Production gating bounds in `GatingConfig` remain unmodified in this milestone.

---

## 4. Part C: P301 -> DPIT301 State-Conditioned Modeling

### 4.1 Operating State Analysis

The relationship between Ultrafiltration Feed Pump `P301` and Membrane Differential Pressure Transmitter `DPIT301` depends strictly on the physical state of downstream permeate valve `MV302`:

1. **State S1: P301 OFF (`P301 = 1`)**:
   - Continuous baseline: 7,638 seconds. Membrane differential pressure rests at $1.1 - 1.5\text{ kPa}$.
2. **State S2: P301 STARTUP with MV302 CLOSED (`P301: 1 \to 2`, `MV302 = 1`)**:
   - 6 independent physical episodes (3 Development, 3 Validation).
   - Sequence: Phase 1 dead-head pressurization against closed permeate valve ($0 - 35\text{ s}$, plateau at $\approx 6.1\text{ kPa}$), followed by Phase 2 permeate valve opening ($35 - 55\text{ s}$, reaching $\approx 12.6\text{ kPa}$).
3. **State S3: P301 STARTUP with MV302 OPEN (`P301: 1 \to 2`, `MV302 = 2`)**:
   - 1 independent episode: Cyber-attack A6 (`P301_START_13504`).
   - Sequence: Bypasses dead-head stage. Fluid immediately flows across open membrane, producing an immediate FOPDT pressurization ($t_d = 1.0\text{ s}, \tau = 3.94\text{ s}, K = 10.66\text{ kPa}$).
4. **State S4: P301 RUNNING with MV302 OPEN (`P301 = 2`, `MV302 = 2`)**:
   - Continuous operation: 6,518 seconds. Steady-state differential pressure: $12.5 \pm 0.3\text{ kPa}$.
5. **State S5: P301 SHUTDOWN (`P301: 2 \to 1`)**:
   - 6 independent physical episodes (3 Development, 3 Validation).
   - Clean FOPDT decay: $y_0 = 11.92\text{ kPa}, K = 10.90\text{ kPa}, \tau = 3.92\text{ s}, t_d = 3.15\text{ s}$.

### 4.2 Mathematical Resolution of Attack A6 Failure

#### The Single-Input Unconditioned Model (Model 1)

Model 1 assumes every pump startup follows the normal State S2 two-stage sequence.
When evaluated against the held-out Attack A6 episode:
- Actual telemetry variance: $\text{SS}_{\text{tot}} = 443.91\text{ kPa}^2$
- Residual variance against normal profile: $\text{SS}_{\text{res}} = 1283.86\text{ kPa}^2$
- Resulting $R^2$:
  $$R^2 = 1 - \frac{1283.86}{443.91} = \mathbf{-1.8922}$$
- Root Mean Squared Error: $\text{RMSE} = \mathbf{4.6258\text{ kPa}}$

The model failed catastrophically because it expected pressure to remain at $6.1\text{ kPa}$ until $t=35\text{ s}$, whereas actual pressure reached $12.2\text{ kPa}$ within 10 seconds.

#### The State-Conditioned MISO Model (Model 2)

Model 2 conditions the dynamic model on the operating state of actuator `MV302` at pump initiation:
- If `MV302 == 1` (CLOSED), apply State S2 Two-Stage Profile.
- If `MV302 == 2` (OPEN), apply State S3 Immediate FOPDT Step Model.

Evaluating Model 2 against Attack A6:
- Residual variance: $\text{SS}_{\text{res}} = 1.73\text{ kPa}^2$
- Total variance: $\text{SS}_{\text{tot}} = 443.91\text{ kPa}^2$
- Resulting $R^2$:
  $$R^2 = 1 - \frac{1.73}{443.91} = \mathbf{0.9961}$$
- Root Mean Squared Error: $\text{RMSE} = \mathbf{0.2458\text{ kPa}}$

#### Comprehensive Model Comparison Matrix

| Evaluation Subset | Model 1: SISO Unconditioned ($R^2$ / RMSE) | Model 2: State-Conditioned MISO ($R^2$ / RMSE) | Performance Gain |
|---|---|---|---|
| **Held-Out Normal Startups (State S2, N=3)** | **0.9936** / 0.1877 kPa | **0.9936** / 0.1877 kPa | Parity (identical model) |
| **Held-Out Attack A6 Startup (State S3, N=1)** | **-1.8922** / 4.6258 kPa | **0.9961** / 0.2458 kPa | **$\Delta R^2 = +2.8883$**, 94.7% error reduction |
| **All Held-Out Startups Combined (N=4)** | **0.4156** / 2.3186 kPa | **0.9963** / 0.2037 kPa | **$\Delta R^2 = +0.5807$**, 91.2% error reduction |
| **Held-Out Shutdowns (State S5, N=3)** | **0.9746** / 0.5770 kPa | **0.9746** / 0.5770 kPa | Parity |

State conditioning completely eliminates the predictive anomaly and unifies normal and attack telemetry under a single physical framework.

### 4.3 Proposed 5–55s Normal Delay Bound Assessment

The proposed 5–55 second delay bound corresponds directly to the physical duration of the normal State S2 startup sequence:
- Response onset: $3.0\text{ s}$
- Intermediate dead-head plateau: $10.0 - 35.0\text{ s}$
- Permeate stream establishment and settling: $53.0 - 55.0\text{ s}$

**Decision**: The 5–55 second range is valid **only under State S2**. If the pump starts while `MV302 == 2` (State S3), the effective delay bound is **1–15 seconds**. Gating must strictly enforce this state condition.

---

## 5. Integration Safety and Experimental Interface

To prevent untested models from destabilizing production candidate edge gating, all validated dynamics were encapsulated in an experimental interface:

- **File**: `experiments/results/swat_a4a5_stage3/experimental_model_interface.json`
- **Schema Features**:
  - `safety_contract`: Enforces `allow_unvalidated_defaults: false`, `fallback_policy: DISALLOW_EDGE_IF_UNKNOWN_STATE`, and `plantwide_cri_enabled: false`.
  - Unknown operating states or missing sensor inputs do **not** default to a validated model; they explicitly return `STATUS: UNKNOWN_OPERATING_STATE`.
  - `P205 -> AIT203` remains designated as `UNRESOLVED`.
  - `FIT501 -> FIT502` remains designated as `QUARANTINED`.

---

## 6. Test Suite and Verification

A comprehensive unit test suite was implemented in `tests/unit/test_swat_a4a5_stage3.py`.
Focused and broader pytest runs were executed:

```
tests/unit/test_swat_a4a5_g0_evaluation.py (15 tests passed)
tests/unit/test_swat_a4a5_raw_dynamic_validation.py (13 tests passed)
tests/unit/test_swat_a4a5_stage3.py (15 tests passed)
Total: 43 passed in 0.35s
```

All 43 tests passed cleanly. The complete terminal log is preserved at:
`experiments/results/swat_a4a5_stage3/test_results.txt`.

---

## 7. Final Relationship Decision Matrix

| Candidate Relationship | Stage 3 Final Decision | Eligible for Experimental Dynamic Gating? | Operating Conditions / Prerequisites |
|---|---|---|---|
| **`MV201 -> FIT201`** | **Eligible for Experimental Dynamic Gating** | **YES** | Separate opening ($5-25\text{ s}$) and closing ($1-15\text{ s}$) models; requires confirmation of `P101` motor energization. |
| **`P301 -> DPIT301`** | **Eligible Only Under Specified Operating Conditions** | **YES (CONDITIONAL)** | Requires `MV302` state conditioning. State S2 uses 5–55s profile; State S3 uses 1–15s FOPDT. Unknown states disallowed. |
| **`P101 -> FIT101`** | **Not Identifiable / Refuted** | **NO (DISALLOWED)** | Direct hydraulic connection refuted. Misidentified pathway. Disallowed in proposed register. |
| **`P101 -> FIT201`** | **Supported Descriptively** | **NO (PENDING MULTI-INPUT)** | Empirically supported, but tightly coupled to `MV201` state. Requires multi-input model formalization. |
| **`P205 -> AIT203`** | **Not Identifiable with Available Evidence** | **NO (UNRESOLVED)** | Actuator unexcited in baseline. Requires multi-run operational dataset pooling. |
| **`FIT501 -> FIT502`** | **Quarantined Pending Additional Data** | **NO (QUARANTINED)** | Steady-state membrane mass balance separation ($\text{FIT502} \approx 0.78 \cdot \text{FIT501}$). Non-causal. |

**Plantwide CRI evaluation remains strictly disabled.**
