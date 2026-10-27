"""
TCMIM — Gating package (S7).

Modules
-------
gates           : Multi-gate directional consistency and gating pipeline (G0-G5).
structural_mask : Physical connectivity constraint mask (G0_STRUCTURAL_MASK).
"""

from tcmim.gating.gates import (
    GateOutcome,
    GatingConfig,
    GatingPipeline,
    gate_delay_feasibility,
    gate_direction_consistency,
    gate_health_consistency,
    gate_ordering,
    gate_relationship_consistency,
    gate_structural_mask,
)
from tcmim.gating.structural_mask import (
    DEFAULT_UNEXCITED_ACTUATORS,
    PhysicalConnectivityRecord,
    PhysicalStructuralMask,
    StructuralMaskConfig,
    StructuralStatus,
)

__all__ = [
    "GateOutcome",
    "GatingConfig",
    "GatingPipeline",
    "gate_structural_mask",
    "gate_delay_feasibility",
    "gate_ordering",
    "gate_direction_consistency",
    "gate_health_consistency",
    "gate_relationship_consistency",
    "PhysicalConnectivityRecord",
    "PhysicalStructuralMask",
    "StructuralMaskConfig",
    "StructuralStatus",
    "DEFAULT_UNEXCITED_ACTUATORS",
]

