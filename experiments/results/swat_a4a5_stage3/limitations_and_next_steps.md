# TCMIM Stage 3: Engineering Limitations and Next Steps

## 1. Overview of Unresolved Engineering Questions

Stage 3 established empirical dynamic models for `MV201 -> FIT201` and `P301 -> DPIT301`, audited the `P101` pathway, and reconciled the Attack A6 sequence violation. However, several critical physical and instrumentation limitations prevent immediate deployment into production gating.

---

## 2. Specific Relationship Limitations

### 2.1 P101 -> FIT101 (Disallowed Instrumentation Misidentification)
- **Status**: **`DISALLOWED`**
- **Evidence Gap Resolved**: Analysis of 14,996 seconds of raw telemetry proved zero direct hydraulic connection ($r = 0.0528$, 0/12 responsive transitions). FIT101 is the municipal raw water supply inflow modulated by motorized valve MV101 ($r = 0.9259$).
- **Limitation**: Although P101 -> FIT101 is refuted as a direct forward edge, an indirect feedback coupling exists through tank T101 level dynamics:
  $$\frac{d}{dt} \text{LIT101} \propto \text{FIT101}(\text{MV101}) - q_{\text{out}}(\text{P101})$$
  This is a mass-balance accumulation loop, not a direct hydraulic flow propagation edge. It cannot be represented as a simple delay edge.

### 2.2 P101 -> FIT201 (Conditionally Supported Transfer Edge)
- **Status**: **`DYNAMICALLY_SUPPORTED` / `INFERRED` (Conditional)**
- **Empirical Evidence**: P101 starts concurrently with MV201 reaching open state; flow FIT201 jumps to 2.34 m³/h.
- **Limitation**:
  1. The raw dataset contains no episodes where P101 is energized while MV201 is closed. The individual hydraulic contribution of P101 cannot be mathematically decoupled from MV201 valve opening without independent actuator perturbation.
  2. Backup raw water pump P102 was completely unexcited ($\sigma = 0.0$) throughout the 2019 dataset. Whether P102 shares the exact manifold impedance to FIT201 is inferable from P&ID drawings but lacks empirical telemetry validation.

### 2.3 P205 -> AIT203 (Sodium Bisulfite Dosing to ORP Analyzer)
- **Status**: **`UNRESOLVED` (Quarantined pending additional operational pooling)**
- **Reason**: Pump P205 (NaHSO3 dosing) was unexcited in the normal baseline period ($\sigma = 0.0$, strictly OFF). While chemical dosing directly alters oxidation-reduction potential (ORP), the baseline data provide zero transient cycles to identify reaction delay, probe diffusion time, or chemical reaction kinetics.
- **Requirement Before Promotion**: Must pool multiple SWaT operational runs (e.g. 2015 baseline or dedicated chemical dosing perturbation logs) to observe clean P205 start/stop transitions.

### 2.4 FIT501 -> FIT502 (Reverse Osmosis Feed to Permeate Flow)
- **Status**: **`QUARANTINED` (Excluded from dynamic causal modeling)**
- **Reason**: The relationship between RO feed flow (FIT501) and permeate flow (FIT502) is a steady-state mass balance separation across the membrane:
  $$\text{FIT502} = \eta \cdot \text{FIT501}$$
  where $\eta$ is the membrane recovery ratio ($\approx 0.75 - 0.80$).
  Both channels fluctuate synchronously under steady-state high-pressure pumping. Zero identifiable dead time or phase lag exists at 1 Hz resolution. Treating this mass balance as a temporal causal propagation edge risks severe gating misclassification.

### 2.5 State S3 for P301 -> DPIT301 (Single-Episode Constraint)
- **Status**: **`CONDITIONALLY_VALIDATED` (Cautionary)**
- **Limitation**: The open-permeate startup state (State S3) is observed in only one episode across the entire 4.16-hour dataset (Attack A6 at row 13,504). Although the single-stage FOPDT model fits this episode with $R^2 = 0.9961$, parameter estimation error bounds cannot be derived from a single episode.

---

## 3. Plantwide CRI Evaluation Guardrails

Plantwide Composite Risk Index (CRI) evaluation remains **STRICTLY DISABLED**.

Rationale:
1. **Cascade Risk Overestimation**: Connecting unvalidated or conditionally supported dynamic models to downstream risk propagation calculations introduces artificial risk amplification along spurious paths.
2. **Structural Prior Prerequisite**: Plantwide CRI requires all candidate edges in the active subgraph to have validated physical bounds. Until P205 -> AIT203, P101 -> FIT201, and FIT501 -> FIT502 reach formal empirical resolution, graph-level risk calculations are scientifically ungrounded.

---

## 4. Specific Actionable Next Steps

| Task ID | Action Item | Target Relationship | Prerequisite / Evidence Needed |
|---|---|---|---|
| **ST4-01** | Multi-run dataset pooling | `P205 -> AIT203`, `P102 -> FIT201` | Ingest SWaT 2015 continuous training logs to extract chemical dosing pump step responses. |
| **ST4-02** | Multi-input MISO formalization | `(P101, MV201) -> FIT201` | Formalize state-space or bilinear model: $y(t) = f(\text{P101}, \text{MV201})$. |
| **ST4-03** | Shadow gating evaluation | `MV201 -> FIT201`, `P301 -> DPIT301` | Run experimental dynamic gating in shadow mode (log decisions without modifying production candidate edges). |
| **ST4-04** | Formal P&ID verification | Stage 1 & Stage 2 Manifold | Obtain signed engineering piping drawings to confirm suction/discharge manifold geometry for P101/P102. |
| **ST4-05** | Delayed recovery guardrail | `MV201 -> FIT201` | Implement interlock detection: delay gate evaluation until P101 energization is confirmed in telemetry. |
