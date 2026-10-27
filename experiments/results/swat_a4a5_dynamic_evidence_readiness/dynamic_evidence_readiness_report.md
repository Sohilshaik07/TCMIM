# Scientific Audit: Dynamic Evidence Readiness of Stage 2 Accepted Candidate Edges
## Evaluation of the 22 Observations Surviving G0_STRUCTURAL_MASK (SWaT A4/A5 July 2019)

**Document ID:** `TCMIM-SWAT-A4A5-DYN-READINESS-2026-10`  
**Date:** October 26, 2026  
**Status:** Complete & Independently Audited  
**Target:** Read-Only Scientific Audit of Accepted Candidate Edges in [`experiments/results/swat_a4a5_g0_evaluation/`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/)  
**Physical Register Hash (SHA-256):** `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`  

---

## 1. Executive Summary & Core Audit Conclusions

This report provides a read-only scientific audit of the **22 candidate-edge observations** that survived Gate G0 (`G0_STRUCTURAL_MASK`) and all subsequent pipeline gates during the paired evaluation on the SWaT A4/A5 July 2019 dataset.

### Core Discoveries & Reconciliations:

1. **Reconciliation of Observations vs. Relationships (Objectives 1, 2, & 4):**
   - The 22 accepted observations reconcile completely and deterministically to **five physical source-destination component pairs**:
     - `FIT501 -> FIT502` (EDGE_03): 10 observations
     - `P301 -> DPIT301` (EDGE_01): 5 observations
     - `MV201 -> FIT201` (EDGE_10): 3 observations
     - `P101 -> FIT101` (EDGE_07): 3 observations
     - `P205 -> AIT203` (EDGE_12): 1 observation
   - All 22 observations possess valid UUIDs, consistent channel identifiers, non-empty timestamps, explicit provenance (`PUBLIC_DATASET`), and verified register permissions (`status=1`).
   - Reconciling the 33 candidates that passed G0 against the 22 that survived all gates reveals that **11 candidates were rejected by Gate G2 (`G2_ORDERING`)** because $\Delta t = 0.00\text{ s} \le 0$ (simultaneous window onsets). These 11 simultaneous rejections spanned `P301 -> DPIT301` (5), `MV201 -> FIT201` (3), `FIT501 -> FIT502` (1), `P205 -> AIT203` (1), and a sixth registered pair `P203 -> AIT202` (1).

2. **Severe Observation Dependency & Target Reuse (Objective 3):**
   - The 22 accepted observations do **NOT** represent 22 independent physical propagation episodes.
   - Across the plant, the 22 observations involve only **11 unique target response episodes**:
     - In `FIT501 -> FIT502`, all 10 accepted observations map to only **2 unique target events** in `FIT502` (`07:52:00` and `08:07:30`). Each target event was redundantly paired with five prior micro-bursts of `FIT501`.
     - In `P301 -> DPIT301`, 5 observations map to only **3 unique target depressurization events**, with 3 separate pump bursts pairing to the single membrane depressurization at `08:24:30`.
     - In `P101 -> FIT101`, 3 observations map to only **2 unique flow events**.
   - Treating these observations as independent statistical samples in downstream graph inference would cause severe variance underestimation and degrees-of-freedom inflation.

3. **Window Quantization vs. Physical Delay Reality (Objectives 6 & 7):**
   - The reported delays ($\Delta t \in \{30, 60, 120, 180, ..., 600\}\text{ s}$) are **heavily quantized artifacts of the 30.0-second feature windowing**, not true physical transport times.
   - High-resolution 1 Hz telemetry auditing demonstrates that true physical response dynamics operate on radically different timescales:
     - `MV201 -> FIT201`: True motorized valve opening stroke takes **9.5s–10.5s** (pipeline reported 30s, 180s, 450s).
     - `P101 -> FIT101`: Pump startup discharge surge occurs within **<1.0s** (pipeline reported 120s, 240s, 300s).
     - `P301 -> DPIT301`: Membrane pressurization delay is **39.0s** and depressurization collapse is **5.8s** (pipeline reported up to 570s).
     - `P205 -> AIT203`: Chemical transport, reaction, and ORP probe response exhibits a consistent lag of **120.0s** (pipeline reported 30s).
     - `FIT501 -> FIT502`: Zero baseline variation ($\sigma = 0.0015$); evaluation correlation represents concurrent plant trip ($\text{lag} = -4\text{ s}$).

