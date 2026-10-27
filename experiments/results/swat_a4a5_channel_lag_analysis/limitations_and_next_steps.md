# TCMIM Stage 2 Readiness, Scientific Limitations, and Next Research Steps

**Document Version**: 1.0  
**Audit Scope**: Empirical Feasibility of Stage 2 Dynamic Influence Modeling on SWaT A4/A5 July 2019 Telemetry  
**Target Repository**: TCMIM (`src/tcmim/`, `experiments/`)  

---

## 1. Executive Summary

This report evaluates whether the experimental findings from the SWaT A4/A5 July 2019 dataset support proceeding directly to Stage 2: **Temporal Cross-Machine Influence Modeling (Dynamic DAG Construction and Cascade Risk Index Estimation)**.

### Definitive Verdict:
> [!CAUTION]
> **Stage 2 CANNOT be scientifically validated on the SWaT A4/A5 July 2019 dataset alone using purely data-driven statistical methods.**
> While specific local actuation edges (such as `P301` $\to$ `DPIT301` with a 4–5s delay) are empirically demonstrable, the dataset suffers from severe structural limitations—including zero baseline excitation of key actuators, pervasive low-frequency chemical drift, extreme autocorrelation, and very short single-session duration (4 hours total). 
> Proceeding to Stage 2 requires **incorporating structural plant topology (P&ID prior knowledge)** and cannot rely on unconstrained empirical correlation or automated Granger-causality discovery.

---

## 2. Comprehensive Limitations Audit

### A. Recording Duration and Session Scope
- **Total Duration**: The dataset spans only **4.17 hours** (14,996 seconds), collected during a single afternoon session on July 20, 2019.
- **Baseline Duration**: The baseline period contains only **2.25 hours** (Windows 10–279, 8,100 seconds).
- **Statistical Implication**: In chemical and water treatment processes, diurnal cycles, filter ripening, ambient temperature swings, and chemical tank batch variations unfold over 24 to 72 hours. A 2.25-hour baseline is an instantaneous snapshot of a single operating state. It cannot characterize the normal distribution of operating regimes.

### B. Attack Interval Durations vs. Dynamic Settling Times
- **Attack Durations**:
  - Attack A1: 105 seconds (1.75 minutes)
  - Attack A2: 272 seconds (4.53 minutes)
  - Attack A3: 231 seconds (3.85 minutes)
  - Attack A4: 450 seconds (7.50 minutes)
  - Attack A5: 120 seconds (2.00 minutes)
  - Attack A6: 802 seconds (13.37 minutes)
- **Dynamic Identification Limitations**:
  - Large hydraulic processes (such as UF tank T301 with volume $> 1000$ L or reverse osmosis stabilization) have settling times ($T_{95}$) ranging from 5 to 30 minutes.
  - Short attack intervals (e.g., A5 at 120s or A1 at 105s) represent rapid truncated transients. The system is cut off before reaching a new dynamic equilibrium. Estimating transfer-function poles and zeros or multi-step impulse responses from 120 samples of an unrepeated transient produces severely underdetermined, high-variance parameter estimates.

### C. The Zero-Excitation Actuator Problem
- In industrial control, a system identification experiment requires persistent excitation (e.g., PRBS signals or repeated setpoint steps) to observe input-output relationships.
- In the SWaT baseline data:
  - Backwash pump `P601` was strictly constant at state 1 (OFF).
  - RO reject valve `MV501` was strictly constant at state 2 (CLOSE).
  - Multiple chemical dosing pumps (`P201`, `P202`, `P204`, `P206`) were never actuated.
- **Mathematical Reality**: A data-driven model fitted on baseline data receives $0.0$ variance for these channels. Any causal discovery algorithm (VAR, Granger causality, mutual information, or Transfer Entropy) will assign **zero directed edges** to these actuators. Stage 2 cannot learn that closing `MV501` causes a pressure spike in `PIT502` because that event literally never occurred in the training data.

### D. Confounding by Plantwide Macro-Disturbances
- **Global Shutdowns**: At 08:35:00 UTC, the plant was shut down, causing flow and pressure sensors across all stages (P1 through P6) to drop concurrently.
- **Analyzer Drift**: Sensor `AIT201` drifted continuously from $z = 0$ to $z > 50$, contaminating anomaly scores and cross-correlations across the entire second half of the dataset.
- Statistical correlation algorithms applied to held-out operational data interpret these shared macroeconomic trends as high-strength directed edges ($r > 0.90$), creating dense, spurious cross-stage connections that have no basis in physical fluid piping.

