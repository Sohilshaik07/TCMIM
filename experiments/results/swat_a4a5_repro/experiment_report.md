# TCMIM SWaT A4/A5 July 2019 Experiment Report

**Execution Date**: 2026-10-26T10:57:18.875354+00:00  
**Protocol**: protocol_a  
**Dry-run**: False  
**Random Seed**: 42  

## 1. Verified Source Files and Provenance

| File Role | Name | Size (Bytes) | SHA-256 Hash |
|---|---|---|---|
| workbook | `SWaT_dataset_Jul 19 v2.xlsx` | 5,536,097 | `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc` |
| schedule_pdf | `SWaT data collection_20-07-2019 v2.pdf` | 65,482 | `ebeedfdb044167111a28fc859c099d3b9d07a4f5c1b832cba4ed2e54860f3256` |
| readme | `readme.docx` | 15,702 | `6fe2c7d5b622cb0b4de94e16e75d7dede8f961a4f7f7c06a8192da3569019aab` |


## 2. Telemetry and Sampling Cadence Verification

- **Total Rows**: 14,996
- **Time Span (UTC)**: 04:30:00 UTC to 08:39:59 UTC (4.17 hours)
- **Nominal Cadence**: 1.0 Hz
- **Observed Cadence**: Median = 1.00 s, Mean = 1.00 s
- **Maximum Internal Gap**: 5.45 s
- **Intervals > 3s**: 1
- **Documented Normal Period (04:35 - 06:50 UTC)**: 8,096 rows (99.95% continuous 1 Hz coverage)
- **Pre-Start Buffer (04:30 - 04:35 UTC)**: 300 rows

## 3. Official Attack Ground Truth and Coverage Verification

| Attack ID | Target Tags | Action | Start (UTC) | End (UTC) | Observed Rows | Coverage | Observability |
|---|---|---|---|---|---|---|---|
| A1 | `FIT401` | Spoof value from 0.8 to 0.5 | 07:08:46 | 07:10:31 | 105 | 100.0% | **OBSERVABLE** |
| A2 | `LIT301` | Spoof value from 835 to 1024 | 07:15:00 | 07:19:32 | 272 | 100.0% | **OBSERVABLE** |
| A3 | `P601` | Switch from OFF to ON | 07:26:57 | 07:30:48 | 232 | 100.4% | **OBSERVABLE** |
| A4 | `MV201, P101` | Switch from CLOSE to OPEN (MV201) and OFF to ON (P101) | 07:38:50 | 07:46:20 | 450 | 100.0% | **OBSERVABLE** |
| A5 | `MV501` | Switch from OPEN to CLOSE | 07:54:00 | 07:56:00 | 120 | 100.0% | **OBSERVABLE** |
| A6 | `P301` | Switch from ON to OFF | 08:02:56 | 08:16:18 | 802 | 100.0% | **OBSERVABLE** |


## 4. Window Eligibility and Gap-Safety Audit

- **Window Size**: 30 s (step = 30 s)
- **Total Sliding Windows**: 500
- **Eligible Windows**: 500 (100.0%)
- **Ineligible Windows (Excluded)**: 0 (due to internal gap > 15 s or < 2 samples)
- Complete window manifest recorded in `window_manifest.csv`.

## 5. Model Evaluation Metrics

- **Evaluated Windows**: 500
- **Excluded Windows (Unobservable Attacks)**: 0
- **Positive Windows**: 66 | **Negative Windows**: 434
- **Confusion Matrix**: TP = 6, FP = 35, TN = 399, FN = 60
- **Precision**: 0.1463
- **Recall**: 0.0909
- **F1 Score**: 0.1121
- **Accuracy**: 0.81

### Observable Attack Detection Breakdown

| Attack | Target Tags | Overlapping Windows | Detected? | First Alert Delay (s) |
|---|---|---|---|---|
| A1 | `FIT401` | 5 | NO | N/A |
| A2 | `LIT301` | 10 | NO | N/A |
| A3 | `P601` | 9 | **YES** | 123.0 s |
| A4 | `MV201, P101` | 16 | **YES** | 340.0 s |
| A5 | `MV501` | 4 | **YES** | 0.0 s |
| A6 | `P301` | 28 | **YES** | 724.0 s |


## 6. Scientific Limitations and Non-Execution of Stage 2

> [!IMPORTANT]
> **Stage 2 (Cross-Machine Influence Modeling and Cascade Risk Estimation) was deliberately NOT executed.**
> 
> **Scientific Rationale**:
> 1. **Hydraulic Coupling vs. Independent Machines**: SWaT process stages P1 through P6 are tightly coupled fluid loops with continuous recirculation (e.g. backwash return, reject lines). Treating them as independent physical machines without calibrated hydraulic lag parameters (V/Q) would falsely attribute hydraulic co-variation to causal failure cascade.
> 2. **Lack of Ground-Truth Propagation Edges**: The dataset provides ground-truth attack execution intervals on specific components, but NO validated ground-truth propagation edges across stages.
> 3. **Temporal Precedence != Causality**: Detection delay across stages is an empirical threshold-crossing lag, not proof of physical failure propagation.
> 4. **Limited Single-Session Extent**: With only ~4.17 hours of operation, multi-cycle causal edge lifecycle progression cannot be validated without risk of overfitting.