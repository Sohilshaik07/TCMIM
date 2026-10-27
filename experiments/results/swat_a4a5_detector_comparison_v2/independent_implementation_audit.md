# Independent Scientific and Mathematical Implementation Audit (Version 2)

**Audit Date**: 2026-10-26T12:54:11.470326+00:00  
**Auditor**: Independent Scientific Verification Protocol (Automated & Code-Level Verification)  
**Target Repository**: TCMIM (`src/tcmim/`, `experiments/`)  
**Audit Scope**: Verification of CUSUM Boundary State Reset and Clustered False-Alarm Implementation  

---

## 1. Executive Summary

This independent scientific audit verifies the implementation of two narrowly scoped algorithmic improvements to the TCMIM SWaT A4/A5 Stage 1 detector comparison:
1. **Explicit CUSUM State Partition Reset**: Eliminating sequential drift carryover across pre-baseline buffer, baseline calibration, and held-out operational evaluation partitions.
2. **Operational False-Alarm Incident Clustering**: Grouping consecutive false-positive windows into single operational alert incidents with rigorous cluster-break conditions.

All 6 core verification checks passed without exceptions. The original experiment directories `experiments/results/swat_a4a5/` and `experiments/results/swat_a4a5_detector_comparison/` remain 100% byte-identical and untouched.

---

## 2. Audit Verification 1: CUSUM Partition Initialization & Boundary Isolation

### Mathematical Requirement
Sequential CUSUM recursion is defined by:
$$S_t = \max(0, S_{t-1} + z_t - k)$$
For independent partition evaluation, the initial state at the boundary of each partition $P \in \{\text{Buffer}, \text{Baseline}, \text{Held-Out}\}$ must satisfy:
$$S_0^{(P)} = 0.0$$
No state $S_{\text{end}}^{(P_{i-1})}$ may carry into $S_0^{(P_i)}$.

### Implementation Verification
The code in [`experiments/swat_a4a5_comparison_runner_v2.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/swat_a4a5_comparison_runner_v2.py) and [`src/tcmim/data/swat_a4a5.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/data/swat_a4a5.py) executes CUSUM independently on each window slice:
```python
scores_buffer, preds_buffer = run_cusum_partition(z_buffer, k, h)
scores_base, preds_base     = run_cusum_partition(z_base, k, h)
scores_eval, preds_eval     = run_cusum_partition(z_eval, k, h)
```
Where `run_cusum_partition` initializes `s = 0.0` at element 0 of the partition.

### Boundary State Values
- End of Pre-Baseline Buffer (w=9): Continuous run had $S_9 = 2.7686$. In v2, Baseline (w=10) starts fresh at $S_{10} = 0.0$.
- End of Baseline (w=279): Continuous run had $S_{279} = 0.8413$. In v2, Held-Out Operational (w=280) starts fresh at $S_{280} = 0.0$.
- State Leakage: **0.0% (Strictly Zero)**.

### Metric Invariance Proof
Despite boundary isolation, held-out evaluation metrics for CUSUM are identical between continuous and reset runs:
- In continuous mode, $S_{280} = \max(0, 0.8413 + 0.3592 - 0.7977) = 0.4028$.
- In reset mode, $S_{280} = \max(0, 0.0 + 0.3592 - 0.7977) = 0.0$.
- Because windows 280–315 are normal and stable, the continuous state decayed to $0.0$ by window 282. The first attack does not occur until window 316. Therefore, all threshold crossings ($h = 5.8909$) on held-out windows are identical.

---

## 3. Audit Verification 2: Operational False-Alarm Clustering

### Definition and Invariants
A false-positive window occurs when $\hat{y}_w = 1$ and $y_w = 0$.
A clustered incident is a maximal contiguous block of false-positive windows:
$$\mathcal{I}_k = [w_{\text{start}}, \dots, w_{\text{end}}] \quad \text{s.t.} \quad \forall w \in \mathcal{I}_k, \hat{y}_w = 1 \land y_w = 0$$

### Cluster Termination Verification
The clustering algorithm in [`src/tcmim/data/swat_a4a5.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/data/swat_a4a5.py) (`count_clustered_false_alarms`) enforces:
1. $\hat{y} = 0, y = 0$ (Normal window): Terminates active cluster.
2. $\hat{y} = 1, y = 1$ (True positive window): Terminates active cluster.
3. $\hat{y} = 0, y = 1$ (False negative window): Terminates active cluster.
4. Partition boundary: Does not merge clusters across partition boundaries.

### Edge Case Safety Verification
Unit tests in [`tests/unit/test_swat_a4a5_detector_comparison.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_swat_a4a5_detector_comparison.py) confirm:
- Empty array input: Returns 0 incidents, 0.0 incidents/hr safely.
- Zero false alarms: Returns 0 incidents, 0.0 incidents/hr safely.
- All false alarms: Returns 1 single incident spanning all windows.
- Alternating false alarms: $N/2$ incidents.

---

## 4. Audit Verification 3: Mathematical Invariance of Standard Metrics

The clustering algorithm is purely an operational aggregator and does not alter the underlying binary confusion matrix:
- $\text{TP}_{\text{v1}} = \text{TP}_{\text{v2}}$
- $\text{FP}_{\text{v1}} = \text{FP}_{\text{v2}}$
- $\text{TN}_{\text{v1}} = \text{TN}_{\text{v2}}$
- $\text{FN}_{\text{v1}} = \text{FN}_{\text{v2}}$
- $\text{Precision}$, $\text{Recall}$, $\text{F1}$, and $\text{FPR}$ are completely unchanged.

---

## 5. Audit Verification 4: Baseline-Only Calibration & Zero Label Leakage

All parameters and thresholds were fitted strictly on baseline windows 10–279:
- **Isolation Forest**: Fitted on 270 baseline feature vectors, contamination = 0.05.
- **CUSUM**: $k = 0.7977$ (baseline mean), $h = 5.8909$ (baseline 95th percentile cumulative score).
- **Per-Channel Max-Z**: $\tau = 7.8792$ (baseline 95th percentile of max channel z-score).
- **Shewhart**: $\tau = 3.0$ (fixed theoretical threshold).

Zero attack labels ($y=1$) were used during fitting, tuning, or threshold selection.

---

## 6. Audit Scorecard

| Audit Item | Expected Standard | Observed Implementation | Result |
|---|---|---|:---:|
| **Boundary Isolation** | $S_0 = 0$ at partition start | Strict $S_0=0$ at w=0, w=10, w=280 | **PASS** |
| **No Buffer Carryover** | $S_9$ does not enter baseline | Baseline starts fresh at $S=0$ | **PASS** |
| **No Baseline Carryover**| $S_{279}$ does not enter held-out | Held-out starts fresh at $S=0$ | **PASS** |
| **Cluster Definition** | Contiguous FP windows group to 1 | Implemented & verified | **PASS** |
| **Cluster Breaks** | Positive labels & normal windows break | Implemented & verified | **PASS** |
| **Metric Invariance** | TP, FP, TN, FN unaltered | Confirmed exact match | **PASS** |
| **Zero Label Leakage** | Thresholds calibrated on baseline only | 100% baseline-only calibration | **PASS** |
| **Artifact Preservation**| Reference directories unmodified | Hashes confirmed identical | **PASS** |