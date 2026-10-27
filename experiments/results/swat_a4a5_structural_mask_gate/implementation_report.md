# TCMIM Milestone Implementation Report: G0_STRUCTURAL_MASK

**Milestone Identifier**: `G0_STRUCTURAL_MASK`  
**Date**: 2026-10-26T13:48:00Z  
**Implementation Target**: TCMIM Stage 2 Candidate-Edge Gating and Risk Evaluation  
**Artifact Directory**: [`experiments/results/swat_a4a5_structural_mask_gate/`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/)  
**Configuration File**: [`structural_mask_config.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/structural_mask_config.json)  
**Change Manifest**: [`change_manifest.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/change_manifest.json)  
**Test Log**: [`test_results.txt`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/test_results.txt)  

---

## 1. Executive Summary

This milestone implements **Gate G0_STRUCTURAL_MASK**, an auditable physical connectivity constraint for Stage 2 candidate-edge processing in TCMIM. Gate G0 evaluates directed candidate pairs $(u \to v)$ before temporal delay feasibility (G1), preventing data-driven statistical methods (such as time-lagged cross-correlation or vector autoregression) from constructing dense, hallucinatory propagation graphs across physically disconnected industrial plant stages.

Key architectural accomplishments delivered in this milestone:
1. **Three-State Structural Mask Encoding**: Formally represents candidate connections as permitted (`1`), explicitly prohibited (`0`), or insufficiently documented/unknown (`?`).
2. **Safe Default for Missing Entries**: Missing register entries strictly default to `?` (UNKNOWN). In accordance with scientific integrity constraints, a missing register entry is treated as an absence of documentation, never as evidence of physical impossibility.
3. **Primary Gate Integration**: G0 is positioned as the primary gate in [`GatingPipeline`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/gates.py), executing strictly prior to `G1_DELAY_FEASIBILITY`.
4. **Policy-Governed Unknown Handling**: Supports strict conservative rejection (`allow_unknown=False`) for SWaT A4/A5 processing while preserving unresolved status in the audit trail without false validation when `allow_unknown=True`.
5. **Full Legacy Backward Compatibility**: Legacy workflows and non-SWaT benchmarks (such as MetroPT-3 or synthetic unit tests) that configure `structural_mask=None` bypass G0 completely, preserving 100% of preexisting behavior.
6. **Unexcited Actuator Identification and State Extension**: Delineates physical connectivity, baseline excitation, statistical identifiability, and dynamic influence. Integrates `EdgeState.UNEXCITED_PRIOR` and explicit metadata into [`EdgeRecord`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/schemas.py).
7. **CRI Uncertainty Safety**: Prevents silent zero-risk conclusions for targets downstream of unexcited actuators by reporting `cri_status = "UNCERTAIN_UNEXCITED"` and identifying upstream unexcited sources.
8. **100% Passing Test Suite**: 29 new focused unit tests pass, and all 757 preexisting unit tests pass without regression (865 passing across the complete repository test suite).

---

## 2. Input Integrity and Physical Connectivity Register

The structural mask derives its physical constraints from the physical connectivity register established during the physical graph audit.

- **Register Path**: [`experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv)
- **Input File SHA-256**: `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`
- **Total Records**: 22
- **Documentary Breakdown**:
  - `DOCUMENTED`: 2 edges (EDGE_14, EDGE_18)
  - `INFERRED`: 16 edges (EDGE_01, EDGE_03–EDGE_13, EDGE_15–EDGE_17, EDGE_19)
  - `DISALLOWED`: 3 edges (EDGE_20, EDGE_21, EDGE_22)
  - `UNKNOWN`: 1 edge (EDGE_02)
- **Mask Status Breakdown**:
  - `1` (ALLOWED): 18 edges (16 INFERRED + 2 DOCUMENTED)
  - `0` (DISALLOWED): 3 edges
  - `?` (UNKNOWN): 1 edge

### Schema Validation Invariants
The loader [`PhysicalStructuralMask.load_from_csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/structural_mask.py) enforces:
- Non-empty source and destination component strings.
- Detection of duplicate edge pairs: raises an actionable `ValueError`.
- Detection of conflicting edge definitions: raises a descriptive `ValueError` specifying the contradictory statuses.
- Validation of status values against permitted representations (`1`, `0`, `?`, and documentary equivalents).
- Project-relative path resolution via `Path(__file__).resolve().parents[3]`, guaranteeing zero dependence on the runtime current working directory (`os.getcwd()`).

---

## 3. Gate G0_STRUCTURAL_MASK Behavior

### Gate Execution Logic
Candidate observations ([`PropagationObservation`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/schemas.py)) pass into `GatingPipeline._gate_one()`:

```
[Candidate Observation (u -> v)]
              |
              v
    +-------------------+
    | G0 STRUCTURAL MASK|
    +-------------------+
      |               |
   status=1       status=0 ----------------------------------> REJECT (G0)
      |               |                                       "Prohibited by physical structural mask"
      |           status=?
      |               |
      |          allow_unknown?
      |          /          \
      |        True        False ----------------------------> REJECT (G0)
      |         |            "Rejected under conservative policy"
      v         v
+-----------------------+
| G1 DELAY FEASIBILITY  |
+-----------------------+
      |
      v
[Subsequent Gates G2-G5]
```

### Execution Invariants
1. **Mask Value `1`**: Candidate proceeds to `G1_DELAY_FEASIBILITY`. Rejection status is `"pass"`.
2. **Mask Value `0`**: Candidate is rejected immediately at Gate G0 with reason:
   `"Prohibited by physical structural mask (status=0): no physical connection {source} -> {target}."`
   Subsequent gates (G1–G5) are never evaluated.
3. **Mask Value `?`**:
   - If `allow_unknown=False` (conservative SWaT operational setting): rejected at G0 with reason:
     `"Rejected under conservative policy (status=?): unverified physical connection {source} -> {target}."`
   - If `allow_unknown=True` (compatibility/audit setting): permitted to continue to G1, with `structural_mask_status="?"` preserved on the observation. It is never labeled as documented or validated.
4. **Ordering Invariant**: If a candidate violates both physical connectivity (status `0`) and delay feasibility (e.g. $\Delta t = -999$ s), Gate G0 executes first and records rejection at `G0_STRUCTURAL_MASK`.

---

## 4. Unexcited Actuator Handling and Lifecycle Integration

### Four-Tier Conceptual Taxonomy
The implementation maintains a strict separation across four distinct conceptual layers:

| Layer | Question Addressed | Operational Representation in TCMIM |
|---|---|---|
| **1. Physical Connectivity** | Does physical piping or wiring connect $u \to v$? | `StructuralStatus` (`1`, `0`, `?`) in `PhysicalStructuralMask` |
| **2. Baseline Excitation** | Did the component transition commands during baseline? | `is_unexcited_actuator` boolean in `EdgeRecord` ($\sigma = 0.0$ in baseline) |
| **3. Statistical Identifiability** | Can baseline data estimate parameters? | `baseline_identifiability` (e.g., `UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE`) |
| **4. Observed Dynamic Influence** | Was an empirical perturbation response measured? | `dynamically_validated` boolean in `EdgeRecord` and `PhysicalConnectivityRecord` |

### Edge State Extension: `EdgeState.UNEXCITED_PRIOR`
- **Initial State**: An unexcited actuator with physical connectivity prior documentation begins in `EdgeState.UNEXCITED_PRIOR`.
- **Downward Resistance**: In [`EdgeLifecycleStateMachine`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/edge/lifecycle.py), normal operational silence (`consecutive_silence >= expired_threshold`) does **NOT** cause `UNEXCITED_PRIOR` to transition to `WEAKENING` or `EXPIRED`. Physical plant piping does not disappear because no anomaly occurred.
- **Upward Transition**: When dynamic excitation occurs and fresh observations arrive in the current cycle (`consecutive_silence == 0` and `evidence_count >= candidate_threshold`), the edge transitions cleanly from `UNEXCITED_PRIOR` to `CANDIDATE`.
- **Structural Prior Weight**: The structural prior weight ($W_{\text{prior}} = 0.5$) is treated strictly as a configurable design parameter, never as an empirical probability or validated confidence score.

---

## 5. Cascade Risk Index (CRI) Safety Requirements

A severe safety hazard identified during audit was the **Zero-Excitation False Assurance Mode**: if an actuator such as `MV501` (RO reject valve) or `P601` (backwash pump) was unexcited in baseline, data-driven estimators drop it, leading an unconstrained pipeline to calculate $\text{CRI} = 0.0$ during an attack on that actuator.

### Safeguards Implemented in [`CRICalculator`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/cri/calculator.py):
1. **Uncertainty Tracking**: Alongside the numeric index, [`CRIRecord`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/schemas.py) now provides:
   - `cri_status`: `"VALIDATED_EMPIRICAL"` or `"UNCERTAIN_UNEXCITED"`
   - `unexcited_sources`: List of unexcited actuator IDs present upstream of the target machine.
2. **Triggering Conditions for `UNCERTAIN_UNEXCITED`**:
   - Any path in the dynamic graph traverses a node in `unexcited_actuators` or an edge marked `is_unexcited_actuator=True` / `state=EdgeState.UNEXCITED_PRIOR`.
   - The target node has zero active dynamic paths, but the structural mask confirms a permitted physical connection (`status=1`) from an unexcited actuator (e.g. `P601` $\to$ `LIT101`).
