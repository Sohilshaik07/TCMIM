# TCMIM Stage 3.1: Physical Topology and Structural Condition Audit

## Executive Summary

This audit assesses the physical topology changes proposed in Stage 3:
1. **`EDGE_07` (`P101 -> FIT101`)**: Proposed as **`DISALLOWED`** (previously `INFERRED`).
2. **`EDGE_23` (`P101 -> FIT201`)**: Proposed as a new forward hydraulic edge with status **`INFERRED`**, marked as conditional on `MV201 == 2`.

This audit concludes that:
- The disallowance of `P101 -> FIT101` is **fully verified and physically sound**.
- The physical association `P101 -> FIT201` is **empirically supported**, but the current codebase **cannot safely represent or enforce its conditional status**.
- Registering `EDGE_23` with status `INFERRED` causes the production `PhysicalStructuralMask` and Gate `G0` to treat `P101 -> FIT201` as **universally permitted across all operating states**—including when motorized valve `MV201` is completely closed.

---

## 1. Audit of EDGE_07 (P101 -> FIT101) Disallowance

### 1.1 Empirical Verification
An exhaustive analysis of all 14,996 records in the raw SWaT A4/A5 dataset confirms:
- **Correlation**: $\text{corr}(\text{P101}, \text{FIT101}) = \mathbf{0.0528}$.
- **Zero Transient Response**: Pump `P101` underwent 12 physical transitions (6 startups, 6 shutdowns). In all 12 episodes, flow `FIT101` showed zero step response ($\Delta < 0.005\text{ m}^3/\text{h}$, 0/12 responsive transitions).
- **Actuator Decoupling**: For all 4,453 seconds where raw water pump `P101` was running while inlet valve `MV101` was closed, flow `FIT101` was identically **$0.000000\text{ m}^3/\text{h}$** (zero variance).
- **Inlet Control Evidence**: Flow `FIT101` is strongly correlated with municipal inlet valve `MV101` ($\text{corr}(\text{MV101}, \text{FIT101}) = \mathbf{0.9259}$). When `MV101` is open (`2`), `FIT101` reads $4.38\text{ m}^3/\text{h}$ regardless of `P101` state.

### 1.2 Physical and Architectural Grounding
- `FIT101` is the raw water intake flow transmitter located on the municipal supply feed line into raw water storage tank `T101`.
- `P101` is a centrifugal suction pump located at the base of tank `T101`, discharging liquid out of Stage 1 into Stage 2.
- The hypothesis that `P101` discharge directly feeds `FIT101` was an instrumentation naming confusion during initial tag registration.
- **Audit Verdict**: The disallowance of `EDGE_07` is **VERIFIED AND DEFECT-FREE**. It corrects an invalid edge that previously allowed spurious correlation candidates to survive G0.

---

## 2. Audit of EDGE_23 (P101 -> FIT201) and the MV201 Dependency

### 2.1 Empirical Support for Transfer Coupling
- Plantwide correlation between pump `P101` and Stage 2 flow transmitter `FIT201` is $r = \mathbf{0.8845}$. When valve `MV201` is open, correlation exceeds $0.98$.
- At all 12 transitions of `P101`, flow `FIT201` exhibits an immediate flow transition between $0.00\text{ m}^3/\text{h}$ and $2.34\text{ m}^3/\text{h}$.
- Pump `P101` provides the motive pressure necessary to drive liquid from tank `T101` into the chemical dosing pipe monitored by `FIT201`.

### 2.2 The Operating-State Condition
Fluid delivery from `P101` to `FIT201` is physically impossible unless inline motorized valve `MV201` is open:
$$\text{FIT201}(t) = f(\text{P101}(t), \text{MV201}(t))$$
- When `MV201 == 1` (CLOSED), the pipe is physically blocked. Even if `P101` is running, no fluid reaches `FIT201`.
- When `P101 == 1` (OFF), no motive head exists. Even if `MV201` is open, gravity/static flow is negligible ($<0.002\text{ m}^3/\text{h}$).
- Normal operation in SWaT PLC ladder logic tightly couples the two actuators: `MV201` opens first ($1 \to 0 \to 2$ over 7–8s); upon confirming open state, `P101` is commanded ON ($1 \to 2$).
- In abnormal recovery cycles (e.g. row 11,221), `P101` energization was delayed by 6 seconds, during which `FIT201` remained at $0.00\text{ m}^3/\text{h}$ despite `MV201` being open.

---

## 3. Critical Code Defect: Structural Mask Cannot Represent State Conditions

### 3.1 Code Inspection of PhysicalStructuralMask and Gate G0
Inspection of `src/tcmim/gating/structural_mask.py` and `src/tcmim/gating/gates.py` reveals how candidate edges are evaluated:

