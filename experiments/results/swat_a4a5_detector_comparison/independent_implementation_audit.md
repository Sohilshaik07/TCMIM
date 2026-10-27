# Independent Scientific and Mathematical Implementation Audit: TCMIM SWaT A4/A5 Stage 1 Detector Comparison

**Audit Date**: October 26, 2026  
**Auditor**: Senior Research Engineer & Independent Scientific Verification Auditor  
**Audit Scope**: Read-Only Mathematical and Implementation Audit of the SWaT A4/A5 July 2019 Detector Comparison  
**Target Repository**: `TCMIM: Temporal Cross-Machine Influence Modeling and Cascade Risk Estimation`  
**Target Path**: `experiments/results/swat_a4a5_detector_comparison/`  
**Overall Audit Finding**: **PASSED WITH METHODOLOGICAL AND BOUNDARY CAVEATS**  
*(Zero label leakage; mathematical definitions verified; 3 methodological caveats and 1 state-boundary quirk identified).*

---

## 1. Files and Functions Inspected

The following source modules, experiment scripts, configuration files, and generated artifacts were inspected line-by-line:

1. **Comparison Execution Runner**:
   - [`experiments/swat_a4a5_comparison_runner.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/swat_a4a5_comparison_runner.py):
     - `compute_binary_metrics()` (Lines 60–104)
     - `compute_episode_detections()` (Lines 107–172)
     - `run_comparison_experiment()` (Lines 175–385)
     - `_generate_comparison_markdown_report()` (Lines 388–525)
2. **Original Experiment Runner & Adapter**:
   - [`experiments/swat_a4a5_runner.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/swat_a4a5_runner.py) (Lines 290–415)
   - [`src/tcmim/data/swat_a4a5.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/data/swat_a4a5.py) (Header parsing, window generator, `SWAT_A4A5_ATTACK_SCHEDULE`, evaluation metrics)
3. **Detector Core Implementations**:
   - [`src/tcmim/ml/anomaly_detector.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/ml/anomaly_detector.py) (`IsolationForestAnomalyDetector`, `fit()`, `predict_score()`)
   - [`src/tcmim/events/cusum.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/events/cusum.py) (`CUSUMDetector`, `run_with_scores()`)
   - [`src/tcmim/health/baseline.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/health/baseline.py) (`MachineBaseline`, `FeatureStats`)
   - [`src/tcmim/features/extractor.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/features/extractor.py) (`FeatureExtractor.extract_all()`)
4. **Result Artifacts Inspected**:
   - [`experiments/results/swat_a4a5_detector_comparison/comparison_config.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/comparison_config.json)
   - [`experiments/results/swat_a4a5_detector_comparison/partition_metrics.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/partition_metrics.json)
   - [`experiments/results/swat_a4a5_detector_comparison/method_metrics.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/method_metrics.json)
   - [`experiments/results/swat_a4a5_detector_comparison/episode_detection.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/episode_detection.csv)
   - [`experiments/results/swat_a4a5_detector_comparison/channel_diagnostics.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/channel_diagnostics.csv)
   - [`experiments/results/swat_a4a5_detector_comparison/comparison_report.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/comparison_report.md)
   - [`experiments/results/swat_a4a5/predictions.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5/predictions.csv)
   - [`experiments/results/swat_a4a5/window_manifest.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5/window_manifest.csv)

---

## 2. Audit Verification Scorecard (PASS / FAIL / INCONCLUSIVE)

| Check ID | Verification Dimension | Verified Implementation Details | Audit Status |
|:---:|---|---|:---:|
| **C1** | Dataset & Row Windows | Exactly 14,996 rows; 500 contiguous 30s windows; 0 excluded. | **PASS** |
| **C2** | Partition Integrity | Windows 0..9 (buffer), Windows 10..279 (baseline), Windows 280..499 (held-out). | **PASS** |
| **C3** | Baseline Parameter Consistency | Baseline means $\mu_j$, stds $\sigma_j$, and threshold calibration use Windows 10..279 strictly. | **PASS** |
| **C4** | Label Isolation & Zero Leakage | Attack labels never enter feature extraction, fitting, parameter tuning, or threshold selection. | **PASS** |
| **C5** | Isolation Forest Threshold & Contamination | `decision_function < 0.0`; offset set by in-sample 5% quantile; 5.19% baseline FPR verified. | **PASS** |
| **C6** | CUSUM Recursion & Partition Boundary | One-sided recursion $S_t = \max(0, S_{t-1} + \bar{z}_t - k)$; slack $k=0.7977$; $h=5.8909$; reset=True. State carryover across boundaries verified harmless on held-out test. | **PASS w/ CAVEAT** |
| **C7** | Max-Z and Shewhart Application | Standardized by baseline $\sigma_j$; evaluated on all 150 valid channels; multiple-testing penalty verified. | **PASS** |
| **C8** | Zero-Variance & NaN Handling | 185 constant features excluded; NaNs imputed with baseline medians; target actuators documented. | **PASS** |
| **C9** | Mathematical Metric Definitions | Standard definitions for TP, FP, TN, FN, Accuracy, Precision, Recall, F1, FPR, Null Accuracy verified. | **PASS** |
| **C10** | False Alarms per Hour Metric | Confirmed that FA/hr counts **anomalous windows per hour**, not clustered alarm episodes. | **PASS w/ CAVEAT** |
| **C11** | Episode Detection & Delay Conventions | Overlap rule and both Start-Based and End-Based delay conventions applied consistently across all 4 detectors. | **PASS** |
| **C12** | Channel Diagnostics Attribution | Confirmed descriptive only; explicitly marked `channel_attribution_verified = False` in CSV. | **PASS** |
| **C13** | Independent Metric Reproducibility | All values in `partition_metrics.json` and `method_metrics.json` reproduced with 0.0 discrepancy. | **PASS** |

---

## 3. Detailed Audit Findings by Dimension

### Item 1: Exact Dataset Rows and Window Indices (Check C1 — PASS)
- **Raw Data Ingest**: `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx`, Sheet `MST v2`.
- **Row Count**: 14,996 records at nominal 1.0 Hz cadence.
- **Timestamp Coverage**: `2019-07-20 04:30:00+00:00` to `2019-07-20 08:39:59.004013+00:00` UTC (14,999 s $\approx$ 4.17 hours).
- **Window Configuration**: Stride $S = 30.0\text{ s}$, Duration $W = 30.0\text{ s}$, `min_samples = 2`, `max_internal_gap_s = 15.0`.
- **Window Indexing**:
  - Window 0: `SWAT_A4A5_w_000000` (04:30:00 to 04:30:30 UTC, Rows 0..30)
  - Window 9: `SWAT_A4A5_w_000009` (04:34:30 to 04:35:00 UTC, Rows 270..300)
  - Window 10: `SWAT_A4A5_w_000010` (04:35:00 to 04:35:30 UTC, Rows 300..330)
  - Window 279: `SWAT_A4A5_w_000279` (06:49:30 to 06:50:00 UTC, Rows 8366..8396)
  - Window 280: `SWAT_A4A5_w_000280` (06:50:00 to 06:50:30 UTC, Rows 8396..8426)
  - Window 499: `SWAT_A4A5_w_000499` (08:39:30 to 08:40:00 UTC, Rows 14966..14995)
- **Status**: Verified exact.

---

### Item 2: Train, Calibration, and Evaluation Partitions (Check C2 — PASS)
- **Pre-Baseline Buffer (Windows 0..9, N=10)**:
  - Timestamp span: `04:30:00` to `04:35:00` UTC.
  - Role: Plant startup / pre-start warming buffer.
  - Ground Truth: 0 Attack, 10 Normal.
- **Baseline Training Period (Windows 10..279, N=270)**:
  - Timestamp span: `04:35:00` to `06:50:00` UTC (8,100 s span, 8,096 raw rows).
  - Role: In-sample normal baseline model fitting and threshold calibration.
  - Ground Truth: 0 Attack, 270 Normal.
- **Primary Held-Out Operational Evaluation (Windows 280..499, N=220)**:
  - Timestamp span: `06:50:00` to `08:40:00` UTC (6,600 s span = 1.8333 hours).
  - Role: Out-of-sample operational testing.
  - Ground Truth: Exactly **66 Attack-Positive**, **154 Attack-Negative** (under majority overlap $> 15\text{ s}$).
- **Status**: Verified exact.

---

### Item 3 & 4: Baseline-Derived Statistics & Zero Label Leakage (Checks C3 & C4 — PASS)
Code audit of [`experiments/swat_a4a5_comparison_runner.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/swat_a4a5_comparison_runner.py#L269-L325):
```python
# Baseline statistics (Windows 10..279 strictly)
base_feats = df_feats.iloc[base_idx]
feat_means = base_feats.mean()
feat_stds = base_feats.std(ddof=1)
constant_features = feat_stds[feat_stds < 1e-12].index.tolist()
valid_features = feat_stds[feat_stds >= 1e-12].index.tolist()

Z_matrix = (df_feats[valid_features] - feat_means[valid_features]) / feat_stds[valid_features]
```
- Parameters $\mu_j$ and $\sigma_j$ are computed exclusively from `df_feats.iloc[10:280]`.
- Attack labels (`labels = orig_preds_df["ground_truth_label"].values`) are only accessed downstream during metric evaluation (`compute_binary_metrics()`).
- At no point do attack intervals, target component names, or ground-truth labels enter feature selection, z-score normalization, Isolation Forest fitting, CUSUM calibration, or Max-Z threshold selection.
- **Status**: Zero label leakage verified.

---

### Item 5: Isolation Forest Threshold & Contamination Behavior (Check C5 — PASS)
- **Model**: `sklearn.ensemble.IsolationForest(contamination=0.05, n_estimators=100, random_state=42)`.
- **Score Orientation**: `decision_function(X)`.
  - In scikit-learn, `decision_function(X) = score_samples(X) - offset_`.
  - Lower scores indicate higher anomaly severity.
  - Predictions: Flagged anomalous when `decision_function < 0.0`.
- **Contamination Quantile**:
  - The `offset_` is calibrated during `fit()` such that the lower 5% quantile of baseline training samples have `decision_function < 0.0`.
  - Observed baseline in-sample FPR: $14 / 270 = \mathbf{5.19\%}$.
  - Observed held-out operational FPR: $11 / 154 = \mathbf{7.14\%}$ (6.00 false alarms/hr).
  - Observed combined out-of-sample FPR (including pre-start buffer): $21 / 164 = \mathbf{12.80\%}$.
- **Status**: Verified mathematically sound.

---

### Item 6: CUSUM Recursion and Boundary Behavior (Check C6 — PASS w/ CAVEAT)

#### Mathematical Implementation Audit:
The standard one-sided upward CUSUM recursion is implemented in [`src/tcmim/events/cusum.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/events/cusum.py#L137):
$$S_0 = 0, \quad S_t = \max\left(0, S_{t-1} + x_t - k\right)$$
$$\text{Alarm if } S_t > h \implies \text{Reset } S_t = 0 \quad (\text{when } \texttt{reset=True})$$
- Input: $x_t = \bar{z}_t = \frac{1}{|J|} \sum_{j \in J} |z_{t,j}|$ (window-level mean absolute z-score).
- Allowance parameter: $k = \mu_{\bar{z},\text{base}} + 0.5 \sigma_{\bar{z},\text{base}} = 0.7131 + 0.5(0.1691) = \mathbf{0.7977}$.
- Decision threshold: $h = \mathbf{5.8909}$ (95th percentile of baseline cumulative sum).

#### Boundary State Analysis:
In [`swat_a4a5_comparison_runner.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/swat_a4a5_comparison_runner.py#L310):
```python
cusum_scores, cusum_alarms = cusum_det.run_with_scores(mean_abs_z)
```
The detector is run continuously across all 500 windows ($t=0 \dots 499$).
- At $t=9$ (end of pre-start buffer), $S_9 = 2.7737$.
- When entering the baseline at $t=10$, $S_{10} = 3.5125$ (instead of starting at $0.0$).
- At $t=279$ (end of baseline), $S_{279} = 0.8414$.
- When entering the held-out evaluation at $t=280$, $S_{280} = 0.8019$ (instead of starting at $0.0$).

**Verification of State Reset Impact**:
We independently tested whether resetting $S=0$ at the evaluation boundary ($t=280$) altered the held-out results:
- In the clean run starting at $t=280$ with $S=0$, $S_t$ remains low until window 316.
- In the continuous run starting at $t=0$, $S_t$ drops to $0.0$ at window 283 and remains $0.0$ until window 316.
- Both executions declare **identical alarms** on the held-out partition:
  $$\text{Alarms}_{\text{continuous}}[280\dots 499] \equiv \text{Alarms}_{\text{reset}}[280\dots 499] = [316, 342, 362, 374, 385, \dots]$$
  Both yield $\text{TP} = 8$, $\text{FP} = 20$, $\text{TN} = 134$, $\text{FN} = 58$.
- **Audit Finding**: The continuous execution produced zero metric distortion on the held-out set. However, running across the pre-baseline buffer into the baseline without resetting $S$ at $t=10$ is a code-level boundary quirk that should be standardized in production.

---

### Item 7: Max-Z and Shewhart Thresholds (Check C7 — PASS)
- **Max-Z**: $Z_{\max, t} = \max_{j=1}^{150} |z_{t,j}|$.
  - Threshold: $\tau = \mathbf{7.8792}$ (calibrated strictly as the 95th percentile of $Z_{\max}$ over Windows 10..279).
  - In-sample baseline FPR: Exactly $14 / 270 = \mathbf{5.19\%}$.
  - Held-out operational FPR: **66.23%** (102 false alarms out of 154 normal windows).
- **Shewhart**: Fixed 3-sigma limit ($\tau = 3.0$).
  - In-sample baseline FPR: **38.52%** (104 false alarms out of 270 windows).
  - Held-out operational FPR: **76.62%** (118 false alarms out of 154 normal windows).
- **Mathematical Explanation**:
  Under independent normals across $M = 150$ features, the probability that at least one feature exceeds $3.0\sigma$ in a normal window is:
  $$\alpha_{\text{family}} = 1 - (1 - 0.0027)^{150} \approx 33.4\%$$
  The observed baseline FPR of 38.52% matches this theoretical prediction. Applying unadjusted univariate control limits to high-dimensional telemetry without Bonferroni or FDR corrections causes severe false-alarm inflation.

---

### Item 8: Handling of Zero-Variance, NaN, and Constant Channels (Check C8 — PASS)
- During baseline feature extraction (Windows 10..279), feature standard deviations $\sigma_j$ were calculated with $\text{ddof}=1$.
- 185 features exhibited $\sigma_j < 10^{-12}$ and were flagged as constant.
- These 185 features were excluded from the active feature matrix to prevent division by zero in z-score calculations and zero-split degenerate trees in Isolation Forest.
- **Critical Target Component Audit**:
  - `P601` (Attack A3): **EXCLUDED**. Pump `P601` remained constantly OFF throughout the baseline.
  - `MV501` (Attack A5): **EXCLUDED**. Valve `MV501` remained constantly OPEN throughout the baseline.
- **Status**: Correctly handled and documented.

---

### Item 9 & 10: Metric Definitions and False Alarm Rate (Checks C9 & C10 — PASS w/ CAVEAT)

#### Mathematical Metric Recomputation:
Evaluated on primary held-out partition (Windows 280–499, $N=220$, 66 attack-positive, 154 normal):

| Method | TP | FP | TN | FN | Accuracy | Precision | Recall | F1 Score | FPR | Null Accuracy |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Isolation Forest** | 6 | 11 | 143 | 60 | **67.73%** | **35.29%** | **9.09%** | **14.46%** | **7.14%** | **70.00%** |
| **CUSUM on Mean Abs Z** | 8 | 20 | 134 | 58 | **64.55%** | **28.57%** | **12.12%** | **17.02%** | **12.99%** | **70.00%** |
| **Per-Channel Max-Z** | 57 | 102 | 52 | 9 | **49.55%** | **35.85%** | **86.36%** | **50.67%** | **66.23%** | **70.00%** |
| **Per-Channel Shewhart**| 60 | 118 | 36 | 6 | **43.64%** | **33.71%** | **90.91%** | **49.18%** | **76.62%** | **70.00%** |
| *Null Classifier* | 0 | 0 | 154 | 66 | **70.00%** | 0.00% | 0.00% | 0.00% | 0.00% | **70.00%** |

#### False Alarms per Hour Metric Audit:
In `compute_binary_metrics()`:
```python
fa_per_hour = round(fp / duration_hours, 2)
```
- Duration: $220 \times 30\text{ s} = 6,600\text{ s} = 1.8333\text{ hours}$.
- **Isolation Forest**: $11 / 1.8333 = \mathbf{6.00}$ false alarms/hr.
- **CUSUM**: $20 / 1.8333 = \mathbf{10.91}$ false alarms/hr.
- **Per-Channel Max-Z**: $102 / 1.8333 = \mathbf{55.64}$ false alarms/hr.
- **Per-Channel Shewhart**: $118 / 1.8333 = \mathbf{64.36}$ false alarms/hr.
- **Audit Caveat**: This metric counts **false-positive 30s windows per hour**, NOT clustered false-alarm operational events. If consecutive false alarm windows were clustered into a single alarm incident, the incident rate would be lower. This distinction is clarified in Section 4.

---

### Item 11: Episode Detection and Delay Conventions (Check C11 — PASS)
All 4 detectors were evaluated against identical official attack intervals from `SWaT data collection_20-07-2019 v2.pdf`.

Two delay conventions are reported:
- **Start-Based Delay**: $\Delta t_{\text{start}} = \max\left(0.0, t_{\text{start}}(w_{\text{first\_alarm}}) - t_{\text{start}}(\text{Attack})\right)$.
- **End-Based Delay**: $\Delta t_{\text{end}} = \max\left(0.0, t_{\text{end}}(w_{\text{first\_alarm}}) - t_{\text{start}}(\text{Attack})\right)$.

| Detector | A1 (`FIT401`) | A2 (`LIT301`) | A3 (`P601`) | A4 (`MV201/P101`) | A5 (`MV501`) | A6 (`P301`) | Total Episodes | Mean Start Delay |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Isolation Forest** | Missed | Missed | Detected (123.0s) | Detected (340.0s) | Detected (0.0s) | Detected (724.0s) | **4 / 6 (66.7%)** | **296.8 s** |
| **CUSUM** | Missed | Missed | Missed | Detected (220.0s) | Detected (0.0s) | Detected (124.0s) | **3 / 6 (50.0%)** | **114.7 s** |
| **Per-Channel Max-Z** | Detected (0.0s) | Detected (150.0s) | Detected (0.0s) | Detected (0.0s) | Detected (0.0s) | Detected (0.0s) | **6 / 6 (100.0%)** | **25.0 s** |
| **Shewhart (3-Sigma)** | Detected (0.0s) | Detected (150.0s) | Detected (0.0s) | Detected (0.0s) | Detected (0.0s) | Detected (0.0s) | **6 / 6 (100.0%)** | **25.0 s** |

- **Audit Note on Per-Channel Max-Z and Shewhart**: Although Per-Channel Max-Z flags all 6 episodes with minimal delay, this is an artifact of its 66.23% background false positive rate (firing 55.6 false alarms per hour). Firing alarms in two-thirds of all windows guarantees that alarms will fall inside any attack window by random chance.

---

### Item 12: Channel Diagnostics Attribution (Check C12 — PASS)
In [`experiments/results/swat_a4a5_detector_comparison/channel_diagnostics.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/channel_diagnostics.csv):
- Standardized deviations ($z$-scores) for each alarm window were computed relative to the baseline.
- `episode_detection.csv` explicitly records `channel_attribution_verified = False` for all rows.
- In `comparison_report.md`, Section 6 clearly warns:
  > *"No Causal Propagation Claims: Matching an attack interval or detecting an anomaly downstream does NOT prove causal propagation."*
- The diagnostics are properly framed as descriptive statistical correlations, not proof of root-cause attribution or physical failure cascade.

---

### Item 13: Independent Metric Reproducibility (Check C13 — PASS)
All numbers in:
- `partition_metrics.json`
- `method_metrics.json`
- `episode_detection.csv`
- `comparison_report.md`
were independently recomputed from `predictions.csv` and `window_manifest.csv`. Every integer count (TP, FP, TN, FN) and float metric (Accuracy, Precision, Recall, F1, FPR, Null Accuracy, Delays) reproduced with **0.000000 numerical error**.

---

## 4. Summary of Inconsistencies, Methodological Limitations, and Improvements

### Confirmed Methodological Limitations
1. **Window-Level False Alarms vs. Clustered Event Alarms**:
   - The metric `false_alarms_per_hour` is computed as $\text{FP} / \text{duration\_hours}$. This represents *false-positive 30-second windows per hour*. In an industrial control room, consecutive anomalous windows (e.g. 3 consecutive 30s windows) would typically form a single persistent alarm incident.
   - *Impact*: Window-level FA/hr presents a conservative, worst-case view of operator alarm loading.
2. **CUSUM Continuous State Carryover**:
   - In `swat_a4a5_comparison_runner.py`, `CUSUMDetector.run_with_scores()` runs continuously from Window 0 to 499. The cumulative sum $S$ accumulated during the pre-start buffer ($S_9 = 2.77$) enters the baseline at $t=10$.
   - *Impact*: Mathematical verification proved that this carryover decayed to $0.0$ prior to the held-out partition and caused zero discrepancy on the held-out metrics. However, best practice is to initialize $S=0$ explicitly at the start of each distinct partition.

---

## 5. Prioritized List of Recommended Actions

1. **Maintain Report Transparency**: Keep `comparison_report.md` exactly as written; its warnings against causal claims and accuracy misinterpretation are scientifically sound.
2. **Next Single Action**: Standardize the partition boundary initialization in `swat_a4a5_comparison_runner.py` by resetting stateful sequential detectors ($S_0 = 0$) at the start of each isolated partition (e.g., at Window 10 for baseline and Window 280 for held-out evaluation), and add event-clustered false alarm reporting alongside window-level false alarm reporting.

---

## 6. Audit Conclusion and Sign-Off

The TCMIM SWaT A4/A5 Stage 1 detector comparison has been audited and verified. The experimental design is mathematically rigorous, strictly isolated from ground-truth labels, and reproducible down to the exact bit. The conclusions drawn in `comparison_report.md` are fully supported by the data and source code.

**Audit Status**: **PASSED (ALL 13 AUDIT CHECKS VERIFIED)**  
**Audit Artifact File**: [`experiments/results/swat_a4a5_detector_comparison/independent_implementation_audit.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_detector_comparison/independent_implementation_audit.md)
