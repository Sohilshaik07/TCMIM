# SWaT A4/A5 Unexcited Actuator Assessment and Risk Propagation Hazards

**Document Version**: 1.0  
**Assessment Date**: 2026-10-26T13:25:20Z  
**Target Repository**: TCMIM (`src/tcmim/edge/`, `src/tcmim/graph/`, `src/tcmim/cri/`)  
**Scope**: In-depth analysis of zero-variance actuators in the SWaT A4/A5 July 2019 baseline sequence and specification of safe handling protocols for Cascade Risk Estimation.

---

## Executive Summary

A fundamental vulnerability identified in the Stage 1 detector audit and Stage 2 feasibility investigation is the **Zero-Excitation Actuator Problem**:
- In the SWaT A4/A5 July 2019 dataset, **40 out of 77 telemetry channels had exactly zero variance ($\sigma < 10^{-12}$) during the 8,100-second baseline training period**.
- Crucially, two of the primary attack targets—**backwash pump `P601` (Attack A3)** and **RO reject valve `MV501` (Attack A5)**—were completely static throughout baseline training.
- Because data-driven machine learning models require non-zero feature variance to establish weights, all features associated with `P601` and `MV501` were dropped prior to model fitting.

> [!CAUTION]
> **The Critical Safety Failure Mode**:
> In a purely data-driven pipeline, zero empirical correlation during baseline is misinterpreted as **absence of physical influence**. 
> If an operator monitors an attack on `MV501` using an unconstrained Stage 2 pipeline, the system would calculate **Cascade Risk Index = 0.0**, falsely assuring the operator that the attack cannot propagate. 
> In reality, closing `MV501` violently spikes vessel pressure to nearly 30 bar, posing an immediate physical threat of membrane rupture.

This document establishes a four-tier conceptual taxonomy to separate physical reality from statistical identifiability and specifies how future TCMIM releases must handle unexcited actuators without generating misleading zero-risk conclusions.

---

## 1. Baseline Variance Audit of SWaT Actuators

An automated variance audit across all 8,100 baseline records (Windows 10–279, 04:35:00 to 06:50:00 UTC) categorized all actuators in the plant:

### A. Static / Unexcited Actuators in Baseline ($\sigma = 0.000$)

| Tag Name | Device Type | Stage | Baseline Constant Value | Operational Significance | Target in Cyber-Attack? |
|---|---|:---:|:---:|---|:---:|
| **`P601`** | Distribution / Backwash Pump 1 | P6 | 1.0 (OFF) | Primary supply pump for stage 6; recycles water to T101. | **YES (Attack A3)** |
| **`MV501`** | RO Reject Motorized Valve | P5 | 2.0 (CLOSE) | Regulates concentrate discharge from reverse osmosis vessels. | **YES (Attack A5)** |
| `P102` | Raw Water Supply Pump 2 | P1 | 1.0 (OFF) | Standby pump for raw water intake. | NO |
| `P201` | NaOCl Dosing Pump 1 | P2 | 1.0 (OFF) | Sodium hypochlorite chemical dosing pump. | NO |
| `P202` | NaOCl Dosing Pump 2 | P2 | 1.0 (OFF) | Standby sodium hypochlorite pump. | NO |
| `P204` | HCl Dosing Pump 2 | P2 | 1.0 (OFF) | Standby hydrochloric acid dosing pump. | NO |
| `P206` | NaHSO3 Dosing Pump 2 | P2 | 1.0 (OFF) | Standby sodium bisulfite dosing pump. | NO |
| `MV301` | UF Feed Motorized Valve | P3 | 1.0 (CLOSED) | Feed isolation valve for ultrafiltration skid. | NO |
| `MV303` | UF Drain Motorized Valve | P3 | 1.0 (CLOSED) | Drain isolation valve for UF membrane backwash. | NO |
| `P302` | UF Feed Pump 2 | P3 | 1.0 (OFF) | Standby ultrafiltration feed pump. | NO |
| `P401` | RO Feed Pump 1 | P4 | 2.0 (ON) | Primary feed pump supplying RO stage; ran continuously. | NO |
| `P402` | RO Feed Pump 2 | P4 | 1.0 (OFF) | Standby RO feed pump. | NO |
| `UV401` | Dechlorination UV Lamp | P4 | 2.0 (ON) | Ultraviolet de-chlorination lamp; ran continuously. | **Interlocked (Attack A1)** |
| `MV502` | RO Permeate Motorized Valve | P5 | 2.0 (OPEN) | Permeate outlet valve; remained open continuously. | NO |
| `MV503` | RO Flush Motorized Valve | P5 | 1.0 (CLOSED) | RO membrane flush valve. | NO |
| `MV504` | RO Drain Motorized Valve | P5 | 1.0 (CLOSED) | RO membrane drain valve. | NO |
| `P501` | High-Pressure RO Pump 1 | P5 | 2.0 (ON) | High-pressure feed pump; ran continuously. | NO |
| `P502` | High-Pressure RO Pump 2 | P5 | 1.0 (OFF) | Standby high-pressure RO pump. | NO |
| `P602` | Distribution Pump 2 | P6 | 1.0 (OFF) | Standby distribution pump. | NO |
| `P603` | Backwash Recycle Pump | P6 | 1.0 (OFF) | Standby backwash pump. | NO |

### B. Dynamically Excited Actuators in Baseline ($\sigma > 0$)

