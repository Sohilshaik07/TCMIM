# TCMIM Stage 2 Physical Structural Mask Specification

**Document Version**: 1.0  
**Specification Date**: 2026-10-26T13:25:20Z  
**Target Repository**: TCMIM (`src/tcmim/gating/`, `src/tcmim/graph/`, `src/tcmim/cri/`)  
**Scope**: Formal architectural specification of the Physical Structural Adjacency Mask ($\mathbf{M}_{\text{phys}}$) to prevent unconstrained data-driven edge hallucinations in Stage 2.

---

## 1. Motivation and Theoretical Basis

The previous empirical investigation on the SWaT A4/A5 July 2019 dataset established that purely data-driven statistical methods (time-lagged cross-correlation, VAR, Granger causality) cannot be trusted to discover physical propagation topologies:
- Pervasive low-frequency sensor drift (e.g., `AIT201` drifting continuously across multiple hours) generates massive empirical correlations ($r > 0.8$) between completely disconnected stages.
- Plantwide disturbances (such as the shutdown at 08:35:00 UTC) force concurrent downward steps across all 77 telemetry channels, creating spurious cross-stage correlation spikes.
- Tank integration dynamics cause bivariate cross-correlations to peak at arbitrary search boundaries (e.g., $\tau = -120$ s for `FIT201` $\to$ `LIT301`).

To prevent Stage 2 from constructing dense, hallucinatory graphs, TCMIM requires an auditable **Physical Structural Mask** ($\mathbf{M}_{\text{phys}}$) acting as an absolute gatekeeper.

---

## 2. Formal Mathematical Definition

Let $\mathcal{V}$ be the set of physical components (sensors and commanded actuators) in the plant:
$$\mathcal{V} = \{c_1, c_2, \dots, c_N\}$$
The Physical Structural Mask is a ternary matrix:
$$\mathbf{M}_{\text{phys}} \in \{0, 1, ?\}^{N \times N}$$
Where for each directed candidate pair $(u, v) \in \mathcal{V} \times \mathcal{V}$:
- **$\mathbf{M}_{\text{phys}}(u, v) = 1$ (ALLOWED)**: A direct physical hydraulic pipe, physical mechanical actuation, mass-transfer boundary, or verified electrical control interlock connects source $u$ to destination $v$. Dynamic evaluation and delay estimation are permitted.
- **$\mathbf{M}_{\text{phys}}(u, v) = 0$ (DISALLOWED)**: Fluid piping or electrical control connections are physically absent, structurally blocked (e.g., check valves preventing reverse flow), or isolated by intermediate buffer tanks. Stage 2 must **strictly mask this edge to zero**, regardless of empirical correlation strength.
- **$\mathbf{M}_{\text{phys}}(u, v) = ?$ (UNKNOWN)**: Physical connectivity is undetermined due to missing P&ID drawings in the supplied documentation. Handled according to safety policy (conservative mode: masked out; audit mode: flagged for inspection).

> [!IMPORTANT]
> **Scientific Rule: `UNKNOWN` is NOT `DISALLOWED`**. An edge marked `UNKNOWN` indicates a gap in documentation, not proof of physical impossibility. However, to maintain reproducibility, no edge marked `UNKNOWN` may be promoted to an active propagation graph without explicit documentary justification.

---

## 3. Macro Stage-to-Stage Physical Topology Matrix

Based on the verified SWaT process sequence, fluid flows strictly forward through sequential stages, with specific documented recycle paths:

| From Stage \ To Stage | P1 (Raw Water) | P2 (Chemical Dosing) | P3 (Ultrafiltration) | P4 (Dechlorination) | P5 (Reverse Osmosis) | P6 (Distribution/Backwash) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **P1 (Raw Water)** | **ALLOWED** (Intra) | **ALLOWED** (Pump P101) | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** |
| **P2 (Chemical Dosing)** | **0 (DISALLOWED)** | **ALLOWED** (Intra) | **ALLOWED** (Flow FIT201) | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** |
| **P3 (Ultrafiltration)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **ALLOWED** (Intra) | **ALLOWED** (Pump P301) | **0 (DISALLOWED)** | **0 (DISALLOWED)** |
| **P4 (Dechlorination)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **ALLOWED** (Intra) | **ALLOWED** (Pump P401) | **0 (DISALLOWED)** |
| **P5 (Reverse Osmosis)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **ALLOWED** (Intra) | **ALLOWED** (Permeate FIT502) |
| **P6 (Distribution)** | **ALLOWED** (Recycle P601) | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **0 (DISALLOWED)** | **ALLOWED** (Intra) |

### Key Physical Constraints:
1. **No "Skip" Edges**: Direct hydraulic edges jumping stages (e.g., P1 $\to$ P3, P2 $\to$ P5, P3 $\to$ P6) are **strictly DISALLOWED**. Fluid must pass through intermediate buffer tanks (T201, T301, T401) with physical capacitance and residence times.
2. **Reverse Flow Prohibited**: Flow from downstream stages back to upstream stages (e.g., P5 $\to$ P3, P4 $\to$ P2) is physically prevented by check valves and positive pump heads.
3. **Documented Recycle Line (P6 $\to$ P1)**: Backwash pump `P601` is explicitly documented in Attack A3 as recycling water from Stage 6 back to raw water tank T101 in Stage 1. This is the **only permitted reverse cross-stage edge**.

---

## 4. Component-Level Structural Mask Specification