---

## 3. Stage 2 Feasibility and Risk Assessment

| Stage 2 Component | Core Theoretical Assumption | Empirical Reality in SWaT A4/A5 | Feasibility on This Dataset | Risk / Failure Mode |
|---|---|---|:---:|---|
| **Dynamic DAG Construction** | Actuators and sensors have non-zero baseline variance; directed edges can be inferred from time-lagged cross-correlation or Granger causality. | Key actuators (`P601`, `MV501`) have zero baseline variance. Telemetry has $\rho_1 \approx 0.999$, producing spurious boundary correlations. | **UNFEASIBLE without P&ID Prior** | Data-driven discovery will infer spurious edges from drift and miss true physical actuation paths. |
| **Edge Delay Estimation ($\tau_{ij}$)** | Peak lagged cross-correlation reflects hydraulic or chemical transport delay. | Only local pump-to-pressure pairs (`P301` $\to$ `DPIT301`) exhibit identifiable peaks. Level sensors integrate flow and peak at arbitrary search boundaries. | **PARTIALLY FEASIBLE (Local Only)** | Cross-stage lags cannot be reliably determined without hydraulic pipe geometry. |
| **Influence Weighting ($W_{ij}$)** | Coupling strength represents physical impact of node $i$ on node $j$. | Steady-state closed-loop control masks coupling in normal data ($r \approx 0.04$ on `FIT501` $\to$ `PIT501`). Correlation only appears during plant shutdowns. | **HIGH RISK of Overfitting** | Weights fitted on held-out data will memorize the shutdown sequence rather than physical transfer functions. |
| **Cascade Risk Index (CRI)** | Anomaly scores propagate along directed edges to estimate cascade failure probability. | Alarms are often driven by unrelated sensor drift (`AIT201`) rather than physical attack targets. | **INVALID VALIDATION** | A high CRI value would falsely validate against coincidental alarms rather than physical cascade failure. |

---

## 4. Required Evidence for Validating Stage 2

To make Stage 2 scientifically defensible and reproducible, the project must acquire or construct the following external engineering artifacts:

1. **Piping and Instrumentation Diagram (P&ID) Structural Topology**:
   - Explicit directed graph representing physical pipe connections, tank boundaries, and valve locations (e.g., Tank T101 $\to$ Pump P101 $\to$ Valve MV101 $\to$ Tank T201).
   - This structural topology must serve as a **hard constraint (mask)** on allowed edges in the dynamic DAG, preventing data-driven discovery from hallucinating impossible connections (such as Stage 6 backwash directly influencing Stage 2 chemical conductivity without fluid piping).
2. **Hydraulic Geometry Metadata**:
   - Pipe nominal diameters ($D$), pipe lengths ($L$), nominal flow velocities ($v = Q/A$), and tank surface areas ($A_{\text{tank}}$).
   - These parameters establish **pre-experimental bounds on physical transport delay**:
     $$\tau_{\text{transit}} = \frac{L}{v}$$
3. **Multi-Session or Active Excitation Data**:
   - Telemetry from controlled perturbation tests (step tests on valves and pumps) or multi-day normal operating logs that capture intentional pump cycling and valve transitions.

---

## 5. Single Recommended Next Research Task

### Recommended Task: **Structural P&ID Graph Constraint Formulation and Local Actuation Edge Verification**

Rather than launching an unconstrained automated Stage 2 pipeline on this 4-hour dataset, the next narrowly scoped research milestone should be:

1. **Formalize the SWaT Physical Graph Prior**:
   - Extract the physical connectivity matrix $\mathcal{G}_{\text{physical}} = (\mathcal{V}, \mathcal{E}_{\text{physical}})$ directly from the official SWaT process documentation and P&ID diagrams.
   - Enforce that a directed edge $(i, j)$ may exist in the dynamic influence model if and only if there is a documented physical hydraulic, chemical, or electrical pathway connecting device $i$ to device $j$.
2. **Implement Structural Gating for Stage 2**:
   - Restrict data-driven lag and weight estimation to the permitted physical edges in $\mathcal{E}_{\text{physical}}$.
   - Verify that validated local pairs (such as `P301` $\to$ `DPIT301` at $\tau = 4.5$ s) are preserved, while spurious non-physical edges (such as `AIT201` $\to$ `FIT501`) are mathematically masked to zero.
3. **Document the Baseline Observability Boundary**:
   - Explicitly flag nodes with zero baseline variance (`P601`, `MV501`) as *structurally unexcited*, preventing the algorithm from reporting misleading zero-risk cascade indices.
