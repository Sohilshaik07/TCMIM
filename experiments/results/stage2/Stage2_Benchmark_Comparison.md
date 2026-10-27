# TCMIM Stage 2 - Comprehensive Benchmark Configuration Comparison
**Random Seeds Evaluated:** [42, 43, 44, 45, 46]  
**Configurations Evaluated:** 6  

---

## 1. Executive Summary: Configuration Comparison

| # | Configuration Name | Estimator | Min Edge State | Macro Precision | Macro Recall | Macro F1 | Macro FPR | Macro Lag MAE (s) | Filtered Edges |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Mean + Candidate Filter (Baseline)** | `mean` | `CANDIDATE` | 0.330 (n=7) | 1.000 (n=4) | 0.724 (n=4) | 0.531 | 8.69s | 0.0 |
| 2 | **Median + Candidate Filter** | `median` | `CANDIDATE` | 0.330 (n=7) | 1.000 (n=4) | 0.724 (n=4) | 0.531 | 0.75s | 0.0 |
| 3 | **Trimmed Mean (20%) + Candidate Filter** | `trimmed_mean` | `CANDIDATE` | 0.330 (n=7) | 1.000 (n=4) | 0.724 (n=4) | 0.531 | 4.41s | 0.0 |
| 4 | **Mean + Provisional Filter** | `mean` | `PROVISIONAL` | N/A | 0.000 (n=4) | N/A | 0.000 | N/A | 28.8 |
| 5 | **Median + Provisional Filter** | `median` | `PROVISIONAL` | N/A | 0.000 (n=4) | N/A | 0.000 | N/A | 28.8 |
| 6 | **Strict Stable Filter** | `median` | `STABLE` | N/A | 0.000 (n=4) | N/A | 0.000 | N/A | 28.8 |

> **Metric Definitions & Aggregations:**
> - **Undefined Metrics (Scientific Integrity):** When ground truth is empty (Negative Control, Common Cause, Reversed Order) or zero predictions are made,
>   precision, recall, and F1 are mathematically undefined and preserved as `None` / `null` / `N/A`. They are never converted to 1.0 or 0.0.
> - **Macro Metrics:** Unweighted arithmetic mean across scenarios where the metric is defined (reporting `n_defined` explicitly).
> - **Micro Metrics:** Aggregated across all scenario edge predictions. Total TP across all scenarios for
>   single-batch provisional/stable configs is 0 (since cold-start evidence is 1 < threshold 3), so Micro Precision = N/A and Micro Recall = 0.0.
> - **Standard Deviations:** Reported standard deviations use population std (`ddof=0`). For reference, sample
>   std (`ddof=1`) on the 5 seeds is 0.126 for Negative Control FPR (0.700 ± 0.126) and 0.224 for Noisy Cascade FPR (0.850 ± 0.224).

---

## 2. Noisy Cascade Delay Estimation Accuracy Across Seeds

Evaluates the primary target of robust delay aggregation: `scenario_7_noisy` with jitter, 15% dropout, and Poisson noise events.

| Configuration | Estimator | Graph View | Noisy Lag MAE mean+/-std (s) | Noisy Precision mean+/-std | Noisy Recall mean+/-std | Noisy FPR mean+/-std |
|---|---|---|---|---|---|---|
| **Mean + Candidate Filter (Baseline)** | `mean` | `CANDIDATE` | 34.77 +/- 40.50s | 0.380 +/- 0.065 | 1.000 +/- 0.000 | 0.850 +/- 0.200 |
| **Median + Candidate Filter** | `median` | `CANDIDATE` | 3.00 +/- 1.77s | 0.380 +/- 0.065 | 1.000 +/- 0.000 | 0.850 +/- 0.200 |
| **Trimmed Mean (20%) + Candidate Filter** | `trimmed_mean` | `CANDIDATE` | 17.62 +/- 26.57s | 0.380 +/- 0.065 | 1.000 +/- 0.000 | 0.850 +/- 0.200 |
| **Mean + Provisional Filter** | `mean` | `PROVISIONAL` | N/A (filtered) | N/A | 0.000 +/- 0.000 | 0.000 +/- 0.000 |
| **Median + Provisional Filter** | `median` | `PROVISIONAL` | N/A (filtered) | N/A | 0.000 +/- 0.000 | 0.000 +/- 0.000 |
| **Strict Stable Filter** | `median` | `STABLE` | N/A (filtered) | N/A | 0.000 +/- 0.000 | 0.000 +/- 0.000 |

---

## 3. False-Positive Filtering: Negative Control Across Seeds

Evaluates the capacity of confidence-filtered graph views to eliminate spurious candidate edges in independent streams (`scenario_4_negative_control`).

| Configuration | Graph View Filter | Negative Control FPR mean+/-std | Filtered Candidate Edges | Surviving False Positives |
|---|---|---|---|---|
| **Mean + Candidate Filter (Baseline)** | `CANDIDATE` | 0.700 +/- 0.113 | 0.0 / 12 | 8 |
| **Median + Candidate Filter** | `CANDIDATE` | 0.700 +/- 0.113 | 0.0 / 12 | 8 |
| **Trimmed Mean (20%) + Candidate Filter** | `CANDIDATE` | 0.700 +/- 0.113 | 0.0 / 12 | 8 |
| **Mean + Provisional Filter** | `PROVISIONAL` | 0.000 +/- 0.000 | 8.4 / 12 | 0 |
| **Median + Provisional Filter** | `PROVISIONAL` | 0.000 +/- 0.000 | 8.4 / 12 | 0 |
| **Strict Stable Filter** | `STABLE` | 0.000 +/- 0.000 | 8.4 / 12 | 0 |

---

## 4. Scientific Provenance & Methodological Trade-offs

1. **Delay Estimation Trade-offs:**
   - **Median Aggregation:** Provides near-optimal robustness against large asymmetric spurious delay pairs
     without discarding valid observations. Lag MAE on the noisy cascade drops by over 90% (3.00s vs 34.77s) compared to mean.
   - **Trimmed Mean (20%):** Symmetrically trims extreme values. Achieves 17.62s MAE. Effective when outlier pairs
     occur on both tails, but slightly less effective than median when noise events produce large positive delays.
   - **Arithmetic Mean:** Retains maximum statistical efficiency when delay errors are Gaussian and noise-free,
     but suffers severe degradation (34.77s MAE across seeds, and 113.11s on seed 42) due to uncorrelated spurious events within wide matching windows.

2. **Confidence Filtering & Multi-Cycle Dynamics:**
   - Filtering at `EdgeState.PROVISIONAL` or `EdgeState.STABLE` completely eliminates spurious edges
     in the negative control scenario (FPR = 0.000, 8.0 false candidate edges filtered).
   - In single-batch evaluation from a cold start, deterministic lifecycle transitions advance one step
     at a time (`NONE -> CANDIDATE`). Consequently, multi-cycle accumulation is required before true cascade
     edges reach provisional status.

3. **Integrity Boundaries:**
   - All benchmark data originates from synthetic fixtures (`Provenance.SYNTHETIC`).
   - These comparisons validate software integration, sensitivity, and mathematical trade-offs;
     they do NOT constitute empirical industrial proof of physical failure propagation.
   - Candidate, provisional, and stable graph edges reflect evidence accumulation, NOT physical causality.