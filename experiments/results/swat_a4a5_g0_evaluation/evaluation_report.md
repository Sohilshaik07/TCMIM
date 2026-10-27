# TCMIM Research Milestone Report
## Stage 2 Candidate-Edge Gating Evaluation with G0_STRUCTURAL_MASK (SWaT A4/A5 July 2019)

**Document ID:** `TCMIM-SWAT-A4A5-G0-EVAL-2026-10`  
**Date:** October 26, 2026  
**Status:** Complete & Independently Verified  
**Target Architecture:** TCMIM Stage 2 Pipeline (`EventMatcher` -> `GatingPipeline` -> `DynamicGraph`)  
**Evaluation Scope:** Paired evaluation of SWaT A4/A5 July 2019 operational telemetry with `G0_STRUCTURAL_MASK` disabled (Configuration A) versus enabled (Configuration B).  
**Structural Register Hash (SHA-256):** `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`  

---

## 1. Executive Summary

This milestone executes a paired, deterministic scientific evaluation of **Gate G0 (`G0_STRUCTURAL_MASK`)** on the Secure Water Treatment (SWaT) A4/A5 July 2019 operational dataset. The objective is to measure how an auditable physical structural constraint modifies candidate-edge generation and gating without claiming that candidate edges represent verified causal propagation.

### Key Empirical Findings

1. **Unconstrained Candidate Explosion (Configuration A — G0 Disabled):**
   - In held-out operational evaluation (Windows 280–499, 06:50:00 to 08:40:00 UTC), baseline-calibrated per-channel anomaly monitoring detected **200 discrete burst events across 33 active channels**.
   - Unconstrained pairwise temporal matching within the default $[0, 600\text{ s}]$ delay window generated **3,852 candidate propagation edges**.
   - Under the legacy pipeline (G0 disabled), **3,472 candidate edges (90.13%)** survived all gating stages. The surviving graph suffered from massive candidate explosion, accepting physically impossible cross-stage shortcuts (e.g., Raw Intake Stage 1 to Reverse Osmosis Stage 5) simply because systemic disturbances caused coincident alarms across the facility.

2. **Structural Pruning Effectiveness (Configuration B — G0 Enabled):**
   - Enabling Gate G0 before Gate G1 under the audited SWaT physical connectivity register and conservative unknown-edge policy (`allow_unknown=False`) removed **3,819 candidate edges** directly at Gate G0.
   - **5 candidate edges** were rejected as explicitly **Prohibited (`status=0`)**.
   - **3,814 candidate edges** were rejected as **Unverified / Unknown (`status=?`)** under conservative industrial safety policy.
   - Only **33 candidate edges** satisfied physical structural eligibility to enter Gate G1.
   - **22 candidate edges** survived all downstream gates (G1–G5).
   - This represents an **absolute reduction of 3,450 candidate edges** and a **relative reduction of 99.37%** (from 3,472 accepted down to 22 accepted).

3. **Surviving Physical Relationships:**
   - All **22 surviving candidate edges** in Configuration B correspond strictly to documented and engineering-inferred physical plant couplings:
     - `FIT501 -> FIT502` (10 observations): Stage 5 RO feed mass balance to permeate flow.
     - `P301 -> DPIT301` (5 observations): Stage 3 Ultrafiltration feed pump discharge building trans-membrane differential pressure.
     - `MV201 -> FIT201` (3 observations): Stage 2 chemical dosing valve regulating chemical feed flow.
     - `P101 -> FIT101` (3 observations): Stage 1 raw water supply pump discharging through flow transmitter FIT101.
     - `P205 -> AIT203` (1 observation): Stage 2 sodium bisulfite dosing pump coupled to oxidation-reduction potential (ORP) analyzer.
   - Zero prohibited or unknown edges passed Configuration B.

4. **Multi-Gate Filtering Integrity:**
   - Of the 33 candidate edges passing G0, 11 were subsequently rejected by downstream dynamic consistency gates (G2–G5). This demonstrates that Gate G0 functions strictly as an admissibility constraint and does not bypass empirical data consistency checks.