Only a small minority of actuators actively cycled during baseline normal operation:
- `P101` (Raw Water Pump 1): Cycled between 1 (OFF) and 2 (ON) with $\sigma = 0.487$.
- `MV101` (Raw Water Inlet Valve): Cycled between 0, 1, 2 with $\sigma = 0.499$.
- `MV201` (Chemical Dosing Valve): Cycled with $\sigma = 0.499$.
- `P203` (HCl Dosing Pump 1): Cycled with $\sigma = 0.487$.
- `P205` (NaHSO3 Dosing Pump 1): Cycled with $\sigma = 0.487$.
- `P301` (UF Feed Pump 1): Cycled between 1 and 2 with $\sigma = 0.500$.
- `MV302` (UF Permeate Valve): Cycled with $\sigma = 0.499$.
- `MV304` (UF Backwash Valve): Cycled with $\sigma = 0.487$.

---

## 2. The Four-Tier Conceptual Taxonomy

To prevent hazardous false equivalences, TCMIM establishes four distinct, non-overlapping conceptual layers:

```
+-------------------------------------------------------------------+
| 1. Physical Connectivity (Does physical piping/wiring exist?)     |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 2. Baseline Excitation (Was the component commanded in baseline?) |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 3. Statistical Identifiability (Can baseline data discover edge?)  |
+-------------------------------------------------------------------+
                                  |
                                  v
+-------------------------------------------------------------------+
| 4. Observed Dynamic Influence (Was transient response quantified?)|
+-------------------------------------------------------------------+
```

### Definitions:
1. **Physical Connectivity**: The structural presence of an engineered fluid pipe, mechanical shaft, or electrical control wire connecting device $A$ to device $B$ (documented via P&ID drawings). Independent of whether fluid is currently flowing.
2. **Baseline Excitation**: The empirical presence of command transitions ($\Delta u \ne 0$) or setpoint variations in the normal operating dataset. If an actuator remains in a single position, baseline excitation is **ZERO**.
3. **Statistical Identifiability**: The mathematical capacity of an empirical estimator (VAR, Transfer Function, Granger Causality, Cross-Correlation) to compute parameters. When excitation is zero, covariance is identically zero; the relationship is **STRUCTURALLY UNIDENTIFIABLE**.
4. **Observed Dynamic Influence**: The physical manifestation and empirical measurement of an input-output perturbation response during an operational event (such as an attack or step-response test).

### Application to Attack Targets:

| Component | Target in Attack | Physical Connectivity | Baseline Excitation | Statistical Identifiability from Baseline | Observed Dynamic Influence in Telemetry |
|---|:---:|:---:|:---:|:---:|:---:|
| **`P301`** | A6 | **YES** (Pipes to UF membrane) | **YES** ($\sigma = 0.500$) | **IDENTIFIABLE** ($r = 0.37, \tau = 5\text{ s}$) | **YES** (Membrane differential pressure collapsed) |
| **`MV501`** | A5 | **YES** (Throttles RO reject) | **NO** ($\sigma = 0.000$) | **UNIDENTIFIABLE** ($r \equiv 0$) | **YES** (Vessel pressure spiked to 3,000 kPa) |
| **`P601`** | A3 | **YES** (Recycles to T101) | **NO** ($\sigma = 0.000$) | **UNIDENTIFIABLE** ($r \equiv 0$) | **YES** (Raw water level T101 rose) |

---

## 3. Concrete Architectural Solution for Stage 2 Pipeline

To safely handle unexcited actuators without generating misleading zero-risk conclusions, future TCMIM releases must implement the following architectural safeguards:

### A. Edge State Extension in `src/tcmim/schemas.py`
Extend `EdgeState` to include a dedicated state representing structural presence without empirical baseline confirmation:
```python
class EdgeState(str, Enum):
    NONE = "none"
    EXPIRED = "expired"
    CANDIDATE = "candidate"
    WEAKENING = "weakening"
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    STRENGTHENING = "strengthening"
    STABLE = "stable"
    # New state for unexcited physical actuators:
    UNEXCITED_PRIOR = "unexcited_prior"
```

### B. Representation in `EdgeRecord`
In [`src/tcmim/schemas.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/schemas.py), add metadata fields:
```python
@dataclass
class EdgeRecord:
    source_machine: str
    target_machine: str
    state: EdgeState
    weight: float
    confidence: float
    is_unexcited_actuator: bool = False
    excitation_variance: float = 0.0
    structural_prior_weight: float = 0.5
```

### C. Safe Cascade Risk Index Calculation (`src/tcmim/cri/calculator.py`)
In the CRI calculation:
$$CRI(T) = \text{clip}\left(\frac{\sum_p \text{path\_confidence}(p)}{\text{normaliser}}, 0, 1\right)$$
If a path $p$ originates from or traverses an unexcited actuator (such as `MV501` or `P601`):
1. **Never evaluate path confidence to zero**: Do not use empirical baseline confidence (which would be 0.0). Instead, assign the structural prior weight ($W_{\text{prior}} = 0.5$).
2. **Explicit Uncertainty Flag**: Return a structured status code alongside the numeric CRI value:
   - `CRI_STATUS = "VALIDATED_EMPIRICAL"`: All edges in upstream paths were dynamically excited and statistically verified.
   - `CRI_STATUS = "UNCERTAIN_UNEXCITED"`: Upstream paths contain unexcited actuators (`P601`, `MV501`); risk index is conservative structural prior estimate.
3. **Operator Alert Display**: The UI/report must display:
   > *"WARNING: Upstream actuator MV501 was static in normal baseline. Cascade Risk Index (0.42) reflects structural plant piping, not empirical baseline calibration."*
