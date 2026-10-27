# TCMIM Stage 3.2: Test Coverage Audit and Regression Suite Update

## 1. Executive Summary

This document audits the test coverage changes implemented in **TCMIM Stage 3.2**, identifies the unsafe assertions from Stage 3 that were replaced, details the 17 new scientific regression tests in [test_swat_a4a5_stage3_2.py](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_swat_a4a5_stage3_2.py), and reports the verified execution results across the full repository test suite.

---

## 2. Audit of Previous Stage 3 Test Assertions

During the Stage 3.1 independent verification audit, two specific testing weaknesses were identified:

### 2.1 Unsafe Assertion in `test_swat_a4a5_stage3.py`
In Stage 3, `TestTopologyRegisterAudit.test_p101_to_fit201_permitted_conditionally_in_proposed_register` contained the following assertions:

```python
# PREVIOUS UNSAFE IMPLEMENTATION (Stage 3):
def test_p101_to_fit201_permitted_conditionally_in_proposed_register(self):
    mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
    status = mask.get_status("P101", "FIT201")
    assert status == StructuralStatus.ALLOWED      # UNSAFE: Accepted unconditioned ALLOWED status
    assert mask.is_permitted("P101", "FIT201")     # UNSAFE: Permitted without actuator evidence
```

**Why this was unsafe**:
This test codified the architectural flaw where `suitable_as_structural_constraint = CONDITIONAL` was silently overridden by `status = INFERRED`, promoting the edge to unconditional `ALLOWED` (`'1'`).

**Remediation Applied in Stage 3.2**:
In accordance with the prompt's instruction (*"If an existing test encodes an unsafe assumption, replace it with a test for the correct invariant and document the reason"*), the test was updated to verify the corrected invariant:

```python
# CORRECTED IMPLEMENTATION (Stage 3.2):
def test_p101_to_fit201_permitted_conditionally_in_proposed_register(self):
    """P101 -> FIT201 must be recognized as CONDITIONAL ('C'), never unconditional ALLOWED ('1')."""
    mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
    status = mask.get_status("P101", "FIT201")
    assert status == StructuralStatus.CONDITIONAL
    assert mask.is_conditional("P101", "FIT201")
    # Must fail closed when state evidence is missing
    assert not mask.is_permitted("P101", "FIT201")
    # Must pass when state evidence confirms MV201 == 2
    assert mask.is_permitted("P101", "FIT201", state_evidence={"MV201": 2})
    # Must fail closed when MV201 is closed
    assert not mask.is_permitted("P101", "FIT201", state_evidence={"MV201": 1})
```

---

## 3. New Stage 3.2 Scientific Regression Suite

A dedicated regression test file [tests/unit/test_swat_a4a5_stage3_2.py](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_swat_a4a5_stage3_2.py) was implemented, containing 17 rigorous behavioral tests organized into three test classes:

### 3.1 Class `TestSafeConditionalConnectivity` (Task A)
1. `test_mv201_open_satisfied`: Verifies that when `MV201 == 2`, `P101 -> FIT201` passes Gate G0 with reason `pass: conditional constraint satisfied`.
2. `test_mv201_closed_rejected`: Verifies that when `MV201 == 1`, `P101 -> FIT201` is rejected at Gate G0 with diagnostic reason `actuator condition failed`.
3. `test_missing_actuator_state_rejected`: Verifies fail-closed behavior when state evidence is `None`, empty dict `{}`, or omits actuator `MV201`.
4. `test_unknown_actuator_value_rejected`: Verifies fail-closed behavior when actuator values are `?`, `UNKNOWN`, `NAN`, `INVALID`, `CONTRADICTORY`, or `None`.
5. `test_stale_state_evidence_rejected`: Verifies that evidence with `is_stale=True` or timestamp age exceeding `max_age_s` is rejected.
6. `test_malformed_conditional_predicate_fails_closed`: Verifies that invalid or empty predicates fail closed safely without unhandled runtime exceptions.
7. `test_unconditional_allowed_edge_preserved`: Verifies that unconditional edges (e.g. `P301 -> DPIT301`) pass G0 without requiring state evidence.
8. `test_disallowed_edge_always_rejected`: Verifies that `P101 -> FIT101` is always rejected, regardless of any actuator state evidence provided.
9. `test_allow_unknown_policy_cannot_bypass_conditional`: Verifies that `allow_unknown=True` policy NEVER bypasses a `CONDITIONAL` edge.
10. `test_gating_pipeline_integration`: Verifies end-to-end batch gating in `GatingPipeline.apply()` with observation-level and map-level evidence.