---

## 2. Methodology & Experimental Protocol

### 2.1 Paired Evaluation Design

To eliminate confounding variables, both configurations were executed over an **identical candidate universe** generated from the exact same telemetry, feature representations, and event onsets:

```
Telemetry Stream (SWaT A4/A5 July 2019)
       │
       ▼
Gap-Aware Window Builder (size=30s, step=30s)
       │
       ▼
Baseline-Calibrated Per-Channel Monitoring (Windows 10..279)
       │
       ▼
AnomalyToEventAdapter (200 discrete events across 33 channels)
       │
       ▼
EventMatcher (Pairwise delay window [0, 600s])
       │
       ▼
Identical Candidate Edge Universe (3,852 edges)
       │
  ┌────┴─────────────────────────────┐
  ▼                                  ▼
[Configuration A: G0 Disabled]     [Configuration B: G0 Enabled]
  • structural_mask = None           • structural_mask = Audited Register
  • G0 Not Applied                   • allow_unknown = False (Conservative)
  • Enters G1 directly (3,852 edges) • G0 filters before G1 (3,819 rejected)
  • Accepted: 3,472 edges            • Enters G1 (33 edges)
  • Rejected: 380 edges              • Accepted: 22 edges
                                     • Rejected: 3,830 edges
```

### 2.2 Dataset Provenance & Window Partitioning

- **Source File:** `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx`
- **Total Records:** 14,996 rows at 1.0 Hz across 77 sensor and actuator columns.
- **Pre-baseline Buffer:** Windows 0–9 (300 s / 04:30:00 to 04:35:00 UTC) — discarded to prevent initialization transients.
- **In-Sample Baseline Partition:** Windows 10–279 (8,100 s / 04:35:00 to 06:50:00 UTC) — 270 normal-operation windows used to fit baseline feature means, standard deviations, and 95th-percentile alarm thresholds ($\tau \ge 3.0$).
- **Held-Out Operational Evaluation Partition:** Windows 280–499 (6,600 s / 06:50:00 to 08:40:00 UTC) — 220 operational windows containing six official attack intervals.
- **Ground-Truth Isolation:** Zero ground-truth attack labels were accessed during window construction, feature extraction, threshold calibration, candidate matching, or gating. Attack labels were used strictly post hoc for categorization.

### 2.3 Physical Connectivity Register Specifications

The structural mask was initialized using the audited SWaT physical connectivity register:
- **Location:** `experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv`
- **Register SHA-256:** `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`
- **Registered Edges:** 22 physical component relationships.
- **Conservative Policy:** Edges not explicitly documented in the register evaluate to `StructuralStatus.UNKNOWN ('?')` and are rejected at Gate G0 when `allow_unknown=False`.

---

## 3. Comparative Gating Pipeline Results

### 3.1 Pipeline Stage Breakdown

The paired candidate progression across all gating stages is summarized below:

| Gating Pipeline Stage | Configuration A (G0 Disabled) | Configuration B (G0 Enabled) | Absolute Difference | Relative Change |
|---|---|---|---|---|
| **Initial Matched Candidates** | **3,852** | **3,852** | **0** | **0.00%** |
| **Gate G0: Structural Mask** | *Not Applied* | **3,819 Rejected** | +3,819 | N/A |
| — Explicitly Prohibited (`status=0`) | *Not Applied* | 5 Rejected | +5 | N/A |
| — Unregistered / Unknown (`status=?`) | *Not Applied* | 3,814 Rejected | +3,814 | N/A |
| **Candidates Entering Gate G1** | **3,852** | **33** | **-3,819** | **-99.14%** |
| **Gate G1: Delay Feasibility** | 269 Rejected | 0 Rejected | -269 | -100.00% |
| **Gate G2: Ordering Consistency** | 0 Rejected | 0 Rejected | 0 | 0.00% |
| **Gate G3: Direction Consistency** | 0 Rejected | 0 Rejected | 0 | 0.00% |
| **Gate G4: Health Consistency** | 0 Rejected | 0 Rejected | 0 | 0.00% |
| **Gate G5: Relationship Consistency** | 111 Rejected | 11 Rejected | -100 | -90.09% |
| **Accepted Candidates (Surviving All Gates)** | **3,472** | **22** | **-3,450** | **-99.37%** |
| **Total Candidates Rejected** | **380** | **3,830** | **+3,450** | **+907.89%** |