3. **No Fabrication of Risk**:
   - When no dynamic path exists, the calculator does **not** fabricate a synthetic risk number; `cri` remains `0.0`.
   - The critical difference is that the record explicitly signals `cri_status = "UNCERTAIN_UNEXCITED"` and lists `unexcited_sources = ["P601"]`, preventing operators from misinterpreting `0.0` as proven absence of risk.
4. **Path Pruning in PathFinder**: [`PathFinder`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/graph/path_finder.py) prunes any path containing an edge marked `status=0` (DISALLOWED) under the configured structural mask, preventing cross-stage shortcuts.

---

## 6. Comprehensive Test Verification

All tests were executed using Python 3.13.12 and pytest 9.1.1 on Windows.

### Test Execution Summary

| Test Category | Suite / File | Total Tests | Passed | Skipped | Failed | Execution Time |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **Focused Structural Mask Tests** | `tests/unit/test_structural_mask_gate.py` | 29 | 29 | 0 | 0 | 0.43s |
| **Complete Unit Test Suite** | `tests/unit/` | 786 | 786 | 0 | 0 | 8.31s |
| **Complete Repository Test Suite** | `tests/` (Unit + Integration) | 872 | 865 | 7* | 0 | 12.59s |

*\*Note: 7 skipped integration tests require optional local hardware captures or external MetroPT-3 datasets not present in this workspace.*

### Detailed Focused Test Coverage:
1. `TestRegisterLoadingAndValidation`:
   - `test_load_default_register`: Verified 22 records, exact SHA-256 match, 18 permitted, 3 disallowed, 1 unknown.
   - `test_missing_file_raises_error`: Validated FileNotFoundError on invalid path.
   - `test_missing_required_columns_raises_error`: Validated missing header check.
   - `test_empty_identifiers_raise_error`: Validated non-empty component identifier enforcement.
   - `test_invalid_status_raises_error`: Validated rejection of unrecognized status values.
   - `test_duplicate_edge_records_raise_error`: Validated detection of duplicate pairs.
   - `test_conflicting_edge_records_raise_error`: Validated detection of contradictory definitions.
2. `TestMaskQuerySemantics`:
   - `test_permitted_edges`: Verified status `1` for forward piping (`P301` $\to$ `DPIT301`, `P601` $\to$ `LIT101`).
   - `test_prohibited_edges`: Verified status `0` for impossible edges (`AIT201` $\to$ `FIT501`, `P601` $\to$ `AIT201`, `MV501` $\to$ `DPIT301`).
   - `test_explicit_unknown_edge`: Verified status `?` for ambiguous measurement (`FIT501` $\to$ `PIT501`).
   - `test_missing_unregistered_edge_returns_unknown_not_prohibited`: Verified that missing edges return `?`, never `0`.
   - `test_separate_field_preservation`: Confirmed distinct fields for documentary status, mask status, identifiability, and dynamic validation.
3. `TestGateStructuralMaskDirect`:
   - Verified pass/fail outcomes and reason formatting for status `1`, `0`, and `?` under conservative and permissive policies.
4. `TestGatingPipelineIntegration`:
   - `test_gate_ordering_g0_before_g1`: Confirmed G0 rejects before G1 evaluates.
   - `test_permitted_edge_proceeds_to_subsequent_gates`: Confirmed permitted edges pass to G1.
   - `test_unknown_edge_audit_trail_preservation`: Confirmed `structural_mask_status="?"` is retained under permissive mode.
   - `test_legacy_behavior_without_structural_mask`: Confirmed default `structural_mask=None` preserves 100% legacy gating behavior.
5. `TestUnexcitedActuatorsAndLifecycle`:
   - Confirmed detection of 17 static actuators (`P601`, `MV501`, etc.).
   - Confirmed `EdgeState.UNEXCITED_PRIOR` resists decay on silence and transitions to `CANDIDATE` on dynamic excitation.
   - Confirmed `EdgeRecord` metadata fields.
6. `TestCRISafetyAndUncertainty`:
   - Confirmed isolated nodes receive `VALIDATED_EMPIRICAL` with `cri=0.0`.
   - Confirmed target with unexcited physical predecessor (`P601` $\to$ `LIT101`) is flagged `UNCERTAIN_UNEXCITED` even with `cri=0.0`.
   - Confirmed active paths traversing unexcited actuators set `cri_status="UNCERTAIN_UNEXCITED"`.
   - Confirmed standard empirical paths set `cri_status="VALIDATED_EMPIRICAL"`.
   - Confirmed `PathFinder` prunes prohibited edges during multi-hop path search.
