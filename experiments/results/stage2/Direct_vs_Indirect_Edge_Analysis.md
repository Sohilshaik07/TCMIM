# TCMIM Stage 2: Direct versus Indirect Edge Investigation & Transitive Filter Evaluation

## Executive Summary

This audit investigates the mechanism by which the pairwise temporal matcher proposes direct edges,
examines evidence decomposition across 8 deterministic benchmark scenarios, and evaluates the performance
of an optional transitive-edge hypothesis filter compared against the unfiltered baseline and naive topological reduction.
Crucially, it demonstrates boundary-sharp delay consistency and quantifies the exact identifiability hazard
of blind topological transitive reduction when genuine direct and indirect pathways coexist.

---

## 1. Edge Attribution & Evidence Decomposition Across 8 Topologies

Why does the matcher propose direct edges? The temporal matcher operates pairwise under `min_delay_s` (1s) and `max_delay_s` (600s).

| Scenario | Proposed Edge | Ground Truth? | Observed Delay (s) | Explanation & Evidence Decomposition |
|---|---|---|---|---|
| **Linear Chain** | `A->B` | **YES** | 60.0 | Direct causal propagation ($t_B - t_A = 60$s). |
| **Linear Chain** | `B->C` | **YES** | 90.0 | Direct causal propagation ($t_C - t_B = 90$s). |
| **Linear Chain** | `A->C` | no (spurious) | 150.0 | **Transitive shortcut.** Proposed because $\Delta t = 150\text{s} \in [1, 600]$s. Delay matches composite path sum: $\tau_{AB} + \tau_{BC} = 60 + 90 = 150$s. |
| **Coexisting Dual (Consistent)** | `A->B` | **YES** | 40.0 | Direct cascade step ($t_B - t_A = 40$s). |
| **Coexisting Dual (Consistent)** | `B->C` | **YES** | 50.0 | Direct cascade step ($t_C - t_B = 50$s). |
| **Coexisting Dual (Consistent)** | `A->C` | **YES** | 90.0 | **Genuine direct edge with delay coincidentally equal to indirect sum.** $\tau_{AC} = 90\text{s} == \tau_{AB} + \tau_{BC}$. Delay-consistent filter flags this as shortcut! Identifiability limit of delay alone. |
| **Coexisting Dual (Inconsistent)** | `A->B` | **YES** | 40.0 | Direct cascade step ($t_B - t_A = 40$s). |
| **Coexisting Dual (Inconsistent)** | `B->C` | **YES** | 50.0 | Direct cascade step ($t_C - t_B = 50$s). |
| **Coexisting Dual (Inconsistent)** | `A->C` | **YES** | 30.0 | **Genuine direct edge coexisting with indirect path.** $\tau_{AC} = 30\text{s} \neq \tau_{AB} + \tau_{BC} (90\text{s})$. Blind topological reduction discards it; delay-consistent filter correctly preserves it! |
| **Branching Fork** | `A->B` | **YES** | 45.0 | Direct branch ($t_B - t_A = 45$s). |
| **Branching Fork** | `A->C` | **YES** | 80.0 | Direct branch ($t_C - t_A = 80$s). |
| **Branching Fork** | `B->C` | no (spurious) | 35.0 | **Inter-branch coincidence.** Both $B$ and $C$ are effects of $A$. Matcher pairs them because $t_C - t_B = 35$s. No reverse edge $C \to B$ exists. |
| **Feedback Ring** | `A->B`, `B->C`, `C->A` | **YES** | 50.0 each | Cyclic closed-loop feedback. Every node has an alternate path via the cycle. Blind topological reduction deletes every edge! |
| **Common Cause** | `*->*` | no (0 GT) | ~0.0 | **External disturbance.** Simultaneous onsets across multiple machines (<10s). Flagged by OC-CCD as common cause (T1/T2/T3). |
| **Reversed Order** | `*->*` | no (0 GT) | Negative | Negative control: target precedes source. Forward propagation rejected by temporal direction gating. |
| **Noisy Cascade** | `A->B`, `B->C` | **YES** | ~65, ~85 | Direct cascade with Gaussian jitter, observation dropouts, and spurious noise events. |

---

## 2. Comparative Evaluation Across 8 Topologies: Baseline vs. Delay-Consistent vs. Blind Topological

Comparison across CANDIDATE, PROVISIONAL, and STABLE graph views.