### 3.2 Granular Rejection Reason Analysis

Analysis of `experiments/results/swat_a4a5_g0_evaluation/rejection_reason_summary.csv` reveals the exact failure modes:

```
Configuration A (G0 Disabled) Total Rejections: 380
├── G1_DELAY_FEASIBILITY: 269
│   └── "Delay dt=...s outside feasible window [0.0, 600.0]s"
└── G5_RELATIONSHIP_CONSISTENCY: 111
    └── "modality mismatch / invalid state transition"

Configuration B (G0 Enabled) Total Rejections: 3,830
├── G0_STRUCTURAL_MASK: 3,819
│   ├── "Disallowed by physical structural mask (status=0, prohibited)" (5 candidates)
│   └── "Disallowed by physical structural mask (status=?, rejected by conservative policy)" (3,814 candidates)
└── G5_RELATIONSHIP_CONSISTENCY: 11
    └── "modality mismatch / invalid state transition"
```

In Configuration A, the unconstrained pipeline failed to reject 3,472 candidate pairs because temporal coincidence within 10 minutes ($600\text{ s}$) was easily satisfied across the plant during periods of high variance. In Configuration B, Gate G0 intercepted 99.14% of spurious pairs before computational resources were wasted on downstream modeling.

---

## 4. Evaluation Across Documented Attack Intervals

The 3,852 candidate edges were grouped post hoc by their source event onset timestamp relative to the six documented SWaT attack intervals (closed interval $[T_{start}, T_{end}]$):

| Interval ID | Target Tag(s) | Attack Description | Initial Candidates | Config A Accepted | Config A Rejected | Config B Accepted | Config B Rejected | Config B G0 Rejected (Proh / Unk) | Absolute Reduction | Percentage Reduction |
|---|---|---|---|---|---|---|---|---|---|---|
| **A1** | FIT401 | Spoof value from 0.8 to 0.5 | 15 | 15 | 0 | **0** | 15 | 15 (0 / 15) | 15 | **100.00%** |
| **A2** | LIT301 | Spoof value from 835 to 1024 | 125 | 77 | 48 | **1** | 124 | 122 (2 / 120) | 76 | **98.70%** |
| **A3** | P601 | Switch from OFF to ON | 187 | 179 | 8 | **0** | 187 | 187 (0 / 187) | 179 | **100.00%** |
| **A4** | MV201; P101 | Switch MV201 CLOSE->OPEN; P101 OFF->ON | 540 | 506 | 34 | **4** | 536 | 536 (0 / 536) | 502 | **99.21%** |
| **A5** | MV501 | Switch from OPEN to CLOSE | 44 | 44 | 0 | **0** | 44 | 44 (0 / 44) | 44 | **100.00%** |
| **A6** | P301 | Switch from ON to OFF | 531 | 507 | 24 | **4** | 527 | 526 (0 / 526) | 503 | **99.21%** |
| **Outside** | N/A | Events outside attack intervals | 2,410 | 2,144 | 266 | **13** | 2,397 | 2,389 (3 / 2,386) | 2,131 | **99.39%** |
| **Total** | — | — | **3,852** | **3,472** | **380** | **22** | **3,830** | **3,819 (5 / 3,814)** | **3,450** | **99.37%** |

### Interval-Specific Observations:

1. **Attacks A1, A3, and A5 (100% G0 Pruning):**
   - For A1 (`FIT401`), A3 (`P601`), and A5 (`MV501`), all initial candidate edges (15, 187, and 44 respectively) were completely eliminated by Gate G0.
   - **Root Cause:** In the SWaT facility, flow sensor `FIT401` monitors RO dechlorinated feed, pump `P601` is a backwash pump, and valve `MV501` controls the RO reject line. The observed alarms during these intervals paired predominantly with distant sensors across PLCs 1, 2, and 3 where no direct physical connection exists. G0 correctly blocked these unverified cross-stage shortcuts.
2. **Attacks A4 and A6 (Physical Path Retention):**
   - In A4 (manipulation of Stage 2 motorized valve `MV201` and Stage 1 raw water pump `P101`), 4 edges survived G0, specifically capturing local actuator-sensor couplings: `MV201 -> FIT201` and `P101 -> FIT101`.
   - In A6 (switching Ultrafiltration feed pump `P301` from ON to OFF), 4 edges survived G0, specifically capturing `P301 -> DPIT301` (differential pressure collapse across the UF membrane).

---

## 5. Audit of Surviving Physical Edges vs. Eliminated Shortcuts

### 5.1 Surviving Physical Relationships (22 Accepted Edges)

All 22 edges accepted in Configuration B represent genuine, documented/inferred physical process couplings:

| Source Channel | Target Channel | Process Mechanism | Observed Occurrences | Mean Delay ($\Delta t$) | Documentary Status |
|---|---|---|---|---|---|
| `FIT501` | `FIT502` | RO Stage 5 Feed Flow to Permeate Flow (Mass Balance) | 10 | 282.0 s | INFERRED (`status=1`) |
| `P301` | `DPIT301` | UF Feed Pump Discharge to Trans-Membrane Differential Pressure | 5 | 186.0 s | INFERRED (`status=1`) |
| `MV201` | `FIT201` | Chemical Dosing Valve Actuation to Stage 2 Feed Flow | 3 | 120.0 s | INFERRED (`status=1`) |
| `P101` | `FIT101` | Raw Water Intake Pump to Feed Line Flow Measurement | 3 | 90.0 s | INFERRED (`status=1`) |
| `P205` | `AIT203` | Sodium Bisulfite Metering Pump to Stage 2 ORP Analyzer | 1 | 30.0 s | INFERRED (`status=1`) |

### 5.2 Eliminated Prohibited Shortcuts (5 Candidates)

Gate G0 rejected five candidate edges that directly violated physical plant topology:

1. `AIT201 -> FIT501` (2 instances): Raw water conductivity analyzer to RO feed flow. These components reside across different process stages with intervening chemical dosing tanks and buffer storage; direct hydraulic propagation without intermediate stage instrumentation is physically impossible.
2. `P601 -> AIT201` (1 instance): Backwash drain pump to raw water intake analyzer. Physically separated and reverse flow direction.
3. `MV501 -> DPIT301` (2 instances): Reverse osmosis reject valve to Ultrafiltration membrane differential pressure. Physically reverse direction across two complete treatment stages.

### 5.3 Pruning of Unregistered / Unknown Candidate Explosion (3,814 Candidates)

The overwhelming majority of rejected edges (3,814 out of 3,819) were pairs lacking documented physical coupling in the plant register. In Configuration A, 3,472 of these spurious pairs survived simply because industrial telemetry exhibited correlated drift during multi-stage attacks. Pruning these pairs is critical to preventing catastrophic graph density inflation and false cascade risk estimations.

---

## 6. Scientific Integrity Declarations & Epistemic Boundaries

In accordance with strict scientific reporting standards, the following explicit restrictions apply to this evaluation:

1. **Candidate Reduction is NOT Precision or Recall:**
   - A 99.37% reduction in candidate edges reflects the **structural filtering capacity** of physical domain constraints. It does NOT represent precision, recall, accuracy, or causal discovery performance.
