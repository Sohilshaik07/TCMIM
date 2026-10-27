# TCMIM SWaT A4/A5 Stage 1 Anomaly Detection: Rigorous Scientific Evaluation Audit

**Audit Type**: Read-Only Independent Scientific Evaluation & Diagnostic Audit  
**Target Repository**: `TCMIM: Temporal Cross-Machine Influence Modeling and Cascade Risk Estimation`  
**Dataset**: SWaT A4/A5 (July 20, 2019) Operational Dataset (`SWaT_dataset_Jul 19 v2.xlsx`)  
**Audit Report Path**: `experiments/results/swat_a4a5/stage1_evaluation_audit.md`  
**Audit Date**: October 26, 2026  
**Auditor**: Senior Research Engineer & Scientific Verification Auditor  
**Status**: **VERIFIED WITH SCIENTIFIC CORRECTIONS**

---

## Executive Summary

This diagnostic audit provides an honest, mathematically rigorous, out-of-sample re-evaluation of the completed Stage 1 anomaly detection experiment on the SWaT A4/A5 July 2019 dataset. 

The original experiment report (`experiment_report.md`) reported an aggregate accuracy of **81.00%**, False Positive Rate of **8.06%**, and an episode detection rate of **66.67%** (4 out of 6 attacks). 

This audit reveals three critical scientific findings that qualify and correct those claims:
1. **In-Sample Evaluation Conflation**: The reported 81.00% accuracy and 8.06% FPR are heavily padded because **54.0% of the evaluation windows (270 out of 500) were the exact training data used to fit the Isolation Forest model**. When evaluated strictly out-of-sample ($N=230$), **accuracy drops to 64.78%**, the **False Positive Rate rises to 12.80%**, and **Precision is 22.22%**.
2. **The Accuracy Paradox**: Because 86.80% of all windows in the session are normal, a zero-information null classifier predicting "Normal" for all windows achieves **86.80% accuracy**, which outperforms the trained Isolation Forest model (81.00%). Overall accuracy is completely uninformative for this imbalanced benchmark.
3. **Actuator Exclusion & Secondary Hydraulic Coupling**: Two target actuators (`P601` in Attack A3 and `MV501` in Attack A5) were **completely excluded from the model feature matrix** during baseline fitting because they exhibited zero variance during normal operation. The detection of A5 was driven by a massive secondary pressure surge in downstream sensor `PIT502` ($z = 1309.20$) and flow drops in `FIT501`/`FIT401`, not by direct actuator state observation. Furthermore, episode detection reflects plant-wide temporal co-occurrence, not target-channel attribution.

---

## 1. Dataset, Protocol, and Evaluation Partition

### 1.1 Source Telemetry and Baseline Configuration
- **File**: `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx` (Sheet: `MST v2`)
- **Total Duration**: 14,996 records at nominal 1.0 Hz cadence (14,999 s $\approx$ 4.17 hours, from `04:30:00` to `08:39:59.004013` UTC).
- **Windowing**: 500 contiguous non-overlapping sliding windows ($W = 30\text{ s}$, $S = 30\text{ s}$, min samples = 2, max gap = 15 s). All 500 windows are eligible.
- **Protocol**: Protocol A (Supervised Normal Baseline Slice).
  - Configured normal period: `2019-07-20 04:35:00+00:00` to `2019-07-20 06:50:00+00:00` UTC (8,100 s span, 8,096 rows).
  - Pre-start buffer: `2019-07-20 04:30:00+00:00` to `2019-07-20 04:35:00+00:00` UTC (300 rows, 10 windows).

### 1.2 Evaluation Partition Breakdown

To prevent ambiguity between chronological index slicing and actual training baseline timestamps, metrics are independently recomputed across all relevant partitions:

