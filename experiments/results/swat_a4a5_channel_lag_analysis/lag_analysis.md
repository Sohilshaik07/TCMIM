# SWaT A4/A5 Lagged Cross-Correlation and Physical Sensor Coupling Analysis

**Analysis Date**: 2026-10-26T13:14:06Z  
**Dataset SHA-256**: `39ea28e3d0e5ba1507ba551630bee232ce2cf66abdc9da978391dc00a989bbdc`  
**Sampling Rate**: 1 Hz (1-second sampling interval, 14,996 total records)  
**Sign Convention**: A positive lag ($\tau > 0$) indicates that the source channel leads the target channel by $\tau$ seconds ($x_t$ is correlated with $y_{t+\tau}$).

---

## Executive Summary

This study evaluates whether the 1 Hz telemetry in the SWaT A4/A5 July 2019 dataset supports meaningful, physically interpretable lagged relationships for Stage 2 dynamic influence modeling. 

We investigated five predeclared sensor pairs grounded in chemical and hydraulic process engineering:
1. **`P301` $\to$ `DPIT301` (Stage 3)**: UF feed pump actuation to membrane differential pressure.
2. **`FIT501` $\to$ `PIT501` (Stage 5)**: Reverse Osmosis (RO) feed pump discharge flow to membrane inlet pressure.
3. **`FIT501` $\to$ `FIT502` (Stage 5)**: RO feed flow to RO permeate flow (membrane mass separation).
4. **`FIT201` $\to$ `LIT301` (Cross-Stage P2 $\to$ P3)**: Stage 2 inflow to Stage 3 tank level accumulation.
5. **`MV501` $\to$ `PIT502` (Stage 5)**: RO reject valve closure to vessel pressure transient.

### Core Discoveries:
1. **Severe Autocorrelation and Spurious Level Correlation**: All continuous telemetry channels exhibit extreme inertia ($\rho_1 \ge 0.998$). On raw sensor levels, cross-correlation curves peak at the arbitrary boundary of the search window (e.g., $\tau = -120$ s for `FIT201` $\to$ `LIT301`), reflecting common slow trends rather than physical transport delay.
2. **Confirmed Physical Actuation Lag (`P301` $\to$ `DPIT301`)**: When pre-whitened via first differencing ($\Delta x_t, \Delta y_t$), the physical actuation relationship between pump `P301` and membrane differential pressure `DPIT301` is statistically and physically robust across both normal baseline ($r = 0.3703$, $\tau = +5$ s) and held-out attack periods ($r = 0.3739$, $\tau = +4$ s; Attack A6 $r = 0.4754$, $\tau = +4$ s). This 4–5 second lag represents the fluid inertia and pressure transducer settling time.
3. **The Event-Induced Correlation Fallacy**: In normal steady-state baseline, variables like `FIT501` and `PIT501` operate within narrow control bands ($\sigma_{\text{flow}} = 0.001$ m3/h), exhibiting zero correlation ($r = 0.0448$). However, during held-out operations containing plant shutdowns and attacks, correlation jumps to $-0.9197$. **High correlation in held-out data is an artifact of shared macro-disturbances, not an identifiable baseline transfer function.**
4. **Zero Baseline Observability for Valves**: Actuators such as `MV501` were never operated during the 2.25-hour baseline. Models trained on baseline cannot learn any edges from `MV501`, preventing Stage 2 from anticipating its influence prior to an attack.

---

## 1. Candidate Sensor Pairs and Physical Architecture