The component-level mask $\mathbf{M}_{\text{phys}}(u, v)$ is derived from the [`physical_connectivity_register.csv`](file:///c:/Users/SKSOH/OneDrive/Desktop/Project1-new/tcmim/experiments/results/swat_a4a5_physical_graph_audit/physical_connectivity_register.csv).

### A. Explicitly Permitted Physical Edges ($\mathbf{M}_{\text{phys}} = 1$)

| Edge ID | Source ($u$) | Target ($v$) | Relationship Type | Physical Mechanism |
|---|---|---|---|---|
| `EDGE_01` | `P301` | `DPIT301` | Hydraulic | UF feed pump actuation generates trans-membrane differential pressure. |
| `EDGE_03` | `FIT501` | `FIT502` | Mass Balance | RO membrane separation mass balance (Feed $\to$ Permeate). |
| `EDGE_04` | `FIT201` | `LIT301` | Hydraulic | Chemical dosing flow enters Tank T301 (requires differential level formulation). |
| `EDGE_05` | `MV501` | `PIT502` | Hydraulic | RO reject valve closure causes vessel backpressure surge. |
| `EDGE_06` | `MV101` | `LIT101` | Hydraulic | Raw water inlet valve controls inflow to Tank T101. |
| `EDGE_07` | `P101` | `FIT101` | Hydraulic | Raw water supply pump discharge generates flow FIT101. |
| `EDGE_08` | `P101` | `LIT101` | Hydraulic | Pump P101 suction draws fluid from Tank T101. |
| `EDGE_09` | `LIT101` | `P101` | Control Interlock | Low-level trip / high-level start interlock in PLC1. |
| `EDGE_10` | `MV201` | `FIT201` | Hydraulic | Chemical dosing valve controls fluid passage into Stage 2 pipe. |
| `EDGE_11` | `P203` | `AIT202` | Chemical Injection | Hydrochloric acid pump P203 directly alters pH measured by AIT202. |
| `EDGE_12` | `P205` | `AIT203` | Chemical Injection | Sodium bisulfite pump P205 directly alters ORP measured by AIT203. |
| `EDGE_13` | `LIT301` | `P301` | Control Interlock | PLC3 level control loop (LIT301 high keeps P301 running). |
| `EDGE_14` | `FIT401` | `UV401` | Control Interlock | Low-flow trip interlock in PLC4 (FIT401 < 0.8 shuts off UV lamp). |
| `EDGE_15` | `P401` | `FIT401` | Hydraulic | RO feed pump P401 discharge generates feed flow FIT401. |
| `EDGE_16` | `P501` | `PIT502` | Hydraulic | High-pressure RO pump P501 discharge builds membrane pressure PIT502. |
| `EDGE_17` | `FIT502` | `LIT601` | Hydraulic | Permeate flow delivers clean water to tank T601. |
| `EDGE_18` | `P601` | `LIT101` | Hydraulic | Backwash recycle pump P601 discharges into raw water tank T101. |
| `EDGE_19` | `P601` | `FIT601` | Hydraulic | Distribution pump P601 discharge generates flow FIT601. |

### B. Prohibited Physical Edges ($\mathbf{M}_{\text{phys}} = 0$)

| Edge ID | Source ($u$) | Target ($v$) | Reason for Prohibition |
|---|---|---|---|
| `EDGE_02` | `FIT501` | `PIT501` | **Directionally Inverted**: PIT501 is upstream suction pressure; downstream flow does not cause upstream suction pressure. |
| `EDGE_20` | `AIT201` | `FIT501` | **Physically Disconnected**: Stage 2 conductivity cannot directly cause Stage 5 RO feed flow; separated by 3 buffer tanks. |
| `EDGE_21` | `P601` | `AIT201` | **Physically Disconnected**: Stage 6 backwash pump has no piping connection to Stage 2 conductivity analyzer. |
| `EDGE_22` | `MV501` | `DPIT301` | **Physically Disconnected**: Stage 5 valve closure cannot cause upstream pressure changes in Stage 3 UF membrane. |

---

## 5. Architectural Integration into Stage 2 Pipeline

### A. Integration with Gating Pipeline (`src/tcmim/gating/gates.py`)
Currently, `GatingPipeline` sequentially evaluates:
- G1: DELAY_FEASIBILITY
- G2: ORDERING
- G3: DIRECTION_CONSISTENCY
- G4: HEALTH_CONSISTENCY
- G5: RELATIONSHIP_CONSISTENCY

**Proposed Modification**: Add **Gate G0 — STRUCTURAL_MASK** as the primary gate:
```python
def gate_structural_mask(
    obs: PropagationObservation,
    mask: PhysicalStructuralMask,
) -> GateOutcome:
    """Evaluate whether candidate edge is permissible under the physical mask."""
    status = mask.get_status(obs.source_machine, obs.target_machine)
    if status == StructuralStatus.ALLOWED:
        return GateOutcome(gate="G0_STRUCTURAL_MASK", passed=True, reason="pass")
    elif status == StructuralStatus.DISALLOWED:
        return GateOutcome(
            gate="G0_STRUCTURAL_MASK",
            passed=False,
            reason=f"Physically impossible edge: {obs.source_machine}->{obs.target_machine}",
        )
    else:  # UNKNOWN
        passed = mask.config.allow_unknown
        return GateOutcome(
            gate="G0_STRUCTURAL_MASK",
            passed=passed,
            reason="Unknown physical connection (policy: " + ("pass" if passed else "reject") + ")",
        )
```

### B. Integration with Dynamic Graph (`src/tcmim/graph/dynamic_graph.py`)
- In `DynamicGraph.update(edge_records)`, any edge candidate that fails `G0_STRUCTURAL_MASK` is rejected before state transitions (`PROVISIONAL`, `CONFIRMED`, `STABLE`) can occur.
- Graph snapshots record `is_physically_masked=True` for auditing.

### C. Integration with Cascade Risk Index (`src/tcmim/cri/calculator.py`)
- In `PathFinder.find_paths()`, paths that contain any edge with $\mathbf{M}_{\text{phys}} = 0$ are pruned immediately.
- Eliminates risk inflation caused by spurious cross-stage shortcuts.
