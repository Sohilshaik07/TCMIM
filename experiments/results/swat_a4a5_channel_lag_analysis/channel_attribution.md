# SWaT A4/A5 Channel Attribution and Alarm Observability Audit

**Analysis Date**: 2026-10-26T13:14:06Z  
**Dataset SHA-256**: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`  
**Evaluation Partition**: Primary Held-Out Operational Windows 280–499 (06:50:00 – 08:40:00 UTC, $N=220$)  
**Baseline Reference**: Windows 10–279 (04:35:00 – 06:50:00 UTC, $N=270$, duration = 2.25 hours)  

---

## Executive Summary

This investigation audits the sensor channel contributions to detector alarms across all four Stage 1 detectors (Multivariate Isolation Forest, Sequential CUSUM, Baseline-Calibrated Max-Z, and Fixed 3-Sigma Shewhart) during the held-out operational partition of the SWaT A4/A5 July 2019 dataset.

### Key Scientific Findings:
1. **Actuator Invisibility in Model Feature Space**: For Attack A3 (`P601`) and Attack A5 (`MV501`), **zero features representing the manipulated actuators were present in the model's feature set**. Both actuators were strictly constant throughout the 8,100-second baseline training sequence and were systematically excluded as zero-variance features ($\sigma < 10^{-12}$). Consequently, neither Isolation Forest, CUSUM, nor Max-Z could observe the manipulated actuator itself.
2. **Alarm Coincidence vs. Attribution**: In Attack A3 (`P601`), the alarm triggered by Isolation Forest (Window 358) was dominated by continuous plantwide chemical drift on `AIT201__mean` ($z = 57.94$) and ultrafiltration membrane differential pressure `DPIT301__range` ($z = 8.08$). Attributing this alarm to `P601` is physically and mathematically impossible because `P601` was not in the model.
3. **Downstream Hydraulic Observability**: In Attack A5 (`MV501`), closing the reject valve induced massive hydraulic pressure surges on downstream vessel pressure `PIT502` ($z = 4502.04$ slope, $z = 3443.41$ range, $z = 2845.84$ mean). The models successfully observed the *physical downstream hydraulic consequence*, not the actuator itself.
4. **Historian Ground-Truth Timestamp Misalignment in A1 and A2**: Detailed inspection of raw telemetry reveals that documented attack intervals do not align with physical sensor manipulations:
   - **Attack A1 (`FIT401`)**: The spoofing of `FIT401` to 0.500 occurred from **07:07:00 to 07:08:45 UTC**, *prior* to the documented schedule of 07:08:46 to 07:10:31. During the documented window, `FIT401` was already back to its normal 0.800 flow.
   - **Attack A2 (`LIT301`)**: The spoofing of `LIT301` to 1024.0 occurred at **07:13:27 UTC** (1.5 minutes early) and returned to normal at **07:17:48 UTC** (almost 2 minutes before the documented end of 07:19:32).

---

## 1. Methodology: Standardized Deviations ($z$-scores)

To evaluate channel contribution without label leakage, all feature deviations are computed relative to the mean and sample standard deviation of the **in-sample baseline period** (Windows 10..279, $N=270$):
$$z_{w, j} = \frac{f_{w, j} - \mu_{j, \text{base}}}{\sigma_{j, \text{base}}}$$
Where:
- $f_{w, j}$ is the value of feature $j$ in window $w$.
- $\mu_{j, \text{base}}$ is the baseline mean of feature $j$.
- $\sigma_{j, \text{base}}$ is the baseline sample standard deviation (ddof=1) of feature $j$.
- Constant baseline features ($\sigma_{j, \text{base}} < 10^{-12}$) are excluded prior to model fitting and scoring.

---

## 2. Actuator Feature Usability Audit

The feature extraction pipeline extracted 335 total multimodal features per window across all 77 telemetry channels. In accordance with standard machine learning practice, zero-variance features during baseline were excluded.

The table below documents the presence and usability of features for all 7 documented attack targets:

| Attack ID | Target Tag | Modality / Device Type | Total Features Extracted | Baseline Variability ($\sigma_{\text{base}}$) | Usable Features in Model | Excluded Constant Features | Feature Usability Status |
|---|---|---|:---:|:---:|:---:|:---:|---|
| **A1** | `FIT401` | Flow Transmitter (Stage 4) | 2 | $\sigma_{\text{mean}} = 0.002$ m3/h | **2** (`mean`, `std`) | 0 | **Usable in Model** |
| **A2** | `LIT301` | Level Transmitter (Stage 3) | 2 | $\sigma_{\text{mean}} = 77.39$ mm | **2** (`mean`, `std`) | 0 | **Usable in Model** |
| **A3** | `P601` | Backwash Pump (Stage 6) | 5 | $\sigma = 0.000$ (state = 1) | **0** | **5** (`mode`, `duty`, `n_trans`, `first`, `last`) | **EXCLUDED (Invisible)** |
| **A4** | `MV201` | Motorized Valve (Stage 2) | 5 | $\sigma_{\text{state}} = 0.499$ | **5** (`mode`, `duty`, `n_trans`, `first`, `last`) | 0 | **Usable in Model** |
| **A4** | `P101` | Raw Water Pump (Stage 1) | 5 | $\sigma_{\text{state}} = 0.487$ | **5** (`mode`, `duty`, `n_trans`, `first`, `last`) | 0 | **Usable in Model** |
| **A5** | `MV501` | RO Reject Valve (Stage 5) | 5 | $\sigma = 0.000$ (state = 2) | **0** | **5** (`mode`, `duty`, `n_trans`, `first`, `last`) | **EXCLUDED (Invisible)** |
| **A6** | `P301` | UF Feed Pump (Stage 3) | 5 | $\sigma_{\text{state}} = 0.500$ | **5** (`mode`, `duty`, `n_trans`, `first`, `last`) | 0 | **Usable in Model** |

### Architectural Implication:
- For **A3 (`P601`)** and **A5 (`MV501`)**, any alarm triggered by Isolation Forest, CUSUM, or Max-Z cannot possibly be driven by features of `P601` or `MV501`. 
- Claims that an anomaly detector "detected the pump attack" or "detected the valve attack" are structurally false; the model detected background sensor drift or downstream hydraulic pressure transients.

---

## 3. Attack-by-Attack Attribution Audit

### Attack A1: `FIT401` (De-chlorination flow spoofing)
- **Documented Action**: Spoof flow transmitter `FIT401` from 0.8 to 0.5 m3/h.
- **Documented Schedule**: 07:08:46 – 07:10:31 UTC (Windows 317–321).
- **Historian Telemetry Reality**:
  - Telemetry reveals `FIT401` dropped to 0.500 at **07:07:00 UTC** and jumped back to 0.799 at **07:08:45 UTC**.
  - During the documented attack interval (07:08:46 – 07:10:31), `FIT401` was operating normally at 0.800 m3/h ($\mu = 0.800$, $\sigma = 0.002$).
  - Window 317 (07:08:30 – 07:09:00) caught the upward step transition back to normal, producing `FIT401__std` $z = 352.42$ and `FIT401__mean` $z = 115.83$.
- **Detector Behavior**:
  - **Per-Channel Max-Z**: Flagged Window 317 ($z = 352.42 > \tau = 7.88$). Direct target attribution verified.
  - **Shewhart**: Flagged Window 317 ($z = 352.42 > 3.0$).
  - **Isolation Forest**: Flagged **0 / 5 windows**. The multivariate tree ensemble anomaly score for Window 317 was 0.0197 (normal threshold $\le 0.0$). A single extreme feature out of 150 failed to sufficiently shorten path lengths across trees dominated by normal sensor correlations.
  - **CUSUM**: Flagged **0 / 5 windows**. The mean absolute z-score of Window 317 spiked to 3.12, but slack allowance ($k = 0.798$) and threshold ($h = 5.891$) required persistent cumulative drift that did not accumulate over a single 30s window.

### Attack A2: `LIT301` (UF Tank level spoofing)
- **Documented Action**: Spoof tank level transmitter `LIT301` from 835 to 1024 mm.
- **Documented Schedule**: 07:15:00 – 07:19:32 UTC (Windows 330–339).
- **Historian Telemetry Reality**:
  - `LIT301` jumped to 1024.0 at **07:13:27 UTC** (93 seconds before documented start).
  - `LIT301` dropped back to 789.3 mm at **07:17:48 UTC** (104 seconds before documented end).
  - In Window 335 (07:17:30 – 07:18:00), the downward step transition generated `LIT301__std` $z = 78.73$.
- **Detector Behavior**:
  - **Per-Channel Max-Z & Shewhart**: Flagged Window 335 ($z = 78.73$). Direct target attribution verified.
  - **Isolation Forest & CUSUM**: Flagged **0 / 10 windows**. Both missed the episode.

### Attack A3: `P601` (Backwash pump state manipulation)
- **Documented Action**: Switch pump `P601` from OFF (1) to ON (2).
- **Documented Schedule**: 07:26:57 – 07:30:48 UTC (Windows 353–361).
- **Actuator Usability**: `P601` had 0 features in the model.
- **Detector Behavior**:
  - **Isolation Forest**: Flagged Window 358 (07:29:00 UTC). Top deviating features:
    1. `AIT201__mean` ($z = 57.94$) — Stage 2 conductivity analyzer
    2. `DPIT301__range` ($z = 8.08$) — Stage 3 membrane differential pressure
    3. `DPIT301__std` ($z = 7.06$)
    4. `MV302__n_transitions` ($z = 6.62$)
    5. `DPIT301__slope` ($z = 6.60$)
  - **CUSUM**: Flagged **0 / 9 windows**.
  - **Max-Z & Shewhart**: Flagged all 9 windows. However, every single window was flagged by `AIT201__mean` ($z = 25.44$ to $z = 55.92$), **not by any Stage 6 channel**.
- **Attribution Verdict**: **Pure Alarm Coincidence**. The alarm coincided temporally with the attack window but was triggered exclusively by unmodeled slow chemical drift in Stage 2 (`AIT201`).

### Attack A4: `MV201` and `P101` (Dual valve and pump manipulation)
- **Documented Action**: Switch valve `MV201` to OPEN and pump `P101` to ON.
- **Documented Schedule**: 07:38:50 – 07:46:20 UTC (Windows 377–392).
- **Actuator Usability**: Both actuators present (5 features each).
- **Detector Behavior**:
  - **Isolation Forest**: Flagged Window 389 (07:44:30 UTC). Top deviating features:
    1. `AIT201__mean` ($z = 32.10$)
    2. `P101__n_transitions` ($z = 6.12$) — **Target actuator feature present**
    3. `P203__n_transitions` ($z = 6.12$)
    4. `P205__n_transitions` ($z = 6.12$)
    5. `FIT201__std` ($z = 3.58$)
  - **CUSUM**: Flagged Window 385 (07:42:30 UTC). Top features: `AIT201__mean` ($z = 38.67$), `FIT501__mean` ($z = 3.18$), `FIT504__mean` ($z = 2.82$). Target actuators absent from top features.
  - **Max-Z & Shewhart**: Flagged all 16 windows. In all 16 windows, `AIT201__mean` was the dominant feature ($z = 31.0$ to $54.7$).
- **Attribution Verdict**: **Partial Observability / Secondary Dominance**. In Window 389, `P101` transition activity was observed, but `AIT201` chemical drift contributed 5x larger standardized deviation.

### Attack A5: `MV501` (RO reject valve closure)
- **Documented Action**: Switch valve `MV501` from OPEN to CLOSE.
- **Documented Schedule**: 07:54:00 – 07:56:00 UTC (Windows 408–411).
- **Actuator Usability**: `MV501` had 0 features in the model.
- **Detector Behavior**:
  - **Isolation Forest**: Flagged Windows 408, 409, 410. Top deviating features:
    - Window 408: `PIT502__mean` ($z = 2845.84$), `PIT502__rms` ($z = 2845.64$), `PIT502__median` ($z = 2815.20$).
    - Window 409: `PIT502__slope` ($z = 4502.04$), `PIT502__range` ($z = 3443.41$), `PIT502__std` ($z = 3175.28$).
    - Window 410: `PIT502__range` ($z = 603.55$), `PIT502__slope` ($z = 532.97$).
  - **CUSUM**: Flagged Windows 408, 409, 410. Driven by the same `PIT502` surge.
  - **Max-Z & Shewhart**: Flagged all 4 windows.
- **Attribution Verdict**: **Downstream Physical Hydraulic Consequence**. The detector observed the violent fluid-dynamic backpressure spike on vessel pressure transmitter `PIT502` caused by valve closure. The actuator was unobserved, but the physical propagation effect was observed.

### Attack A6: `P301` (UF pump halt)
- **Documented Action**: Switch pump `P301` from ON (2) to OFF (1).
- **Documented Schedule**: 08:02:56 – 08:16:18 UTC (Windows 425–452).
- **Actuator Usability**: `P301` present (5 features).
- **Detector Behavior**:
  - **Isolation Forest**: Flagged Window 450 (08:15:00 UTC, near end of attack). Top deviating features:
    1. `AIT201__mean` ($z = 30.63$)
    2. `AIT303__mean` ($z = 13.13$)
    3. `DPIT301__iqr` ($z = 12.46$)
    4. `DPIT301__slope` ($z = 9.97$)
    5. `DPIT301__std` ($z = 9.33$)
    Target tag `P301` was absent from the top 5 deviating features.
  - **CUSUM**: Flagged Windows 430, 437, 444, 451. Top features were `AIT201__mean` ($z = 30.6$) and `AIT303__mean` ($z = 14.4$).
- **Attribution Verdict**: **Indirect Consequence / Secondary Dominance**. When `P301` stopped, membrane differential pressure `DPIT301` collapsed. Isolation Forest caught the membrane pressure collapse in Window 450, while chemical analyzer drift (`AIT201`, `AIT303`) remained the largest standardized deviation.

---

## 4. Separation Matrix: Observability vs. Coincidence

| Attack | Documented Target | Target Usable in Model? | Target Present in Top Deviations? | Dominant Deviating Channels | Attribution Classification |
|---|---|:---:|:---:|---|---|
| **A1** | `FIT401` | YES | YES (Window 317 only) | `FIT401` ($z = 352.42$) | **Direct Target Observability** (Missed by IF/CUSUM) |
| **A2** | `LIT301` | YES | YES (Window 335 only) | `LIT301` ($z = 78.73$) | **Direct Target Observability** (Missed by IF/CUSUM) |
| **A3** | `P601` | **NO** | **NO** | `AIT201` ($z = 57.94$), `DPIT301` ($z = 8.08$) | **Alarm Coincidence** (Drift on unrelated channels) |
| **A4** | `MV201`, `P101` | YES | YES (`P101` in Window 389) | `AIT201` ($z = 32.10$), `P101` ($z = 6.12$) | **Secondary Dominance** (Target observable, drift larger) |
| **A5** | `MV501` | **NO** | **NO** | `PIT502` ($z = 4502.04$), `PIT502` ($z = 2845.84$) | **Physical Downstream Consequence** (Hydraulic shock) |
| **A6** | `P301` | YES | **NO** | `AIT201` ($z = 30.63$), `DPIT301` ($z = 12.46$) | **Downstream Consequence & Coincidence** |

---

## 5. Why An Alarm Cannot Automatically Be Attributed to an Attack

In industrial cybersecurity benchmarks, researchers frequently equate **alarm coincidence** (an alarm firing while an attack is active) with **attack detection** (the model recognizing the attack mechanism). This audit demonstrates that this assumption is scientifically invalid for three reasons:

1. **Unmodeled Actuators Cannot Drive Alarms**: When an actuator has zero variance during normal operation, machine learning models drop it. If an alarm fires during that attack, it is mathematically impossible for the actuator to be the cause of the alarm.
2. **Persistent Sensor Drift Creates Continuous False Triggers**: Chemical analyzer `AIT201` suffered from persistent drift throughout the 4-hour recording, reaching $z$-scores exceeding 50. Any detector monitoring standardized deviations (Max-Z, Shewhart, CUSUM) fired continuously across A3, A4, and A6 due to `AIT201`, completely independent of the physical attack.
3. **Downstream Propagation Changes the Measured Channel**: Even when an attack successfully alters plant dynamics (e.g., A5 valve closure), the detector observes the *hydraulic shockwave* (`PIT502`), not the actuator (`MV501`). In Stage 2 influence modeling, attributing this anomaly to an edge originating at `MV501` requires a physical model or structural knowledge, not merely a statistical correlation.