| Pair ID | Source Channel ($x$) | Target Channel ($y$) | Stages | Physical Coupling Mechanism | Predeclared Search Range |
|---|---|---|:---:|---|:---:|
| **PAIR_01** | `P301` (UF Pump State) | `DPIT301` (Differential Pressure) | P3 $\to$ P3 | Pump actuation forces fluid through UF membrane, building trans-membrane differential pressure. | $[-30\text{ s}, +30\text{ s}]$ |
| **PAIR_02** | `FIT501` (RO Feed Flow) | `PIT501` (RO Inlet Pressure) | P5 $\to$ P5 | High-pressure pump P501 discharge flow directly builds inlet membrane pressure across RO elements. | $[-30\text{ s}, +30\text{ s}]$ |
| **PAIR_03** | `FIT501` (RO Feed Flow) | `FIT502` (RO Permeate Flow) | P5 $\to$ P5 | Conservation of mass across RO separation: $Q_{\text{in}} = Q_{\text{permeate}} + Q_{\text{reject}}$. | $[-60\text{ s}, +60\text{ s}]$ |
| **PAIR_04** | `FIT201` (Stage 2 Inflow) | `LIT301` (UF Tank Level) | P2 $\to$ P3 | Inflow from Stage 2 accumulates in tank T301: $\frac{dh}{dt} = \frac{Q_{\text{in}} - Q_{\text{out}}}{A_{\text{tank}}}$. | $[-120\text{ s}, +120\text{ s}]$ |
| **PAIR_05** | `MV501` (RO Reject Valve) | `PIT502` (Vessel Pressure) | P5 $\to$ P5 | Closing reject valve causes sudden fluid deceleration and water hammer backpressure surge in RO vessel. | $[-30\text{ s}, +30\text{ s}]$ |

---

## 2. Telemetry Characteristics and Baseline Variability

All 77 channels contain zero missing values across the entire 14,996-second recording.

| Channel | Physical Description | Engineering Units | Baseline Mean ($\mu_{\text{base}}$) | Baseline Std ($\sigma_{\text{base}}$) | Distinct Values | Dynamic Range Status |
|---|---|:---:|:---:|:---:|:---:|---|
| `P301` | UF Feed Pump 1 | Discrete (1=OFF, 2=ON) | 1.481 | 0.500 | 2 | Actively cycling in baseline |
| `DPIT301` | Differential Pressure across UF | kPa | 6.607 | 5.637 | 358 | Wide dynamic swing (1.1 to 12.9 kPa) |
| `FIT501` | RO Feed Flow Transmitter | m3/h | 0.800 | 0.001 | 64 | Near-constant in baseline (0.794 – 0.807) |
| `PIT501` | RO Feed Pressure Transmitter | bar / kPa | 160.658 | 0.470 | 113 | Narrow band in baseline (159.9 – 163.3) |
| `FIT502` | RO Permeate Flow Transmitter | m3/h | 0.331 | 0.023 | 665 | Moderate variability (0.246 – 0.383) |
| `FIT201` | Stage 2 Water Flow Transmitter | m3/h | 2.441 | 0.038 | 180 | Steady controlled delivery |
| `LIT301` | UF Tank T301 Level | mm | 931.020 | 77.394 | 2250 | Cyclic sawtooth filling/draining |
| `MV501` | RO Reject Motorized Valve | Discrete (1=OPEN, 2=CLOSE) | 2.000 | **0.000** | 1 | **Completely static in baseline** |
| `PIT502` | RO Intermediate Pressure | bar / kPa | 2.947 | 0.068 | 18 | Narrow band (2.819 – 3.188) |

---

## 3. Quantitative Lagged Cross-Correlation Results

To eliminate spurious correlation from non-stationarity, we report both **Raw Levels** ($x_t, y_t$) and **Pre-Whitened First Differences** ($\Delta x_t = x_t - x_{t-1}, \Delta y_t = y_t - y_{t-1}$):