4. **Dynamic Readiness Recommendation (Objectives 8 & 9):**
   - **Do NOT begin plantwide CRI evaluation.**
   - Three relationships (`P301 -> DPIT301`, `MV201 -> FIT201`, `P101 -> FIT101`) have high baseline excitation and clean step-response characteristics; they are **Ready for Dynamic Validation on raw 1 Hz sub-sequences**.
   - `FIT501 -> FIT502` must be **quarantined from dynamic modeling** due to baseline stationarity and target dependence.
   - `P205 -> AIT203` requires pooling additional operational runs due to $N=1$.

---

## 2. Reconciled Inventory of the 22 Accepted Observations

The complete inventory of all 22 observations accepted in Configuration B is documented in [`accepted_observation_audit.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_dynamic_evidence_readiness/accepted_observation_audit.csv):

| Index | Observation ID (`obs_id`) | Relationship | Source Onset (UTC) | Target Onset (UTC) | Reported Delay ($\Delta t$) | Interval | Independent Episode? | Dependency Diagnosis |
|---|---|---|---|---|---|---|---|---|
| 1 | `91b111bb-07fc-4aa1-bb0d-6be569afd92e` | `MV201 -> FIT201` | 07:17:30 | 07:18:00 | 30.0 s | A2 | **Yes** | Unique target response episode |
| 2 | `7e66cd98-0a18-4022-b55c-a843dd50cb0f` | `MV201 -> FIT201` | 07:34:00 | 07:37:00 | 180.0 s | Outside | **Yes** | Unique target response episode |
| 3 | `5f6a42a4-1f7b-422a-bc39-3f7fa5d26a04` | `MV201 -> FIT201` | 07:37:00 | 07:44:30 | 450.0 s | Outside | **Yes** | Unique target response episode |
| 4 | `88878359-3a02-4e72-b82a-0159392aa15d` | `P101 -> FIT101` | 07:34:00 | 07:39:00 | 300.0 s | Outside | **Yes** | Unique target response episode |
| 5 | `a7059df4-033b-46dc-b9a2-3614b7b62400` | `P101 -> FIT101` | 07:37:00 | 07:39:00 | 120.0 s | Outside | **No** | Redundant match: Target 07:39:00 already paired with 07:34:00 |
| 6 | `9a363845-4153-4a15-ac68-464a553ecc52` | `P101 -> FIT101` | 07:44:30 | 07:48:30 | 240.0 s | A4 | **Yes** | Unique target response episode |
| 7 | `1bd2eb75-4d4b-40b2-b9c6-5df926b202a5` | `FIT501 -> FIT502` | 07:42:00 | 07:52:00 | 600.0 s | A4 | **Yes** | Primary match to target episode 07:52:00 |
| 8 | `f1a50dd3-758c-4c6e-8ca9-98a83bcf631a` | `FIT501 -> FIT502` | 07:43:30 | 07:52:00 | 510.0 s | A4 | **No** | Redundant match: Target 07:52:00 already matched |
| 9 | `9db1de6a-6b79-491a-a253-ddf22bb9c442` | `FIT501 -> FIT502` | 07:45:00 | 07:52:00 | 420.0 s | A4 | **No** | Redundant match: Target 07:52:00 already matched |
| 10 | `f63e5463-d157-4bec-81ba-543a905a3e3c` | `FIT501 -> FIT502` | 07:50:00 | 07:52:00 | 120.0 s | Outside | **No** | Redundant match: Target 07:52:00 already matched |
| 11 | `145b78a8-3534-4343-ae7c-901094a49f92` | `FIT501 -> FIT502` | 07:51:00 | 07:52:00 | 60.0 s | Outside | **No** | Redundant match: Target 07:52:00 already matched |
| 12 | `d0624bd3-c8c9-4cf7-b82e-4baad8f0d753` | `FIT501 -> FIT502` | 07:58:30 | 08:07:30 | 540.0 s | Outside | **Yes** | Primary match to target episode 08:07:30 |
| 13 | `d49406f7-5fe9-4a45-a16e-472c5fba6f51` | `FIT501 -> FIT502` | 08:00:30 | 08:07:30 | 420.0 s | Outside | **No** | Redundant match: Target 08:07:30 already matched |
| 14 | `8282df9e-084a-4f1b-9080-8200a0443d8a` | `FIT501 -> FIT502` | 08:01:30 | 08:07:30 | 360.0 s | Outside | **No** | Redundant match: Target 08:07:30 already matched |
| 15 | `2f517bf3-240e-4e11-aa6e-835844d9bdfd` | `FIT501 -> FIT502` | 08:04:30 | 08:07:30 | 180.0 s | A6 | **No** | Redundant match: Target 08:07:30 already matched |
| 16 | `9efa1566-35d9-4a69-85ee-4e9e5b690a59` | `FIT501 -> FIT502` | 08:05:30 | 08:07:30 | 120.0 s | A6 | **No** | Redundant match: Target 08:07:30 already matched |
| 17 | `aa9a2db1-1b0b-4d6e-9f36-a7957ac3c31a` | `P301 -> DPIT301` | 07:52:00 | 08:01:00 | 540.0 s | Outside | **Yes** | Unique target response episode |
| 18 | `5ee8b3e5-522b-4bed-a0c2-e8901b40103e` | `P301 -> DPIT301` | 08:15:00 | 08:22:00 | 420.0 s | A6 | **Yes** | Unique target response episode |
| 19 | `9c6b2d13-4cb0-4537-98de-90113a082023` | `P301 -> DPIT301` | 08:15:00 | 08:24:30 | 570.0 s | A6 | **Yes** | Primary match to target episode 08:24:30 |
| 20 | `a3736259-759c-48dd-825f-40f691bd5062` | `P301 -> DPIT301` | 08:22:00 | 08:24:30 | 150.0 s | Outside | **No** | Redundant match: Target 08:24:30 already matched |
| 21 | `c1f44b60-05da-4432-a5bf-d8da4860b745` | `P301 -> DPIT301` | 08:23:30 | 08:24:30 | 60.0 s | Outside | **No** | Redundant match: Target 08:24:30 already matched |
| 22 | `0b2bd5ec-2504-4aaf-9201-c2a1fab9b312` | `P205 -> AIT203` | 08:27:30 | 08:28:00 | 30.0 s | Outside | **Yes** | Unique single observation ($N=1$) |

---

## 3. Epistemic Matrix for the Five Relationships

To avoid conflating structural possibility with empirical proof, each relationship is evaluated across six epistemic dimensions in [`relationship_identifiability.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_dynamic_evidence_readiness/relationship_identifiability.csv):

