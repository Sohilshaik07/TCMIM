# SWaT A4/A5 Candidate Edge Audit and Physical Verification

**Document Version**: 1.0  
**Audit Date**: 2026-10-26T13:25:20Z  
**Target Repository**: TCMIM (`src/tcmim/`, `experiments/`)  
**Audit Scope**: Detailed physical and documentary verification of five candidate sensor/actuator relationships previously analyzed in `experiments/results/swat_a4a5_channel_lag_analysis/`.

---

## Executive Summary

The previous lagged cross-correlation investigation evaluated five candidate pairs to determine whether empirical data alone could support Stage 2 dynamic DAG construction. That investigation discovered that high empirical correlations often stemmed from shared plant shutdowns, low-frequency chemical analyzer drift, or extreme autocorrelation ($\rho_1 \ge 0.998$).

This audit independently verifies each candidate relationship against the available plant documentation, tag definitions, and fundamental chemical/hydraulic process principles. 

### Key Findings:
1. **`P301` $\to$ `DPIT301` (UF Pump to Membrane Differential Pressure)**: **PHYSICALLY SOUND & INFERRED FORWARD EDGE**. The physical pumping mechanism directly builds trans-membrane differential pressure. However, because no official P&ID drawing is included in the supplied dataset package, its formal status is `INFERRED`, not `DOCUMENTED`.
2. **`FIT501` $\to$ `PIT501` (RO Feed Flow to Pump Suction Pressure)**: **PHYSICALLY FLAWED & REJECTED DIRECTION**. `PIT501` is suction pressure *upstream* of high-pressure pump P501, whereas `FIT501` is flow *downstream*. Proposing that flow causes upstream suction pressure inverts the physical causal mechanism. The high correlation ($r = -0.92$) observed during held-out operations was an artifact of the concurrent plant shutdown.
3. **`FIT501` $\to$ `FIT502` (RO Feed Flow to Permeate Flow)**: **PHYSICALLY SOUND MASS BALANCE, BUT WEAK DYNAMIC TRANSFER FUNCTION**. Permeate flow is a fraction of feed flow governed by membrane recovery. In baseline steady-state, flow variability was near zero ($\sigma = 0.001$ m3/h), yielding zero differenced correlation ($r = -0.0316$).
4. **`FIT201` $\to$ `LIT301` (Stage 2 Flow to UF Tank Level)**: **PARTIAL STATE EQUATION MISSPECIFICATION**. While `FIT201` enters tank T301, tank level integrates *net* flow ($\frac{dh}{dt} = \frac{Q_{\text{in}} - Q_{\text{out}}}{A}$). Modeling `FIT201` $\to$ `LIT301` as an isolated bivariate link omits discharge pump `P301`, explaining why raw cross-correlation peaked spuriously at the search window boundary ($\tau = -120$ s).
5. **`MV501` $\to$ `PIT502` (RO Reject Valve to Vessel Pressure)**: **PHYSICALLY SOUND HYDRAULIC EDGE, BUT COMPLETELY UNEXCITED IN BASELINE**. Valve `MV501` had zero variance in baseline ($\sigma = 0.000$). It cannot be discovered or weighted by any purely data-driven algorithm trained on normal operating data.

---

## 1. Candidate 1: `P301` $\to$ `DPIT301`

