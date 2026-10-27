# TCMIM Stage 3.2: Safe Conditional Structural Connectivity Design

## 1. Executive Summary and Problem Statement

During the **TCMIM Stage 3.1 Independent Scientific Verification Audit**, an architectural vulnerability was identified in Gate G0 (`M-PHY`, Physical Structural Mask):

1. **Unconditional Promotion of Inferred Edges**: In Stage 3, candidate relationship `P101 -> FIT201` was proposed as a physical edge with documentary status `INFERRED` and `suitable_as_structural_constraint = CONDITIONAL`. However, the underlying loader `PhysicalStructuralMask.load_from_csv()` mapped all non-disallowed strings (including `INFERRED`) directly to `StructuralStatus.ALLOWED` (`'1'`).
2. **Lack of Actuator State Telemetry Interface**: The Gate G0 evaluation function `gate_structural_mask(obs, mask, allow_unknown)` received only the source component and destination component (`PropagationObservation.source_machine`, `PropagationObservation.target_machine`). It had no mechanism to accept, validate, or evaluate actuator operating state evidence.
3. **Unsafe Bypass**: Because pump `P101` draws from Tank `T101` and discharges through motorized valve `MV201` into flow transmitter `FIT201`, fluid flow occurs **if and only if** `MV201 == 2` (OPEN). When `MV201 == 1` (CLOSED), hydraulic flow is physically blocked ($0.000\text{ m}^3/\text{h}$). Mapping `P101 -> FIT201` unconditionally to `ALLOWED` allowed candidate propagation edges to bypass G0 even during periods when `MV201` was closed, unknown, or malfunctioning.

This document formalizes the **Stage 3.2 Safe Conditional Connectivity Architecture**, implementing an explicit quaternary status model, predicate parsing and evaluation engine, fail-closed state evidence interface, and strict legacy configuration protection.

---

## 2. Mathematical Formulation of Quaternary Structural Status

Let $V$ denote the set of physical plant components (sensors, actuators, tanks). The physical structural mask $M_{\text{phys}}$ is formalized over candidate directed pairs $(u, v) \in V \times V$:

$$
M_{\text{phys}}(u, v) \in \{1, 0, C, ?\}
$$

Where:
- **`1` (`ALLOWED`)**: Unconditionally permitted by physical piping, direct wiring, or physical interlock. Requires no operating-state evidence to pass G0.
- **`0` (`DISALLOWED`)**: Physically impossible, topologically isolated, or refuted by physical process audit (e.g. `P101 -> FIT101`). Always rejected at G0 regardless of plant telemetry.
- **`C` (`CONDITIONAL`)**: Permitted if and only if an explicit operating-state predicate $\Phi_{(u,v)}(S_t)$ is evaluated as `TRUE` against authenticated, fresh, non-contradictory actuator state evidence $S_t$.
- **`?` (`UNKNOWN`)**: Missing, unregistered, or insufficiently documented. Governed by configuration policy (`allow_unknown = False` in conservative SWaT mode; `allow_unknown = True` in audit discovery mode).

### Invariant: Protection of Conditional Edges
A critical invariant enforced in Stage 3.2 is that **`allow_unknown = True` must NEVER permit a `CONDITIONAL` edge to pass**. The permissive policy applies strictly to status `UNKNOWN` (`'?'`). Any edge registered as `CONDITIONAL` (`'C'`) requires known, valid, and satisfied actuator state evidence to pass. If evidence is missing, unknown, stale, or unsatisfied, the conditional edge **fails closed** (`passed = False`).

---

## 3. Predicate Architecture: `StateConditionPredicate`

Operating conditions are formally represented via the `StateConditionPredicate` frozen dataclass:

```python
@dataclass(frozen=True)
class StateConditionPredicate:
    actuator: str           # Target actuator tag (e.g. 'MV201')
    operator: str           # Comparison operator ('==', '!=', '>=', '<=', '>', '<', 'in')
    required_value: Any     # Required state target (e.g. 2 for OPEN)
    raw_expression: str     # Raw predicate string (e.g. 'MV201 == 2')
```

### Supported Predicate Grammar
The parser `StateConditionPredicate.parse(expr)` parses expressions such as:
- `MV201 == 2`
- `MV201 == 2 (OPEN)` (parenthetical descriptions are safely stripped)
- `MV302 == 1`
- `P101 != 0`

If an expression contains no recognized operator, has empty components, or cannot be parsed, the parser raises `ValueError`. At runtime during Gate G0 evaluation, an edge with a missing or malformed predicate triggers a conservative fail-closed rejection.

---

## 4. Actuator Evidence Interface Protocol

Gate G0 receives state evidence via two supported interfaces:
1. **Direct Parameter Injection**: `gate_structural_mask(obs, mask, state_evidence=...)`
2. **Observation-Level Attachment**: `obs.state_evidence = {...}`
3. **Pipeline-Level Mapping**: `GatingPipeline.apply(observations, state_evidence_map={...})`

### Evidence Data Formats
Evidence may be supplied either as a simple scalar map or a rich telemetry packet:

```python
# Format A: Simple scalar mapping
evidence = {"MV201": 2}

# Format B: Rich authenticated telemetry packet
evidence = {
    "MV201": {
        "value": 2,
        "timestamp": 1563608250.0,
        "quality": "GOOD",          # 'GOOD', 'BAD', 'INVALID', 'UNCERTAIN'
        "is_stale": False,          # Boolean staleness flag
    }
}
```