### 3.2 Class `TestCorrectedScientificEvaluationReporting` (Task B / Task C)
11. `test_attack_a6_labeled_in_sample_descriptive_fit`: Verifies that in `corrected_model_evaluation.csv`, Attack A6 Model 2 is labeled `IN-SAMPLE DESCRIPTIVE FIT`, and out-of-sample validation status is documented as not available due to $N=1$ episode.
12. `test_normal_startup_score_from_independent_episodes_only`: Verifies that the normal startup validation $R^2 = 0.9936$ is calculated strictly from independent normal episodes (9419, 12124, 14024).
13. `test_headline_startup_score_disqualified`: Verifies that the contaminated headline score $R^2 = 0.9963$ is officially labeled as disqualified.
14. `test_closing_failure_episode_visible_per_episode`: Verifies that episode `MV201_CLOSE_11692` has negative $R^2 = -1.7376$ visible in per-episode evaluation and notes pump lead-time shutdown.
15. `test_validation_status_register_authoritative_categories`: Verifies that all 23 candidate edges are classified using strictly authorized audit labels (`INDEPENDENTLY VALIDATED`, `IN-SAMPLE DESCRIPTIVE FIT`, `CONDITIONALLY SUPPORTED`, `DISALLOWED`, `UNRESOLVED`, `NOT VERIFIED`).

### 3.3 Class `TestShadowModeSafety` (Task D)
16. `test_production_gating_config_default_unmodified`: Statically and dynamically verifies that production default `GatingConfig().structural_mask` is `None` and delay bounds $[0, 600]\text{ s}$ remain intact.
17. `test_production_safety_contract_flags`: Verifies that relationship decisions enforce `SHADOW_MODE_PERMITTED` or `QUARANTINED_FROM_GATING`, prohibiting production integration.

---

## 4. Test Matrix and Traceability

| Task | Requirement | Implementing Test Method | Test Status |
|---|---|---|---|
| **Task A** | MV201 == 2 allows conditional edge | `test_mv201_open_satisfied` | **PASSED** |
| **Task A** | MV201 == 1 rejects conditional edge | `test_mv201_closed_rejected` | **PASSED** |
| **Task A** | Missing state evidence fails closed | `test_missing_actuator_state_rejected` | **PASSED** |
| **Task A** | Unknown actuator value rejected | `test_unknown_actuator_value_rejected` | **PASSED** |
| **Task A** | Stale state evidence rejected | `test_stale_state_evidence_rejected` | **PASSED** |
| **Task A** | Malformed predicate fails closed | `test_malformed_conditional_predicate_fails_closed` | **PASSED** |
| **Task A** | Unconditional ALLOWED preserved | `test_unconditional_allowed_edge_preserved` | **PASSED** |
| **Task A** | DISALLOWED edge always rejected | `test_disallowed_edge_always_rejected` | **PASSED** |
| **Task A** | `allow_unknown` policy cannot bypass condition | `test_allow_unknown_policy_cannot_bypass_conditional` | **PASSED** |
| **Task A** | End-to-end pipeline integration | `test_gating_pipeline_integration` | **PASSED** |
| **Task B/C**| Attack A6 labeled in-sample descriptive fit | `test_attack_a6_labeled_in_sample_descriptive_fit` | **PASSED** |
| **Task B/C**| Normal startup score from independent episodes only | `test_normal_startup_score_from_independent_episodes_only` | **PASSED** |
| **Task B/C**| Contaminated headline score disqualified | `test_headline_startup_score_disqualified` | **PASSED** |
| **Task B/C**| Closing failure episode visible per-episode | `test_closing_failure_episode_visible_per_episode` | **PASSED** |
| **Task B/C**| Validated status register categories | `test_validation_status_register_authoritative_categories` | **PASSED** |
| **Task D** | Production gating default disconnected | `test_production_gating_config_default_unmodified` | **PASSED** |
| **Task D** | Plantwide CRI and production gating disabled | `test_production_safety_contract_flags` | **PASSED** |

---

## 5. Verified Execution Summary

### Run 1: Focused Stage 3.2 Regression Suite
- **Command**: `pytest tests/unit/test_swat_a4a5_stage3_2.py -v`
- **Result**: `17 passed in 0.13s`
- **Exit Code**: `0`

### Run 2: Combined Stage 3 + Stage 3.2 Suite
- **Command**: `pytest tests/unit/test_swat_a4a5_stage3.py tests/unit/test_swat_a4a5_stage3_2.py -v`
- **Result**: `32 passed in 0.11s`
- **Exit Code**: `0`

### Run 3: Full Repository Test Suite
- **Command**: `pytest -q`
- **Result**: `908 passed, 7 skipped, 13 warnings in 20.24s`
- **Exit Code**: `0`