```python
# src/tcmim/gating/structural_mask.py
class StructuralStatus(str, Enum):
    ALLOWED = "1"
    DISALLOWED = "0"
    UNKNOWN = "?"

    @classmethod
    def from_raw(cls, val: Any) -> "StructuralStatus":
        s = str(val).strip().upper()
        if s in ("1", "ALLOWED", "PERMITTED", "DOCUMENTED", "INFERRED"):
            return cls.ALLOWED
        if s in ("0", "DISALLOWED", "PROHIBITED", "NO_DISALLOWED"):
            return cls.DISALLOWED
        if s in ("?", "UNKNOWN", "CONDITIONAL", "UNVERIFIED"):
            return cls.UNKNOWN
```

And in `src/tcmim/gating/gates.py`:

```python
def gate_structural_mask(obs: PropagationObservation, mask: PhysicalStructuralMask, ...):
    status = mask.get_status(obs.source_machine, obs.target_machine)
    if status == StructuralStatus.ALLOWED:
        return GateOutcome(gate="G0_STRUCTURAL_MASK", passed=True, reason="pass")
```

### 3.2 The Inadvertent Universal Permissiveness Vulnerability
In `proposed_connectivity_register.csv`, `EDGE_23` is defined as:
```csv
EDGE_23,P101,FIT201,P1,P2,hydraulic,FORWARD,INFERRED,SWaT Process Architecture; Stage 1-2 Transfer Line; Stage 3 Telemetry Audit,Stage 3 Empirical Audit,HIGH,CONDITIONAL,True,IDENTIFIABLE,"STAGE 3 ADDITION: Raw water supply pump P101 draws suction from Tank T101 and discharges through chemical dosing valve MV201 into flow transmitter FIT201. Permitted as structural edge conditional on MV201 == 2 (OPEN)."
```

Notice the conflict:
1. Column `status` is set to `"INFERRED"`.
2. Column `suitable_as_structural_constraint` is set to `"CONDITIONAL"`.
3. In `PhysicalStructuralMask.load_from_csv()`, line 257 calls `StructuralStatus.from_raw(row["status"])`. Because `status == "INFERRED"`, the mask status is set to **`StructuralStatus.ALLOWED`** (`"1"`).
4. The field `suitable_as_structural_constraint` is parsed as a string for metadata logging, but **is never checked by `gate_structural_mask()`**!
5. `gate_structural_mask()` receives only `obs.source_machine` (`"P101"`) and `obs.target_machine` (`"FIT201"`). It does not receive telemetry arrays, timestamp context, or actuator state for `MV201`.
6. Therefore, `mask.get_status("P101", "FIT201")` returns **`StructuralStatus.ALLOWED`** unconditionally.

**Direct Audit Consequence**:
If `proposed_connectivity_register.csv` is loaded into the production pipeline, **`P101 -> FIT201` is treated as universally allowed in all operational states**. Any candidate edge generated between `P101` and `FIT201` while valve `MV201` is closed will pass Gate G0 without inspection.

---

## 4. Test Suite Failure to Detect the Vulnerability

In `tests/unit/test_swat_a4a5_stage3.py`, lines 80–86:

```python
    def test_p101_to_fit201_permitted_conditionally_in_proposed_register(self):
        """P101 -> FIT201 must be ALLOWED / INFERRED in the proposed register."""
        mask = PhysicalStructuralMask.load_from_csv(_prop_register_path)
        status = mask.get_status("P101", "FIT201")
        assert status == StructuralStatus.ALLOWED
        assert mask.is_permitted("P101", "FIT201")
```

This test actually **asserts that `mask.is_permitted("P101", "FIT201")` returns `True` unconditionally**.
The test suite did not test whether `P101 -> FIT201` is rejected when `MV201` is closed, because the class has no method signature to accept operating states. The test provided a false verification of a conditional invariant that the underlying code cannot enforce.

---

## 5. Architectural Recommendations for Stage 4

Before `EDGE_23` can be safely promoted to an active production structural constraint, the codebase requires one of the following architectural changes:

### Option A: Retain as `UNKNOWN` / `CONDITIONAL` in Structural Register (Recommended Immediate Action)
Set `status = "CONDITIONAL"` in `proposed_connectivity_register.csv` for `EDGE_23`.
- `StructuralStatus.from_raw("CONDITIONAL")` resolves to `StructuralStatus.UNKNOWN` (`'?'`).
- Under the conservative policy (`allow_unknown=False`), unverified/conditional candidate edges are rejected at G0.
- Under audit policy (`allow_unknown=True`), candidate edges pass G0 with an explicit `status=?` audit tag, deferring state-conditional evaluation to Gate G1 or G2.

### Option B: State-Conditioned Gate Interface (Stage 4 Target Architecture)
Extend `GateOutcome` and `gate_structural_mask()` to accept telemetry context:

```python
def gate_structural_mask(
    obs: PropagationObservation,
    mask: PhysicalStructuralMask,
    telemetry_context: Optional[pd.Series] = None,
    allow_unknown: bool = False,
) -> GateOutcome:
    rec = mask.get_record(obs.source_machine, obs.target_machine)
    if rec and rec.is_conditional:
        # Evaluate operating state condition, e.g. telemetry_context["MV201"] == 2
        ...
```

Until Option B is implemented, `EDGE_23` **must NOT be registered with status `INFERRED` / `ALLOWED`** in production.
