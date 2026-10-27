# TCMIM

**Temporal Cross-Machine Influence Modelling and Cascade Risk Estimation**  
*Research Software for Early Failure Propagation Analysis in Interconnected Industrial Systems*

---

## 1. Project Overview and Research Objective

Condition monitoring in industrial installations typically asks: *"Is this individual machine or sensor anomalous?"* **TCMIM** investigates the cross-machine propagation question:

> *When an abnormal condition or state transition occurs at an upstream machine or actuator, does a corresponding response follow at downstream instrumentation, after what temporal delay, under what operating regimes, and does the observed sequence adhere to known physical connectivity and control topology?*

TCMIM implements a modular, explainable, stage-gated research pipeline rather than an unconstrained end-to-end black-box model. It incorporates physical structural masking, operating-state resolution, robust delay estimation, and common-cause discrimination to evaluate candidate cross-node relationships.

---

## 2. Architecture and Repository Structure

The codebase is organized into a core library (`src/tcmim/`), an interactive research dashboard (`dashboard/`), experimental evaluation scripts (`experiments/`), automated tests (`tests/`), and embedded sensor firmware (`firmware/`):

```
tcmim/
├── dashboard/
│   ├── app.py                      # Interactive Streamlit dashboard UI
│   ├── backend.py                  # Headless dashboard evaluation engine & export logic
│   └── components/
│       ├── cards.py                # Status and KPI metric renderers
│       └── plots.py                # Matplotlib visualization components
├── data/
│   ├── raw/                        # Local raw datasets (untracked; never commit)
│   └── processed/                  # Intermediate data caches with provenance tags
├── docs/                           # Architectural and design documentation
├── experiments/
│   ├── stage1_anomaly_detection.py # Baseline anomaly detector comparisons
│   ├── stage2_benchmark.py         # Controlled synthetic propagation benchmarks
│   ├── stage4_experimental_gating.py # Operating-state resolver & state-conditioned gates
│   ├── swat_propagation_runner.py  # SWaT testbed evaluation runner
│   └── results/                    # Serialized experimental reports and metrics
├── firmware/
│   └── esp32_adxl345/
│       ├── esp32_adxl345.ino       # ESP32 accelerometer sampling firmware
│       └── platformio.ini          # PlatformIO build configuration
├── src/
│   └── tcmim/
│       ├── analysis/               # Multi-hop path analysis & orchestrator
│       ├── benchmark/              # Synthetic scenarios, metrics, and multi-cycle tests
│       ├── config.py               # Central configuration dataclasses
│       ├── cri/                    # Cascade Risk Index (plantwide mode strictly disabled)
│       ├── data/                   # Data loaders (MetroPT-3, SWaT 2015, SWaT July 2019)
│       ├── edge/                   # Dynamic edge lifecycle state machine
│       ├── events/                 # Event detection (CUSUM, burst adapters)
│       ├── features/               # Feature extractors (vibration, pressure, temperature, digital)
│       ├── gating/                 # Directional gates (G0 structural mask, G1 delay, G2 ordering)
│       ├── graph/                  # Dynamic directed propagation graph
│       ├── hardware/               # Serial telemetry ingestion utilities
│       ├── health/                 # Health baseline and degradation indicators
│       ├── ml/                     # Isolation Forest & event adapters
│       ├── propagation/            # Delay estimation, event matcher, and OC-CCD
│       ├── provenance.py           # Provenance tracking & audit guards
│       ├── reporting/              # Markdown/JSON report generators
│       └── schemas.py              # Canonical dataclasses and enums
├── tests/
│   ├── conftest.py                 # Pytest fixtures and test environment setup
│   ├── integration/                # End-to-end integration tests (MetroPT-3, SWaT)
│   └── unit/                       # Unit test suites across all core modules
├── pyproject.toml                  # PEP 517/518 build specifications
└── requirements.txt                # Pinned production and test dependencies
```

---

## 3. Installation and Environment Setup

### Prerequisites
- **Python**: `>=3.10` (Python 3.10 to 3.13 supported)
- Standard scientific Python toolchain (`pip`, virtual environment, or Conda)

### Setup Instructions

