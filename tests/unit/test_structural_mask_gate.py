"""
TCMIM — Unit tests for G0_STRUCTURAL_MASK milestone.

Covers:
- Physical connectivity register loading, SHA-256 verification, and path resolution.
- Strict schema validation, duplicate detection, conflicting record detection.
- Ternary mask status semantics: ALLOWED ('1'), DISALLOWED ('0'), UNKNOWN ('?').
- Policy handling for unknown/unregistered edges (conservative allow_unknown=False vs permissive allow_unknown=True).
- Gate ordering: G0_STRUCTURAL_MASK evaluated strictly BEFORE G1_DELAY_FEASIBILITY.
- Missing register entries default to UNKNOWN ('?'), never DISALLOWED ('0').
- Unexcited actuator identification and EdgeState.UNEXCITED_PRIOR lifecycle transitions.
- CRI safety: prevents silent zero-risk conclusions, distinguishes physical prior from empirical evidence.
- Full legacy backward compatibility when no structural mask is configured.
- Determinism across repeated runs.
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import pytest

from tcmim.config import EdgeLifecycleConfig
from tcmim.cri.calculator import CRICalculator, CRIConfig
from tcmim.edge.lifecycle import EdgeLifecycleStateMachine
from tcmim.gating.gates import (
    GateOutcome,
    GatingConfig,
    GatingPipeline,
    gate_structural_mask,
)
from tcmim.gating.structural_mask import (
    DEFAULT_UNEXCITED_ACTUATORS,
    PhysicalConnectivityRecord,
    PhysicalStructuralMask,
    StructuralMaskConfig,
    StructuralStatus,
    get_default_register_path,
)
from tcmim.graph.dynamic_graph import DynamicGraph
from tcmim.graph.path_finder import PathFinder, PathFinderConfig
from tcmim.schemas import (
    EdgeRecord,
    EdgeState,
    EventRecord,
    HealthSample,
    Modality,
    PropagationObservation,
    Provenance,
)

NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_obs(
    source: str = "P301",
    target: str = "DPIT301",
    delta_t_s: float = 10.0,
    gate_result: str = "accepted",
    reject_reason: str = None,
) -> PropagationObservation:
    return PropagationObservation(
        source_event=f"evt_{source}",
        target_event=f"evt_{target}",
        source_machine=source,
        target_machine=target,
        delta_t_s=delta_t_s,
        gate_result=gate_result,
        reject_reason=reject_reason,
        provenance=Provenance.SYNTHETIC,
    )


def _make_edge(
    source: str,
    target: str,
    confidence: float = 0.5,
    state: EdgeState = EdgeState.CONFIRMED,
    is_unexcited: bool = False,
) -> EdgeRecord:
    return EdgeRecord(
        source=source,
        target=target,
        state=state,
        evidence_count=6,
        est_delay_s=30.0,
        confidence=confidence,
        last_updated=NOW,
        modality=Modality.PRESSURE,
        provenance=Provenance.SYNTHETIC,
        is_unexcited_actuator=is_unexcited,
    )


# ==============================================================================
# 1. Register Loading, Path Resolution, and Schema Validation
# ==============================================================================

class TestRegisterLoadingAndValidation:
    def test_load_default_register(self):
        """Default register must load cleanly, resolve project-relative path, and have valid hash."""
        default_path = get_default_register_path()
        assert default_path.is_file(), f"Default register path {default_path} not found"

        mask = PhysicalStructuralMask.load_from_csv()
        assert len(mask.all_records()) == 22
        assert len(mask.register_sha256) == 64

        # Verify hash matches actual file bytes
        expected_hash = hashlib.sha256(default_path.read_bytes()).hexdigest()
        assert mask.register_sha256 == expected_hash

        # Verify status breakdown matches audit specification
        permitted = mask.permitted_edges()
        prohibited = mask.prohibited_edges()
        unknown = mask.unknown_edges()

        # 16 INFERRED + 2 DOCUMENTED = 18 permitted
        assert len(permitted) == 18
        # 3 DISALLOWED (EDGE_20, EDGE_21, EDGE_22)
        assert len(prohibited) == 3
        # 1 UNKNOWN (EDGE_02)
        assert len(unknown) == 1

    def test_missing_file_raises_error(self, tmp_path):
        """Non-existent CSV path must raise FileNotFoundError with actionable message."""
        non_existent = tmp_path / "does_not_exist.csv"
        with pytest.raises(FileNotFoundError, match="not found"):
            PhysicalStructuralMask.load_from_csv(csv_path=non_existent)

    def test_missing_required_columns_raises_error(self, tmp_path):
        """CSV missing mandatory columns must raise ValueError."""
        csv_file = tmp_path / "invalid_headers.csv"
        csv_file.write_text("edge_id,source_component\nEDGE_01,P101\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required column"):
            PhysicalStructuralMask.load_from_csv(csv_path=csv_file)

    def test_empty_identifiers_raise_error(self, tmp_path):
        """CSV with empty source or destination component must raise ValueError."""
        csv_file = tmp_path / "empty_component.csv"
        csv_file.write_text(
            "edge_id,source_component,destination_component,status\n"
            "EDGE_01,  ,LIT101,INFERRED\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="source_component is empty"):
            PhysicalStructuralMask.load_from_csv(csv_path=csv_file)

    def test_invalid_status_raises_error(self, tmp_path):
        """CSV with unrecognized status must raise ValueError."""
        csv_file = tmp_path / "invalid_status.csv"
        csv_file.write_text(
            "edge_id,source_component,destination_component,status\n"
            "EDGE_01,P101,LIT101,MAYBE_CONNECTED\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Invalid mask status"):
            PhysicalStructuralMask.load_from_csv(csv_path=csv_file)

    def test_duplicate_edge_records_raise_error(self, tmp_path):
        """CSV with duplicate identical edge pairs must raise ValueError."""
        csv_file = tmp_path / "duplicate_edge.csv"
        csv_file.write_text(
            "edge_id,source_component,destination_component,status\n"
            "EDGE_01,P101,LIT101,INFERRED\n"
            "EDGE_02,P101,LIT101,INFERRED\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Duplicate edge definition"):
            PhysicalStructuralMask.load_from_csv(csv_path=csv_file)

    def test_conflicting_edge_records_raise_error(self, tmp_path):
        """CSV with duplicate pair having conflicting statuses must raise actionable ValueError."""
        csv_file = tmp_path / "conflicting_edge.csv"
        csv_file.write_text(
            "edge_id,source_component,destination_component,status\n"
            "EDGE_01,P101,LIT101,INFERRED\n"
            "EDGE_02,P101,LIT101,DISALLOWED\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="Conflicting duplicate edge definition"):
            PhysicalStructuralMask.load_from_csv(csv_path=csv_file)


# ==============================================================================
# 2. Mask Query Semantics and Unknown-Handling Invariants
# ==============================================================================

class TestMaskQuerySemantics:
    @pytest.fixture
    def swat_mask(self):
        return PhysicalStructuralMask.load_from_csv()

    def test_permitted_edges(self, swat_mask):
        """Documented or inferred physical connections must return ALLOWED ('1')."""
        assert swat_mask.get_status("P301", "DPIT301") == StructuralStatus.ALLOWED
        assert swat_mask.is_permitted("P301", "DPIT301") is True
        assert swat_mask.is_prohibited("P301", "DPIT301") is False

        # Documented recycle line P601 -> LIT101
        assert swat_mask.get_status("P601", "LIT101") == StructuralStatus.ALLOWED
        assert swat_mask.is_permitted("P601", "LIT101") is True

    def test_prohibited_edges(self, swat_mask):
        """Disallowed physical edges must return DISALLOWED ('0')."""
        # Spurious cross-stage candidate AIT201 -> FIT501
        assert swat_mask.get_status("AIT201", "FIT501") == StructuralStatus.DISALLOWED
        assert swat_mask.is_prohibited("AIT201", "FIT501") is True
        assert swat_mask.is_permitted("AIT201", "FIT501") is False

        # Physically disconnected P601 -> AIT201
        assert swat_mask.get_status("P601", "AIT201") == StructuralStatus.DISALLOWED
        assert swat_mask.is_prohibited("P601", "AIT201") is True

        # Inverted hydraulic connection MV501 -> DPIT301
        assert swat_mask.get_status("MV501", "DPIT301") == StructuralStatus.DISALLOWED
        assert swat_mask.is_prohibited("MV501", "DPIT301") is True

    def test_explicit_unknown_edge(self, swat_mask):
        """Explicitly ambiguous record (EDGE_02: FIT501 -> PIT501) must return UNKNOWN ('?')."""
        assert swat_mask.get_status("FIT501", "PIT501") == StructuralStatus.UNKNOWN
        assert swat_mask.is_unknown("FIT501", "PIT501") is True
        assert swat_mask.is_permitted("FIT501", "PIT501") is False
        assert swat_mask.is_prohibited("FIT501", "PIT501") is False

    def test_missing_unregistered_edge_returns_unknown_not_prohibited(self, swat_mask):
        """CRITICAL INVARIANT: Missing register entries must NOT default to prohibited (0)."""
        status = swat_mask.get_status("UNKNOWN_SRC_999", "UNKNOWN_TGT_999")
        assert status == StructuralStatus.UNKNOWN
        assert status.value == "?"
        assert swat_mask.is_prohibited("UNKNOWN_SRC_999", "UNKNOWN_TGT_999") is False

    def test_separate_field_preservation(self, swat_mask):
        """Documentary status, mask status, baseline identifiability, and dynamic validation must be distinct."""
        rec = swat_mask.get_record("P601", "LIT101")
        assert rec is not None
        assert rec.documentary_status == "DOCUMENTED"
        assert rec.mask_status == StructuralStatus.ALLOWED
        assert rec.mask_status.value == "1"
        assert rec.baseline_identifiability == "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE"
        assert rec.dynamically_validated is False


# ==============================================================================
# 3. Gate G0_STRUCTURAL_MASK Direct Function Tests
# ==============================================================================

class TestGateStructuralMaskDirect:
    @pytest.fixture
    def swat_mask(self):
        return PhysicalStructuralMask.load_from_csv()

    def test_permitted_edge_passes(self, swat_mask):
        obs = _make_obs("P301", "DPIT301")
        outcome = gate_structural_mask(obs, swat_mask, allow_unknown=False)
        assert outcome.passed is True
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert outcome.reason == "pass"

    def test_prohibited_edge_rejects(self, swat_mask):
        obs = _make_obs("AIT201", "FIT501")
        outcome = gate_structural_mask(obs, swat_mask, allow_unknown=False)
        assert outcome.passed is False
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert "Prohibited by physical structural mask" in outcome.reason
        assert "status=0" in outcome.reason

    def test_unknown_edge_conservative_policy_rejects(self, swat_mask):
        """Under conservative policy (allow_unknown=False), unknown edges are rejected."""
        obs = _make_obs("FIT501", "PIT501")  # status = ?
        outcome = gate_structural_mask(obs, swat_mask, allow_unknown=False)
        assert outcome.passed is False
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert "Rejected under conservative policy" in outcome.reason
        assert "status=?" in outcome.reason

    def test_unknown_edge_permissive_policy_passes(self, swat_mask):
        """Under permissive policy (allow_unknown=True), unknown edges pass G0."""
        obs = _make_obs("FIT501", "PIT501")  # status = ?
        outcome = gate_structural_mask(obs, swat_mask, allow_unknown=True)
        assert outcome.passed is True
        assert outcome.gate == "G0_STRUCTURAL_MASK"
        assert "Permitted under policy" in outcome.reason
        assert "status=?" in outcome.reason


# ==============================================================================
# 4. GatingPipeline Integration and Gate Ordering
# ==============================================================================

class TestGatingPipelineIntegration:
    @pytest.fixture
    def swat_mask(self):
        return PhysicalStructuralMask.load_from_csv()

    def test_gate_ordering_g0_before_g1(self, swat_mask):
        """G0_STRUCTURAL_MASK must execute strictly BEFORE G1_DELAY_FEASIBILITY.

        If an observation is both physically prohibited (status=0) and delay-infeasible
        (Δt = -999.0s), it MUST be rejected by G0_STRUCTURAL_MASK, NOT by G1.
        """
        cfg = GatingConfig(
            min_delay_s=0.0,
            max_delay_s=600.0,
            structural_mask=swat_mask,
            allow_unknown=False,
        )
        pipeline = GatingPipeline(cfg)

        # AIT201 -> FIT501 is physically DISALLOWED (status=0)
        # delta_t_s = -999.0 would also fail G1
        obs = _make_obs("AIT201", "FIT501", delta_t_s=-999.0)

        accepted, rejected = pipeline.apply([obs])
        assert len(accepted) == 0
        assert len(rejected) == 1

        rej = rejected[0]
        assert rej.gate_result == "rejected"
        assert "Prohibited by physical structural mask" in rej.reject_reason
        # Ensure it was rejected at G0, not G1
        assert "outside feasible window" not in rej.reject_reason
        assert rej.structural_mask_status == "0"

    def test_permitted_edge_proceeds_to_subsequent_gates(self, swat_mask):
        """A permitted edge (status=1) passes G0 and is evaluated by G1."""
        cfg = GatingConfig(
            min_delay_s=5.0,
            max_delay_s=600.0,
            structural_mask=swat_mask,
            allow_unknown=False,
        )
        pipeline = GatingPipeline(cfg)

        # P301 -> DPIT301 is ALLOWED, but delta_t_s = 2.0s fails G1 (min 5.0s)
        obs = _make_obs("P301", "DPIT301", delta_t_s=2.0)

        accepted, rejected = pipeline.apply([obs])
        assert len(accepted) == 0
        assert len(rejected) == 1

        rej = rejected[0]
        # Should be rejected at G1_DELAY_FEASIBILITY because it passed G0
        assert "outside feasible window" in rej.reject_reason
        assert rej.structural_mask_status == "1"

    def test_unknown_edge_audit_trail_preservation(self, swat_mask):
        """allow_unknown=True must preserve status '?' in audit trail and not claim validation."""
        cfg = GatingConfig(
            min_delay_s=0.0,
            max_delay_s=600.0,
            require_positive_dt=False,
            structural_mask=swat_mask,
            allow_unknown=True,  # permissive mode
        )
        pipeline = GatingPipeline(cfg)

        # Unregistered edge pair
        obs = _make_obs("NEW_PUMP_X", "NEW_SENSOR_Y", delta_t_s=15.0)

        accepted, rejected = pipeline.apply([obs])
        assert len(accepted) == 1
        assert len(rejected) == 0

        acc = accepted[0]
        assert acc.gate_result == "accepted"
        # Preserves unresolved status '?' in audit trail
        assert acc.structural_mask_status == "?"

    def test_legacy_behavior_without_structural_mask(self):
        """Default GatingPipeline (no structural mask configured) preserves 100% legacy behavior."""
        cfg = GatingConfig()  # structural_mask is None by default
        pipeline = GatingPipeline(cfg)

        # In legacy mode, any synthetically valid candidate pair passes gating
        obs1 = _make_obs("AIT201", "FIT501", delta_t_s=10.0)
        obs2 = _make_obs("P301", "DPIT301", delta_t_s=20.0)

        accepted, rejected = pipeline.apply([obs1, obs2])
        assert len(accepted) == 2
        assert len(rejected) == 0
        assert accepted[0].structural_mask_status is None


# ==============================================================================
# 5. Unexcited Actuator Handling and Lifecycle Invariants
# ==============================================================================

class TestUnexcitedActuatorsAndLifecycle:
    @pytest.fixture
    def swat_mask(self):
        return PhysicalStructuralMask.load_from_csv()

    def test_unexcited_actuators_identified(self, swat_mask):
        """P601 and MV501 must be recognized as unexcited actuators."""
        assert swat_mask.is_unexcited("P601") is True
        assert swat_mask.is_unexcited("MV501") is True
        assert swat_mask.is_unexcited("UV401") is True
        assert swat_mask.is_unexcited("P501") is True

        # P101 and P301 actively cycled in baseline (sigma > 0)
        assert swat_mask.is_unexcited("P101") is False
        assert swat_mask.is_unexcited("P301") is False

    def test_unexcited_prior_state_in_state_machine(self):
        """EdgeState.UNEXCITED_PRIOR must not expire or weaken on silence, and promotes on evidence."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=2,
            weakening_threshold=3,
            expired_threshold=5,
        )
        sm = EdgeLifecycleStateMachine(cfg)

        # 1. Unexcited physical prior does not decay on silence
        state, evt = sm.transition(
            current_state=EdgeState.UNEXCITED_PRIOR,
            evidence_count=0,
            direction_consistency=0.0,
            consecutive_silence=10,  # Far above expired_threshold
            edge_key="P601→LIT101",
        )
        assert state == EdgeState.UNEXCITED_PRIOR
        assert evt is None

        # 2. Fresh dynamic excitation arriving promotes to CANDIDATE
        state, evt = sm.transition(
            current_state=EdgeState.UNEXCITED_PRIOR,
            evidence_count=2,
            direction_consistency=1.0,
            consecutive_silence=0,
            edge_key="P601→LIT101",
        )
        assert state == EdgeState.CANDIDATE
        assert evt is not None
        assert "Dynamic excitation observed" in evt.reason

    def test_edge_record_metadata_fields(self):
        """EdgeRecord carries explicit unexcited actuator and identifiability metadata."""
        rec = EdgeRecord(
            source="P601",
            target="LIT101",
            state=EdgeState.UNEXCITED_PRIOR,
            evidence_count=0,
            est_delay_s=0.0,
            confidence=0.5,
            last_updated=NOW,
            modality=Modality.PRESSURE,
            provenance=Provenance.SYNTHETIC,
            is_unexcited_actuator=True,
            baseline_identifiability="UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE",
            structural_prior_weight=0.5,
        )
        assert rec.is_unexcited_actuator is True
        assert rec.baseline_identifiability == "UNIDENTIFIABLE_ZERO_BASELINE_VARIANCE"
        assert rec.structural_prior_weight == pytest.approx(0.5)


