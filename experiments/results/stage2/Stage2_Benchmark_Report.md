# TCMIM Stage 2 - Synthetic Multi-Machine Benchmark Report
**Execution Timestamp:** 2026-10-25T15:48:55.842243+00:00 (UTC)  
**Configuration:** default  
**Random Seed:** 42  
**Total Scenarios:** 7  
**Total Runtime:** 0.02s  

---

## 1. Executive Summary & Aggregate Metrics

| Metric | Macro Average (Mean per Scenario) | Micro Aggregate (Overall Pool) |
|---|---|---|
| **Precision** | 0.3476 (n=7) | 0.3333 |
| **Recall** | 1.0000 (n=4) | 1.0000 |
| **F1 Score** | 0.7542 (n=4) | 0.5000 |
| **False Positive Rate (FPR)** | 0.4762 | 0.5143 |
| **Lag MAE (s)** | 28.278s | - |
| **Lag RMSE (s)** | 28.582s | - |
| **Missing Delay Rate** | 0.0% (0/9) | - |

### Confusion Counts Summary
- **True Positives (TP):** 9
- **False Positives (FP):** 18
- **False Negatives (FN):** 0
- **True Negatives (TN):** 17
- **Candidate Edges Filtered Out:** 0

---

## 2. Per-Scenario Benchmark Breakdown

| # | Scenario | GT Edges | Predicted Edges | Filtered | TP | FP | FN | TN | Precision | Recall | F1 | FPR | Lag MAE | Runtime |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **Linear Chain (A -> B -> C)** | `A->B, B->C` | `A->B, A->C, B->C` | 0 | 2 | 1 | 0 | 3 | 0.667 | 1.000 | 0.800 | 0.250 | 0.00s | 0.007s |
| 2 | **Branching Fork (A -> B and A -> C)** | `A->B, A->C` | `A->B, A->C, B->C` | 0 | 2 | 1 | 0 | 3 | 0.667 | 1.000 | 0.800 | 0.250 | 0.00s | 0.002s |
| 3 | **Feedback Ring (A -> B -> C -> A)** | `A->B, B->C, C->A` | `A->B, A->C, B->A, B->C, C->A` | 0 | 3 | 2 | 0 | 1 | 0.600 | 1.000 | 0.750 | 0.667 | 0.00s | 0.002s |
| 4 | **Negative Control (Independent Streams)** | `none` | `M1->M2, M1->M3, M1->M4, M2->M4, M3->M1, M3->M2, M3->M4, M4->M2` | 0 | 0 | 8 | 0 | 4 | 0.000 | N/A | N/A | 0.667 | N/A | 0.002s |
| 5 | **Reversed Temporal Order (Target Precedes Source)** | `none` | `B->A` | 0 | 0 | 1 | 0 | 1 | 0.000 | N/A | N/A | 0.500 | N/A | 0.001s |
| 6 | **Common Cause Disturbance (Shared Environmental Shock)** | `none` | `M1->M2, M1->M3, M2->M3` | 0 | 0 | 3 | 0 | 3 | 0.000 | N/A | N/A | 0.500 | N/A | 0.001s |
| 7 | **Noisy Cascade (Jitter, Dropout, Spurious Events)** | `A->B, B->C` | `A->B, A->C, B->C, C->B` | 0 | 2 | 2 | 0 | 2 | 0.500 | 1.000 | 0.667 | 0.500 | 113.11s | 0.002s |

---

## 3. Detailed Scenario Diagnostics & Delay Accuracy

### Linear Chain (A -> B -> C) (`scenario_1_chain`)
- **Description:** Linear Chain (A -> B -> C)
- **Confusion Breakdown:** TP=2, FP=1, FN=0, TN=3 (out of 6 possible directed pairs)
- **Metrics:** Precision=0.6667, Recall=1.0000, F1=0.8000, FPR=0.2500
- **Delay Errors (Recovered Edges):**
  - `A->B`: Injected=60.00s, Estimated=60.00s, Error=+0.00s (Abs=0.00s)
  - `B->C`: Injected=90.00s, Estimated=90.00s, Error=+0.00s (Abs=0.00s)
- **OC-CCD Diagnostics:** PROPAGATION_CANDIDATE: 18

### Branching Fork (A -> B and A -> C) (`scenario_2_branching`)
- **Description:** Branching Fork (A -> B and A -> C)
- **Confusion Breakdown:** TP=2, FP=1, FN=0, TN=3 (out of 6 possible directed pairs)
- **Metrics:** Precision=0.6667, Recall=1.0000, F1=0.8000, FPR=0.2500
- **Delay Errors (Recovered Edges):**
  - `A->B`: Injected=45.00s, Estimated=45.00s, Error=+0.00s (Abs=0.00s)
  - `A->C`: Injected=80.00s, Estimated=80.00s, Error=+0.00s (Abs=0.00s)
