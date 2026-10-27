# Engineering Parameter Gaps for Physical Delay Bound Calibration
## SWaT A4/A5 July 2019 Stage 2 Candidate-Edge Gating

**Document ID:** `TCMIM-SWAT-A4A5-ENG-GAPS-2026-10`  
**Date:** October 26, 2026  
**Status:** Complete & Independently Audited  
**Scope:** Identification of missing physical, hydraulic, and instrumentation parameters required to calibrate rigorous physical delay bounds $[d_{min}, d_{max}]$ across the five structurally permitted component relationships.

---

## 1. Executive Summary & Purpose

In the TCMIM Stage 2 pipeline, candidate propagation edges were initially matched using an unconstrained default delay window of $[0, 600\text{ s}]$. While Gate G0 (`G0_STRUCTURAL_MASK`) successfully reduced candidate explosion by 99.37% by enforcing topological connectivity, the surviving 22 observations still exhibit reported window-level delays ranging from 30.0s to 600.0s.

Empirical 1 Hz time series auditing reveals that true physical response times (e.g., valve stroke times of 9.5s–10.5s, pump start flow surges of <1s, and membrane pressurization times of 39s) are substantially tighter than the 600-second window. To replace heuristic windows with physically defensible bounds $[d_{min}, d_{max}]$, specific engineering parameters are required. 

This document audits the exact engineering parameter gaps across the SWaT facility, defines the physical equations required to calculate bounds, and establishes strict scientific safeguards against manufacturing synthetic physical constants.

---

## 2. Available vs. Missing Engineering Information

### 2.1 Available Information (From Public SWaT Release)
- **Component Tag Registry (`swat.py` / Data Collection Notes):** Component identifiers, functional descriptions (e.g., `MV201` = motorized valve, `P101` = raw water pump, `DPIT301` = differential pressure across UF), and nominal engineering units (e.g., $m^3/h$, $kPa$, $mV$).
- **Process Stage Hierarchy:** Logical grouping into Stages 1 through 6 (Raw Intake, Chemical Dosing, Ultrafiltration, De-chlorination, Reverse Osmosis, Backwash & Distribution).
- **Attack Intent Descriptions:** Textual summaries of cyber-physical attack scripts (e.g., "Switch MV201 OPEN and P101 ON to overflow tank T301").

### 2.2 Completely Missing Engineering Information
- **Piping and Instrumentation Diagrams (P&IDs):** Formal engineering drawing sheets (e.g., ISA-5.1 diagrams) detailing exact pipe routings, bypasses, manual valves, and branch connections.
- **Pipe Run Geometry:** Pipe nominal pipe size (NPS / diameter $D$), wall schedule, linear run lengths ($L$), elevation heads ($\Delta z$), and internal roughness ($\epsilon$).
- **Actuator Mechanical Specifications:** Motorized valve full stroke time ($T_{stroke}$), actuator motor RPM, valve trim characteristics ($C_v$ vs. % opening), and seat transit deadband.
- **Pump Performance Curves:** Pump manufacturer head-capacity curves ($H-Q$), shutoff head, rated motor kW, and mechanical rotational inertia ($J$).
- **Vessel & Skid Internal Volumes:** Ultrafiltration membrane housing volume, reverse osmosis pressure vessel liquid volume, and filter cake hold-up.
- **Sensor Response & Transmitter Conditioning:** Sensor probe response time constants ($T_{90}$ / $T_{95}$ for chemical analyzers), sample conditioning flow cell volumes, and transmitter digital damping filters ($\tau_{damp}$).

---

## 3. Theoretical Formulations for Physical Delay Bounds

To calculate rigorous delay bounds $[d_{min}, d_{max}]$ between a source component $u$ and target component $v$, the physical delay decomposes into four fundamental transport mechanisms:

$$\Delta t_{physical} = t_{actuation} + t_{acoustic} + t_{advective} + t_{sensor}$$

### 3.1 Actuator Mechanics ($t_{actuation}$)
For motorized valves (e.g., `MV201`), the transition from closed to open is not an instantaneous step:
$$t_{actuation} = T_{dead} + \int_0^{\theta_{crit}} \frac{d\theta}{\omega_{actuator}}$$
Where $\omega_{actuator}$ is the actuator rotational speed and $\theta_{crit}$ is the critical valve opening percentage where flow reaches measurable threshold.
- **Required parameters:** Motor stroke time ($T_{stroke}$), gearbox ratio, and valve plug characteristic curve ($C_v(\theta)$).
- **Available data:** None. Empirically estimated from raw 1 Hz data as $9.5\text{ s} - 10.5\text{ s}$.