1. **Clone or navigate to the repository directory:**
   ```bash
   cd tcmim
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Using venv (Windows)
   python -m venv .venv
   .venv\Scripts\activate

   # Using venv (Linux/macOS)
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install core dependencies and editable package:**
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Verify installation:**
   ```bash
   python -c "import tcmim; print(f'TCMIM version: {tcmim.__version__}')"
   ```

---

## 4. Verified Execution Commands

### Running Automated Tests

- **Run focused dashboard backend regression tests:**
  ```bash
  pytest tests/unit/test_dashboard_backend.py -v
  ```

- **Run all unit tests (offline, no external datasets required):**
  ```bash
  pytest tests/unit/ -v
  ```

- **Run the full test suite with summary reporting:**
  ```bash
  pytest -rs
  ```

### Launching the Research Dashboard

The interactive Streamlit dashboard enables inspection of telemetry channels, independent anomaly detectors, stage-gated evaluations, and JSON/CSV experiment exports:

```bash
streamlit run dashboard/app.py
```
*(Default server runs locally at `http://localhost:8501`)*

---

## 5. Dataset Documentation

Raw sensor data files must **never** be committed to version control. Download raw datasets separately and place them in the locations expected by the respective loaders:

### 5.1 MetroPT-3 (Air Compressor Dataset)
- **Source**: UCI Machine Learning Repository (sampled at ~1 Hz / ~10 s intervals, single compressor).
- **Expected Local Paths** (checked in order by loader):
  - `MetroPT3(AirCompressor).csv` (repository root)
  - `data/raw/MetroPT3(AirCompressor).csv`
- **Integrity Rule**: MetroPT-3 is from a **single machine**. It is used exclusively to evaluate single-machine health indicator baselines, pressure/temperature feature extraction, and CUSUM alerting. It must **not** be used to claim cross-machine failure propagation.

### 5.2 SWaT A4/A5 July 2019 Telemetry
- **Source**: iTrust Secure Water Treatment Testbed, Singapore (July 2019 operational dataset).
- **Format**: Excel workbook (`.xlsx`), single sheet `'MST v2'`, 3-row composite header.
- **Expected Local Path**:
  - `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx`
- **Coverage**: Process Stages P1 through P6, 51 registered sensor/actuator tags.

### 5.3 Legacy SWaT 2015 Attack Dataset
- **Expected Local Path**: `data/raw/SWaT_Dataset_Attack_v0.csv` (or configured via environment variable `TCMIM_SWAT_DATA_PATH`).
- **Status**: Optional. When absent, the seven integration tests in `tests/integration/test_swat_pipeline.py` skip gracefully without failing the suite.

---

## 6. Implemented Capabilities and Maturity Status

TCMIM distinguishes between software implementation, automated test coverage, empirical execution on historical datasets, and physical hardware validation:

| Capability / Subsystem | Implementation File(s) | Test Coverage | Dataset Execution | Physical Hardware Validation |
|---|---|---|---|---|
| **Schemas & Provenance Tracking** | `schemas.py`, `provenance.py` | Extensive unit tests | Validated on all loaders | N/A (software contracts) |
| **Multimodal Feature Extraction** | `features/*.py` | Unit tests for all modalities | MetroPT-3 & SWaT | Tested on recorded telemetry |
| **Sequential Anomaly Detection** | `events/cusum.py`, `ml/anomaly_detector.py` | Unit tests | MetroPT-3 & SWaT | Tested on recorded telemetry |
| **Gate G0: Structural Mask** | `gating/structural_mask.py` | Unit tests | SWaT plant register | Topology-based constraint |
| **Operating-State Resolver** | `experiments/stage4_experimental_gating.py` | Unit & dashboard tests | SWaT July 2019 (`MV302`) | Empirical state conditioning |
| **Gate G1 & G2: Feasibility & Ordering** | `gating/gates.py`, `dashboard/backend.py` | Unit & regression tests | SWaT (`MV201 → FIT201`) | Statistical temporal checks |
| **OC-CCD: Common-Cause Discrimination** | `propagation/occ_ccd.py` | Unit tests | Synthetic & SWaT | Statistical temporal checks |
| **Dynamic Propagation Graph** | `graph/dynamic_graph.py` | Unit tests | Synthetic benchmark | Synthetic multi-cycle execution |
| **Cascade Risk Index (CRI)** | `cri/calculator.py` | Unit tests (synthetic only) | **Plantwide CRI Disabled** | **NOT VALIDATED** |
| **ESP32 Sensor Firmware** | `firmware/esp32_adxl345/` | Syntax & PlatformIO config | Benchtop firmware code | **Hardware rig pending** |