- **OC-CCD Diagnostics:** COMMON_CAUSE_CANDIDATE: 18

### Feedback Ring (A -> B -> C -> A) (`scenario_3_ring`)
- **Description:** Feedback Ring (A -> B -> C -> A)
- **Confusion Breakdown:** TP=3, FP=2, FN=0, TN=1 (out of 6 possible directed pairs)
- **Metrics:** Precision=0.6000, Recall=1.0000, F1=0.7500, FPR=0.6667
- **Delay Errors (Recovered Edges):**
  - `A->B`: Injected=50.00s, Estimated=50.00s, Error=+0.00s (Abs=0.00s)
  - `B->C`: Injected=50.00s, Estimated=50.00s, Error=+0.00s (Abs=0.00s)
  - `C->A`: Injected=50.00s, Estimated=50.00s, Error=+0.00s (Abs=0.00s)
- **OC-CCD Diagnostics:** COMMON_CAUSE_CANDIDATE: 20

### Negative Control (Independent Streams) (`scenario_4_negative_control`)
- **Description:** Negative Control (Independent Streams)
- **Confusion Breakdown:** TP=0, FP=8, FN=0, TN=4 (out of 12 possible directed pairs)
- **Metrics:** Precision=0.0000, Recall=N/A, F1=N/A, FPR=0.6667
- **Delay Errors:** N/A (no ground-truth edges recovered).
- **OC-CCD Diagnostics:** PROPAGATION_CANDIDATE: 4, COMMON_CAUSE_CANDIDATE: 9

### Reversed Temporal Order (Target Precedes Source) (`scenario_5_reversed_order`)
- **Description:** Reversed Temporal Order (Target Precedes Source)
- **Confusion Breakdown:** TP=0, FP=1, FN=0, TN=1 (out of 2 possible directed pairs)
- **Metrics:** Precision=0.0000, Recall=N/A, F1=N/A, FPR=0.5000
- **Delay Errors:** N/A (no ground-truth edges recovered).
- **OC-CCD Diagnostics:** PROPAGATION_CANDIDATE: 6

### Common Cause Disturbance (Shared Environmental Shock) (`scenario_6_common_cause`)
- **Description:** Common Cause Disturbance (Shared Environmental Shock)
- **Confusion Breakdown:** TP=0, FP=3, FN=0, TN=3 (out of 6 possible directed pairs)
- **Metrics:** Precision=0.0000, Recall=N/A, F1=N/A, FPR=0.5000
- **Delay Errors:** N/A (no ground-truth edges recovered).
- **OC-CCD Diagnostics:** COMMON_CAUSE_CANDIDATE: 18

### Noisy Cascade (Jitter, Dropout, Spurious Events) (`scenario_7_noisy`)
- **Description:** Noisy Cascade (Jitter, Dropout, Spurious Events)
- **Confusion Breakdown:** TP=2, FP=2, FN=0, TN=2 (out of 6 possible directed pairs)
- **Metrics:** Precision=0.5000, Recall=1.0000, F1=0.6667, FPR=0.5000
- **Delay Errors (Recovered Edges):**
  - `A->B`: Injected=65.00s, Estimated=194.74s, Error=+129.74s (Abs=129.74s)
  - `B->C`: Injected=85.00s, Estimated=181.48s, Error=+96.48s (Abs=96.48s)
- **OC-CCD Diagnostics:** PROPAGATION_CANDIDATE: 17, COMMON_CAUSE_CANDIDATE: 4

---

## 4. Scientific Provenance & Methodological Limitations

1. **Algorithmic Recovery vs. Physical Causality:**
   This benchmark evaluates the software pipeline's mathematical capacity to identify temporal
   precedence patterns and estimate consistent time lags under controlled synthetic conditions.
   Temporal association does **NOT** prove physical causality between interconnected machines.

2. **Synthetic Data Boundary:**
   All benchmark event records are explicitly generated with `Provenance.SYNTHETIC`.
   These results demonstrate software correctness and algorithmic sensitivity under synthetic conditions;
   they do **NOT** constitute empirical industrial validation of propagation delays or failure propagation.

3. **Transitive Reduction & Direct vs. Indirect Influence:**
   In multi-stage cascade chains (e.g. A -> B -> C with delays 60s and 90s), pairwise temporal matching
   identifies a temporal precedence between A and C (150s lag) within plausible delay windows.
   Without graphical transitive reduction or conditional independence testing, pairwise matching
   identifies both direct and indirect temporal relationships.

4. **CRI Interpretation:**
   The Cascade Risk Index (CRI) computed by the pipeline is an evidence-derived graph topology index,
   **NOT** a calibrated failure probability or verified propagation predictor.

5. **Hardware Prototype Independence:**
   ESP32 hardware ingestion remains separate and is not connected to these benchmark results.