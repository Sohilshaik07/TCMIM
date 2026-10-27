# TCMIM Stage 3.1: Test Suite Coverage and Scientific Invariant Audit

## Executive Summary

The Stage 3 implementation report highlights a 100% pass rate across 43 automated unit tests:
- `tests/unit/test_swat_a4a5_g0_evaluation.py` (15 passed)
- `tests/unit/test_swat_a4a5_raw_dynamic_validation.py` (13 passed)
- `tests/unit/test_swat_a4a5_stage3.py` (15 passed)

This audit inspects the underlying assertions to determine whether they test genuine scientific invariants or merely verify schema compliance and file existence.

The audit reveals that while the test suite provides strong regression protection against file corruption and schema regressions, **it contains critical blindspots that fail to test—and in some cases actively mask—major scientific flaws**.

---

## 1. Breakdown of Test Types Across the 43 Tests

| Test Category | Test Count | Description | Scientific Invariant Tested? |
|---|---|---|---|
| **File and Field Existence** | 14 (32.6%) | Checks that CSV, JSON, PNG, or TXT files exist and contain expected dictionary keys. | NO (Syntactic check only) |
| **Hash Fingerprint Preservation** | 4 (9.3%) | Checks SHA-256 hashes of original dataset and baseline physical register. | **YES (Data integrity invariant)** |
| **Fixed Schema / Range Bounds** | 12 (27.9%) | Checks that parameter values fall within broad numerical bands (e.g. $11 \le t_d \le 15$). | Partially (Plausibility checks) |
| **Output Metric Re-Assertion** | 9 (20.9%) | Reads pre-computed values from `model_comparison.json` and asserts they exceed arbitrary thresholds ($R^2 \ge 0.99$). | **NO (Circular re-assertion)** |
| **Operational Logic / Pipeline Execution** | 4 (9.3%) | Executes `PhysicalStructuralMask` methods or checks G0 gating outcomes on synthetic pairs. | Partially (Tests software logic, not physics) |

---

## 2. Detailed Audit of Specific Scientific Blindspots

### 2.1 Blindspot 1: Training-on-Test / In-Sample Fit Masking
- **Claim**: Model 2 achieves held-out validation $R^2 = 0.9961$ on Attack A6.
- **Test Implementation** (`tests/unit/test_swat_a4a5_stage3.py`, lines 132–136):
  ```python
  def test_state_conditioned_reconciliation(self, model_comparison):
      m2 = model_comparison["part_c_p301_to_dpit301"]["model_comparison"]["model_2_miso_state_conditioned"]
      r2_atk = m2["attack_a6_val_metrics"]["r2"]
      assert r2_atk >= 0.99
      assert m2["overall_val_metrics"]["r2"] >= 0.99
  ```
- **Audit Finding**:
  This test does **not** test whether Attack A6 was held out. It reads the pre-computed JSON metric and asserts that the number is $\ge 0.99$. Because `popt_s3` was fitted directly on Attack A6, the in-sample $R^2$ was $0.9961$. The test passed, giving a false appearance of automated scientific validation for what was actually an in-sample training fit.
- **What a Real Invariant Test Would Require**:
  A test that asserts:
  $$N_{\text{episodes}}(\text{State S3}) \ge 2 \implies N_{\text{dev}} \ge 1 \land N_{\text{val}} \ge 1$$
  Such a test would have failed immediately, alerting researchers that State S3 cannot be independently validated on this dataset.

### 2.2 Blindspot 2: Conditional Connectivity Permissiveness Bypass
- **Claim**: `P101 -> FIT201` is permitted only conditionally when `MV201` is open.
- **Test Implementation** (`tests/unit/test_swat_a4a5_stage3.py`, lines 80–86):
  ```python
  def test_p101_to_fit201_permitted_conditionally_in_proposed_register(self):
      mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
      status = mask.get_status("P101", "FIT201")
      assert status == StructuralStatus.ALLOWED
      assert mask.is_permitted("P101", "FIT201")
  ```
- **Audit Finding**:
  This test literally asserts that `mask.is_permitted("P101", "FIT201")` returns `True` unconditionally. It does not test whether the edge is rejected when `MV201` is closed, because the class method signature `is_permitted(source, destination)` does not accept an operating state. The test actively validated an unconditioned bypass.

### 2.3 Blindspot 3: Metric Calculation Independence
- **Claim**: Metrics reported in markdown and JSON reflect actual prediction errors.
- **Test Implementation**:
  None of the 15 tests in `test_swat_a4a5_stage3.py` load raw telemetry or recalculate $R^2$ or RMSE from actual prediction and target arrays. They read pre-generated JSON files. If a bug in the runner script calculated $R^2$ incorrectly, the test would simply read the buggy number and pass as long as it exceeded the threshold.

### 2.4 Blindspot 4: Dynamic Model Failure Modes in Closing Stroke
- **Claim**: MV201 closing model is validated ($R^2 = 0.5434$).
- **Audit Finding**:
  In validation episode `MV201_CLOSE_11692`, the true per-episode $R^2$ is **$-1.7373$** (due to pump P101 de-energizing 7 seconds early). The test suite only checks the concatenated pooled $R^2$ ($0.5434 \ge 0.50$). The severe per-episode failure was completely masked by the pooled aggregation.

### 2.5 Blindspot 5: Executable Interface Safety Contract
- **Claim**: The experimental model interface safely handles unknown states.
- **Test Implementation** (`tests/unit/test_swat_a4a5_stage3.py`, lines 160–166):
  ```python
  def test_safety_contract_flags(self, interface_data):
      contract = interface_data["safety_contract"]
      assert contract["allow_unvalidated_defaults"] is False
      assert contract["production_gating_connected"] is False
      assert contract["plantwide_cri_enabled"] is False
  ```
- **Audit Finding**:
  This test checks static boolean flags in a JSON dictionary. It does not execute an actual gating function with missing or unknown inputs to verify that an exception is raised or that candidate edges are rejected.

---

## 3. Difference Between Passing Unit Tests and Scientific Validity

The 43 passing tests prove that:
1. The raw dataset and original register have not suffered file corruption or bit-rot.
2. The runner scripts executed and wrote out syntactically valid CSV and JSON artifacts.
3. The proposed register adheres to the DictReader schema requirements.

The 43 passing tests **DO NOT prove that**:
1. Attack A6 generalization was independently validated.
2. The structural mask safely enforces valve conditionality.
3. Closing dynamics are stable across all operating regimes.
4. Gating behavior is robust against unmodeled actuator sequence variations.

---

## 4. Required Invariant Test Suite for Stage 4

Before any model or register is connected to production gating, the following invariant tests must be added:

1. **`test_state_conditioned_structural_mask_rejects_closed_valve`**:
   Execute `gate_structural_mask` with telemetry where `MV201 == 1` and verify that `P101 -> FIT201` is strictly rejected.
2. **`test_no_train_on_test_in_dynamic_models`**:
   Assert that every model fitted on state $S_k$ has $N_{\text{dev}} \ge 1$ and is evaluated exclusively on distinct indices $I_{\text{val}} \cap I_{\text{dev}} = \emptyset$.
3. **`test_per_episode_minimum_performance`**:
   Assert that no individual held-out episode exhibits negative $R^2$ without generating an explicit operational anomaly warning.
4. **`test_recalculate_metrics_from_raw_telemetry`**:
   Recompute RMSE and $R^2$ directly from raw telemetry arrays inside the test rather than reading pre-computed JSON files.