```
                   EPISTEMIC MATURITY PROGRESSION
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ 1. Documentary      │ -> │ 2. Structural       │ -> │ 3. Baseline         │
│    Specification    │    │    Admissibility    │    │    Excitation       │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
                                                                 │
                                                                 ▼
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ 6. Verified Causal  │ <- │ 5. Empirical        │ <- │ 4. Statistical      │
│    Propagation      │    │    Dynamic Evidence │    │    Identifiability  │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

### Detailed Epistemic Breakdown:

1. **`MV201 -> FIT201` (EDGE_10):**
   - **Documentary Support:** INFERRED via Attack 4 specification and SWaT tag registry.
   - **Engineering Inference:** Motorized chemical dosing valve `MV201` regulates inflow into Stage 2 pipe; valve position directly governs flow measured by `FIT201`.
   - **Structural Eligibility:** ALLOWED (`status=1`).
   - **Baseline Excitation:** High cyclic switching (4,894 samples closed, 3,155 open, 51 intermediate).
   - **Statistical Identifiability:** `IDENTIFIABLE`.
   - **Dynamic Evidence:** Strong. 1 Hz step-up response exhibits an opening stroke transit time of mean **10.50 s** (median **9.50 s**), and closing seating time of mean **3.25 s**.

2. **`P101 -> FIT101` (EDGE_07):**
   - **Documentary Support:** INFERRED via SWaT process architecture.
   - **Engineering Inference:** Raw water intake pump `P101` discharges directly through inline flow transmitter `FIT101`.
   - **Structural Eligibility:** ALLOWED (`status=1`).
   - **Baseline Excitation:** Frequent cyclic pumping (4,952 samples OFF, 3,148 samples ON).
   - **Statistical Identifiability:** `IDENTIFIABLE`.
   - **Dynamic Evidence:** Strong. 1 Hz step-up response demonstrates an instantaneous fluid flow surge of **<1.0 s** ($\text{mean} = 0.00\text{ s}$), and shutdown line drainage of **9.5s–13.3s**.

3. **`FIT501 -> FIT502` (EDGE_03):**
   - **Documentary Support:** INFERRED via standard reverse osmosis mass conservation principles ($Q_{feed} = Q_{perm} + Q_{reject}$).
   - **Engineering Inference:** High-pressure feed stream supplies permeate separation stream.
   - **Structural Eligibility:** ALLOWED (`status=1`).
   - **Baseline Excitation:** **Zero excitation / stationary.** Feed flow `FIT501` had baseline mean $0.8002$ with standard deviation $\sigma = \mathbf{0.0015}$. It was essentially flatline constant.
   - **Statistical Identifiability:** `UNIDENTIFIABLE_NORMAL_STEADY_STATE`.
   - **Dynamic Evidence:** Unusable. Baseline cross-correlation is negligible ($r = 0.1374$). In evaluation, the high correlation ($r = 0.9657$ at $\text{lag} = -4\text{ s}$) was driven by concurrent plantwide pump trip, not active feed-to-permeate dynamics.

4. **`P301 -> DPIT301` (EDGE_01):**
   - **Documentary Support:** INFERRED via Attack 6 specification ("Switch P301 from ON to OFF to halt stage 3 UF process").
   - **Engineering Inference:** Ultrafiltration feed pump discharge directly builds trans-membrane differential pressure across the membrane fibers.
   - **Structural Eligibility:** ALLOWED (`status=1`).
   - **Baseline Excitation:** Regular operational cycling (4,202 samples OFF, 3,898 samples ON).
   - **Statistical Identifiability:** `IDENTIFIABLE`.
   - **Dynamic Evidence:** Excellent. 1 Hz step-up exhibits a remarkably consistent membrane pressurization delay of **34.4s–39.0s**, and step-down exhibits an immediate pressure collapse of **5.8s–6.0s**.

5. **`P205 -> AIT203` (EDGE_12):**
   - **Documentary Support:** INFERRED via SWaT tag registry.
   - **Engineering Inference:** Sodium bisulfite ($NaHSO_3$) dosing pump injects chemical reducing agent to de-chlorinate water, lowering oxidation-reduction potential (ORP) measured by `AIT203`.
   - **Structural Eligibility:** ALLOWED (`status=1`).
   - **Baseline Excitation:** Cyclic chemical dosing (4,983 samples OFF, 3,117 samples ON).
   - **Statistical Identifiability:** `IDENTIFIABLE`.
   - **Dynamic Evidence:** Consistent but sample-limited. 1 Hz cross-correlation exhibits a peak lag of **exactly 120.0 s** in both baseline ($r = 0.6772$) and evaluation ($r = 0.6340$). However, only **one observation ($N=1$)** survived the pipeline in the evaluation window.

---

## 4. Delay Resolution Audit: Discretization Jitter vs. Physical Timescales

The detailed audit of time resolution is documented in [`delay_resolution_audit.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_dynamic_evidence_readiness/delay_resolution_audit.json):