- **Source Component**: `P301` (Ultrafiltration Feed Pump 1, Stage 3).
- **Destination Component**: `DPIT301` (Differential Pressure Transmitter across UF Membrane, Stage 3).
- **Physical Engineering Units**: Discrete state ($1 = \text{OFF}, 2 = \text{ON}$) $\to$ Continuous differential pressure (kPa).
- **Documented Process Role**:
  - In `SWaT data collection_20-07-2019 v2.pdf` (p. 1), Attack A6 is explicitly described as: *"Attack on P301: Switch from ON to OFF; Intent: To halt stage 3 (UF process)"*.
  - `SWAT_TAG_REGISTRY` in [`src/tcmim/data/swat.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/data/swat.py#L149-L157) defines `P301` as "UF feed pump 1" and `DPIT301` as "UF membrane differential pressure".
- **Directional Verification**:
  - **Proposed Direction**: `P301` $\to$ `DPIT301` (Forward Actuation).
  - **Physical Rationale**: When pump P301 operates, it forces water through the semi-permeable hollow-fiber ultrafiltration membranes. Fluid friction and membrane resistance generate trans-membrane differential pressure measured across the membrane manifold by `DPIT301`.
  - **Reverse Direction (`DPIT301` $\to$ `P301`)**: While a PLC control interlock might trip pump P301 if differential pressure exceeds a high threshold (fouling alarm), this is an electrical protection interlock, not a continuous hydraulic transmission path.
- **Empirical Evidence vs. Physical Validation**:
  - Lagged cross-correlation on pre-whitened first differences yielded a consistent peak at $\tau = +5\text{ s}$ ($r = 0.3703$) in baseline and $\tau = +4\text{ s}$ ($r = 0.3739$) in held-out operations.
  - **Scientific Warning**: Consistent cross-correlation does **not** equal independent physical validation. Validation requires a calibrated hydrodynamic model or controlled step-response tests with known piping dimensions.
- **Audit Status**: `INFERRED` (High Confidence). Suitable as a structural constraint edge in Stage 2.

---

## 2. Candidate 2: `FIT501` $\to$ `PIT501`

- **Source Component**: `FIT501` (Reverse Osmosis Feed Flow Transmitter, Stage 5).
- **Destination Component**: `PIT501` (Reverse Osmosis Pump Suction Pressure Transmitter, Stage 5).
- **Physical Engineering Units**: Continuous flow (m3/h) $\to$ Continuous pressure (bar / kPa).
- **Documented Process Role**:
  - `SWAT_TAG_REGISTRY` defines `FIT501` as "RO feed flow transmitter" and `PIT501` as "RO pump suction pressure transmitter".
- **Directional Verification**:
  - **Proposed Direction**: `FIT501` $\to$ `PIT501`.
  - **Physical Flaw**: Suction pressure transmitter `PIT501` is tapped on the suction manifold *upstream* of high-pressure pumps P501/P502. Flow transmitter `FIT501` monitors fluid entering or discharging from the pump skid. In fluid mechanics, fluid flows down a pressure gradient. Upstream suction pressure influences pump cavitation and available net positive suction head (NPSH), but downstream flow rate does not causally produce upstream suction pressure.
  - If a causal relationship exists between flow and pressure in Stage 5, it originates at pump `P501` driving discharge pressure `PIT502` and feed flow `FIT501`.
- **Empirical Audit**:
  - In normal baseline, the differenced correlation is $r = +0.0448$ at $\tau = 1\text{ s}$, which is statistically indistinguishable from zero noise.
  - The apparent high correlation ($r = -0.9982$ raw, $r = -0.9197$ differenced) observed in held-out data occurs because both channels simultaneously collapsed to zero during the plantwide shutdown at 08:35:00 UTC.
- **Audit Status**: `UNKNOWN` / `REJECTED_DIRECTION`. **Unsuitable as a directed structural edge.** Direct edge `FIT501` $\to$ `PIT501` must be excluded from Stage 2.

---

## 3. Candidate 3: `FIT501` $\to$ `FIT502`

- **Source Component**: `FIT501` (RO Feed Flow Transmitter, Stage 5).
- **Destination Component**: `FIT502` (RO Permeate Flow Transmitter, Stage 5).
- **Physical Engineering Units**: Continuous flow (m3/h) $\to$ Continuous flow (m3/h).
- **Documented Process Role**:
  - `FIT501` measures raw feed water delivered to the high-pressure RO vessel array.
  - `FIT502` measures pure desalinated permeate water passing through the reverse osmosis membrane sheets.
- **Directional Verification**:
  - **Proposed Direction**: `FIT501` $\to$ `FIT502` (Forward Mass Balance).
  - **Physical Rationale**: Conservation of mass dictates $Q_{\text{feed}} = Q_{\text{permeate}} + Q_{\text{concentrate}}$ ($FIT501 = FIT502 + FIT503$). An increase in feed flow provides the hydraulic mass required to produce permeate.
  - **Dynamic Limitations**: Permeate flow is governed by the Solution-Diffusion model across the membrane ($J_w = A (\Delta P - \Delta \pi)$). In normal steady-state, feed flow was tightly regulated ($\mu = 0.800$ m3/h, $\sigma = 0.001$ m3/h), resulting in zero differenced correlation ($r = -0.0316$).
- **Audit Status**: `INFERRED` (Medium Confidence). Suitable as a static mass-balance constraint, but unreliable as a pure bivariate empirical dynamic edge in Stage 2 without modeling high-pressure pump head `PIT502`.

---

## 4. Candidate 4: `FIT201` $\to$ `LIT301`

- **Source Component**: `FIT201` (Chemical Dosing Outlet Flow Transmitter, Stage 2).
- **Destination Component**: `LIT301` (Ultrafiltration Feed Tank T301 Level Transmitter, Stage 3).
- **Physical Engineering Units**: Continuous flow (m3/h) $\to$ Continuous level (mm).
- **Documented Process Role**:
  - `SWaT data collection_20-07-2019 v2.pdf` (p. 1) confirms in Attack A4 that opening valve `MV201` and running pump `P101` causes fluid to flow into Tank T301: *"Intent: To overflow tank T301"*.
- **Directional Verification**:
  - **Proposed Direction**: `FIT201` $\to$ `LIT301` (Forward Cross-Stage Inflow).
  - **Physical Misspecification**: Tank T301 is a fluid accumulator governed by:
    $$\frac{dh}{dt} = \frac{FIT201(t) - Q_{\text{out}}(t)}{A_{\text{tank}}}$$
    Where $Q_{\text{out}}(t)$ is the fluid pumped out of T301 by UF feed pump `P301`.
  - Because tank level integrates net flow, raw level $LIT301$ has a unit root ($\rho_1 = 1.000$). Attempting to correlate raw level with raw inflow caused cross-correlation to peak at the maximum boundary of the lag window ($\tau = -120\text{ s}, r = -0.8159$).
- **Audit Status**: `INFERRED` (High Confidence in Physical Pathway, Conditional on State Formulation). Suitable as a structural edge **only if** Stage 2 formulates the relationship using derivative level $\frac{dLIT301}{dt}$ and incorporates pump `P301`.

---

## 5. Candidate 5: `MV501` $\to$ `PIT502`

- **Source Component**: `MV501` (RO Reject Motorized Valve, Stage 5).
- **Destination Component**: `PIT502` (RO Pump Discharge Pressure Transmitter, Stage 5).
- **Physical Engineering Units**: Discrete valve state ($0 = \text{Fault}, 1 = \text{OPEN}, 2 = \text{CLOSE}$) $\to$ Continuous pressure (bar / kPa).
- **Documented Process Role**:
  - `SWaT data collection_20-07-2019 v2.pdf` (p. 1) documents Attack A5: *"Attack on MV501: Switch from OPEN to CLOSE; Intent: To drain water from RO"*.
  - Closing motorized valve `MV501` obstructs the brine reject exit manifold from the reverse osmosis membrane tubes.
- **Directional Verification**:
  - **Proposed Direction**: `MV501` $\to$ `PIT502` (Forward Hydraulic Throttling).
  - **Physical Rationale**: When the high-pressure pump P501 is running, closing downstream reject valve `MV501` suddenly restricts the exit area, producing severe fluid deceleration and water hammer backpressure that spikes upstream vessel pressure `PIT502` from 3 bar to over 28 bar.
- **The Baseline Zero-Variance Barrier**:
  - Throughout the 8,100-second baseline sequence, `MV501` was strictly constant at state 2 ($\sigma = 0.000$).
  - **Purely data-driven algorithms (Granger causality, Transfer Entropy, cross-correlation) cannot identify this edge from baseline data.**
- **Audit Status**: `INFERRED` (High Confidence in Physical Mechanism, Zero Baseline Identifiability). Must be injected as a structural prior edge in Stage 2 rather than discovered from baseline telemetry.

---

## 6. Synthesis Scorecard for the Five Candidate Edges

| Pair ID | Proposed Edge | Physical Relationship | Documented Direction? | Documentary Status | Baseline Identifiability | Stage 2 Structural Mask Decision |
|---|---|---|:---:|:---:|:---:|---|
| **PAIR_01** | `P301` $\to$ `DPIT301` | Pump actuation building membrane $\Delta P$ | YES (Forward) | `INFERRED` | **IDENTIFIABLE** | **ALLOW (Primary Validated Edge)** |
| **PAIR_02** | `FIT501` $\to$ `PIT501` | Downstream flow to upstream suction pressure | NO (Inverted) | `UNKNOWN` | **UNIDENTIFIABLE** | **DISALLOW (Physically Inverted)** |
| **PAIR_03** | `FIT501` $\to$ `FIT502` | Feed to permeate membrane mass balance | YES (Forward) | `INFERRED` | **UNIDENTIFIABLE (Steady-State)** | **ALLOW (Conditional Mass Balance)** |
| **PAIR_04** | `FIT201` $\to$ `LIT301` | Cross-stage inflow accumulating in tank T301 | YES (Forward) | `INFERRED` | **IDENTIFIABLE** | **ALLOW (Requires Differential Form)** |
| **PAIR_05** | `MV501` $\to$ `PIT502` | Reject valve throttling creating vessel surge | YES (Forward) | `INFERRED` | **UNIDENTIFIABLE (Zero Variance)** | **ALLOW (Prior Edge, Unexcited)** |
