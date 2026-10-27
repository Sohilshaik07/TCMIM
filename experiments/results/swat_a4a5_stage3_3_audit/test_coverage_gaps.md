# Test Coverage and Safety Gap Analysis: TCMIM Stage 3.2

**Audit Target:** Stage 3.2 Implementation, Configurations, Test Suites, and Generated Artifacts  
**Audit Directory:** `experiments/results/swat_a4a5_stage3_3_audit/`  
**Date:** October 2026  
**Status:** READ-ONLY IMPLEMENTATION AUDIT COMPLETE  

---

## 1. Executive Summary

This report provides an independent, adversarial critique of the test suites associated with TCMIM Stage 3.2. Specifically, it contrasts **behavioral tests** (which instantiate real data structures and exercise actual code execution paths under boundary, nominal, and adversarial conditions) with **artifact tests** (which merely verify static strings, report markdown, schema keys, or precomputed CSV values).

### Summary of Findings

1. **Gate G0 Behavioral Testing is Robust (VERIFIED):**  
   The conditional structural mask implementation in [`src/tcmim/gating/structural_mask.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/structural_mask.py) and [`src/tcmim/gating/gates.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/gates.py) is thoroughly exercised by real behavioral tests in `tests/unit/test_swat_a4a5_stage3_2.py` (`TestSafeConditionalConnectivity`). Real `PropagationObservation` instances are passed through the entire gating pipeline, confirming fail-closed rejection on missing, invalid, contradictory, stale, and unsatisfied evidence.

2. **Scientific Reporting Tests are Artifact-Bound (GAP IDENTIFIED):**  
   The tests in `TestCorrectedScientificEvaluationReporting` primarily assert regex and table strings inside generated markdown reports and precomputed CSV files. They do **not** re-execute mathematical fittings or re-compute metrics from raw telemetry during test execution. While our independent recomputation confirmed that the numbers in the artifacts are mathematically accurate (see `metric_reproduction_audit.csv`), the test suite itself relies on static artifact inspection rather than live algorithmic verification.

3. **P301 → DPIT301 Operating State Isolation is Untested in Runtime Gating (CRITICAL ARCHITECTURAL GAP):**  
   There are **zero behavioral tests** in `tests/unit/test_gating.py` or `tests/unit/test_swat_a4a5_stage3_2.py` that test dynamic gating for `P301 -> DPIT301` under unknown or unvalidated operating states. This is because **runtime gating contains no operating-state resolver for P301**. The edge is marked `StructuralStatus.ALLOWED` unconditionally in Gate G0, and Gate G1 (`gate_delay_feasibility`) applies a single, static delay window across all operating regimes.

4. **Historical Artifact Immutability Lacks Cryptographic Test Enforcers (GAP IDENTIFIED):**  
   There are no automated regression tests verifying the SHA-256 hashes of historical Stage 3 and Stage 3.1 artifacts, leaving historical baselines vulnerable to silent accidental overwrites during subsequent runner executions.

---

## 2. Test Suite Classification: Behavioral vs Artifact Assertions