| Partition Name | Window Range | UTC Timestamp Span | Sample Count ($N$) | Ground Truth (Pos / Neg) | Status / Role |
|---|---|---|:---:|:---:|---|
| **Baseline Training Period** | Windows 10..279 | 04:35:00 – 06:50:00 | 270 | 0 / 270 | **In-Sample** (Used to fit Isolation Forest) |
| **Pre-Start Buffer** | Windows 0..9 | 04:30:00 – 04:35:00 | 10 | 0 / 10 | **Out-of-Sample** (Plant warm-up / transient) |
| **Operational & Attack Period** | Windows 280..499 | 06:50:00 – 08:40:00 | 220 | 66 / 154 | **Out-of-Sample** (Unseen operation + 6 attacks) |
| **Total Unseen (Out-of-Sample)** | Windows [0..9 + 280..499] | Mixed (Pre + Post) | 230 | 66 / 164 | **Pure Out-of-Sample Evaluation** |
| **Index Partition [0..269]** | Windows 0..269 | 04:30:00 – 06:45:00 | 270 | 0 / 270 | Mixed (10 pre-start + 260 baseline) |
| **Index Partition [270..499]**| Windows 270..499 | 06:45:00 – 08:40:00 | 230 | 66 / 164 | Mixed (10 baseline + 220 post) |
| **Complete Timeline** | Windows 0..499 | 04:30:00 – 08:40:00 | 500 | 66 / 434 | **Mixed Timeline Summary** (54% in-sample) |

---

## 2. Independent Metric Calculations by Partition

### 2.1 Confusion Matrices and Classification Performance

$$\text{Accuracy} = \frac{\text{TP} + \text{TN}}{N}, \quad \text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}, \quad \text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}, \quad \text{FPR} = \frac{\text{FP}}{\text{FP} + \text{TN}}$$

| Metric | In-Sample Baseline (Win 10..279, N=270) | Out-of-Sample Pure (Win 0..9 + 280..499, N=230) | Out-of-Sample Post-Only (Win 280..499, N=220) | Naive Index Split (Win 270..499, N=230) | Complete Timeline (Win 0..499, N=500) |
|---|:---:|:---:|:---:|:---:|:---:|
| **True Positives (TP)** | 0 | **6** | **6** | **6** | **6** |
| **False Positives (FP)** | 14 | **21** | **11** | **12** | **35** |
| **True Negatives (TN)** | 256 | **143** | **143** | **152** | **399** |
| **False Negatives (FN)** | 0 | **60** | **60** | **60** | **60** |
| **Accuracy** | 94.81% | **64.78%** | **67.73%** | **68.70%** | **81.00%** |
| **Precision** | 0.00% (no pos) | **22.22%** | **35.29%** | **33.33%** | **14.63%** |
| **Recall** | 0.00% (no pos) | **9.09%** | **9.09%** | **9.09%** | **9.09%** |
| **F1 Score** | Undefined | **12.90%** | **14.46%** | **14.29%** | **11.21%** |
| **False Positive Rate (FPR)** | **5.19%** | **12.80%** | **7.14%** | **7.32%** | **8.06%** |
| **Null Classifier Accuracy** | 100.00% | **71.30%** | **70.00%** | **71.30%** | **86.80%** |

### 2.2 Key Takeaways from Independent Metric Calculations

1. **In-Sample Nominal Fit**: In the 270 baseline windows used to fit the model, $\text{FPR} = 14 / 270 = \mathbf{5.19\%}$. This reflects scikit-learn's internal threshold setting calibrated to `contamination = 0.05` ($5\%$).
2. **Out-of-Sample False Positive Inflation**: In the 230 unseen windows, $\text{FPR} = 21 / 164 = \mathbf{12.80\%}$—more than **2.4 times** the nominal contamination rate.
3. **Pre-Start Transient Sensitivity**: In the 10 pre-start buffer windows (Windows 0..9, 04:30 to 04:35 UTC), **10 out of 10 windows triggered alarms** ($\text{FP} = 10$, $\text{FPR} = 100\%$). Because the model was fitted on steady-state operation post-04:35, transient warm-up telemetry falls far outside the baseline manifold.
4. **Accuracy Fallacy**: On the complete timeline, the model achieves 81.00% accuracy. However, predicting all windows as "Normal" yields **86.80% accuracy**. In the pure out-of-sample evaluation, the null classifier achieves **71.30% accuracy** versus the model's **64.78%**. Overall accuracy is an uninformative metric for this dataset.