# ==============================================================================
# 6. CRI Safety and Uncertainty Handling
# ==============================================================================

class TestCRISafetyAndUncertainty:
    @pytest.fixture
    def swat_mask(self):
        return PhysicalStructuralMask.load_from_csv()

    def test_isolated_node_zero_risk_status(self):
        """Node with no predecessors and no physical upstream connections receives VALIDATED_EMPIRICAL."""
        graph = DynamicGraph()
        graph.update([_make_edge("A", "B", confidence=0.7)])
        calc = CRICalculator()

        record = calc.compute("A", graph)
        assert record.cri == pytest.approx(0.0)
        assert record.cri_status == "VALIDATED_EMPIRICAL"
        assert len(record.unexcited_sources) == 0

    def test_target_with_unexcited_upstream_connection_flags_uncertainty(self, swat_mask):
        """Safety requirement: An unexcited actuator must NOT silently receive zero risk.

        Target LIT101 has zero dynamic paths in graph. However, P601 is physically
        connected upstream to LIT101 (EDGE_18) and had zero baseline variance.
        CRI must flag UNCERTAIN_UNEXCITED and record P601 as unexcited source.
        """
        graph = DynamicGraph()
        # Graph has no edges pointing to LIT101
        cfg = CRIConfig(
            structural_mask=swat_mask,
            unexcited_actuators={"P601", "MV501"},
        )
        calc = CRICalculator(cfg)

        record = calc.compute("LIT101", graph)
        assert record.cri == pytest.approx(0.0)
        # CRITICAL SAFETY CHECK: Not silently VALIDATED_EMPIRICAL
        assert record.cri_status == "UNCERTAIN_UNEXCITED"
        assert "P601" in record.unexcited_sources

    def test_path_traversing_unexcited_actuator_flags_uncertainty(self):
        """If an active path traverses an unexcited actuator, CRI status is UNCERTAIN_UNEXCITED."""
        graph = DynamicGraph()
        # Path: MV501 (unexcited) -> PIT502
        edge = _make_edge("MV501", "PIT502", confidence=0.5, is_unexcited=True)
        graph.update([edge])

        cfg = CRIConfig(unexcited_actuators={"MV501"})
        calc = CRICalculator(cfg)

        record = calc.compute("PIT502", graph)
        assert record.cri > 0.0
        assert record.cri_status == "UNCERTAIN_UNEXCITED"
        assert "MV501" in record.unexcited_sources

    def test_normal_path_without_unexcited_actuator_is_validated_empirical(self):
        """Standard dynamic path between excited machines produces VALIDATED_EMPIRICAL."""
        graph = DynamicGraph()
        graph.update([_make_edge("P101", "FIT101", confidence=0.8)])
        calc = CRICalculator()

        record = calc.compute("FIT101", graph)
        assert record.cri > 0.0
        assert record.cri_status == "VALIDATED_EMPIRICAL"
        assert len(record.unexcited_sources) == 0

    def test_path_finder_prunes_prohibited_edges(self, swat_mask):
        """PathFinder prunes paths containing physically disallowed edges."""
        graph = DynamicGraph()
        # Create a graph containing a prohibited cross-stage shortcut:
        # AIT201 -> FIT501 (DISALLOWED) -> FIT502 (ALLOWED)
        e1 = _make_edge("AIT201", "FIT501", confidence=0.9)
        e2 = _make_edge("FIT501", "FIT502", confidence=0.8)
        graph.update([e1, e2])

        # 1. PathFinder without mask finds 2-hop path
        finder_no_mask = PathFinder(PathFinderConfig(max_hops=3))
        paths_raw = finder_no_mask.find_all_paths(graph, "AIT201")
        assert len(paths_raw) == 2

        # 2. PathFinder with structural mask prunes AIT201 -> FIT501
        finder_with_mask = PathFinder(PathFinderConfig(max_hops=3, structural_mask=swat_mask))
        paths_masked = finder_with_mask.find_all_paths(graph, "AIT201")
        assert len(paths_masked) == 0


# ==============================================================================
# 7. Determinism Across Repeated Runs
# ==============================================================================

class TestDeterminism:
    def test_deterministic_results_across_repeated_runs(self):
        """Evaluations across multiple repeated runs must produce identical results."""
        mask = PhysicalStructuralMask.load_from_csv()
        cfg = GatingConfig(
            structural_mask=mask,
            allow_unknown=False,
        )
        pipeline = GatingPipeline(cfg)

        obs_batch = [
            _make_obs("P301", "DPIT301", delta_t_s=10.0),
            _make_obs("AIT201", "FIT501", delta_t_s=15.0),
            _make_obs("UNKNOWN_A", "UNKNOWN_B", delta_t_s=20.0),
        ]

        results = []
        for _ in range(5):
            accepted, rejected = pipeline.apply(obs_batch)
            res_summary = (
                [o.source_machine for o in accepted],
                [o.source_machine for o in rejected],
                [o.reject_reason for o in rejected],
            )
            results.append(res_summary)

        # All 5 runs must be identical
        for r in results[1:]:
            assert r == results[0]