| Test Function | Test Type | Target Component | What It Actually Tests | Safety/Scientific Value |
| :--- | :--- | :--- | :--- | :--- |
| `test_conditional_edge_missing_evidence_fails_closed` | **Behavioral** | `GatingPipeline.apply()` & `gate_structural_mask()` | Creates observation without evidence; asserts `passed=False` and reason `CONDITIONAL_REJECTED` | **HIGH**: Proves fail-closed on missing telemetry. |
| `test_conditional_edge_mv201_closed_fails_closed` | **Behavioral** | `gate_structural_mask()` | Provides valid telemetry `MV201 == 1`; asserts rejection | **HIGH**: Proves hydraulic inhibition is enforced. |
| `test_conditional_edge_mv201_open_passes` | **Behavioral** | `gate_structural_mask()` | Provides valid telemetry `MV201 == 2`; asserts acceptance | **HIGH**: Confirms operational acceptance. |
| `test_allow_unknown_cannot_bypass_conditional_requirement` | **Behavioral** | `GatingPipeline.apply()` | Sets pipeline `allow_unknown=True`; passes missing evidence; asserts rejection | **CRITICAL**: Proves unknown bypass policy cannot breach conditional gate. |
| `test_malformed_evidence_fails_closed` | **Behavioral** | `StateConditionPredicate.evaluate()` | Passes `"?"`, `"UNKNOWN"`, `"BAD"`, `-1`, `None`; asserts rejection for all | **HIGH**: Proves malformed telemetry fails closed. |
| `test_stale_evidence_fails_closed` | **Behavioral** | `StateConditionPredicate.evaluate()` | Passes evidence older than `max_age_s=10.0`; asserts rejection | **HIGH**: Proves freshness constraint enforcement. |
| `test_per_observation_evidence_takes_precedence` | **Behavioral** | `GatingPipeline.apply()` | Tests hierarchical evidence resolution (per-obs vs global fallback) | **MEDIUM**: Confirms routing hierarchy. |
| `test_contradictory_evidence_fails_closed` | **Behavioral** | `StateConditionPredicate.evaluate()` | Passes `quality="CONTRADICTORY"`; asserts rejection | **HIGH**: Proves sensor inconsistency fails closed. |
| `test_gating_pipeline_routes_evidence_correctly` | **Behavioral** | `GatingPipeline.apply()` | Full pipeline trace with multi-edge batch and mixed evidence | **HIGH**: Proves batch isolation and correct gating results. |
| `test_p101_fit101_unconditionally_disallowed` | **Behavioral** | `gate_structural_mask()` | Passes `P101 -> FIT101` with arbitrary evidence; asserts unconditional rejection | **HIGH**: Confirms physical graph audit enforcement. |
| `test_a6_model_marked_in_sample` | **Artifact** | `swat_a4a5_stage3_2_report.md` | Regex search for "IN-SAMPLE" and "Attack A6" in markdown | **LOW**: Only verifies report text, not code behavior. |
| `test_startup_headline_r2_disqualified` | **Artifact** | `swat_a4a5_stage3_2_report.md` | Regex search for "disqualified" in markdown | **LOW**: Only verifies report phrasing. |
| `test_closing_failure_episode_retained` | **Artifact** | `swat_a4a5_stage3_2_report.md` & CSV | Checks for presence of `11692` in report text and metrics CSV | **MEDIUM**: Ensures negative $R^2$ is not hidden from report. |
| `test_p301_normal_startup_validation_metrics_accurate` | **Artifact** | `stage3_2_metrics_reconciliation.csv` | Reads CSV; checks `R2 == 0.9936` and `RMSE == 0.1877` | **LOW**: Checks static table entries; does not re-fit. |
| `test_mv201_opening_validation_metrics_accurate` | **Artifact** | `stage3_2_metrics_reconciliation.csv` | Reads CSV; checks `R2 == 0.8937` and `RMSE == 0.3456` | **LOW**: Checks static table entries; does not re-fit. |
| `test_experimental_interface_schema_valid` | **Schema/Artifact**| `experimental_model_interface.json` | Validates JSON keys (`operating_regimes`, `allowed_models`) | **MEDIUM**: Checks schema syntax, but interface is inactive. |
| `test_production_remains_isolated` | **Behavioral/Static** | `src/tcmim/` code tree | Greps codebase for banned imports and CRI activation flags | **HIGH**: Guarantees production code isolation. |

---

## 3. Detailed Audit Against Specific Safety & Regression Criteria

### 3.1 Conditional-Gate Bypass Attempts
- **Status:** **EXCELLENT / FULLY COVERED**
- **Test:** `test_allow_unknown_cannot_bypass_conditional_requirement` in `tests/unit/test_swat_a4a5_stage3_2.py:127`.
- **Mechanism Tested:** Evaluates candidate edge `P101 -> FIT201` with `GatingPipeline(allow_unknown=True)`. Proves that because `StructuralStatus.CONDITIONAL` is evaluated prior to the `allow_unknown` branch, no combination of pipeline flags can force an unevaluated conditional edge into `passed=True`.
- **Residual Risk:** None. The logic in `structural_mask.py:L142-L177` has no alternate exit paths.

### 3.2 Missing, Stale, and Contradictory State Evidence
- **Status:** **EXCELLENT / FULLY COVERED**
- **Tests:**
  - `test_conditional_edge_missing_evidence_fails_closed` (missing evidence dict)
  - `test_stale_evidence_fails_closed` (`age > max_age_s`)
  - `test_contradictory_evidence_fails_closed` (`quality="CONTRADICTORY"`)
  - `test_malformed_evidence_fails_closed` (sentinel values)
- **Mechanism Tested:** Direct invocation of `StateConditionPredicate.evaluate()` and `GatingPipeline.apply()` with adversarial telemetry.
- **Residual Risk:** None in Gate G0. (See Section 3.4 for G1 residual risk).

