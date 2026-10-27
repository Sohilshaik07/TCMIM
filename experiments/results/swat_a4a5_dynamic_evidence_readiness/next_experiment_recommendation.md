# Next Experiment Recommendation: Dynamic Evidence Readiness
## SWaT A4/A5 Stage 2 Physical Candidate Validation

**Document ID:** `TCMIM-SWAT-A4A5-NEXT-EXP-2026-10`  
**Date:** October 26, 2026  
**Status:** Complete & Independently Audited  
**Target:** Recommendation for the next research milestone following the read-only audit of the 22 observations surviving `G0_STRUCTURAL_MASK`.

---

## 1. Executive Summary & Recommended Decision

Following the scientific audit of the 22 candidate-edge observations accepted by Gate G0 on the SWaT A4/A5 dataset, the core finding is that **the 22 observations represent only 11 unique physical target response episodes across five component relationships**, and that **reported window-level delays (30s to 600s) are heavily distorted by 30-second window quantization and multi-burst pairing**.

### Recommended Research Decision:
**Do NOT begin plantwide Cascade Risk Index (CRI) evaluation.**

Proceed instead to **Targeted 1 Hz Dynamic Transfer Function Validation** focused exclusively on the three physically excitable, statistically identifiable relationships:
1. `P301 -> DPIT301` (UF Membrane Skid Hydraulics)
2. `MV201 -> FIT201` (Chemical Feed Motorized Valve Regulation)
3. `P101 -> FIT101` (Raw Water Intake Pump Hydraulics)

Quarantine the remaining two relationships:
- `FIT501 -> FIT502`: Cannot be evaluated dynamically due to zero baseline variation ($\sigma = 0.0015$) and multi-burst target dependence.
- `P205 -> AIT203`: Requires pooling additional operational runs due to a single observation ($N=1$) in the held-out evaluation set.

---

## 2. Categorization of the Five Relationships

| Category | Relationship | Registered Edge ID | Dynamic Readiness Assessment | Recommended Analysis Method |
|---|---|---|---|---|
| **Category A: Ready for Dynamic Analysis** | `P301 -> DPIT301` | `EDGE_01` | **Fully Ready.** High baseline excitation, repeated cyclic switching, highly consistent raw physical step responses (39.0s startup, 5.8s shutdown). | Piecewise non-linear step-response estimation / Asymmetric first-order transfer function on raw 1 Hz telemetry. |
| **Category A: Ready for Dynamic Analysis** | `MV201 -> FIT201` | `EDGE_10` | **Fully Ready.** Continuous operational cycling in baseline and evaluation, clean valve stroke dynamics (mean opening delay 10.5s, median 9.5s). | First-Order Plus Dead Time (FOPDT) or Auto-Regressive with Exogenous Inputs (ARX) modeling on raw 1 Hz telemetry. |
| **Category A: Ready for Dynamic Analysis** | `P101 -> FIT101` | `EDGE_07` | **Fully Ready.** Frequent pump cycling in baseline and evaluation. Instantaneous flow surge (<1s) upon startup and coastdown drainage (9.5s–13.3s) upon shutdown. | State-dependent impulse response / Step response modeling on raw 1 Hz telemetry. |
| **Category B: Requires Additional Engineering Evidence** | `P205 -> AIT203` | `EDGE_12` | **Conditionally Feasible.** Strong physical coupling and rock-solid 120s cross-correlation in both baseline and evaluation, but only $N=1$ accepted observation in evaluation window. | Distributed Lag Model (DLM) / Transfer Entropy with fixed 120s dead time, requiring pooled evaluation over extended operational datasets. |
| **Category C: Cannot Currently Be Evaluated Reliably** | `FIT501 -> FIT502` | `EDGE_03` | **Unidentifiable / Infeasible.** Near-zero variance in baseline ($\sigma=0.0015$). In evaluation, 10 candidate edges represent repeated combinations against only 2 target shutdown episodes. | Quarantine from dynamic modeling. Treat strictly as an algebraic static mass balance constraint ($Q_{perm} \le Q_{feed}$) rather than a dynamic causal edge. |

---

## 3. Mandatory Methodological Refinements for Next Milestone

### 3.1 Transition from 30-Second Windows to 1 Hz Continuous Telemetry
The Stage 2 windowing pipeline (30-second window, 30-second step) was designed for coarse macro-level anomaly detection. However, for dynamic validation:
- A motorized valve opening stroke takes **9.5s–10.5s**. Quantizing it to a 30s window introduces up to 300% error.
- Pump startup hydraulic surge is **sub-second (<1s)**. Requiring $\Delta t > 0$ at the window level caused 10 valid simultaneous observations to be rejected by Gate G2 (`\Delta t = 0.00\text{ s} \le 0`).
- UF membrane pressurization takes **39s**, but window-level pairing reported delays up to **570s** because late target windows were paired with early source bursts.

**Requirement:** The next experiment must extract raw, unwindowed 1 Hz telemetry sub-sequences ($\pm 120\text{ s}$ around candidate event onsets) to estimate true continuous-time transfer functions.

### 3.2 Component-Specific Delay Calibration
Replace the unconstrained heuristic window $[0, 600\text{ s}]$ with tight, component-specific physical delay bounds derived from raw step responses:
- `MV201 -> FIT201`: $[5.0\text{ s}, 25.0\text{ s}]$
- `P101 -> FIT101`: $[0.0\text{ s}, 15.0\text{ s}]$
- `P301 -> DPIT301`: $[5.0\text{ s}, 50.0\text{ s}]$
- `P205 -> AIT203`: $[90.0\text{ s}, 150.0\text{ s}]$

---

## 4. Scientific Safeguards & Epistemic Boundaries

1. **No Plantwide CRI Prematurely:**
   - Computing a plantwide Cascade Risk Index (CRI) while only 3 edges have verified dynamic responses and 3,814 edges remain unmodeled unknowns would produce an unvalidated, misleading risk number.
2. **Repeated Observations Are NOT Independent Samples:**
   - Statistical estimators (degrees of freedom, p-values, Fisher information) must account for the fact that `FIT501 -> FIT502` has only 2 unique target episodes, not 10 independent trials.
3. **Correlation $\ne$ Causation:**
   - Cross-correlation lags (e.g. 120s on `P205 -> AIT203` or -4s on `FIT501 -> FIT502`) reflect observed association during plant operations, not unconfounded interventionist causation.

---

## 5. Proposed Next Milestone Scope

**Proposed Milestone:**
`SWaT A4/A5 Stage 2 Step-Response and Transfer Function Estimation on Raw 1 Hz Telemetry for Category A Edges (EDGE_01, EDGE_07, EDGE_10).`

**Deliverables:**
1. Extraction of 1 Hz raw event transition sub-sequences.
2. Fitting of continuous-time transfer functions (gain $K$, time constant $\tau$, dead time $\theta$).
3. Goodness-of-fit validation ($R^2$, normalized root-mean-square error).
4. Rigorous empirical calibration of delay bounds $[d_{min}, d_{max}]$.