---

## 3. Episode-Detection Methodology Audit

### 3.1 Distinction Between Evaluation Levels

To prevent scientific misrepresentation, three distinct evaluation levels must be strictly separated:
- **Level 1: Window-Level Classification**: Binary classification of individual 30 s windows. Evaluates continuous anomaly persistence. (Result: Recall = 9.09%, 6/66).
- **Level 2: Episode-Level Temporal-Overlap Detection**: An attack episode is marked detected if **at least one** overlapping window triggers an alarm. Evaluates early-warning operational alerting. (Result: Detection Rate = 66.67%, 4/6).
- **Level 3: Target-Channel Attribution**: Verifying that the alarm was specifically caused by anomalous residuals in the targeted component or its direct causal graph neighbors. (Result: **NOT IMPLEMENTED** in the current Isolation Forest pipeline).

### 3.2 Audit of the Six Official Attack Intervals

All attack intervals are verified from the official schedule (`SWaT data collection_20-07-2019 v2.pdf`), converted from SGT (GMT+8) to UTC using closed intervals $[t_{\text{start}}, t_{\text{end}}]$.

Two delay conventions are reported:
- **Start-Based Delay Convention**: $\Delta t_{\text{start}} = \max\left(0.0, t_{\text{start}}(w_{\text{first\_alarm}}) - t_{\text{start}}(\text{Attack})\right)$. (Matches `metrics.json`).
- **End-Based Delay Convention**: $\Delta t_{\text{end}} = \max\left(0.0, t_{\text{end}}(w_{\text{first\_alarm}}) - t_{\text{start}}(\text{Attack})\right)$. (Represents the earliest timestamp at which a 30s window has completed and can be scored in online streaming).

| Attack ID | Target Channel(s) | Stage | UTC Interval | Duration | Overlapping Windows (Any / Maj) | Flagged Windows | First Alarm Window & Start (UTC) | Start-Based Delay | End-Based Delay | Alarm Timing Relative to Attack | Target Attribution Evaluated? |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **A1** | `FIT401` | P4 | 07:08:46 – 07:10:31 | 105 s | 5 / 3 | 0 / 5 (0.0%) | None | N/A | N/A | No alarm | No |
| **A2** | `LIT301` | P3 | 07:15:00 – 07:19:32 | 272 s | 10 / 9 | 0 / 10 (0.0%) | None | N/A | N/A | No alarm | No |
| **A3** | `P601` | P6 | 07:26:57 – 07:30:48 | 231 s | 9 / 8 | 1 / 9 (11.1%) | `SWAT_A4A5_w_000358` (07:29:00) | **123.0 s** | **153.0 s** | During | **No** (P601 excluded from model) |
| **A4** | `MV201`, `P101` | P2, P1 | 07:38:50 – 07:46:20 | 450 s | 16 / 15 | 1 / 16 (6.3%) | `SWAT_A4A5_w_000389` (07:44:30) | **340.0 s** | **370.0 s** | During | **No** (Global iForest score) |
| **A5** | `MV501` | P5 | 07:54:00 – 07:56:00 | 120 s | 4 / 4 | 3 / 4 (75.0%) | `SWAT_A4A5_w_000408` (07:54:00) | **0.0 s** | **30.0 s** | Instantaneous | **No** (MV501 excluded from model) |
| **A6** | `P301` | P3 | 08:02:56 – 08:16:18 | 802 s | 28 / 27 | 1 / 28 (3.6%) | `SWAT_A4A5_w_000450` (08:15:00) | **724.0 s** | **754.0 s** | During (+12 min) | **No** (Global iForest score) |

