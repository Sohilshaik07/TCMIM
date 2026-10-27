# Limitations and Next Steps: Stage 2 Raw Telemetry Dynamic Validation
## SWaT A4/A5 July 2019 Operational Telemetry

**Document ID:** `TCMIM-SWAT-A4A5-LIMITATIONS-2026-10`  
**Date:** October 26, 2026  
**Status:** Complete & Independently Audited  
**Scope:** Explicit declaration of scientific limitations, unmodeled physical confounding, instrumentation misidentifications, and requirements for subsequent research milestones.

---

## 1. Epistemic Separation of Validation Stages

To prevent over-claiming, the TCMIM project enforces strict boundaries between four distinct levels of inferential certainty:

```
LEVEL 1: Structural Admissibility
         Component pair is physically piped or wired according to P&ID documentation.
         (Enforced by G0_STRUCTURAL_MASK; necessary but NOT sufficient for dynamic propagation).
                             │
                             ▼
LEVEL 2: Dynamic Association
         Source actuator transition statistically associates with a repeatable target sensor step.
         (Demonstrated here for P301 -> DPIT301 and MV201 -> FIT201 on raw 1 Hz data).
                             │
                             ▼
LEVEL 3: Physical Transfer Function Identifiability
         Empirical response can be parameterized into a stable, held-out validated dynamical model.
         (Validated here for MV201 -> FIT201 FOPDT and P301 -> DPIT301 normal startup/shutdown).
                             │
                             ▼
LEVEL 4: Verified Causal Propagation
         Proof that an upstream fault or anomaly causally propagates through the physical medium
         to induce a downstream cascade failure under unconfounded interventionist conditions.
         (NOT established in this milestone; requires controlled counterfactual perturbation).
```

Passing Gate G0 or achieving a high $R^2$ on a held-out step response does **NOT** constitute proof of Level 4 causal propagation.

---

## 2. Identified Confounding and Process State Dependencies

### 2.1 Multi-Actuator Process Confounding in `P301 -> DPIT301`
- **Finding:** Ultrafiltration feed pump `P301` operates in tight coordination with motorized permeate valve `MV302`.
- **Confounding Mechanism:** Under normal operations, the PLC starts `P301` against closed `MV302` for 32 seconds before opening `MV302`. This creates a two-phase pressure curve (Phase 1: dead-head rise to 6.1 kPa; Phase 2: permeate flux surge to 12.6 kPa at $t \approx 55\text{ s}$).
- **Attack Disruption:** During Attack A6, the attacker commanded `P301` ON while `MV302` was already open (state 2). Consequently, `DPIT301` pressurized in a single 1-second burst to 12.2 kPa, causing the normal model to produce $R^2 = -1.89$.
- **Scientific Implication:** Modeling `P301 -> DPIT301` as a single input-single output (SISO) transfer function without conditioning on `MV302` is physically incomplete. A multi-input (MISO) or state-dependent model is required.

### 2.2 Instrumentation Misidentification in `P101 -> FIT101`
- **Finding:** The physical connectivity register (`physical_connectivity_register.csv`, `EDGE_07`) documented `P101 -> FIT101` as a forward hydraulic edge, assuming `FIT101` was the pump discharge flow transmitter.
- **Physical Reality:** Cross-tabulation and tag registry auditing prove that `FIT101` is the raw water **inflow** meter into Tank T101, strictly governed by inlet motorized valve `MV101` ($r = 0.926$). Pump `P101` is the **outflow** suction pump that pumps water out of Tank T101 into Stage 2.
- **Scientific Implication:** `P101 -> FIT101` has zero direct hydraulic response ($r = 0.053$, 0/12 responsive transitions). The true discharge of pump `P101` is measured downstream in Stage 2 by `FIT201`. Register `EDGE_07` must be formally de-registered or marked non-identifiable.

---

## 3. Data and Telemetry Limitations

1. **Nominal 1 Hz Temporal Resolution:**
   - The sampling interval is $1.000\text{ s} \pm 0.045\text{ s}$. Fast hydrodynamic acoustic waves ($t < 0.02\text{ s}$) and pump electric motor start surges ($t < 0.5\text{ s}$) are unresolvable.
   - Any response occurring within the same second as the actuator command registers as $\Delta t = 0\text{ s}$ delay.
2. **Limited Independent Episode Counts:**
   - Over the 4.17-hour dataset, only 7 startups and 6 shutdowns occurred for `P301`, and 6 complete opening/closing cycles occurred for `MV201`.
   - While held-out cross-validation was successful ($R^2 = 0.9936$ for normal P301 startup, $R^2 = 0.9746$ for shutdown, $R^2 = 0.8600$ for MV201 opening), larger statistical sample sizes from multi-day recordings are necessary for confidence interval convergence.
3. **Missing Certified P&IDs:**
   - The public SWaT release lacks certified mechanical drawings, pipe lengths, and valve flow coefficient ($C_v$) curves. All delay bounds derived herein are empirical observations from operational telemetry, not analytical solutions from first-principles Navier-Stokes equations.

---

## 4. Required Next Steps

1. **Re-Register Stage 1 Hydraulic Topology:**
   - Submit a formal recommendation to update the physical connectivity register:
     - Mark `EDGE_07` (`P101 -> FIT101`) as `DISALLOWED_MISIDENTIFIED` (`status=0`).
     - Register `MV101 -> FIT101` as a valid hydraulic coupling (`status=1`).
     - Register `P101 -> FIT201` as the true inter-stage pump delivery coupling (`status=1`).
2. **Multi-Input Modeling for Ultrafiltration:**
   - Extend the `P301 -> DPIT301` dynamical model to take both `P301` and `MV302` states as inputs:
     $$y(t) = f(\text{P301}(t), \text{MV302}(t))$$
3. **Quarantine `FIT501 -> FIT502` and `P205 -> AIT203`:**
   - Maintain quarantine on `FIT501 -> FIT502` until operational perturbation data is available.
   - Pool additional operational datasets (e.g. SWaT 2015 multi-day normal collection) to acquire sufficient independent episodes for `P205 -> AIT203`.
4. **Do NOT Proceed to Plantwide CRI:**
   - Plantwide Cascade Risk Index (CRI) calculation must remain paused until these topological corrections and state-dependent models are formalized.