7. `TestDeterminism`:
   - Verified byte-for-byte and float-exact determinism across 5 repeated evaluation batches.

---

## 7. Change Manifest and Integrity Audit

### Modified Files:
- [`src/tcmim/gating/__init__.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/__init__.py): Exported structural mask classes and gate function.
- [`src/tcmim/gating/gates.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/gates.py): Integrated Gate G0, added config attributes, preserved audit status.
- [`src/tcmim/schemas.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/schemas.py): Added `structural_mask_status` to `PropagationObservation`, added `UNEXCITED_PRIOR` to `EdgeState`, added unexcited fields to `EdgeRecord` and `CRIRecord`.
- [`src/tcmim/edge/lifecycle.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/edge/lifecycle.py): Added `UNEXCITED_PRIOR` lifecycle transitions.
- [`src/tcmim/graph/path_finder.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/graph/path_finder.py): Added structural mask pruning in `PathFinderConfig` and `_dfs`.
- [`src/tcmim/cri/calculator.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/cri/calculator.py): Integrated unexcited actuator tracking and `cri_status` uncertainty reporting.

### Created Files:
- [`src/tcmim/gating/structural_mask.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/src/tcmim/gating/structural_mask.py)
- [`tests/unit/test_structural_mask_gate.py`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_structural_mask_gate.py)
- [`experiments/results/swat_a4a5_structural_mask_gate/structural_mask_config.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/structural_mask_config.json)
- [`experiments/results/swat_a4a5_structural_mask_gate/test_results.txt`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/test_results.txt)
- [`experiments/results/swat_a4a5_structural_mask_gate/change_manifest.json`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/change_manifest.json)
- [`experiments/results/swat_a4a5_structural_mask_gate/implementation_report.md`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_structural_mask_gate/implementation_report.md)

### Preserved Work (Untouched Reference Artifacts):
- `experiments/results/swat_a4a5/` (9 reference files)
- `experiments/results/swat_a4a5_detector_comparison/` (7 reference files)
- `experiments/results/swat_a4a5_detector_comparison_v2/` (8 reference files)
- `experiments/results/swat_a4a5_channel_lag_analysis/` (5 reference files)
- `experiments/results/swat_a4a5_physical_graph_audit/` (6 reference files, including `physical_connectivity_register.csv` SHA-256: `08e0ce5764419c6bbfbec716644b1e4bdd046c6c81548f3fd98f573e8379b3c3`)

---

## 8. Scientific Integrity and Governance Invariants

In accordance with strict scientific integrity standards:
1. **No Inferred Causality**: Permitting an edge in Gate G0 indicates only that physical connectivity is documented or physically inferred. It does **not** prove causality, dynamic activation, or temporal propagation.
2. **Correlation != Causality**: Statistical cross-correlation alone remains strictly insufficient to promote candidate edges to confirmed propagation edges.
3. **No False Equivalence for Unexcited Actuators**: Zero variance during the 8,100-second baseline training period does **not** imply zero physical influence. It implies only that empirical statistical estimators cannot compute parameters from that baseline.
4. **No Fabrication of Risk**: When baseline unidentifiability prevents empirical risk computation, TCMIM does not invent a numeric risk value. It transparently flags `cri_status = "UNCERTAIN_UNEXCITED"` and reports the unexcited upstream sources.
5. **No Stage 2 Validation Claim**: Successful execution of unit tests establishes software correctness and structural constraint enforcement, **not** dynamic cross-machine propagation validation.

---

## 9. Unresolved Limitations and Next Research Decision

### Current Limitations:
1. **Incomplete Plant Coverage**: The physical register contains 22 audited pairs. Full plant coverage for SWaT's 77 channels across stages P1–P6 requires official engineering P&ID diagrams currently missing from the supplied dataset package.
2. **Missing Differential Tank Level Formulation**: Hydraulic edges entering tanks (such as `FIT201` $\to$ `LIT301`) require integrating pump discharge outflows (`P301`) into a differential mass balance equation ($\frac{dL}{dt} = \frac{Q_{in} - Q_{out}}{A}$) rather than simple pairwise correlation.

### Recommended Next Research Decision:
With Gate G0_STRUCTURAL_MASK successfully implemented and verified, the next recommended research step is **Stage 2 Candidate Edge Feasibility Evaluation with G0 Constraint**:
- Run Stage 2 candidate edge matching on the SWaT A4/A5 anomaly events with G0 active.
- Compare candidate edge generation rates with and without G0 to quantify the exact hallucination reduction achieved by the physical prior.
- Maintain strict separation between verified physical edges and unresolved candidates.