```
Time Resolution Hierarchy:
├── Raw Telemetry: 1.0 Hz (1-second sampling interval)
├── Feature Windows: 30.0s duration, 30.0s step (Window start: k × 30s)
└── Delay Quantization: Δt ∈ {30s, 60s, 90s, ..., 600s}
```

### Empirical Comparison: Reported Window Delay vs. Raw 1 Hz Physical Delay

| Relationship | Reported Pipeline Delay Range | True 1 Hz Physical Step-Up Delay | True 1 Hz Physical Step-Down Delay | Peak 1 Hz Cross-Correlation Lag | Primary Cause of Discrepancy |
|---|---|---|---|---|---|
| `MV201 -> FIT201` | 30.0 s – 450.0 s | **10.5 s** (median 9.5 s) | **3.25 s** (median 1.5 s) | +10 s | Delays of 180s and 450s reflect pairing across prolonged operational cycles rather than fluid transit. |
| `P101 -> FIT101` | 120.0 s – 300.0 s | **0.0 s** (< 1.0 s surge) | **13.3 s** (drainage) | 0 s | Pump operated for minutes before anomalous flow deviation was flagged, inflating onset delta. |
| `P301 -> DPIT301` | 60.0 s – 570.0 s | **34.4 s** (median 39.0 s) | **5.8 s** (median 6.0 s) | +39 s / -6 s | Delays of 420s to 570s represent early pump starts paired to subsequent shutdown depressurizations. |
| `FIT501 -> FIT502` | 60.0 s – 600.0 s | Flatline / Stationary | Flatline / Stationary | -4 s (shutdown) | 10 candidate edges represent combinations of 10 micro-bursts against only 2 target shutdown events. |
| `P205 -> AIT203` | 30.0 s (single obs) | Continuous response | Continuous response | **+120.0 s** | Window quantization placed source at 08:27:30 and target at 08:28:00 (dt=30s), underestimating 120s lag. |