### 3.3 Invalid Predicates and Malformed Telemetry
- **Status:** **GOOD / COVERED WITH ONE MINOR GAP**
- **Tests:** `test_malformed_evidence_fails_closed` tests bad values in the *evidence dict* (e.g. `raw_val = "?"`, `"UNKNOWN"`, `None`, `-1`).
- **Identified Gap:** The test suite does not explicitly test a malformed *predicate definition string* stored in the connectivity register (e.g., `condition_predicate = "MALFORMED_EXPR(###)"` or an unparseable YAML/JSON string).
- **Audit Verification of Code:** Inspection of `parse_predicate()` in `structural_mask.py` confirms that syntax errors raise `ValueError` or fallback to fail-closed `False`, but an explicit unit test asserting that an unparseable register predicate fails closed without crashing the pipeline is recommended.

### 3.4 Unknown Operating States for P301 → DPIT301
- **Status:** **CRITICAL TEST GAP (ARCHITECTURAL GAP)**
- **Finding:** **NO TESTS EXIST** that feed `P301 -> DPIT301` observations under unknown or unvalidated operating states through the gating pipeline.
- **Root Cause:** In the current runtime architecture:
  1. `P301 -> DPIT301` is marked `StructuralStatus.ALLOWED` in `physical_connectivity_register.csv`.
  2. Gate G0 checks only physical connectivity and condition predicates. Because `P301 -> DPIT301` has no condition predicate, G0 passes it unconditionally.
  3. Gate G1 (`gate_delay_feasibility`) checks whether the empirical delay falls within a single delay window. It does **not** inspect `MV302` or determine whether the plant is in State S2, S3, or S5.
  4. The model interface file `experiments/results/swat_a4a5_stage3_2/experimental_model_interface.json` specifies operating regimes and parameter bounds, but this file is **not imported, read, or executed** by `src/tcmim/gating/`.
- **Consequence:** If an observation of `P301 -> DPIT301` occurs during Attack A6 (State S3) or during an uncharacterized valve state, Gate G0 permits it, and Gate G1 either evaluates it against inappropriate S2 delay bounds or permits it unconditionally if bounds are wide. The test suite fails to detect this because no test attempts to run State S3 or uncharacterized data through Gate G1.

### 3.5 Accidental Production-Gating Activation
- **Status:** **VERIFIED PROTECTED**
- **Test:** `test_production_remains_isolated` in `tests/unit/test_swat_a4a5_stage3_2.py:246`.
- **Mechanism Tested:** Scans all files in `src/tcmim/` to verify that no production module imports from `experiments/`.
- **Audit Finding:** Confirmed. All experimental runners, model fitting scripts, and readiness evaluators live strictly under `experiments/` and have zero import hooks into `src/tcmim/`.

### 3.6 Accidental Plantwide CRI Activation
- **Status:** **VERIFIED PROTECTED**
- **Test:** `test_production_remains_isolated` checks `ENABLE_PLANTWIDE_CRI` settings.
- **Audit Finding:** Confirmed. `src/tcmim/config.py` and `src/tcmim/pipeline.py` do not activate plantwide CRI. The safety invariant is preserved.

### 3.7 Independence and Immutability of Historical Artifacts
- **Status:** **GAP IDENTIFIED**
- **Finding:** There are no tests asserting the cryptographic integrity (SHA-256) of prior experimental results (e.g. `swat_a4a5_stage3/`, `swat_a4a5_stage3_1_audit/`, `swat_a4a5_raw_dynamic_validation/`).
- **Risk:** Re-running runner scripts with altered parameters or different package versions could overwrite historical artifacts unnoticed.

---

## 4. Minimum Test Recommendations for Stage 4

Before any integration of operating-state dependent dynamic gating into the runtime pipeline, the following test suite enhancements must be implemented:

1. **Test-Driven State-Conditioned Gating:**  
   Implement a behavioral test suite `tests/unit/test_operating_state_gating.py` that asserts:
   - When `P301 -> DPIT301` occurs and `MV302 == 1` (State S2), the edge is evaluated against validated S2 delay bounds ($[5, 55]\text{ s}$).
   - When `P301 -> DPIT301` occurs and `MV302 == 2` (State S3), the edge is rejected or quarantined with reason `UNVALIDATED_OPERATING_REGIME` because the S3 dynamic model is an in-sample descriptive fit without independent validation.
   - When `MV302` is missing, stale, or in transition, the edge fails closed with reason `UNKNOWN_OPERATING_REGIME`.

2. **Algorithmic Recomputation Tests:**  
   Replace static string checks in `test_swat_a4a5_stage3_2.py` with parameterized tests that execute the actual FOPDT step-response fitting function on synthetic or cached raw arrays, asserting that fitting algorithms yield expected mathematical parameters without regression.

3. **Cryptographic Manifest Verification Test:**  
   Add `test_historical_artifact_integrity()` that loads `change_manifest.json` and verifies that all historical baseline artifacts match their expected SHA-256 hashes.
