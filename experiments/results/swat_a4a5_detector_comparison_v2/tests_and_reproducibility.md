# Tests and Reproducibility Documentation (Version 2)

**Execution Date**: 2026-10-26T12:54:11.471277+00:00  
**Test Suite Path**: [`tests/unit/test_swat_a4a5_detector_comparison.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_swat_a4a5_detector_comparison.py)  
**Execution Environment**: Python 3.13.12, pytest 9.1.1, Windows (x86_64)  

---

## 1. Test Suite Coverage

A dedicated unit test suite with 10 test cases was authored to rigorously validate the partition reset and clustering logic:

| Test Case Name | Target Behavior | Validation Assertion | Status |
|---|---|---|:---:|
| `test_cusum_starts_at_zero_for_each_partition` | Partition-level state initialization | Verifies $S_0 = 0.0$ for each partition independently | **PASS** |
| `test_no_state_carryover_buffer_to_baseline` | Buffer-to-baseline boundary isolation | Confirms non-zero buffer terminal state does not alter baseline state | **PASS** |
| `test_no_state_carryover_baseline_to_heldout`| Baseline-to-held-out boundary isolation | Confirms non-zero baseline terminal state does not enter held-out | **PASS** |
| `test_consecutive_false_positive_windows_form_one_incident` | Alarm grouping | Verifies 5 adjacent FP windows collapse to exactly 1 incident | **PASS** |
| `test_normal_window_breaks_false_alarm_cluster` | Normal-window cluster break | Verifies interleaved normal window splits FPs into 2 incidents | **PASS** |
| `test_positive_labelled_window_breaks_false_alarm_cluster` | Attack-window cluster break | Verifies True Positive window terminates active false-alarm incident | **PASS** |
| `test_false_negative_window_breaks_false_alarm_cluster` | FN-window cluster break | Verifies False Negative window terminates active false-alarm incident | **PASS** |
| `test_empty_and_zero_false_alarm_cases_handled_safely` | Robust edge case handling | Tests empty array and zero-alarm array for zero division or index crashes | **PASS** |
| `test_hourly_rate_calculation` | Time rate calculation | Verifies incidents per hour under duration scaling | **PASS** |
| `test_clustered_metrics_do_not_alter_standard_confusion_matrix` | Mathematical invariance | Confirms standard TP, FP, TN, FN, precision, recall, F1, FPR are invariant | **PASS** |

---

## 2. Test Execution Commands & Verified Outputs

### Dedicated Unit Tests
```powershell
pytest tests/unit/test_swat_a4a5_detector_comparison.py -v
```
**Actual Output**:
```
tests/unit/test_swat_a4a5_detector_comparison.py::test_cusum_starts_at_zero_for_each_partition PASSED [ 10%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_no_state_carryover_buffer_to_baseline PASSED [ 20%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_no_state_carryover_baseline_to_heldout PASSED [ 30%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_consecutive_false_positive_windows_form_one_incident PASSED [ 40%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_normal_window_breaks_false_alarm_cluster PASSED [ 50%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_positive_labelled_window_breaks_false_alarm_cluster PASSED [ 60%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_false_negative_window_breaks_false_alarm_cluster PASSED [ 70%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_empty_and_zero_false_alarm_cases_handled_safely PASSED [ 80%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_hourly_rate_calculation PASSED [ 90%]
tests/unit/test_swat_a4a5_detector_comparison.py::test_clustered_metrics_do_not_alter_standard_confusion_matrix PASSED [100%]

============================== 10 passed in 0.27s ===============================
```

### Full Unit Test Suite (Regression Protection)
```powershell
pytest tests/unit/ -q
```
**Actual Output**:
```
====================== 757 passed, 6 warnings in 15.64s =======================
```
All 757 tests across the repository pass without error.

---

## 3. Reference Result Integrity Verification

The original reference directories were verified via SHA-256 hashes to guarantee they were strictly preserved:
- `experiments/results/swat_a4a5/`: 9 artifacts, unmodified.
- `experiments/results/swat_a4a5_detector_comparison/`: 7 artifacts, unmodified.

---

## 4. End-to-End Reproduction Command

To reproduce all Version 2 results, tables, and JSON manifests from scratch:
```powershell
python experiments/swat_a4a5_comparison_runner_v2.py
```
Outputs are written to: `experiments/results/swat_a4a5_detector_comparison_v2/`.