---

## 7. Experimental Findings and Bounded Observations

Experimental investigations conducted on the SWaT July 2019 dataset establish specific, bounded observations:

1. **`MV201 → FIT201` Actuator-Sensor Dynamic Response**:
   - At raw workbook row 580 (04:39:40 UTC), valve `MV201` transitions from state 2 (OPEN) to state 1 (CLOSED).
   - Inflow meter `FIT201` registers a corresponding flow collapse beginning at row 583 (04:39:49.99 UTC).
   - Coarse sliding-window analysis (30 s window, 10 s stride) estimates an onset difference of $\Delta t \approx 10.0\text{ s}$, while sample-level point analysis identifies an empirical physical dead time of $t_d \approx 3.74\text{ s}$ ($\tau \approx 4.07\text{ s}$).
   - Feasible delay bounds of $[1.0, 25.0]\text{ s}$ encompass both closing ($t_d \approx 3.74\text{ s}$) and opening ($t_d \approx 12.92\text{ s}$) stroke dead times.
   - Gate G0 (`ALLOWED`), Gate G2 (`PASSED`), Gate G1 (`PASSED`), and OC-CCD classify this pair as `RELATIONSHIP_SUPPORTED`.

2. **`P301 → DPIT301` Operating-State Conditioning**:
   - In State S2 (Normal Startup, `MV302 == 1` CLOSED), differential pressure follows pump startup with validated empirical delay bounds $[5.0, 55.0]\text{ s}$ ($R^2 = 0.9936$).
   - In State S3 (Permeate-Open Startup, `MV302 == 2` OPEN, associated with Attack A6), dynamics lack out-of-sample replication (single episode) and remain strictly **QUARANTINED**.
   - Missing, unreadable, or stale actuator telemetry fails closed (`UNKNOWN_OPERATING_STATE`).

3. **`P101 → FIT101` Structural Negative Control**:
   - P101 is located on the chemical dosing / raw water intake line, hydraulically separated from FIT101 by check valves and control logic. Across all 12 transitions of P101, flow FIT101 showed 0/12 responsive transitions ($r = 0.0528$).
   - Gate G0 unconditionally marks this relationship `DISALLOWED` (`UNCONFIRMED`), preventing false attribution even if both tags register simultaneous anomalies.

---

## 8. Test Execution Status

### Last Reported Verification Suite Outcome
```
================ 975 passed, 7 skipped, 17 warnings in 41.72s =================
```
*(Last reported result from verification audit, October 2026, under Python 3.13.12 / pytest-9.1.1 on Windows x86_64)*

- **Passed (975)**: Covers data ingestion, schemas, feature extraction, anomaly detectors, temporal matchers, directional gates, edge lifecycle state machines, graph algorithms, and dashboard backend operations.
- **Skipped (7)**: Integration tests in `tests/integration/test_swat_pipeline.py` requiring the legacy 2015 `SWaT_Dataset_Attack_v0.csv`.
- **Warnings (17)**: Benign runtime precision-loss warnings in `scipy.stats.kurtosis` / `skew` during constant-signal baseline checks where standard deviation $\sigma < 10^{-12}$.

---

## 9. Hardware Firmware Status and Limitations

- **Firmware Location**: `firmware/esp32_adxl345/`
- **Target Hardware**: Espressif ESP32 Dev Module paired with Analog Devices ADXL345 3-axis I2C/SPI accelerometer.
- **Current Status**: Standalone Arduino/PlatformIO firmware source code providing high-frequency acceleration sampling and JSON-formatted serial output.
- **Hardware Limitation**: While the firmware code is present in the repository, a physical dual-machine coupled mechanical testbed with hardware synchronization (e.g., PPS GPS or ESP-NOW clock sync) has **not** been constructed or experimentally validated.