| Pair ID | Evaluated Partition | Samples ($N$) | Raw Peak $r$ | Raw Lag ($\tau$) | Raw $\rho_1(x)$ | Raw $\rho_1(y)$ | Diff Peak $r$ | Diff Lag ($\tau$) | Diff $\rho_1(x)$ | Diff $\rho_1(y)$ | Scientific Validity Verdict |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **PAIR_01** (`P301` $\to$ `DPIT301`) | Baseline (04:35–06:50) | 8,096 | **+0.9900** | +8 s | 0.999 | 1.000 | **+0.3703** | **+5 s** | 0.000 | 0.915 | **Validated Physical Actuation** |
| **PAIR_01** (`P301` $\to$ `DPIT301`) | Held-Out (06:50–08:40) | 6,600 | **+0.9872** | +7 s | 0.998 | 1.000 | **+0.3739** | **+4 s** | 0.000 | 0.926 | **Validated Physical Actuation** |
| **PAIR_01** (`P301` $\to$ `DPIT301`) | Attack A6 Window | 960 | **+0.9974** | +6 s | 0.997 | 1.000 | **+0.4754** | **+4 s** | -0.001 | 0.943 | **Pump Trip Depressurization** |
| **PAIR_02** (`FIT501` $\to$ `PIT501`) | Baseline (04:35–06:50) | 8,096 | -0.2689 | +30 s | 0.922 | 0.997 | **+0.0448** | +1 s | 0.117 | 0.114 | **Noise Dominated in Normal State** |
| **PAIR_02** (`FIT501` $\to$ `PIT501`) | Held-Out (06:50–08:40) | 6,600 | -0.9982 | -1 s | 0.999 | 0.999 | **-0.9197** | -1 s | 0.883 | 0.936 | **Event-Induced Spurious Coupling** |
| **PAIR_03** (`FIT501` $\to$ `FIT502`) | Baseline (04:35–06:50) | 8,096 | +0.1328 | +58 s | 0.922 | 0.961 | **-0.0316** | +32 s | 0.117 | 0.178 | **Noise Dominated in Normal State** |
| **PAIR_03** (`FIT501` $\to$ `FIT502`) | Held-Out (06:50–08:40) | 6,600 | +0.9656 | -4 s | 0.999 | 0.992 | **+0.4405** | -4 s | 0.883 | 0.354 | **Event-Induced Spurious Coupling** |
| **PAIR_04** (`FIT201` $\to$ `LIT301`) | Baseline (04:35–06:50) | 8,096 | -0.8159 | -120 s | 1.000 | 1.000 | **-0.1181** | -40 s | 0.967 | 0.342 | **Integrator Confounding** |
| **PAIR_04** (`FIT201` $\to$ `LIT301`) | Held-Out (06:50–08:40) | 6,600 | -0.6074 | -120 s | 1.000 | 0.999 | **-0.2033** | -18 s | 0.933 | 0.004 | **Integrator Confounding** |
| **PAIR_05** (`MV501` $\to$ `PIT502`) | Baseline (04:35–06:50) | 8,096 | 0.0000 | 0 s | 0.000 | 0.000 | **0.0000** | 0 s | 0.000 | 0.000 | **Zero Variance (Unobservable)** |
| **PAIR_05** (`MV501` $\to$ `PIT502`) | Held-Out (06:50–08:40) | 6,600 | -0.8874 | 0 s | 0.974 | 0.999 | **-0.2038** | -1 s | 0.000 | 0.969 | **Transient-Induced Correlation** |
| **PAIR_05** (`MV501` $\to$ `PIT502`) | Attack A5 Window | 300 | -0.9488 | -1 s | 0.971 | 0.999 | **-0.3999** | -1 s | -0.001 | 0.964 | **Hydraulic Water Hammer Spike** |

---

## 4. Deep-Dive Interpretation of Physical Pairs

### A. PAIR_01: `P301` $\to$ `DPIT301` (Confirmed Dynamic Edge)
- **Physical Context**: Pump `P301` operates intermittently to feed water through the ultrafiltration membrane.
- **Empirical Consistency**:
  - In baseline, switching `P301` from OFF to ON correlates with `DPIT301` rising from ~1.1 kPa to ~12.5 kPa.
  - The raw cross-correlation is $0.9900$.
  - Differencing eliminates level persistence ($\rho_1(x) = 0.000$). The differenced cross-correlation achieves a sharp, clean peak at $\tau = +5$ seconds ($r = 0.3703$, $p < 10^{-50}$).
  - In held-out operations, the differenced peak occurs at $\tau = +4$ seconds ($r = 0.3739$).
  - During Attack A6 (where `P301` was maliciously switched OFF), the differenced correlation peaks at $\tau = +4$ seconds ($r = 0.4754$).
