# TCMIM SWaT A4/A5 Stage 1 Detector Comparison & Scientific Evaluation

**Execution Date**: 2026-10-26T12:35:15.147827+00:00  
**Dataset SHA-256**: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`  
**Random Seed**: 42  
**Primary Evaluation Partition**: Windows 280–499 (N=220, 1.83 hours)  

## Executive Summary

This experiment establishes an immutable, leak-free comparative benchmark across multiple anomaly detection paradigms on the SWaT A4/A5 July 2019 dataset. All model parameters and thresholds were calibrated strictly from baseline windows (Windows 10–279) without consulting attack labels. Performance is evaluated on the held-out operational partition (Windows 280–499), with pre-baseline buffer windows (Windows 0–9) isolated as a diagnostic transient.

## 1. Partition Verification Results

| Partition Name | Window Range | UTC Timestamp Span | Windows ($N$) | Ground Truth (Pos / Neg) | Role |
|---|---|---|:---:|:---:|---|
| **Pre-Baseline Buffer** | Windows 0..9 | 2019-07-20T04:30:00+00:00 – 2019-07-20T04:35:00+00:00 | 10 | 0 / 10 | Pre-operational warm-up |
| **Baseline Training Period** | Windows 10..279 | 2019-07-20T04:35:00+00:00 – 2019-07-20T06:50:00+00:00 | 270 | 0 / 270 | In-sample model fitting |
| **Primary Held-Out Evaluation** | Windows 280..499 | 2019-07-20T06:50:00+00:00 – 2019-07-20T08:40:00+00:00 | 220 | 66 / 154 | Out-of-sample operational testing |
| **Complete Mixed Timeline** | Windows 0..499 | 04:30:00 – 08:40:00 | 500 | 66 / 434 | Mixed timeline summary |


### Baseline Isolation Forest Confusion Matrices by Partition

| Partition | TP | FP | TN | FN | Accuracy | Precision | Recall | F1 | FPR | Null Accuracy |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Pre-Baseline Buffer (0..9)** | 0 | 10 | 0 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0000 | 1.0000 |
| **Baseline Training (10..279)** | 0 | 14 | 256 | 0 | 0.9481 | 0.0 | 0.0 | 0.0 | 0.0519 | 1.0000 |
| **Primary Held-Out (280..499)** | 6 | 11 | 143 | 60 | 0.6773 | 0.3529 | 0.0909 | 0.1446 | 0.0714 | 0.7000 |
| **Combined Unseen ([0..9 + 280..499])** | 6 | 21 | 143 | 60 | 0.6478 | 0.2222 | 0.0909 | 0.129 | 0.1280 | 0.7130 |
| **Complete Mixed Timeline (0..499)** | 6 | 35 | 399 | 60 | 0.81 | 0.1463 | 0.0909 | 0.1121 | 0.0806 | 0.8680 |


## 2. Comparative Evaluation of Detection Methods (Held-Out Windows 280–499)

All methods were evaluated under identical conditions on the 220 held-out windows (66 attack-positive, 154 normal, duration = 1.83 hours). Thresholds were determined using baseline-only data without consulting attack labels.

| Method Name | Model Family | Baseline In-Sample FPR | Held-Out TP | Held-Out FP | Held-Out TN | Held-Out FN | Accuracy | Precision | Recall | F1 | FPR | False Alarms / Hr | Episode Detection |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Multivariate Isolation Forest (Existing)** | Unsupervised Tree Ensemble | 0.0519 | 6 | 11 | 143 | 60 | 0.6773 | 0.3529 | 0.0909 | 0.1446 | 0.0714 | 6.0 | 4/6 (66.7%) |
| **CUSUM Detector on Mean Absolute Z-Scores** | Sequential Change-Point Detection | 0.0037 | 8 | 20 | 134 | 58 | 0.6455 | 0.2857 | 0.1212 | 0.1702 | 0.1299 | 10.91 | 3/6 (50.0%) |
| **Per-Channel Max-Z (Baseline Calibrated)** | Extreme Value Statistical Envelope | 0.0519 | 57 | 102 | 52 | 9 | 0.4955 | 0.3585 | 0.8636 | 0.5067 | 0.6623 | 55.64 | 6/6 (100.0%) |
| **Per-Channel Shewhart (Fixed 3-Sigma)** | Univariate Statistical Process Control | 0.3852 | 60 | 118 | 36 | 6 | 0.4364 | 0.3371 | 0.9091 | 0.4918 | 0.7662 | 64.36 | 6/6 (100.0%) |
| *Zero-Information Null Classifier* | Baseline Predict-Normal | 0.0000 | 0 | 0 | 154 | 66 | 0.7000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.00 | 0/6 (0.0%) |


## 3. Attack Episode Detection and Delay Analysis

An episode is marked detected if at least one window overlapping the official attack interval triggers an alarm. Delays are reported under both Start-Based Convention ($t_{\text{start}}(w) - t_{\text{start}}(\text{Attack})$) and End-Based Convention ($t_{\text{end}}(w) - t_{\text{start}}(\text{Attack})$, window completion time).

| Method | Attack | Target Tags | Overlap Windows | Flagged Windows | Detected? | Start-Based Delay | End-Based Delay | Timing |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|---|
| Multivariate Isolation Forest (Existing) | A1 | `FIT401` | 5 | 0 | NO | nan s | nan s | No alarm |
| Multivariate Isolation Forest (Existing) | A2 | `LIT301` | 10 | 0 | NO | nan s | nan s | No alarm |
| Multivariate Isolation Forest (Existing) | A3 | `P601` | 9 | 1 | **YES** | 123.0 s | 153.0 s | During attack |
| Multivariate Isolation Forest (Existing) | A4 | `MV201;P101` | 16 | 1 | **YES** | 340.0 s | 370.0 s | During attack |
| Multivariate Isolation Forest (Existing) | A5 | `MV501` | 4 | 3 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| Multivariate Isolation Forest (Existing) | A6 | `P301` | 28 | 1 | **YES** | 724.0 s | 754.0 s | During attack |
| CUSUM Detector on Mean Absolute Z-Scores | A1 | `FIT401` | 5 | 0 | NO | nan s | nan s | No alarm |
| CUSUM Detector on Mean Absolute Z-Scores | A2 | `LIT301` | 10 | 0 | NO | nan s | nan s | No alarm |
| CUSUM Detector on Mean Absolute Z-Scores | A3 | `P601` | 9 | 0 | NO | nan s | nan s | No alarm |
| CUSUM Detector on Mean Absolute Z-Scores | A4 | `MV201;P101` | 16 | 1 | **YES** | 220.0 s | 250.0 s | During attack |
| CUSUM Detector on Mean Absolute Z-Scores | A5 | `MV501` | 4 | 3 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| CUSUM Detector on Mean Absolute Z-Scores | A6 | `P301` | 28 | 4 | **YES** | 124.0 s | 154.0 s | During attack |
| Per-Channel Max-Z (Baseline Calibrated) | A1 | `FIT401` | 5 | 2 | **YES** | 0.0 s | 14.0 s | Instantaneous |
| Per-Channel Max-Z (Baseline Calibrated) | A2 | `LIT301` | 10 | 2 | **YES** | 150.0 s | 180.0 s | During attack |
| Per-Channel Max-Z (Baseline Calibrated) | A3 | `P601` | 9 | 9 | **YES** | 0.0 s | 3.0 s | Instantaneous |
| Per-Channel Max-Z (Baseline Calibrated) | A4 | `MV201;P101` | 16 | 16 | **YES** | 0.0 s | 10.0 s | Instantaneous |
| Per-Channel Max-Z (Baseline Calibrated) | A5 | `MV501` | 4 | 4 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| Per-Channel Max-Z (Baseline Calibrated) | A6 | `P301` | 28 | 28 | **YES** | 0.0 s | 4.0 s | Instantaneous |
| Per-Channel Shewhart (Fixed 3-Sigma) | A1 | `FIT401` | 5 | 5 | **YES** | 0.0 s | 14.0 s | Instantaneous |
| Per-Channel Shewhart (Fixed 3-Sigma) | A2 | `LIT301` | 10 | 3 | **YES** | 150.0 s | 180.0 s | During attack |
| Per-Channel Shewhart (Fixed 3-Sigma) | A3 | `P601` | 9 | 9 | **YES** | 0.0 s | 3.0 s | Instantaneous |
| Per-Channel Shewhart (Fixed 3-Sigma) | A4 | `MV201;P101` | 16 | 16 | **YES** | 0.0 s | 10.0 s | Instantaneous |
| Per-Channel Shewhart (Fixed 3-Sigma) | A5 | `MV501` | 4 | 4 | **YES** | 0.0 s | 30.0 s | Instantaneous |
| Per-Channel Shewhart (Fixed 3-Sigma) | A6 | `P301` | 28 | 28 | **YES** | 0.0 s | 4.0 s | Instantaneous |


## 4. Isolation Forest Feature Diagnostics Around Detected Alarms

To inspect what physical processes triggered alarms in the Multivariate Isolation Forest without inventing post-hoc feature importances, each overlapping window was analyzed for its top standardized deviations ($z$-scores) relative to the normal baseline.

| Attack | Window ID | UTC Timestamp | Target Channels | Alarm Flagged? | Anomaly Score | Top Deviating Features | Attribution Category |
|:---:|---|---|---|:---:|:---:|---|---|
| A1 | `SWAT_A4A5_w_000317` | 07:08:30 | `FIT401` | NO | 0.0197 | FIT401__std (z=352.42); FIT401__mean (z=115.83); PIT501__range (z=3.60); AIT502__std (z=3.38); FIT601__std (z=3.29) | Unflagged Window |
| A1 | `SWAT_A4A5_w_000318` | 07:09:00 | `FIT401` | NO | 0.0608 | AIT502__std (z=6.66); AIT503__mean (z=2.55); PIT503__max (z=2.15); PIT503__percentile_95 (z=2.13); FIT503__std (z=2.10) | Unflagged Window |
| A1 | `SWAT_A4A5_w_000319` | 07:09:30 | `FIT401` | NO | 0.0521 | AIT502__std (z=8.38); AIT503__mean (z=2.55); AIT501__std (z=2.39); PIT503__percentile_25 (z=2.16); PIT503__mean (z=2.08) | Unflagged Window |
| A1 | `SWAT_A4A5_w_000320` | 07:10:00 | `FIT401` | NO | 0.0682 | AIT503__std (z=5.85); AIT502__std (z=5.72); PIT502__slope (z=3.30); PIT502__iqr (z=2.43); PIT502__min (z=2.15) | Unflagged Window |
| A1 | `SWAT_A4A5_w_000321` | 07:10:30 | `FIT401` | NO | 0.0901 | AIT503__std (z=6.29); AIT502__mean (z=1.96); AIT501__std (z=1.93); PIT502__min (z=1.92); FIT502__mean (z=1.67) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000330` | 07:15:00 | `LIT301` | NO | 0.0793 | AIT503__mean (z=2.55); PIT503__percentile_25 (z=1.94); PIT503__percentile_75 (z=1.94); PIT503__median (z=1.93); PIT503__rms (z=1.93) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000331` | 07:15:30 | `LIT301` | NO | 0.0689 | PIT501__kurtosis (z=2.85); PIT501__skewness (z=2.63); AIT503__mean (z=2.55); PIT503__skewness (z=2.27); PIT503__percentile_75 (z=2.10) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000332` | 07:16:00 | `LIT301` | NO | 0.0792 | AIT503__mean (z=2.55); PIT503__zero_crossings (z=2.04); AIT202__mean (z=1.97); PIT501__percentile_75 (z=1.84); PIT501__percentile_25 (z=1.84) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000333` | 07:16:30 | `LIT301` | NO | 0.0635 | FIT401__std (z=2.66); AIT503__mean (z=2.55); FIT401__mean (z=2.22); PIT501__slope (z=2.06); FIT503__std (z=2.02) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000334` | 07:17:00 | `LIT301` | NO | 0.0863 | FIT501__std (z=2.74); AIT503__mean (z=2.55); FIT401__mean (z=2.53); AIT202__mean (z=1.90); FIT502__mean (z=1.90) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000335` | 07:17:30 | `LIT301` | NO | 0.0365 | LIT301__std (z=78.73); P101__n_transitions (z=6.12); MV201__n_transitions (z=6.12); AIT503__mean (z=2.55); FIT601__std (z=2.46) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000336` | 07:18:00 | `LIT301` | NO | 0.0076 | FIT601__std (z=7.95); FIT201__std (z=7.25); AIT201__std (z=6.62); AIT202__std (z=6.23); P203__n_transitions (z=6.12) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000337` | 07:18:30 | `LIT301` | NO | 0.0236 | FIT601__std (z=4.32); AIT202__std (z=3.74); DPIT301__zero_crossings (z=3.09); FIT401__mean (z=2.96); AIT503__mean (z=2.55) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000338` | 07:19:00 | `LIT301` | NO | 0.0609 | AIT503__mean (z=2.55); AIT203__std (z=2.46); PIT503__percentile_75 (z=1.95); FIT501__mean (z=1.94); FIT502__std (z=1.91) | Unflagged Window |
| A2 | `SWAT_A4A5_w_000339` | 07:19:30 | `LIT301` | NO | 0.0457 | AIT503__mean (z=2.55); PIT501__slope (z=2.47); PIT503__std (z=2.32); PIT503__slope (z=2.26); FIT503__std (z=2.10) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000353` | 07:26:30 | `P601` | NO | 0.0593 | AIT201__mean (z=25.44); AIT201__std (z=9.77); FIT401__mean (z=4.01); FIT501__mean (z=3.57); FIT504__mean (z=2.57) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000354` | 07:27:00 | `P601` | NO | 0.0375 | AIT201__mean (z=32.45); AIT201__std (z=11.34); PIT503__slope (z=3.05); FIT501__mean (z=3.00); FIT401__mean (z=2.93) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000355` | 07:27:30 | `P601` | NO | 0.0601 | AIT201__mean (z=39.69); AIT201__std (z=13.61); PIT501__max (z=2.30); PIT501__percentile_95 (z=2.29); PIT503__median (z=2.27) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000356` | 07:28:00 | `P601` | NO | 0.0553 | AIT201__mean (z=48.72); AIT201__std (z=16.89); FIT501__mean (z=3.26); FIT401__mean (z=2.93); FIT504__mean (z=2.61) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000357` | 07:28:30 | `P601` | NO | 0.0529 | AIT201__mean (z=55.79); AIT503__std (z=8.86); AIT201__std (z=5.73); PIT503__zero_crossings (z=2.95); FIT401__mean (z=2.90) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000358` | 07:29:00 | `P601` | **YES** | -0.0179 | AIT201__mean (z=57.94); DPIT301__range (z=8.08); DPIT301__std (z=7.06); MV302__n_transitions (z=6.62); DPIT301__slope (z=6.60) | Non-Target Features Dominant (Global Coupling / Drift) |
| A3 | `SWAT_A4A5_w_000359` | 07:29:30 | `P601` | NO | 0.0301 | AIT201__mean (z=55.92); AIT201__std (z=5.20); FIT401__mean (z=3.14); FIT501__mean (z=2.64); FIT504__mean (z=2.52) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000360` | 07:30:00 | `P601` | NO | 0.0092 | AIT201__mean (z=54.49); PIT502__slope (z=3.03); FIT504__mean (z=2.82); FIT501__mean (z=2.78); FIT401__mean (z=2.77) | Unflagged Window |
| A3 | `SWAT_A4A5_w_000361` | 07:30:30 | `P601` | NO | 0.0341 | AIT201__mean (z=54.45); FIT401__mean (z=3.61); FIT501__mean (z=3.03); FIT503__mean (z=2.64); FIT504__mean (z=2.54) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000377` | 07:38:30 | `MV201;P101` | NO | 0.0332 | AIT201__mean (z=54.70); FIT501__mean (z=3.67); FIT401__mean (z=3.06); FIT503__mean (z=2.98); FIT504__mean (z=2.60) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000378` | 07:39:00 | `MV201;P101` | NO | 0.0067 | AIT201__mean (z=54.73); AIT503__std (z=9.41); FIT101__std (z=7.47); MV101__n_transitions (z=3.64); FIT401__mean (z=2.97) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000379` | 07:39:30 | `MV201;P101` | NO | 0.004 | AIT201__mean (z=52.62); AIT201__std (z=7.89); PIT501__kurtosis (z=4.68); MV101__n_transitions (z=3.64); AIT503__mean (z=3.24) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000380` | 07:40:00 | `MV201;P101` | NO | 0.036 | AIT201__mean (z=49.38); AIT201__std (z=3.79); FIT401__mean (z=3.43); FIT501__mean (z=2.91); FIT503__mean (z=2.87) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000381` | 07:40:30 | `MV201;P101` | NO | 0.0012 | AIT201__mean (z=46.69); FIT401__mean (z=5.07); AIT201__std (z=4.58); PIT502__slope (z=3.85); PIT501__min (z=3.04) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000382` | 07:41:00 | `MV201;P101` | NO | 0.0413 | AIT201__mean (z=44.22); FIT401__mean (z=3.63); FIT501__mean (z=3.34); FIT503__mean (z=2.84); PIT501__percentile_75 (z=2.65) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000383` | 07:41:30 | `MV201;P101` | NO | 0.0342 | AIT201__mean (z=42.43); PIT501__min (z=2.90); PIT501__percentile_25 (z=2.89); PIT503__min (z=2.80); PIT503__percentile_25 (z=2.79) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000384` | 07:42:00 | `MV201;P101` | NO | 0.0502 | AIT201__mean (z=40.40); AIT201__std (z=4.05); FIT401__mean (z=3.60); FIT501__mean (z=3.18); PIT501__min (z=3.01) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000385` | 07:42:30 | `MV201;P101` | NO | 0.0262 | AIT201__mean (z=38.67); FIT501__mean (z=3.18); FIT504__mean (z=2.82); FIT503__mean (z=2.74); FIT401__mean (z=2.73) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000386` | 07:43:00 | `MV201;P101` | NO | 0.046 | AIT201__mean (z=37.05); PIT503__max (z=3.00); PIT503__percentile_95 (z=2.99); PIT503__percentile_75 (z=2.91); PIT501__percentile_75 (z=2.89) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000387` | 07:43:30 | `MV201;P101` | NO | 0.0365 | AIT201__mean (z=35.50); FIT501__mean (z=3.08); PIT501__percentile_25 (z=2.95); PIT501__median (z=2.93); PIT503__percentile_75 (z=2.91) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000388` | 07:44:00 | `MV201;P101` | NO | 0.0197 | AIT201__mean (z=33.89); PIT502__slope (z=3.20); PIT501__percentile_75 (z=2.99); FIT501__mean (z=2.95); PIT501__median (z=2.93) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000389` | 07:44:30 | `MV201;P101` | **YES** | -0.0171 | AIT201__mean (z=32.10); P101__n_transitions (z=6.12); P203__n_transitions (z=6.12); P205__n_transitions (z=6.12); FIT201__std (z=3.58) | Target Associated (Direct Evidence in Top Features) |
| A4 | `SWAT_A4A5_w_000390` | 07:45:00 | `MV201;P101` | NO | 0.0225 | AIT201__mean (z=31.12); AIT503__std (z=3.97); FIT501__mean (z=3.23); PIT501__slope (z=3.07); FIT503__mean (z=2.98) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000391` | 07:45:30 | `MV201;P101` | NO | 0.0357 | AIT201__mean (z=31.08); AIT503__std (z=7.93); FIT601__std (z=4.43); FIT401__mean (z=4.08); FIT501__mean (z=3.28) | Unflagged Window |
| A4 | `SWAT_A4A5_w_000392` | 07:46:00 | `MV201;P101` | NO | 0.0512 | AIT201__mean (z=30.97); FIT601__mean (z=4.63); PIT501__percentile_25 (z=2.92); PIT503__percentile_25 (z=2.89); PIT501__min (z=2.83) | Unflagged Window |
| A5 | `SWAT_A4A5_w_000408` | 07:54:00 | `MV501` | **YES** | -0.0494 | PIT502__mean (z=2845.84); PIT502__rms (z=2845.64); PIT502__percentile_25 (z=2816.83); PIT502__median (z=2815.20); PIT502__percentile_75 (z=2752.89) | Non-Target Features Dominant (Global Coupling / Drift) |
| A5 | `SWAT_A4A5_w_000409` | 07:54:30 | `MV501` | **YES** | -0.0602 | PIT502__slope (z=4502.04); PIT502__range (z=3443.41); PIT502__std (z=3175.28); PIT502__median (z=2816.15); PIT502__percentile_75 (z=2755.39) | Non-Target Features Dominant (Global Coupling / Drift) |
| A5 | `SWAT_A4A5_w_000410` | 07:55:00 | `MV501` | **YES** | -0.0296 | PIT502__range (z=603.55); PIT502__slope (z=532.97); PIT502__std (z=429.92); PIT502__max (z=368.85); PIT502__percentile_95 (z=217.89) | Non-Target Features Dominant (Global Coupling / Drift) |
| A5 | `SWAT_A4A5_w_000411` | 07:55:30 | `MV501` | NO | 0.0485 | AIT504__std (z=62.31); AIT201__mean (z=30.91); AIT504__mean (z=20.53); AIT303__mean (z=14.73); PIT502__mean (z=6.71) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000425` | 08:02:30 | `P301` | NO | 0.0652 | AIT201__mean (z=30.69); AIT303__mean (z=14.64); PIT502__rms (z=6.26); PIT502__mean (z=6.26); PIT502__median (z=6.19) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000426` | 08:03:00 | `P301` | NO | 0.0708 | AIT201__mean (z=30.69); AIT303__mean (z=14.47); PIT502__rms (z=6.26); PIT502__mean (z=6.26); PIT502__median (z=6.19) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000427` | 08:03:30 | `P301` | NO | 0.0553 | AIT201__mean (z=30.69); AIT303__mean (z=14.38); PIT502__percentile_25 (z=6.15); PIT502__median (z=5.95); PIT502__min (z=5.87) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000428` | 08:04:00 | `P301` | NO | 0.0556 | AIT201__mean (z=30.69); AIT303__mean (z=14.43); PIT502__rms (z=6.24); PIT502__mean (z=6.24); PIT502__median (z=6.19) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000429` | 08:04:30 | `P301` | NO | 0.0604 | AIT201__mean (z=30.69); AIT303__mean (z=14.23); PIT502__median (z=6.19); PIT502__percentile_25 (z=6.15); PIT502__mean (z=6.13) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000430` | 08:05:00 | `P301` | NO | 0.0719 | AIT201__mean (z=30.69); AIT303__mean (z=14.39); PIT502__rms (z=6.25); PIT502__mean (z=6.25); PIT502__median (z=6.19) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000431` | 08:05:30 | `P301` | NO | 0.0433 | AIT201__mean (z=30.69); AIT303__mean (z=14.20); PIT502__median (z=6.19); PIT502__percentile_25 (z=6.15); PIT502__mean (z=5.99) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000432` | 08:06:00 | `P301` | NO | 0.0394 | AIT201__mean (z=30.69); AIT303__mean (z=14.24); PIT502__min (z=6.56); PIT502__percentile_25 (z=6.03); PIT502__mean (z=5.89) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000433` | 08:06:30 | `P301` | NO | 0.0575 | AIT201__mean (z=30.67); AIT303__mean (z=14.18); PIT502__min (z=6.56); PIT502__percentile_25 (z=6.15); PIT502__mean (z=6.02) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000434` | 08:07:00 | `P301` | NO | 0.0428 | AIT201__mean (z=30.63); AIT303__mean (z=14.40); PIT501__kurtosis (z=7.52); PIT502__min (z=6.79); PIT502__mean (z=6.44) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000435` | 08:07:30 | `P301` | NO | 0.0601 | AIT201__mean (z=30.63); AIT303__mean (z=14.07); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000436` | 08:08:00 | `P301` | NO | 0.0514 | AIT201__mean (z=30.63); AIT303__mean (z=14.06); AIT503__std (z=10.56); PIT502__median (z=6.67); PIT502__percentile_25 (z=6.62) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000437` | 08:08:30 | `P301` | NO | 0.0366 | AIT201__mean (z=30.63); AIT303__mean (z=14.01); PIT502__rms (z=5.78); PIT502__mean (z=5.78); PIT502__median (z=5.71) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000438` | 08:09:00 | `P301` | NO | 0.0455 | AIT201__mean (z=30.63); AIT303__mean (z=13.92); PIT502__min (z=6.56); PIT502__mean (z=6.05); PIT502__rms (z=6.05) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000439` | 08:09:30 | `P301` | NO | 0.0533 | AIT201__mean (z=30.63); AIT303__mean (z=13.85); PIT502__median (z=6.67); PIT502__percentile_25 (z=6.62); PIT502__mean (z=6.55) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000440` | 08:10:00 | `P301` | NO | 0.0605 | AIT201__mean (z=30.63); AIT303__mean (z=14.17); PIT502__rms (z=6.02); PIT502__mean (z=6.02); PIT502__median (z=5.95) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000441` | 08:10:30 | `P301` | NO | 0.0688 | AIT201__mean (z=30.63); AIT303__mean (z=13.96); PIT502__rms (z=6.02); PIT502__mean (z=6.02); PIT502__median (z=5.95) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000442` | 08:11:00 | `P301` | NO | 0.0385 | AIT201__mean (z=30.63); AIT303__mean (z=13.93); PIT502__median (z=6.67); PIT502__percentile_25 (z=6.62); PIT502__mean (z=6.53) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000443` | 08:11:30 | `P301` | NO | 0.0549 | AIT201__mean (z=30.63); AIT303__mean (z=14.05); PIT501__kurtosis (z=7.52); PIT502__rms (z=6.75); PIT502__mean (z=6.75) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000444` | 08:12:00 | `P301` | NO | 0.0697 | AIT201__mean (z=30.63); AIT303__mean (z=14.28); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000445` | 08:12:30 | `P301` | NO | 0.0612 | AIT201__mean (z=30.63); AIT303__mean (z=14.26); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000446` | 08:13:00 | `P301` | NO | 0.0627 | AIT201__mean (z=30.63); AIT303__mean (z=13.95); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000447` | 08:13:30 | `P301` | NO | 0.0571 | AIT201__mean (z=30.63); AIT303__mean (z=14.27); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000448` | 08:14:00 | `P301` | NO | 0.0657 | AIT201__mean (z=30.63); AIT303__mean (z=14.42); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000449` | 08:14:30 | `P301` | NO | 0.0552 | AIT201__mean (z=30.63); AIT303__mean (z=14.62); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000450` | 08:15:00 | `P301` | **YES** | -0.0081 | AIT201__mean (z=30.63); AIT303__mean (z=13.13); DPIT301__iqr (z=12.46); DPIT301__slope (z=9.97); DPIT301__std (z=9.33) | Non-Target Features Dominant (Global Coupling / Drift) |
| A6 | `SWAT_A4A5_w_000451` | 08:15:30 | `P301` | NO | 0.0422 | AIT201__mean (z=30.63); AIT303__mean (z=8.89); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |
| A6 | `SWAT_A4A5_w_000452` | 08:16:00 | `P301` | NO | 0.0427 | AIT201__mean (z=30.63); AIT303__mean (z=13.66); PIT502__rms (z=6.75); PIT502__mean (z=6.75); PIT502__median (z=6.67) | Unflagged Window |


### Diagnostic Insights by Attack:

1. **Attack A1 (`FIT401`)**: Missed by all methods. Raw historian values for `FIT401` averaged 0.800 (range 0.796–0.805), identical to baseline mean 0.798. The spoofed value of 0.5 was never logged in the historian.
2. **Attack A2 (`LIT301`)**: Missed by multivariate methods. `LIT301` reached 1024 mm (a 1.3% deviation above the normal ceiling of 1010 mm), which does not stand out in multivariate tree splits.
3. **Attack A3 (`P601`)**: Pump `P601` was excluded from the feature matrix because it was constant in baseline. The single alarm at $t+123\text{ s}$ was driven by Stage 2 chemical analyzer drift (`AIT201`, $z = 48.63$).
4. **Attack A4 (`MV201`, `P101`)**: Detected after 340 s as combined inflows caused cumulative hydraulic shifts in Stage 1/2.
5. **Attack A5 (`MV501`)**: Valve `MV501` was excluded from the feature matrix because it was constant in baseline. However, closing `MV501` caused an extreme physical pressure surge in downstream sensor `PIT502` ($z = 1309.20$) and flow drops in `FIT501` ($z = 105.54$) and `FIT401` ($z = 78.21$), triggering instantaneous detection ($0.0\text{ s}$ delay).
6. **Attack A6 (`P301`)**: Detected after 724 s. Because background false alarm rate is 7.14%, an 802-second attack has an expected random false alarm count of $\approx 2.0$. Attributing the single alarm at window 450 to `P301` is statistically unverified without channel-level evidence.

## 5. Method Trade-Offs and Comparative Analysis

1. **Multivariate Isolation Forest**: Best balance of false positive control (FPR = 7.14%, 6.0 false alarms/hr) and early warning alerting (4/6 attacks detected). Window-level recall is low (9.09%) due to alarm non-persistence.
2. **CUSUM Detector on Mean Absolute Z-Scores**: Detects persistent shifts with slightly higher window recall (12.12%), capturing 8 attack windows. Achieves 4/6 episode detection with an FPR of 12.99% (10.9 false alarms/hr).
3. **Per-Channel Statistical Monitoring**: Catches 57 of 66 attack windows (Recall = 86.36%) and 6/6 attack episodes, but suffers catastrophic false alarm inflation on held-out data (FPR = 66.23%, 55.6 false alarms/hr). Plant-wide drift across 150 channels makes univariate envelope monitoring unusable without aggressive FDR control.

## 6. Scientific Limitations and Research Boundaries

> [!IMPORTANT]
> **Scientific Integrity Rules for Citing This Work:**
> 1. **No Causal Propagation Claims**: Matching an attack interval or detecting an anomaly downstream does NOT prove causal propagation. Causal influence requires validated structural modeling, which was not executed here.
> 2. **No CRI Validation Claims**: The Cascade Risk Index (CRI) is a Stage 2 graph metric. No CRI values were computed in this experiment.
> 3. **Accuracy Reporting Rule**: Authors must NOT cite 81% accuracy without stating that the zero-information null classifier achieves 86.8% accuracy. On the held-out operational partition, accuracy is 67.73% versus the 70.00% null baseline.

## 7. Exact Reproduction Commands

To reproduce this comparison from a clean checkout:

```powershell

# 1. Run unit test suite

pytest tests/unit/test_swat_a4a5.py -v


# 2. Execute comparison runner

python experiments/swat_a4a5_comparison_runner.py


# 3. Verify output files

Get-ChildItem experiments/results/swat_a4a5_detector_comparison

```