**Episode Detection Summary**:
- **Detected Episodes**: 4 out of 6 (**66.67%**)
- **Mean Start-Based Delay (Detected)**: $(123.0 + 340.0 + 0.0 + 724.0) / 4 = \mathbf{296.75\text{ s}}$ (~4.9 minutes)
- **Mean End-Based Delay (Detected)**: $(153.0 + 370.0 + 30.0 + 754.0) / 4 = \mathbf{326.75\text{ s}}$ (~5.4 minutes)

---

## 4. Anomaly Score Diagnostics and Root-Cause Analysis

### 4.1 Detector Score Distributions Across Operational Regimes

In scikit-learn's `IsolationForest`, the anomaly score is computed via `decision_function(X)`. Values $< 0.0$ are classified as anomalies; lower values indicate more severe statistical deviation from the baseline.

| Operational Regime | Window Count | Min Score | Mean Score | Median Score | Max Score | Alarms Flagged |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Baseline Normal (04:35 – 06:50 UTC)** | 270 | -0.0747 | +0.1029 | +0.1084 | +0.1702 | 14 (5.19%) |
| **Pre-Start Buffer (04:30 – 04:35 UTC)** | 10 | -0.0771 | -0.0547 | -0.0545 | -0.0334 | 10 (100.0%) |
| **Post-Baseline Normal (Unattacked)** | 154 | -0.1071 | +0.0577 | +0.0612 | +0.1122 | 11 (7.14%) |
| **Attack A1 (`FIT401`)** | 5 | +0.0197 | +0.0582 | +0.0601 | +0.0901 | 0 (0.0%) |
| **Attack A2 (`LIT301`)** | 10 | +0.0076 | +0.0552 | +0.0574 | +0.0863 | 0 (0.0%) |
| **Attack A3 (`P601`)** | 9 | -0.0179 | +0.0356 | +0.0412 | +0.0601 | 1 (11.1%) |
| **Attack A4 (`MV201`, `P101`)** | 16 | -0.0171 | +0.0267 | +0.0289 | +0.0512 | 1 (6.3%) |
| **Attack A5 (`MV501`)** | 4 | -0.0602 | -0.0227 | -0.0315 | +0.0485 | 3 (75.0%) |
| **Attack A6 (`P301`)** | 28 | -0.0081 | +0.0529 | +0.0547 | +0.0719 | 1 (3.6%) |

### 4.2 Diagnostic Inspection of Feature Extraction and Target Actuators

Inspection of `IsolationForestAnomalyDetector.fit()` reveals that out of 335 candidate features extracted across 77 channels, **187 features were excluded** due to zero variance ($\text{std} < 10^{-12}$) during the 2.25-hour baseline period, leaving 148 fitted features.

#### Feature Inclusion Status for Attack Target Channels:
- **`FIT401` (A1)**: Included (`FIT401__mean`, `FIT401__std`).
- **`LIT301` (A2)**: Included (`LIT301__mean`, `LIT301__std`).
- **`P601` (A3)**: **EXCLUDED**. All 5 features (`duty_cycle`, `first_state`, `last_state`, `mode_state`, `n_transitions`) dropped because pump `P601` remained constantly OFF throughout the baseline.
- **`MV201` (A4)**: Included (cycling valve).
- **`P101` (A4)**: Included (cycling pump).
- **`MV501` (A5)**: **EXCLUDED**. All 5 features dropped because valve `MV501` remained constantly OPEN throughout the baseline.
- **`P301` (A6)**: Included (cycling pump).

### 4.3 Root-Cause Diagnoses by Attack

#### Attack A1 (`FIT401`, Missed — Verified Finding):
- **Documented Action**: "Spoof value from 0.8 to 0.5".
- **Observed Telemetry**: During the official interval (07:08:46 to 07:10:31 UTC), raw `FIT401` recorded a mean of 0.800 (min = 0.796, max = 0.805). In the baseline, `FIT401` recorded a mean of 0.798 (min = 0.792, max = 0.805).
- **Finding**: **The spoofed value of 0.5 was never logged in the historian**. The physical or logged telemetry remained indistinguishable from baseline flow. The detector scored all windows between +0.0197 and +0.0901, correctly reflecting nominal telemetry.