### Evaluation Decision Table

| Actuator Evidence Condition | Evaluation Result | G0 Gate Outcome | Diagnostic Reason |
|---|---|---|---|
| `evidence is None` | `False` | `REJECTED` | `missing actuator state evidence (fail-closed)` |
| `actuator not in evidence` | `False` | `REJECTED` | `actuator 'MV201' missing from state evidence` |
| `value is None` | `False` | `REJECTED` | `actuator 'MV201' state value is None` |
| `value in ('?', 'UNKNOWN', 'NAN')` | `False` | `REJECTED` | `actuator 'MV201' state is invalid/unknown` |
| `quality in ('BAD', 'INVALID')` | `False` | `REJECTED` | `actuator 'MV201' state quality invalid` |
| `is_stale is True` | `False` | `REJECTED` | `actuator 'MV201' state is flagged as stale` |
| `current_time - timestamp > max_age_s` | `False` | `REJECTED` | `actuator 'MV201' state is stale: age exceeds max_age_s` |
| `value == 1` (CLOSED) | `False` | `REJECTED` | `actuator condition failed: MV201 (1) == 2 is false` |
| `value == 2` (OPEN, valid, fresh) | `True` | **`PASSED`** | `pass: conditional constraint satisfied (MV201 == 2)` |

---

## 5. Freshness Policy and Timestamp Limitations

### Scientific Integrity Principle
In accordance with the repository safety rules:
> *"If no trustworthy timestamp or freshness metadata is available, do not invent a freshness guarantee. Document the limitation and require a trustworthy state input before integration."*

### Implementation Rules:
1. **Zero Fabrication**: If telemetry samples do not include high-resolution synchronization timestamps or reliable quality bits, `gate_structural_mask` does not invent or assume timestamps.
2. **Explicit Staleness Enforcement**: When `max_age_s` is configured:
   - If timestamp metadata is present, age is strictly checked against `current_time`.
   - If `require_freshness=True` and no timestamp is present in the evidence packet, the gate fails closed (`rejected`).
   - If `max_age_s is None` (default in offline audit mode), evidence value validity is verified without asserting synthetic freshness.
3. **Integration Prerequisite**: Before Stage 4 online dynamic gating can operate in production, the data adapter must provide cryptographically verified historian timestamps with bounded latency.

---

## 6. Protection Against Legacy Bypass

To satisfy Requirement 9 (*"Ensure legacy configurations cannot silently bypass the new conditional checks"*):

1. **Loader Multi-Column Inspection**: `PhysicalStructuralMask.load_from_csv()` inspects `status`, `suitable_as_structural_constraint`, `operating_condition`, and `physical_mechanism_and_notes`.
2. **Automatic Detection of Legacy Conditional Edges**: If a legacy CSV specifies `status == "INFERRED"` but `notes` mentions `conditional on MV201 == 2` or `suitable_as_structural_constraint == "CONDITIONAL"`, the loader automatically extracts the predicate and assigns status `StructuralStatus.CONDITIONAL`.
3. **No Fallback to Allowed**: Under no circumstances does a conditional edge default to `ALLOWED`. If the condition cannot be parsed or evaluated, the edge fails closed.

---

## 7. Software Architecture and Call Graph

```mermaid
graph TD
    A[PropagationObservation] -->|Candidate Edge (u, v)| B[GatingPipeline.apply]
    B --> C{Structural Mask Configured?}
    C -->|No| D[G1 Delay Feasibility (Legacy Mode)]
    C -->|Yes| E[gate_structural_mask (G0)]
    
    E --> F{mask.get_status(u, v)}
    F -->|ALLOWED '1'| G[Pass G0 -> Proceed to G1]
    F -->|DISALLOWED '0'| H[Reject G0: Structurally Prohibited]
    F -->|UNKNOWN '?'| I{allow_unknown?}
    I -->|False| J[Reject G0: Conservative Mode]
    I -->|True| K[Pass G0: Audit Permitted]
    
    F -->|CONDITIONAL 'C'| L{State Evidence Provided?}
    L -->|No / Missing| M[Reject G0: Fail-Closed Missing State]
    L -->|Yes| N{Predicate.evaluate(evidence)}
    N -->|Invalid / Stale / Bad Quality| O[Reject G0: State Invalid/Stale]
    N -->|Condition False (MV201 == 1)| P[Reject G0: Condition Not Met]
    N -->|Condition True (MV201 == 2)| Q[Pass G0 -> Proceed to G1]
```

---

## 8. Summary of Verification Status

All 10 requirements of Task A are verified by dedicated unit tests in [test_swat_a4a5_stage3_2.py](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/tests/unit/test_swat_a4a5_stage3_2.py):
- `test_mv201_open_satisfied`: PASSED
- `test_mv201_closed_rejected`: PASSED
- `test_missing_actuator_state_rejected`: PASSED
- `test_unknown_actuator_value_rejected`: PASSED
- `test_stale_state_evidence_rejected`: PASSED
- `test_malformed_conditional_predicate_fails_closed`: PASSED
- `test_unconditional_allowed_edge_preserved`: PASSED
- `test_disallowed_edge_always_rejected`: PASSED
- `test_allow_unknown_policy_cannot_bypass_conditional`: PASSED
- `test_gating_pipeline_integration`: PASSED