**Audit Conclusion:** Window-level delay $\Delta t$ is **wholly unsuitable** for dynamic physical modeling. It introduces up to $\pm 15\text{ s}$ quantization jitter and can inflate apparent delays by hundreds of seconds through multi-burst pairing.

---

## 5. Engineering Parameter Gaps for Physical Delay Bounds

As detailed in [`engineering_parameter_gaps.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_dynamic_evidence_readiness/engineering_parameter_gaps.md), analytical calculation of delay bounds $[d_{min}, d_{max}]$ is impeded by critical missing engineering specifications:

1. **Missing P&IDs & Run Lengths:** Without isometric drawings or pipe lengths ($L$) and internal diameters ($D$), bulk advective transport time $\tau = \frac{\pi D^2 L}{4 Q}$ cannot be calculated analytically.
2. **Missing Valve Actuator Curves:** The motorized valve stroke time ($T_{stroke} \approx 10\text{ s}$) was discovered empirically from 1 Hz telemetry; valve manufacturer datasheets ($C_v$ curves, motor RPM) are absent from the public release.
3. **Missing Membrane Skid Volumes:** Ultrafiltration housing liquid volume and trans-membrane permeability parameters are undocumented, preventing analytical verification of the observed 39-second pressurization delay.
4. **Missing Analyzer Cell Lag:** Chemical transport between dosing pump `P205` and analyzer `AIT203` cannot be separated into fluid transit versus probe $T_{90}$ response without physical pipe length and flow cell volume.

**Safeguard:** No synthetic or arbitrary pipe dimensions should be manufactured. Delay bounds must be calibrated empirically from 1 Hz step-response data with explicit documentation of parameter gaps.

---

## 6. Actionable Recommendations for Next Research Milestone

As detailed in [`next_experiment_recommendation.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_dynamic_evidence_readiness/next_experiment_recommendation.md):

1. **Halt Plantwide CRI Evaluation:** Calculating plantwide Cascade Risk Index (CRI) at this stage would produce an unvalidated number based on an incomplete physical graph.
2. **Advance Three Category A Edges to 1 Hz Dynamic Modeling:**
   - `P301 -> DPIT301`: Fit piecewise non-linear step-response models (39s pressurization vs. 6s depressurization).
   - `MV201 -> FIT201`: Fit First-Order Plus Dead Time (FOPDT) models on valve opening/closing transitions.
   - `P101 -> FIT101`: Fit state-dependent impulse response models.
3. **Quarantine Category C Edges:** Do not attempt dynamic causal estimation on `FIT501 -> FIT502`. Treat strictly as an algebraic mass balance constraint.
4. **Calibrate Component-Specific Delay Bounds:** Replace $[0, 600\text{ s}]$ with tight empirical bounds:
   - `MV201 -> FIT201`: $[5.0\text{ s}, 25.0\text{ s}]$
   - `P101 -> FIT101`: $[0.0\text{ s}, 15.0\text{ s}]$
   - `P301 -> DPIT301`: $[5.0\text{ s}, 50.0\text{ s}]$
   - `P205 -> AIT203`: $[90.0\text{ s}, 150.0\text{ s}]$