#### Attack A2 (`LIT301`, Missed — Verified Finding):
- **Documented Action**: "Spoof value from 835 to 1024 mm".
- **Observed Telemetry**: `LIT301` reached 1024.0 mm during the attack. However, during normal baseline operation, `LIT301` naturally cycles between 792.5 mm and 1010.5 mm (mean = 931.0 mm).
- **Finding**: A level of 1024 mm is only 13.5 mm above the normal operating ceiling. Across a 148-dimensional multivariate tree space, a 1.3% deviation in a single level sensor is insufficient to push the Isolation Forest decision function below 0.0 (scores remained between +0.0076 and +0.0863).

#### Attack A3 (`P601`, Detected at t+123 s — Code-Derived Finding & Hypothesis):
- **Observed Telemetry**: Pump `P601` switched from 1.0 (OFF) to 2.0 (ON). However, `P601` was **excluded from the model**.
- **Mechanism**: The single alarm at window 358 (07:29:00 UTC, score = -0.0179) was driven by secondary process drift in Stage 2 chemical analyzer `AIT201` ($z = 48.63$, dropping from 143.85 to 119.07). Whether this chemical drift was physically caused by dechlorination pump recycle or background drift remains an unverified hypothesis.

#### Attack A4 (`MV201`, `P101`, Detected at t+340 s — Code-Derived Finding):
- **Observed Telemetry**: `MV201` and `P101` were both active features in the model.
- **Mechanism**: Both actuators cycled during normal baseline, so turning them ON/OPEN was not immediately anomalous in isolation. An alarm triggered only at 07:44:30 UTC (window 389, score = -0.0171), over 5.5 minutes after initiation, when the combined inflow altered Stage 2/3 hydraulic balances.

#### Attack A5 (`MV501`, Detected at t+0 s — Verified Finding):
- **Observed Telemetry**: Valve `MV501` closed. `MV501` was **excluded from the model**.
- **Mechanism**: Closing the RO reject valve caused an immediate, massive physical hydraulic surge in downstream reverse osmosis pressure sensor `PIT502` ($z = 1309.20$, soaring from baseline mean of 2.95 up to 92.31 psi) and sharp flow drops in `FIT501` ($z = 105.54$) and `FIT401` ($z = 78.21$). Three of the four overlapping windows triggered severe anomaly scores (down to -0.0602). Detection was instantaneous and robust due to extreme secondary physical coupling.

#### Attack A6 (`P301`, Detected at t+724 s — Scientific Caveat & Hypothesis):
- **Observed Telemetry**: `P301` switched from ON to OFF. Attack duration was 802 seconds (28 windows).
- **Mechanism**: Only 1 out of 28 windows triggered an alarm (`w_000450` at 08:15:00 UTC, score = -0.0081, barely below 0.0). The delay was over 12 minutes.
- **Statistical Precaution**: Because the background false alarm rate in post-baseline data is 7.14% (and 12.80% overall out-of-sample), the expected number of random false alarms across 28 unattacked windows is $28 \times 0.0714 \approx 2.0$ (or $28 \times 0.1280 \approx 3.58$). Attributing this single late alarm to `P301` rather than random background drift is statistically unverified.

---

## 5. Threshold and Baseline Limitations

### 5.1 Misinterpretation of Nominal Contamination Rate
- In `IsolationForest(contamination=0.05)`, the parameter `contamination` controls the training quantile threshold `offset_` applied to `decision_function`.
- By mathematical definition, approximately 5% of training points will be assigned scores $< 0.0$ (observed in-sample FPR: **5.19%**).
- **Critical Risk**: Treating `contamination = 0.05` as an operational guarantee of a 5% false alarm rate in deployment is mathematically invalid. In the presence of unmodeled operational variation, seasonal/ambient drift, or pre-start transitions, the observed out-of-sample FPR was **12.80%**, with 100% false alarms during plant start-up.