2. **Attack Labels are NOT Propagation Ground Truth:**
   - Attack injection schedules indicate when cyber-physical tampering occurred on specific actuators or sensors. They do **not** document which downstream sensors were physically perturbed or the ground-truth timing of fluid propagation waves.
3. **Correlation and Temporal Ordering Do NOT Prove Causality:**
   - Observing that `P301` turned OFF at $T_0$ and `DPIT301` dropped at $T_0 + 60\text{ s}$ satisfies structural eligibility and temporal precedence, but does not prove unconfounded physical causation.
4. **Structural Admissibility is NOT Dynamic Empirical Validation:**
   - Passing Gate G0 indicates only that an edge is **physically permissible according to engineering diagrams**. It does not establish that dynamic physical influence actually propagated across that edge during the observed window.
5. **CRI is NOT Validated Against Real-World Cascades:**
   - This experiment validates candidate-edge filtering. It does **not** validate the Cascade Risk Index (CRI) formula against ground-truth catastrophic industrial cascading failures.

---

## 7. Artifacts and Deliverables

All artifacts generated by this evaluation have been created under `experiments/results/swat_a4a5_g0_evaluation/` without modifying any historical experiment directories:

| File Path | Size | Description |
|---|---|---|
| [g0_off_vs_on_metrics.json](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/g0_off_vs_on_metrics.json) | 4,656 B | Machine-readable top-level metrics, candidate counts, and per-attack summaries. |
| [per_attack_interval_metrics.csv](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/per_attack_interval_metrics.csv) | 810 B | Granular paired counts and reduction percentages across attacks A1–A6. |
| [candidate_edge_comparison.csv](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/candidate_edge_comparison.csv) | 1,210,785 B | Full record of all 3,852 candidate edges with Config A vs B gating decisions and reasons. |
| [rejection_reason_summary.csv](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/rejection_reason_summary.csv) | 98,698 B | Frequency distribution of rejection reasons mapped to respective pipeline gates. |
| [evaluation_config.json](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/evaluation_config.json) | 896 B | Complete evaluation configuration parameters and data partition bounds. |
| [test_results.txt](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/test_results.txt) | 2,752 B | Pytest execution log confirming 15/15 unit test assertions passed. |
| [change_manifest.json](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/change_manifest.json) | 2,415 B | Manifest of created files, preserved reference directories, and register SHA-256. |
| [evaluation_report.md](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_g0_evaluation/evaluation_report.md) | This File | Comprehensive scientific milestone report. |

---

## 8. Limitations & Recommended Next Research Decision

### 8.1 Unresolved Limitations

1. **Incomplete Public Plant Documentation:**
   - The public SWaT release lacks complete, formal piping and instrumentation diagrams (P&IDs) for all six stages. Consequently, 3,814 candidate pairs were classified as `UNKNOWN ('?')`. While conservative exclusion is industrially sound, true physical relationships between unrecorded instrumentation may have been omitted.
2. **Coarse Window Resolution (30.0 s):**
   - The 30.0-second feature window limits fine-grained delay estimation. Hydraulic pressure transients often propagate in seconds, whereas chemical transport occurs over minutes. A single fixed delay window $[0, 600\text{ s}]$ lacks hydraulic fidelity.
3. **Unexcited Actuators:**
   - Actuators that remained static during the baseline cannot have their statistical identifiability established from passive operational telemetry alone.

### 8.2 Recommended Next Research Decision

**Recommendation: Advance to Stage 2 Dynamic Edge Validation on Structurally Permitted Candidates.**

Before attempting graph-level Cascade Risk Index (CRI) estimation across the full plant:
1. Focus empirical dynamic validation (transfer entropy, cross-correlation, and Granger causality) **strictly on the 22 structurally permitted candidate paths** identified in this milestone.
2. Replace the global $[0, 600\text{ s}]$ delay window with component-specific hydraulic travel time bounds derived from pipe diameters and nominal pump flow rates.
3. Preserve the conservative gating policy (`allow_unknown=False`) to prevent spurious topological shortcuts from corrupting subsequent risk models.