- **Scientific Conclusion**: **This is a genuine, physically verifiable transfer function.** Fluid inertia, check valve opening dynamics, and pressure transducer sensor lag combine to create an empirical 4- to 5-second delay between pump command execution and full membrane differential pressure establishment. Stage 2 dynamic DAG construction can legitimately place a directed edge from `P301` to `DPIT301` with nominal delay $\tau = 4\text{ s} \pm 1\text{ s}$.

### B. PAIR_02 & PAIR_03: The Event-Induced Correlation Fallacy
- **The Phenomenon**: In baseline, `FIT501` $\to$ `PIT501` has zero differenced correlation ($r = 0.0448$). In held-out, it jumps to $r = -0.9197$.
- **Why did this occur?**
  - In normal operation, high-pressure pump P501 runs continuously under closed-loop PI speed control. Flow fluctuates within a tiny band of $\pm 0.001$ m3/h. The recorded 1 Hz signals represent minor high-frequency measurement noise and hydraulic turbulence, which do not correlate linearly across sensor locations.
  - In held-out operation, major plant events occurred: Attack A5 (valve closed), Attack A6 (feed pump tripped), and the final plant shutdown at 08:35 UTC. During these events, **both flow and pressure simultaneously collapsed toward zero**.
  - Standard cross-correlation calculates covariance over the entire series. Because both signals experienced massive concurrent downward steps, the statistical estimator calculates $r \approx -0.92$.
- **Scientific Caution**: This correlation does NOT reflect a high-fidelity dynamic transfer function. It merely reflects **common external forcing (plant shutdown / attack intervention)**. Attempting to fit a Stage 2 ARX or transfer-function model on held-out data would fit the shutdown trajectory rather than the true inter-machine hydraulic physics.

### C. PAIR_04: `FIT201` $\to$ `LIT301` (The Integrator Confounding Effect)
- **The Phenomenon**: Cross-correlating raw `FIT201` flow and `LIT301` tank level yielded $r = -0.8159$ at the search window boundary ($\tau = -120$ s).
- **Physical Reason**: A fluid storage tank is an ideal integrator:
  $$h(t) = h(0) + \frac{1}{A} \int_0^t (Q_{\text{in}}(\tau) - Q_{\text{out}}(\tau)) d\tau$$
- Tank level $h(t)$ is non-stationary ($I(1)$ with $\rho_1 = 1.000$). When cross-correlating a flow rate with an integrated level, the cross-correlation does not exhibit a local peak corresponding to fluid velocity; instead, it exhibits monotonic drift that peaks at whatever maximum lag the investigator allows.
- Without measuring or including $Q_{\text{out}}$ (discharge from pump `P301`), cross-correlation between single-channel inflow and level is physically uninterpretable.

### D. PAIR_05: `MV501` $\to$ `PIT502` (The Missing Baseline Variance Problem)
- **The Phenomenon**: During baseline training, valve `MV501` had zero state transitions ($\sigma = 0.000$). Cross-correlation is mathematically undefined (or zero).
- In Attack A5, `MV501` was closed, producing a pressure spike on `PIT502` to 3,000 kPa ($r = -0.9488$ at $\tau = -1$ s).
- **Implication for Stage 2**: A data-driven model trained on normal operating data **cannot learn any relationship between `MV501` and `PIT502`**. Stage 2 cannot assign influence weights or cascade risk to unexercised actuators without structural P&ID prior knowledge.

---

## 5. Statistical Rigor and Confounding Controls

### Autocorrelation and Effective Sample Size
When computing significance for time series with high autocorrelation ($\rho_1 \approx 0.999$), the nominal sample size $N = 8,096$ is severely misleading. According to Bartlett's formula:
$$N_{\text{eff}} \approx N \frac{1 - \rho_x \rho_y}{1 + \rho_x \rho_y}$$
For $\rho_x = 0.999$ and $\rho_y = 0.999$, $N_{\text{eff}} \approx 8,096 \times \frac{0.002}{1.998} \approx 8.1$ independent observations. 
Standard $p$-values computed on raw levels are wildly anti-conservative and generate massive false-positive edge discoveries. Pre-whitening via differencing is mandatory for Stage 2 edge candidate selection.
