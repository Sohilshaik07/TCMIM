# TCMIM SWaT A4/A5 Stage 1 Detector Comparison Report (Version 2)

**Execution Date**: 2026-10-26T12:54:11.468040+00:00  
**Dataset SHA-256**: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`  
**Random Seed**: 42  
**Primary Evaluation Partition**: Windows 280–499 (N=220, 1.83 hours)  

---

## Executive Summary

This Version 2 report documents the scientific improvements implemented following the independent audit of the SWaT A4/A5 July 2019 detector comparison:
1. **CUSUM Boundary State Reset**: The sequential CUSUM detector is explicitly initialized with $S_0 = 0$ at the start of each independent evaluation partition (Pre-baseline Buffer: Windows 0–9; Baseline Calibration: Windows 10–279; Held-out Operational: Windows 280–499). Cross-partition state carryover is completely eliminated.
2. **Operational Clustered False-Alarm Metrics**: Alongside standard window-level confusion metrics, consecutive false-positive windows are aggregated into single operational alarm incidents (with positive/attack windows breaking clusters) to reflect true operator alarm loading.
3. **Reference Results Preservation**: The original experiment artifacts under `experiments/results/swat_a4a5/` and `experiments/results/swat_a4a5_detector_comparison/` remain strictly unmodified as immutable reference results.

---

## 1. Evaluation Partition Verification

The 500 contiguous sliding windows (10-second duration, 2-second stride, 80% overlap) are strictly partitioned as follows:

| Partition Name | Window Range | UTC Timestamp Span | Windows ($N$) | Ground Truth (Pos / Neg) | Operational Role |
|---|---|---|:---:|:---:|---|
| **Pre-Baseline Buffer** | Windows 0..9 | 2019-07-20T04:30:00+00:00 – 2019-07-20T04:35:00+00:00 | 10 | 0 / 10 | Diagnostic warm-up (excluded from calibration) |
| **Baseline Training Period** | Windows 10..279 | 2019-07-20T04:35:00+00:00 – 2019-07-20T06:50:00+00:00 | 270 | 0 / 270 | In-sample parameter & threshold calibration |
| **Primary Held-Out Evaluation** | Windows 280..499 | 2019-07-20T06:50:00+00:00 – 2019-07-20T08:40:00+00:00 | 220 | 66 / 154 | Out-of-sample operational evaluation |
| **Complete Mixed Timeline** | Windows 0..499 | 04:30:00 – 08:40:00 | 500 | 66 / 434 | Mixed timeline diagnostic summary |

All 6 official attack intervals (A1–A6) reside exclusively within the held-out operational partition (Windows 280–499). Zero attack-labelled windows exist in the buffer or baseline periods.

---

## 2. Before-and-After Comparison of CUSUM State Correction

### Mathematical Implementation and Boundary Behavior
In Version 1, CUSUM recursion $S_t = \max(0, S_{t-1} + z_t - k)$ was executed continuously across all 500 windows:
- At Window 9 (end of pre-baseline buffer), accumulated drift reached $S_9 = 2.769$. This non-zero state entered Window 10 (baseline training).
- At Window 279 (end of baseline training), the state stood at $S_{279} = 0.841$. This entered Window 280 (held-out evaluation).

In Version 2, the CUSUM state is explicitly initialized to $S_0 = 0.0$ at the first window of each partition:
- Buffer (w=0): $S_0 = 0.0$.
- Baseline (w=10): $S_{10} = 0.0$ (independent of buffer).
- Held-out Evaluation (w=280): $S_{280} = 0.0$ (independent of baseline).

### Empirical Impact on Detection Performance
As shown below, the partition reset produces **empirically identical held-out metrics** to the continuous run:

| Metric | Version 1 (Continuous) | Version 2 (Partition Reset) | Metric Difference ($\Delta$) | Explanation |
|---|:---:|:---:|:---:|---|
| **Held-Out TP** | 8 | 8 | 0 | Drift decays to zero before first attack |
| **Held-Out FP** | 20 | 20 | 0 | Window 280 $S=0$ vs $0.40$ decays by window 282 |
| **Held-Out TN** | 134 | 134 | 0 | No baseline drift affects later windows |
| **Held-Out FN** | 58 | 58 | 0 | Identical alarms |
| **Accuracy** | 0.6455 | 0.6455 | 0.0000 | Invariant |
| **Precision** | 0.2857 | 0.2857 | 0.0000 | Invariant |
| **Recall** | 0.1212 | 0.1212 | 0.0000 | Invariant |
| **F1 Score** | 0.1702 | 0.1702 | 0.0000 | Invariant |
| **FPR** | 0.1299 | 0.1299 | 0.0000 | Invariant |
| **Episode Detection** | 3 / 6 (50.0%) | 3 / 6 (50.0%) | 0.0% | Invariant |
| **Mean Start Delay** | 114.7 s | 114.7 s | 0.0 s | Invariant |

**Scientific Rationale**:
The small positive state entering held-out evaluation in continuous mode ($S_{280} = \max(0, 0.8413 + 0.3592 - 0.7977) = 0.4028$) decayed to $0.0$ within two quiet operational windows (by Window 282). The first attack (A1) does not begin until Window 316. By Window 316, both continuous and reset states had decayed to $0.0$ for over 30 windows. 

> [!IMPORTANT]
> The CUSUM state reset is a **boundary-consistency correction**, not an optimization. We do not claim that resetting state improves detector accuracy. It guarantees that the held-out operational evaluation is mathematically independent of baseline in-sample sequences.

---

## 3. Window-Level vs. Clustered Operational False-Alarm Metrics

### Clustering Methodology and Operational Definition
Standard window-level FPR treats each 10-second sliding window independently. In industrial operations, an alarm that persists across consecutive sliding windows represents a single sustained alert episode rather than multiple independent alarms.
- **False-Positive Window**: A window $w$ where prediction is anomalous ($\hat{y}_w = 1$) but ground truth is normal ($y_w = 0$).
- **Clustered False-Alarm Incident**: A maximal contiguous sequence of adjacent false-positive windows: $[w_i, w_{i+1}, \dots, w_{i+m}]$.
- **Cluster Break Condition**: An incident is terminated when a window has $\hat{y} = 0$ (detector returns to normal) OR $y = 1$ (an attack occurs).
- **Time Convention**: Evaluated over 220 operational windows spanning 1.8333 hours (6,600 seconds).

### Comprehensive Comparative Results on Held-Out Operational Partition

| Detector | Model Family | Baseline In-Sample FPR | Held-Out FP Windows | FP Windows / Hr | Held-Out Clustered Incidents | Clustered Incidents / Hr | Compression Ratio | Mean Run Length (Windows) |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Isolation Forest (Existing)** | Unsupervised Tree Ensemble | 0.0519 (14/270) | 11 | 6.00 | **5** | **2.73** | 54.5% | 2.2 |
| **CUSUM (Partition Reset)** | Sequential Change-Point | 0.0037 (1/270) | 20 | 10.91 | **16** | **8.73** | 20.0% | 1.25 |
| **Per-Channel Max-Z (Calibrated)** | Extreme Value Envelope | 0.0519 (14/270) | 102 | 55.64 | **9** | **4.91** | 91.2% | 11.33 |
| **Per-Channel Shewhart (Fixed 3$\sigma$)** | Univariate SPC | 0.3852 (104/270) | 118 | 64.36 | **14** | **7.64** | 88.1% | 8.43 |
| *Zero-Information Null* | Baseline Reference | 0.0000 (0/270) | 0 | 0.00 | 0 | 0.00 | 0.0% | 0.0 |

### Key Operational Insights
1. **Isolation Forest has the lowest operational alarm rate**: At 2.73 clustered incidents/hour, Isolation Forest produces the quietest operational behavior, triggering only 5 distinct false-alarm events over nearly 2 hours.
2. **Extreme Value Clustering in Per-Channel Detectors**: Per-channel Max-Z triggers 102 false-positive windows (55.6 windows/hr), which looks severe at the window level. However, clustering reveals that these occur in just 9 sustained incidents with an average duration of 11.3 consecutive windows (~32 seconds). These persistent runs are driven by static sensor offsets on non-attack tags (e.g., `AIT402`, `AIT502`).
3. **CUSUM Transient Spikes**: CUSUM false alarms are brief and fragmented (mean run length 1.25 windows), leading to a higher incident rate (8.73 incidents/hr) despite having only 20 FP windows.

---

## 4. Full Comparative Performance Matrix (Held-Out Windows 280–499)

| Metric | Isolation Forest | CUSUM (Reset) | Per-Channel Max-Z | Per-Channel Shewhart | Null Classifier |
|---|:---:|:---:|:---:|:---:|:---:|
| **True Positives (TP)** | 6 | 8 | 57 | 60 | 0 |
| **False Positives (FP)** | 11 | 20 | 102 | 118 | 0 |
| **True Negatives (TN)** | 143 | 134 | 52 | 36 | 154 |
| **False Negatives (FN)** | 60 | 58 | 9 | 6 | 66 |
| **Accuracy** | 0.6773 | 0.6455 | 0.4955 | 0.4364 | **0.7000** |
| **Precision** | 0.3529 | 0.2857 | **0.3585** | 0.3371 | 0.0000 |
| **Recall** | 0.0909 | 0.1212 | 0.8636 | **0.9091** | 0.0000 |
| **F1 Score** | 0.1446 | 0.1702 | **0.5067** | 0.4918 | 0.0000 |
| **Window-Level FPR** | **0.0714** | 0.1299 | 0.6623 | 0.7662 | 0.0000 |
| **FP Windows / Hr** | **6.00** | 10.91 | 55.64 | 64.36 | 0.00 |
| **Clustered Alarm Incidents** | **5** | 16 | 9 | 14 | 0 |
| **Incidents / Hr** | **2.73** | 8.73 | 4.91 | 7.64 | 0.00 |
| **Episode Detection Rate** | 4 / 6 (66.7%) | 3 / 6 (50.0%) | **6 / 6 (100.0%)** | **6 / 6 (100.0%)** | 0 / 6 (0.0%) |
| **Mean Start Delay** | 296.8 s | 114.7 s | **25.0 s** | **25.0 s** | N/A |
| **Mean End Delay** | 326.8 s | 144.7 s | **40.2 s** | **40.2 s** | N/A |

> [!WARNING]
> **The Accuracy Paradox**: All four detectors achieve accuracy lower than the 70.00% accuracy of the zero-information null classifier (which predicts normal for every window). Point accuracy is dominated by class imbalance (70% normal, 30% attack) and is uninformative for evaluating anomaly detectors in this benchmark.

---

## 5. Attack Episode Detection and Delay Analysis

An episode is marked detected if at least one window overlapping the official attack interval triggers an alarm.

| Method | Attack | Target Tags | Overlap Windows | Flagged Windows | Detected? | Start-Based Delay | End-Based Delay | Timing Classification |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|---|
| **Isolation Forest** | A1 | `FIT401` | 5 | 0 | NO | nan s | nan s | Undetected |
| **Isolation Forest** | A2 | `LIT301` | 10 | 0 | NO | nan s | nan s | Undetected |
| **Isolation Forest** | A3 | `P601` | 9 | 1 | **YES** | 123.0 s | 153.0 s | During attack |
| **Isolation Forest** | A4 | `MV201;P101` | 16 | 1 | **YES** | 340.0 s | 370.0 s | During attack |
| **Isolation Forest** | A5 | `MV501` | 4 | 3 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| **Isolation Forest** | A6 | `P301` | 28 | 1 | **YES** | 724.0 s | 754.0 s | During attack |
| **CUSUM (Reset)** | A1 | `FIT401` | 5 | 0 | NO | nan s | nan s | Undetected |
| **CUSUM (Reset)** | A2 | `LIT301` | 10 | 0 | NO | nan s | nan s | Undetected |
| **CUSUM (Reset)** | A3 | `P601` | 9 | 0 | NO | nan s | nan s | Undetected |
| **CUSUM (Reset)** | A4 | `MV201;P101` | 16 | 1 | **YES** | 220.0 s | 250.0 s | During attack |
| **CUSUM (Reset)** | A5 | `MV501` | 4 | 3 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| **CUSUM (Reset)** | A6 | `P301` | 28 | 4 | **YES** | 124.0 s | 154.0 s | During attack |
| **Per-Channel Max-Z** | A1 | `FIT401` | 5 | 2 | **YES** | 0.0 s | 14.0 s | Instantaneous |
| **Per-Channel Max-Z** | A2 | `LIT301` | 10 | 2 | **YES** | 150.0 s | 180.0 s | During attack |
| **Per-Channel Max-Z** | A3 | `P601` | 9 | 9 | **YES** | 0.0 s | 3.0 s | Instantaneous |
| **Per-Channel Max-Z** | A4 | `MV201;P101` | 16 | 16 | **YES** | 0.0 s | 10.0 s | Instantaneous |
| **Per-Channel Max-Z** | A5 | `MV501` | 4 | 4 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| **Per-Channel Max-Z** | A6 | `P301` | 28 | 28 | **YES** | 0.0 s | 4.0 s | Instantaneous |
| **Per-Channel Shewhart**| A1 | `FIT401` | 5 | 5 | **YES** | 0.0 s | 14.0 s | Instantaneous |
| **Per-Channel Shewhart**| A2 | `LIT301` | 10 | 3 | **YES** | 150.0 s | 180.0 s | During attack |
| **Per-Channel Shewhart**| A3 | `P601` | 9 | 9 | **YES** | 0.0 s | 3.0 s | Instantaneous |
| **Per-Channel Shewhart**| A4 | `MV201;P101` | 16 | 16 | **YES** | 0.0 s | 10.0 s | Instantaneous |
| **Per-Channel Shewhart**| A5 | `MV501` | 4 | 4 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| **Per-Channel Shewhart**| A6 | `P301` | 28 | 28 | **YES** | 0.0 s | 4.0 s | Instantaneous |

---

## 6. Scientific Constraints and Future Research Guidance

> [!IMPORTANT]
> **Mandatory Scientific Rules for Citing These Findings:**
> 1. **Temporal Overlap $\neq$ Causal Attribution**: Observing an alarm during an attack window does not demonstrate that the detector detected the physical mechanism of that attack. Channel diagnostics show that alarms often trigger on auxiliary sensors (`AIT402`, `AIT502`) rather than attack target actuators (`P601`, `FIT401`).
> 2. **No CRI Validity Claims**: The Cascade Risk Index (CRI) was not evaluated in Stage 1. No claims regarding CRI predictive accuracy or propagation graphs are justified by this detector comparison.
> 3. **Accuracy Reporting**: Authors must not cite 81% or 67% accuracy in isolation without stating that the zero-information null classifier achieves 86.8% across the full timeline and 70.0% on held-out operational data.
