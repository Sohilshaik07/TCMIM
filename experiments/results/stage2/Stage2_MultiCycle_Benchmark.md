# TCMIM Stage 2 — Chronological Multi-Cycle Benchmark Report

> **Scientific boundary:** All events are synthetic (`Provenance.SYNTHETIC`).
> This benchmark demonstrates edge lifecycle progression, NOT physical industrial causality.
> CRI is a structural topology score, not a failure probability.
> Empty ground-truth scenarios (e.g. Negative Control) are evaluated by False Positive Count ($FP=0$)
> and False Positive Rate ($FPR=0.0$), NOT by edge retention or positive predictive power.

---

## 1. Summary Table: Final-Cycle Metrics by Graph View

| Scenario | View | P | R | F1 | FPR | Path Recall | GT Retention | FP Suppression | Cycles |
|---|---|---|---|---|---|---|---|---|---|
| Linear Chain (A -> B -> C) | `CANDIDATE` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | N/A | 22 |
| Linear Chain (A -> B -> C) | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 22 |
| Linear Chain (A -> B -> C) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 22 |
| Branching Fork (A -> B and A ->  | `CANDIDATE` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | N/A | 21 |
| Branching Fork (A -> B and A ->  | `PROVISIONAL` | 0.667 | 1.000 | 0.800 | 0.250 | 1.000 | 1.000 | 0.000 | 21 |
| Branching Fork (A -> B and A ->  | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 21 |
| Feedback Ring (A -> B -> C -> A) | `CANDIDATE` | 0.600 | 1.000 | 0.750 | 0.667 | 1.000 | 1.000 | N/A | 7 |
| Feedback Ring (A -> B -> C -> A) | `PROVISIONAL` | 0.600 | 1.000 | 0.750 | 0.667 | 1.000 | 1.000 | 0.000 | 7 |
| Feedback Ring (A -> B -> C -> A) | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 7 |
| Negative Control (Independent St | `CANDIDATE` | N/A | N/A (empty GT) | N/A | 0.000 | N/A (empty GT) | N/A (empty GT) | N/A | 48 |
| Negative Control (Independent St | `PROVISIONAL` | N/A | N/A (empty GT) | N/A | 0.000 | N/A (empty GT) | N/A (empty GT) | N/A | 48 |
| Negative Control (Independent St | `STABLE` | N/A | N/A (empty GT) | N/A | 0.000 | N/A (empty GT) | N/A (empty GT) | N/A | 48 |
| Reversed Temporal Order (Target  | `CANDIDATE` | 0.000 | N/A (empty GT) | N/A | 0.500 | N/A (empty GT) | N/A (empty GT) | N/A | 21 |
| Reversed Temporal Order (Target  | `PROVISIONAL` | 0.000 | N/A (empty GT) | N/A | 0.500 | N/A (empty GT) | N/A (empty GT) | 0.000 | 21 |
| Reversed Temporal Order (Target  | `STABLE` | N/A | N/A (empty GT) | N/A | 0.000 | N/A (empty GT) | N/A (empty GT) | 1.000 | 21 |
| Common Cause Disturbance (Shared | `CANDIDATE` | 0.000 | N/A (empty GT) | N/A | 0.500 | N/A (empty GT) | N/A (empty GT) | N/A | 21 |
| Common Cause Disturbance (Shared | `PROVISIONAL` | 0.000 | N/A (empty GT) | N/A | 0.500 | N/A (empty GT) | N/A (empty GT) | 0.000 | 21 |
| Common Cause Disturbance (Shared | `STABLE` | N/A | N/A (empty GT) | N/A | 0.000 | N/A (empty GT) | N/A (empty GT) | 1.000 | 21 |
| Noisy Cascade (Jitter, Dropout,  | `CANDIDATE` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | N/A | 32 |
| Noisy Cascade (Jitter, Dropout,  | `PROVISIONAL` | 1.000 | 0.500 | 0.667 | 0.000 | 0.500 | 0.500 | 1.000 | 32 |
| Noisy Cascade (Jitter, Dropout,  | `STABLE` | N/A | 0.000 | N/A | 0.000 | 0.000 | 0.000 | 1.000 | 32 |

---

## 2. Ground-Truth Lifecycle Confirmation & Stability Summary

Tracking how genuine propagation pathways progress through thresholds: `CANDIDATE` (>= 1 obs), `PROVISIONAL` (>= 3 obs), and `STABLE` (>= 15 obs).
Distinguishes edges still accumulating evidence from edges that expired or were never observed.

| Scenario | GT Edges | CAND (Prop) | PROV (Prop) | STABLE (Prop) | Never PROV | Never STABLE | Med Cycles (C/P/S) | Accumulating | Never Obs | Expired GT |
|---|---|---|---|---|---|---|---|---|---|---|
| scenario_1_chain | 2 | 2 (1.000) | 2 (1.000) | 0 (0.000) | 0 (0.000) | 2 (1.000) | 0.0 / 8.0 / - | 1 | 0 | 0 |
| scenario_2_branching | 2 | 2 (1.000) | 2 (1.000) | 0 (0.000) | 0 (0.000) | 2 (1.000) | 0.0 / 8.0 / - | 0 | 0 | 0 |
| scenario_3_ring | 3 | 3 (1.000) | 3 (1.000) | 0 (0.000) | 0 (0.000) | 3 (1.000) | 0.0 / 4.0 / - | 0 | 0 | 0 |
| scenario_4_negative_control | 0 | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | - / - / - | 0 | 0 | 0 |
| scenario_5_reversed_order | 0 | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | - / - / - | 0 | 0 | 0 |
| scenario_6_common_cause | 0 | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | 0 (N/A) | - / - / - | 0 | 0 | 0 |
| scenario_7_noisy | 2 | 2 (1.000) | 2 (1.000) | 0 (0.000) | 0 (0.000) | 2 (1.000) | 4.0 / 12.5 / - | 0 | 0 | 2 |

---

## 3. Edge Lifecycle & Path Participation Traces

Full lifecycle history for all observed machine pairs. `GT` = ground truth, `Status` = termination status, `Path?` = contributes to active path, `Trans?` = hypothetical transitive shortcut.

| Scenario | Edge | GT? | First Seen | CAND | PROV | STABLE | Expired | Status | Final State | Evidence | In Path? | Transitive? |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scenario_1_chain | `A->B` | **YES** | 0 | 0 | 8 | - | - | `PROVISIONAL` | `CONFIRMED` | 6 | YES | no |
| scenario_1_chain | `A->C` | no | 0 | 0 | 8 | - | - | `ACCUMULATING_UNCONFIRMED` | `WEAKENING` | 5 | YES | YES |
| scenario_1_chain | `B->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_1_chain | `B->C` | **YES** | 0 | 0 | 8 | - | - | `ACCUMULATING_UNCONFIRMED` | `WEAKENING` | 5 | YES | no |
| scenario_1_chain | `C->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_1_chain | `C->B` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_2_branching | `A->B` | **YES** | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | no |
| scenario_2_branching | `A->C` | **YES** | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | YES |
| scenario_2_branching | `B->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_2_branching | `B->C` | no | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | no |
| scenario_2_branching | `C->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_2_branching | `C->B` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_3_ring | `A->B` | **YES** | 0 | 0 | 4 | - | - | `PROVISIONAL` | `PROVISIONAL` | 4 | YES | no |
| scenario_3_ring | `A->C` | no | 0 | 0 | 4 | - | - | `PROVISIONAL` | `PROVISIONAL` | 4 | YES | YES |
| scenario_3_ring | `B->A` | no | 0 | 0 | 4 | - | - | `PROVISIONAL` | `PROVISIONAL` | 4 | YES | YES |
| scenario_3_ring | `B->C` | **YES** | 0 | 0 | 4 | - | - | `PROVISIONAL` | `PROVISIONAL` | 4 | YES | YES |
| scenario_3_ring | `C->A` | **YES** | 0 | 0 | 4 | - | - | `PROVISIONAL` | `PROVISIONAL` | 4 | YES | no |
| scenario_3_ring | `C->B` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M1->M2` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M1->M3` | no | 3 | 3 | - | - | 10 | `EXPIRED` | `EXPIRED` | 1 | no | no |
| scenario_4_negative_control | `M1->M4` | no | 3 | 3 | - | - | 10 | `EXPIRED` | `EXPIRED` | 2 | no | no |
| scenario_4_negative_control | `M2->M1` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M2->M3` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M2->M4` | no | 15 | 15 | - | - | 22 | `EXPIRED` | `EXPIRED` | 1 | no | no |
| scenario_4_negative_control | `M3->M1` | no | 3 | 3 | - | - | 10 | `EXPIRED` | `EXPIRED` | 1 | no | no |
| scenario_4_negative_control | `M3->M2` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M3->M4` | no | 3 | 3 | - | - | 10 | `EXPIRED` | `EXPIRED` | 1 | no | no |
| scenario_4_negative_control | `M4->M1` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M4->M2` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_4_negative_control | `M4->M3` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_5_reversed_order | `A->B` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_5_reversed_order | `B->A` | no | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | no |
| scenario_6_common_cause | `M1->M2` | no | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | no |
| scenario_6_common_cause | `M1->M3` | no | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | YES |
| scenario_6_common_cause | `M2->M1` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_6_common_cause | `M2->M3` | no | 0 | 0 | 8 | - | - | `PROVISIONAL` | `PROVISIONAL` | 6 | YES | no |
| scenario_6_common_cause | `M3->M1` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_6_common_cause | `M3->M2` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_7_noisy | `A->B` | **YES** | 4 | 4 | 17 | - | 15 | `EXPIRED` | `EXPIRED` | 4 | no | no |
| scenario_7_noisy | `A->C` | no | 0 | 0 | 4 | - | 23 | `EXPIRED` | `EXPIRED` | 6 | no | no |
| scenario_7_noisy | `B->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_7_noisy | `B->C` | **YES** | 4 | 4 | 8 | - | 23 | `PROVISIONAL` | `CONFIRMED` | 7 | YES | no |
| scenario_7_noisy | `C->A` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |
| scenario_7_noisy | `C->B` | no | - | - | - | - | - | `NEVER_OBSERVED` | `NONE` | 0 | no | no |

---

## 4. Per-Cycle Precision / Recall Progression (CANDIDATE view)

Shows how precision and recall evolve as evidence accumulates over time windows.

| Scenario | Cycle | Events | P (CAND) | R (CAND) | F1 (CAND) | P (PROV) | R (PROV) | F1 (PROV) |
|---|---|---|---|---|---|---|---|---|
| scenario_1_chain | 0 | 3 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 1 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 2 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 3 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 4 | 3 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 5 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 6 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 7 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 8 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 9 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 10 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 11 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 12 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 13 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 14 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 15 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 16 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 17 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 18 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_1_chain | 19 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_1_chain | 20 | 2 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_1_chain | 21 | 1 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_2_branching | 0 | 3 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 1 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 2 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 3 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 4 | 3 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 5 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 6 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 7 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 8 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 9 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 10 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 11 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 12 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 13 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 14 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 15 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 16 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 17 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 18 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_2_branching | 19 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_2_branching | 20 | 3 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_3_ring | 0 | 4 | 0.600 | 1.000 | 0.750 | N/A | 0.000 | N/A |
| scenario_3_ring | 1 | 0 | 0.600 | 1.000 | 0.750 | N/A | 0.000 | N/A |
| scenario_3_ring | 2 | 4 | 0.600 | 1.000 | 0.750 | N/A | 0.000 | N/A |
| scenario_3_ring | 3 | 0 | 0.600 | 1.000 | 0.750 | N/A | 0.000 | N/A |
| scenario_3_ring | 4 | 4 | 0.600 | 1.000 | 0.750 | 0.600 | 1.000 | 0.750 |
| scenario_3_ring | 5 | 0 | 0.600 | 1.000 | 0.750 | 0.600 | 1.000 | 0.750 |
| scenario_3_ring | 6 | 4 | 0.600 | 1.000 | 0.750 | 0.600 | 1.000 | 0.750 |
| scenario_4_negative_control | 0 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 1 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 2 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 3 | 4 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 4 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 5 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 6 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 7 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 8 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 9 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 10 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 11 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 12 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 13 | 2 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 14 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 15 | 2 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 16 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 17 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 18 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 19 | 1 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 20 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 21 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 22 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 23 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 24 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 25 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 26 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 27 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 28 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 29 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 30 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 31 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 32 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 33 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 34 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 35 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 36 | 2 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 37 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 38 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 39 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 40 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 41 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 42 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 43 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 44 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 45 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 46 | 0 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_4_negative_control | 47 | 1 | N/A | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 0 | 2 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 1 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 2 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 3 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 4 | 2 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 5 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 6 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 7 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 8 | 2 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 9 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 10 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 11 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 12 | 2 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 13 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 14 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 15 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 16 | 2 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 17 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 18 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_5_reversed_order | 19 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_5_reversed_order | 20 | 2 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 0 | 3 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 1 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 2 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 3 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 4 | 3 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 5 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 6 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 7 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 8 | 3 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 9 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 10 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 11 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 12 | 3 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 13 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 14 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 15 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 16 | 3 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 17 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 18 | 0 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_6_common_cause | 19 | 0 | 0.000 | N/A | N/A | N/A | N/A | N/A |
| scenario_6_common_cause | 20 | 3 | 0.000 | N/A | N/A | 0.000 | N/A | N/A |
| scenario_7_noisy | 0 | 2 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A |
| scenario_7_noisy | 1 | 0 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A |
| scenario_7_noisy | 2 | 0 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A |
| scenario_7_noisy | 3 | 0 | 0.000 | 0.000 | 0.000 | N/A | 0.000 | N/A |
| scenario_7_noisy | 4 | 4 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 5 | 0 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 6 | 0 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 7 | 0 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_7_noisy | 8 | 3 | 0.667 | 1.000 | 0.800 | 0.500 | 0.500 | 0.500 |
| scenario_7_noisy | 9 | 2 | 0.667 | 1.000 | 0.800 | 0.500 | 0.500 | 0.500 |
| scenario_7_noisy | 10 | 0 | 0.667 | 1.000 | 0.800 | 0.500 | 0.500 | 0.500 |
| scenario_7_noisy | 11 | 2 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 12 | 2 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 13 | 0 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 14 | 0 | 0.667 | 1.000 | 0.800 | 0.000 | 0.000 | 0.000 |
| scenario_7_noisy | 15 | 0 | 0.500 | 0.500 | 0.500 | N/A | 0.000 | N/A |
| scenario_7_noisy | 16 | 3 | 0.667 | 1.000 | 0.800 | 0.500 | 0.500 | 0.500 |
| scenario_7_noisy | 17 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_7_noisy | 18 | 0 | 0.667 | 1.000 | 0.800 | 0.667 | 1.000 | 0.800 |
| scenario_7_noisy | 19 | 1 | 0.667 | 1.000 | 0.800 | N/A | 0.000 | N/A |
| scenario_7_noisy | 20 | 2 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 21 | 1 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 22 | 0 | 0.667 | 1.000 | 0.800 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 23 | 0 | 1.000 | 0.500 | 0.667 | N/A | 0.000 | N/A |
| scenario_7_noisy | 24 | 0 | 1.000 | 0.500 | 0.667 | N/A | 0.000 | N/A |
| scenario_7_noisy | 25 | 2 | 1.000 | 1.000 | 1.000 | N/A | 0.000 | N/A |
| scenario_7_noisy | 26 | 0 | 1.000 | 1.000 | 1.000 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 27 | 0 | 1.000 | 0.500 | 0.667 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 28 | 1 | 1.000 | 0.500 | 0.667 | N/A | 0.000 | N/A |
| scenario_7_noisy | 29 | 2 | 1.000 | 0.500 | 0.667 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 30 | 0 | 1.000 | 0.500 | 0.667 | 1.000 | 0.500 | 0.667 |
| scenario_7_noisy | 31 | 1 | 1.000 | 0.500 | 0.667 | 1.000 | 0.500 | 0.667 |

---

## 5. Methodological & Scientific Notes

1. **Cold Start vs. Evidence Accumulation:**
   - In Cycle 0, newly formed edges begin at `CANDIDATE` (evidence = 1).
   - Multi-cycle accumulation is required before true edges reach `PROVISIONAL` (>= 3 observations).
2. **Spurious Edge Decay in Independent Streams:**
   - Negative control edges accumulate 1-2 random coincidences and never reach `PROVISIONAL`.
   - As silent cycles accumulate, unreinforced candidate edges decay to `EXPIRED`.
3. **Transitive Shortcuts vs. Direct Connections:**
   - An edge A -> C can be proposed if delta_t = t_C - t_A <= max_delay_s (600s), even when A -> B -> C explains the delay.
   - When delay consistency is evaluated (|tau_AC - (tau_AB + tau_BC)| <= tolerance), transitive shortcuts can be identified.
   - Transitive reduction must remain an exploratory view filter: if genuine direct and indirect connections coexist (e.g. A->C direct cable + A->B->C mechanical cascade), blind topological transitive reduction would discard the genuine direct edge.
4. **Empty Ground-Truth and Empty Prediction Conventions:**
   - Precision is undefined (`None` / `N/A`) when 0 positive edges are predicted.
   - Recall is undefined (`None` / `N/A`) when 0 ground-truth edges exist (e.g. negative control, reversed temporal order, common cause).
   - An empty graph is NOT interpreted as evidence of high recall or precision. In negative-control scenarios, zero predicted edges correctly reflect zero false positives (FPR = 0.0, suppression = 1.0), while precision and recall are documented as undefined (N/A).
   - Path recall is undefined (`None` / `N/A`) when no ground-truth propagation paths exist.
5. **Integrity Boundary:**
   - All benchmark data originates from synthetic fixtures (`Provenance.SYNTHETIC`).
   - These results demonstrate software sensitivity and state-machine transitions, NOT physical industrial causality.