### 3.2 Acoustic & Hydraulic Pressure Waves ($t_{acoustic}$)
Pressure disturbances (e.g., pump discharge surge from `P101` to `FIT101`, or `P301` to `DPIT301`) travel through fluid at the speed of sound in the conduit:
$$c_{pipe} = \sqrt{\frac{K / \rho}{1 + \frac{K D}{E e} c_1}}, \quad t_{acoustic} = \frac{L}{c_{pipe}}$$
Where $K$ is bulk modulus of water ($2.15 \times 10^9\text{ Pa}$), $\rho$ is density ($1000\text{ kg/m}^3$), $D$ is pipe diameter, $E$ is Young's modulus of pipe material (e.g., PVC or stainless steel), and $e$ is pipe wall thickness.
- For typical industrial water skids ($L \approx 5 - 20\text{ m}$), $c_{pipe} \approx 1000 - 1300\text{ m/s}$, resulting in:
$$t_{acoustic} \approx 0.004\text{ s} - 0.020\text{ s}$$
- **Engineering Implication:** Pressure transients are effectively **instantaneous** relative to 1 Hz telemetry and completely imperceptible at 30-second windowing.

### 3.3 Bulk Fluid Advection ($t_{advective}$)
For mass transport (chemical dosing from `P205` to `AIT203`, or permeate flow `FIT501` to `FIT502`), the fluid parcel travel time depends on pipe volume divided by volumetric flow rate $Q(t)$:
$$t_{advective} = \int_0^L \frac{A(x)}{Q(t)} dx = \frac{\pi D^2 L}{4 \bar{Q}}$$
- **Required parameters:** Pipe inner diameter $D$, linear distance between injection point and sensor $L$, and volumetric flow rate $Q$.
- **Empirical observation:** In `P205 -> AIT203`, raw cross-correlation reveals a peak lag of exactly $120.0\text{ s}$.

### 3.4 Sensor & Transmitter Response ($t_{sensor}$)
Transmitters do not register physical state instantaneously:
- **Magnetic Flow Meters (`FIT101`, `FIT201`):** Faraday's induction is instantaneous, but transmitter firmware applies low-pass damping:
$$\tau_{damp} \approx 0.5\text{ s} - 2.0\text{ s}$$
- **Electrochemical Analyzers (`AIT203` - ORP):** Chemical reduction of sodium bisulfite requires diffusion across a glass/platinum electrode membrane:
$$t_{sensor} \approx T_{90} \approx 30\text{ s} - 90\text{ s}$$

---

## 4. Parameter Gap Matrix Across the Five Relationships

| Relationship ID | Component Pair | Documented Parameters | Inferred Parameters | Completely Missing Parameters | Impact on Delay Bound Estimation |
|---|---|---|---|---|---|
| **EDGE_10** | `MV201 -> FIT201` | Valve tag, Flow tag ($m^3/h$) | Valve modulates flow to Stage 2 | Valve stroke time, motor RPM, pipe diameter, pipe length $L$ | Cannot calculate $d_{min}$ analytically; empirical 1 Hz stroke time is 9.5s–10.5s. |
| **EDGE_07** | `P101 -> FIT101` | Pump tag, Flow tag ($m^3/h$) | Inline pump discharge to flow meter | Impeller diameter, pump curve, pipe length $L$, fluid inertia | Surge is sub-second ($<1\text{ s}$); coastdown drainage requires pipe elevation head. |
| **EDGE_03** | `FIT501 -> FIT502` | Feed flow tag, Permeate flow tag | Mass conservation across RO membrane | Membrane vessel volume, flux rate, recovery ratio, reject pipe routing | Flow dynamics in baseline are stationary ($\sigma=0.0015$); cannot estimate bounds without perturbation. |
| **EDGE_01** | `P301 -> DPIT301` | Pump tag, Differential pressure tag ($kPa$) | Pump discharge builds trans-membrane $\Delta P$ | Membrane module volume, clean water permeability, housing compliance | Pressurization delay is empirically 39s; depressurization is 6s. Theory requires membrane permeability. |
| **EDGE_12** | `P205 -> AIT203` | Dosing pump tag, ORP analyzer tag ($mV$) | NaHSO3 reduces oxidation potential | Injection quill location, pipe length to flow cell, probe $T_{90}$, mixing volume | Advection and sensor lag total 120s; cannot separate transport delay from probe response without quill distance. |

---

## 5. Epistemic Safeguards & Restrictions

To preserve scientific rigor in subsequent research milestones:

1. **No Synthetic Dimensioning:**
   - Under no circumstances should arbitrary pipe lengths (e.g., "assume $L = 10\text{ m}$") or synthetic valve stroke times be manufactured to force analytical equations to match observed data.
2. **Empirical Measurement over Heuristic Windows:**
   - Where engineering documentation is missing, delay bounds must be calibrated **empirically from high-resolution 1 Hz step-response data**, clearly declaring that the bounds reflect empirical observation rather than verified P&ID parameters.
3. **Disclosing Parameter Gaps:**
   - Any publication or report utilizing these delay bounds must explicitly declare that SWaT public documentation lacks certified engineering P&IDs, and that bounds are subject to unmodeled instrumentation damping.