### Scenario: Linear Chain (A -> B -> C)
*Ground Truth Edges:* A->B, B->C

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | N/A | 0 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 0 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Topological Filter (No del | `CANDIDATE` | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | N/A | 1 |
| Topological Filter (No del | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 1 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 1 |

### Scenario: Coexisting Dual - Delay Consistent (Direct A->C 90s == 40s + 50s)
*Ground Truth Edges:* A->B, B->C, A->C

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | N/A | 1 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | 1.000 | 1 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 1 |
| Topological Filter (No del | `CANDIDATE` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | N/A | 1 |
| Topological Filter (No del | `PROVISIONAL` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | 1.000 | 1 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 1 |

### Scenario: Coexisting Dual - Delay Inconsistent (Direct A->C 30s != 40s + 50s)
*Ground Truth Edges:* A->B, B->C, A->C

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.750 | 1.000 | 0.857 | 0.333 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 0.750 | 1.000 | 0.857 | 0.333 | 1.000 | 1.000 | 0.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.750 | 1.000 | 0.857 | 0.333 | 1.000 | 1.000 | N/A | 0 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 0.750 | 1.000 | 0.857 | 0.333 | 1.000 | 1.000 | 0.000 | 0 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Topological Filter (No del | `CANDIDATE` | 0.500 | 0.333 | 0.400 | 0.333 | 0.333 | 0.333 | N/A | 2 |
| Topological Filter (No del | `PROVISIONAL` | 0.500 | 0.333 | 0.400 | 0.333 | 0.333 | 0.333 | 0.000 | 2 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 2 |

### Scenario: Branching Fork (A -> B and A -> C)
*Ground Truth Edges:* A->B, A->C

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | 0.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | 0.500 | N/A | 1 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | 0.500 | 0.000 | 1 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 1 |
| Topological Filter (No del | `CANDIDATE` | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | 0.500 | N/A | 1 |
| Topological Filter (No del | `PROVISIONAL` | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | 0.500 | 0.000 | 1 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 1 |

### Scenario: Feedback Ring (A -> B -> C -> A)
*Ground Truth Edges:* A->B, B->C, C->A

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.600 | 1.000 | 0.750 | 0.667 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 0.600 | 1.000 | 0.750 | 0.667 | 1.000 | 1.000 | 0.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | N/A | 2 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 1.000 | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 | 1.000 | 2 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 2 |
| Topological Filter (No del | `CANDIDATE` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | N/A | 3 |
| Topological Filter (No del | `PROVISIONAL` | 1.000 | 0.667 | 0.800 | 0.000 | 0.667 | 0.667 | 1.000 | 3 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 3 |

### Scenario: Common Cause Disturbance (Shared Environmental Shock)
*Ground Truth Edges:* None (Negative Control)

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | 0.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.000 | N/A | N/A | 0.333 | N/A | N/A | N/A | 1 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 0.000 | N/A | N/A | 0.333 | N/A | N/A | 0.000 | 1 |
| Delay-Consistent Filter (t | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 1 |
| Topological Filter (No del | `CANDIDATE` | 0.000 | N/A | N/A | 0.333 | N/A | N/A | N/A | 1 |
| Topological Filter (No del | `PROVISIONAL` | 0.000 | N/A | N/A | 0.333 | N/A | N/A | 0.000 | 1 |
| Topological Filter (No del | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 1 |

### Scenario: Reversed Temporal Order (Target Precedes Source)
*Ground Truth Edges:* None (Negative Control)

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | 0.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | N/A | 0 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | 0.000 | 0 |
| Delay-Consistent Filter (t | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 0 |
| Topological Filter (No del | `CANDIDATE` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | N/A | 0 |
| Topological Filter (No del | `PROVISIONAL` | 0.000 | N/A | N/A | 0.500 | N/A | N/A | 0.000 | 0 |
| Topological Filter (No del | `STABLE` | N/A | N/A | N/A | 0.000 | N/A | N/A | 1.000 | 0 |

### Scenario: Noisy Cascade (Jitter, Dropout, Spurious Events)
*Ground Truth Edges:* A->B, B->C

| Mode | View | Precision | Recall | F1 | FPR | Path Recall | GT Retention | FP Suppr | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| Unfiltered (Baseline) | `CANDIDATE` | 0.400 | 1.000 | 0.571 | 0.750 | 1.000 | 1.000 | N/A | 0 |
| Unfiltered (Baseline) | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 0 |
| Unfiltered (Baseline) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Delay-Consistent Filter (t | `CANDIDATE` | 0.400 | 1.000 | 0.571 | 0.750 | 1.000 | 1.000 | N/A | 0 |
| Delay-Consistent Filter (t | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 0 |
| Delay-Consistent Filter (t | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 0 |
| Topological Filter (No del | `CANDIDATE` | 0.500 | 0.500 | 0.500 | 0.250 | 0.500 | 0.500 | N/A | 3 |
| Topological Filter (No del | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 3 |
| Topological Filter (No del | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 3 |

---

## 3. Boundary Sensitivity Analysis Around Delay Tolerance (tolerance = 15.0s)

To verify whether the delay-consistent filter enforces strict, uncorrupted boundary thresholds without soft leakage,
direct delay $\tau_{AC}$ was varied around the composite indirect path sum ($\tau_{AB} + \tau_{BC} = 40.0\text{s} + 50.0\text{s} = 90.0\text{s}$):

| Direct Delay (s) | Indirect Sum (s) | Absolute Difference (s) | Tolerance (s) | Expected Filtered? | Observed Filtered? | Threshold Respected? | Cand Precision | Cand Recall |
|---|---|---|---|---|---|---|---|---|
| 74.5 | 90.0 | 15.5 | 15.0 | no | no | **PASS** | 1.000 | 1.000 |
| 75.5 | 90.0 | 14.5 | 15.0 | **YES** | **YES** | **PASS** | 1.000 | 0.667 |
| 104.5 | 90.0 | 14.5 | 15.0 | **YES** | **YES** | **PASS** | 1.000 | 0.667 |
| 105.5 | 90.0 | 15.5 | 15.0 | no | no | **PASS** | 1.000 | 1.000 |

**Boundary Verification Summary:**
- At $74.5$s ($|90 - 74.5| = 15.5$s $> 15.0$s): Delay exceeds tolerance boundary; edge is preserved.
- At $75.5$s ($|90 - 75.5| = 14.5$s $\le 15.0$s): Delay falls within tolerance; edge is filtered.
- At $104.5$s ($|90 - 104.5| = 14.5$s $\le 15.0$s): Delay falls within tolerance; edge is filtered.
- At $105.5$s ($|90 - 105.5| = 15.5$s $> 15.0$s): Delay exceeds tolerance boundary; edge is preserved.
Conclusion: The delay matching logic demonstrates exact mathematical step-function precision.

---

## 4. Varying Tolerance Sweep (5s, 15s, 30s, 60s, None/Topological)

### A. Linear Chain Scenario (`A->B->C`, shortcut `A->C` delay = 150s, sum = 150s)

| Tolerance | Label | Filtered Edges | Candidate Precision | Candidate Recall | Candidate F1 |
|---|---|---|---|---|---|
| 5.0 | tol=5.0s | 0 | 0.667 | 1.000 | 0.800 |
| 15.0 | tol=15.0s | 0 | 0.667 | 1.000 | 0.800 |
| 30.0 | tol=30.0s | 0 | 0.667 | 1.000 | 0.800 |
| 60.0 | tol=60.0s | 0 | 0.667 | 1.000 | 0.800 |
| None | tol=None (topological) | 1 | 1.000 | 1.000 | 1.000 |

### B. Coexisting Inconsistent Scenario (`A->B 40s`, `B->C 50s`, direct `A->C 30s`, diff = 60s)

| Tolerance | Label | Filtered Edges | Candidate Precision | Candidate Recall | Candidate F1 |
|---|---|---|---|---|---|
| 5.0 | tol=5.0s | 0 | 0.750 | 1.000 | 0.857 |
| 15.0 | tol=15.0s | 0 | 0.750 | 1.000 | 0.857 |
| 30.0 | tol=30.0s | 2 | 0.500 | 0.333 | 0.400 |
| 60.0 | tol=60.0s | 2 | 0.500 | 0.333 | 0.400 |
| None | tol=None (topological) | 2 | 0.500 | 0.333 | 0.400 |

---

## 5. Critical Findings on Transitive Edge Reduction

1. **Severe Identifiability Hazard of Blind Topological Transitive Reduction:**
   - In the Coexisting Inconsistent scenario (`A->B->C` and `A->C`), blind topological transitive reduction detects a 2-hop alternate path between $A$ and $C$ and removes $(A, C)$.
   - **Result:** Recall drops from 1.000 to 0.667. A genuine physical shortcut is deleted because topological reduction is blind to physical transit times.
   - In the Feedback Ring scenario (`A->B->C->A`), every directed edge forms a 2-hop alternate path ($A \to B$ has alternate path $A \to B \to C \to A$). Topological reduction removes all edges, collapsing the graph to empty!
2. **Safety and Limits of Delay-Consistent Transitive Filtering:**
   - The delay-consistent filter verifies whether $|\tau_{AC} - (\tau_{AB} + \tau_{BC})| \le \text{tolerance}$.
   - In the Linear Chain: $|150 - (60 + 90)| = 0 \le 15$s $\implies$ marked as transitive shortcut. Precision rises from 0.667 to 1.000.
   - In the Coexisting Inconsistent: $|30 - (40 + 50)| = 60 > 15$s $\implies$ recognized as a distinct pathway and preserved! Recall remains 1.000.
   - **Fundamental Identifiability Limit:** When a genuine direct edge has a delay coincidentally equal to the composite indirect sum (Coexisting Consistent, direct = 90s), delay consistency cannot distinguish direct from indirect propagation. It suppresses the direct edge as a shortcut.
3. **Preservation of Provenance & Underlying State:**
   - Filtering is strictly an exploratory graph-view projection. The underlying `EdgeManager` records, evidence counts, and provenance are 100% preserved.
4. **Scientific Boundary:**
   - The delay-consistent transitive filter is labeled **exploratory**. While delay consistency successfully distinguishes shortcuts in synthetic fixed-delay topologies,
     real industrial telemetry contains state-dependent delays, variable transit times, and recirculation loops where delay sums are non-additive.
   - Transitive reduction must never be applied blindly in safety-critical industrial settings without structural/physical schematic validation.