### 5.2 Single-Session Duration Constraints
- The SWaT A4/A5 dataset spans only 4.17 hours, containing a single 2.25-hour baseline period.
- Normal chemical cleaning cycles, backwash sequences, and tank draining cycles in SWaT operate on multi-hour schedules. Actuators that were stationary during this short baseline were eliminated by zero-variance filtering, rendering the detector blind to direct state changes on those actuators during attacks.

---

## 6. Scientific Guidelines for Paper Citation

To ensure the highest standard of scientific integrity, authors citing this experiment must observe the following requirements:

### Permissible Paper Claims:
1. May report: *"On the 4.17-hour SWaT A4/A5 July 2019 dataset, an unsupervised multivariate Isolation Forest baseline detected 4 out of 6 cyber-physical attack episodes (66.7%) with an average detection delay of 296.8 s."*
2. May report: *"Attack A5 (closing RO reject valve MV501) was detected instantaneously due to massive secondary pressure surges in PIT502 (z = 1309.2)."*
3. May cite: Pure out-of-sample window classification metrics ($N=230$: Recall = 9.09%, Precision = 22.22%, False Positive Rate = 12.80%, Accuracy = 64.78%).

### Prohibited Paper Claims:
1. **Do NOT report 81% accuracy without citing the 86.8% null classifier baseline**. Presenting 81% accuracy as evidence of high detection performance is scientifically misleading.
2. **Do NOT claim Stage 2 Cross-Machine Influence Modeling or Cascade Risk Index (CRI) validation**. No causal discovery, Transfer Entropy, or CRI calculations were performed on this dataset.
3. **Do NOT claim target-channel attribution**. The detector generates a plant-wide scalar score from 148 pooled features and does not isolate the root-cause machine.

---

## 7. Exact Reproduction Commands

The completed experiment and all evaluation artifacts can be reproduced deterministically using the existing repository codebase:

```powershell
# 1. Verify environment and execute full unit tests (30/30 passing)
pytest tests/unit/test_swat_a4a5.py -v

# 2. Run the deterministic experiment runner (Protocol A, seed=42)
python experiments/swat_a4a5_runner.py --protocol protocol_a --output-dir experiments/results/swat_a4a5

# 3. Verify output files
Get-ChildItem experiments/results/swat_a4a5
```

---

## 8. Summary of Inspected Files, Findings, and Status

| Category | Item | Verified Status |
|---|---|:---:|
| **Files Inspected** | `src/tcmim/data/swat_a4a5.py`, `experiments/swat_a4a5_runner.py`, `metrics.json`, `predictions.csv`, `window_manifest.csv`, `SWaT_dataset_Jul 19 v2.xlsx`, `SWaT data collection_20-07-2019 v2.pdf` | **ALL VERIFIED** |
| **Partition Audit** | 270 in-sample baseline windows (10..279); 230 out-of-sample windows ([0..9 + 280..499]) | **VERIFIED** |
| **Window Recall** | 9.09% (6 / 66 positive windows) | **VERIFIED** |
| **Episode Detection** | 66.67% (4 / 6 episodes detected: A3, A4, A5, A6) | **VERIFIED** |
| **Out-of-Sample FPR** | 12.80% (21 / 164 normal windows) | **VERIFIED** |
| **Null Accuracy** | 86.80% (Complete timeline) / 71.30% (Out-of-sample) | **VERIFIED** |
| **Tests Executed** | `pytest tests/unit/test_swat_a4a5.py` $\to$ **30 passed in 6.48s** | **ALL PASSED** |
| **Reproduction** | 100% bit-exact reproduction confirmed (max score diff = 0.0) | **REPRODUCIBLE** |