---

## 10. Scientific Integrity Rules

TCMIM strictly enforces the following principles across its codebase and reports:

1. **Temporal Association $\neq$ Causal Proof**: An observed temporal lag $\Delta t > 0$ that satisfies structural and delay gates demonstrates statistical temporal consistency under a bounded experimental protocol. It is **not** mathematical proof of causality.
2. **Cyberattack Labels $\neq$ Physical Failure Ground Truth**: SWaT dataset attack labels denote cybersecurity perturbation intervals. They do not represent mechanical component degradation or multi-machine failure cascade ground truth.
3. **No Uncalibrated Physical Flow Conversions**: Pulse count channels (such as `Caudal_impulses` in MetroPT-3) remain raw counts unless manufacturer calibration curves are present.
4. **Mandatory Provenance Enforcement**: Data samples carry explicit provenance attributes (`SYNTHETIC`, `BENCHMARK`, `PUBLIC_DATASET`, `PHYSICAL_TESTBED`). Mixing synthetic data into real-dataset reports raises a `ProvenanceViolation`.
5. **No Synthetic Extrapolation**: Synthetic benchmark propagation accuracy must never be cited as real-world industrial detection accuracy.
6. **No Plantwide Cascade Risk Claims**: Plantwide Cascade Risk Index (CRI) calculation is disabled pending empirical multi-node cascade ground truth.

---

## 11. Reproducibility Instructions

To independently verify the software demonstration and gate evaluation behavior:

1. **Execute the automated test suite:**
   ```bash
   pytest tests/unit/test_dashboard_backend.py -v
   pytest -rs
   ```

2. **Verify Gate G0 Precedence over Gate G2:**
   - In `dashboard/backend.py`, Gate G0 (Physical Structural Mask) is evaluated before Gate G2 (Temporal Ordering).
   - **`P101 → FIT101` with simultaneous anomaly timestamps ($\Delta t = 0.00\text{ s}$)**: Gate G0 rejects the structurally disallowed relationship (`DISALLOWED`, returning `PresentationStatus.UNCONFIRMED`) before temporal ordering (Gate G2) is evaluated.
   - **`MV201 → FIT201` with simultaneous anomaly timestamps ($\Delta t = 0.00\text{ s}$)**: Gate G0 permits the structurally allowed relationship (`ALLOWED`), and subsequently Gate G2 rejects the simultaneous event ordering (`ORDERING_VIOLATION`, returning `PresentationStatus.BOTH_NODES_ANOMALOUS`).

3. **Run the Dashboard:**
   ```bash
   streamlit run dashboard/app.py
   ```
   Under `Mode 1: Real SWaT Physical Nodes (Verified Testbed)` (this is the dashboard's label for the real SWaT dataset demonstration and does not mean a physical multi-machine hardware testbed has been constructed or validated), select presets to observe stage-gating:
   - `MV201 → FIT201`: Observes valid response lag ($\Delta t \approx 10\text{ s}$) within $[1.0, 25.0]\text{ s}$ yielding `RELATIONSHIP_SUPPORTED`.
   - `P301 → DPIT301`: Tests State S2 normal bounds vs. State S3 permeate-open quarantine.
   - `P101 → FIT101`: Demonstrates structural disallowance by Gate G0 (`UNCONFIRMED`).

---

## 12. Known Limitations and Future Work

- **Dataset Version Control**: Large raw datasets (`data/raw/MetroPT3(AirCompressor).csv` and `data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx`) are untracked in Git to prevent repository bloat; they must be acquired externally and placed into `data/raw/` prior to running full integration tests.
- **Integration Test Coverage**: The seven skipped tests in `tests/integration/test_swat_pipeline.py` depend on the historical 2015 SWaT CSV dataset; test fixtures could be extended to accept the active July 2019 Excel workbook to achieve zero skips.
- **Physical Testbed (Milestone M9)**: Genuine physical multi-machine failure propagation requires empirical experimental validation using synchronized sensor nodes on mechanically coupled machinery.