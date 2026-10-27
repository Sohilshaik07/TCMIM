"""
tests/unit/test_dashboard_backend.py
====================================
Headless unit tests for the TCMIM Two-Node Research Dashboard backend engine.

Tests:
1. Synthetic benchmark telemetry loading.
2. User CSV telemetry validation and error handling.
3. Independent anomaly detector execution (Isolation Forest & CUSUM).
4. Node B independence (Node B does NOT become anomalous merely because Node A is anomalous).
5. Gate G0 disallowance for refuted hydraulic edge P101 -> FIT101.
6. State S2 normal validation for P301 -> DPIT301 (MV302 == 1).
7. State S3 quarantine enforcement for P301 -> DPIT301 (MV302 == 2).
8. Missing/stale operating evidence fail-closed behavior.
9. Unvalidated user relationship reporting (UNKNOWN).
10. Temporal ordering violation (dt <= 0).
11. Delay out-of-bounds rejection (UNCONFIRMED).
12. Export serialization (JSON & CSV).
13. Real SWaT testbed telemetry loading.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from dashboard.backend import (
    MANDATORY_DISCLAIMER,
    CrossNodeAnalysisResult,
    NodeDetectionResult,
    NodeTelemetry,
    PresentationStatus,
    evaluate_cross_node_relationship,
    export_experiment_record,
    export_observations_csv,
    get_channel_modality_and_state_map,
    load_swat_node_telemetry,
    load_synthetic_benchmark_telemetry,
    load_user_csv_telemetry,
    run_node_detection,
)
from tcmim.data.validator import validate_dataframe
from tcmim.data.windower import WindowBuilder
from tcmim.features.extractor import FeatureExtractor
from tcmim.schemas import EventRecord, Modality, Provenance


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_node_telemetry() -> NodeTelemetry:
    """Nominal synthetic telemetry for Node A with 100 samples and realistic variance."""
    np.random.seed(42)
    base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts = [base_t + timedelta(seconds=i) for i in range(100)]
    vals = np.random.normal(10.0, 0.4, 100)
    vals[40:60] += 15.0  # Anomaly burst
    return NodeTelemetry(
        node_id="Test_Node_A",
        timestamps=ts,
        values=vals,
        provenance=Provenance.SYNTHETIC,
        sampling_interval_s=1.0,
        channel_name="val_A",
    )


@pytest.fixture
def nominal_node_telemetry() -> NodeTelemetry:
    """Strictly nominal synthetic telemetry for Node B (no anomalies)."""
    base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts = [base_t + timedelta(seconds=i) for i in range(100)]
    vals = np.ones(100) * 5.0 + np.random.normal(0, 0.05, 100)
    return NodeTelemetry(
        node_id="Test_Node_B",
        timestamps=ts,
        values=vals,
        provenance=Provenance.SYNTHETIC,
        sampling_interval_s=1.0,
        channel_name="val_B",
    )


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

class TestDashboardTelemetryIngestion:
    """Tests covering data ingestion, synthetic generation, and CSV parsing."""

    def test_load_synthetic_benchmark_telemetry(self):
        tel_a = load_synthetic_benchmark_telemetry("scenario_1_chain", "Node_A", n_samples=200)
        tel_b = load_synthetic_benchmark_telemetry("scenario_1_chain", "Node_B", n_samples=200)
        assert len(tel_a.values) == 200
        assert len(tel_b.values) == 200
        assert tel_a.provenance == Provenance.SYNTHETIC
        assert tel_a.channel_name == "Node_A_val"
        assert tel_b.channel_name == "Node_B_val"

    def test_load_user_csv_telemetry_valid(self):
        csv_text = "timestamp,pressure\n2026-01-01T00:00:00Z,12.5\n2026-01-01T00:00:01Z,12.7\n2026-01-01T00:00:02Z,13.1\n2026-01-01T00:00:03Z,12.9\n2026-01-01T00:00:04Z,12.8\n"
        tel = load_user_csv_telemetry(csv_text, "User_Sensor_1")
        assert len(tel.values) == 5
        assert tel.node_id == "User_Sensor_1"
        assert tel.values[0] == pytest.approx(12.5)

    def test_load_user_csv_telemetry_insufficient_rows(self):
        csv_text = "timestamp,pressure\n2026-01-01T00:00:00Z,12.5\n"
        with pytest.raises(ValueError, match="insufficient data rows"):
            load_user_csv_telemetry(csv_text, "User_Sensor_1")

    def test_load_user_csv_telemetry_no_numeric_column(self):
        csv_text = "timestamp,label\n2026-01-01T00:00:00Z,A\n2026-01-01T00:00:01Z,B\n2026-01-01T00:00:02Z,C\n2026-01-01T00:00:03Z,D\n2026-01-01T00:00:04Z,E\n"
        with pytest.raises(ValueError, match="No numeric telemetry columns"):
            load_user_csv_telemetry(csv_text, "User_Sensor_1")


class TestDashboardDetectionPipelines:
    """Tests covering independent detector execution."""

    def test_independent_detection_isolation_forest(self, synthetic_node_telemetry):
        res = run_node_detection(
            synthetic_node_telemetry,
            detector_type="isolation_forest",
            contamination=0.1,
            window_size=10,
            step_size=5,
        )
        assert res.node_id == "Test_Node_A"
        assert res.detector_name == "isolation_forest"
        assert len(res.anomaly_scores) > 0
        assert res.anomalous_count > 0
        assert len(res.event_records) >= 1
        assert res.first_onset_time is not None

    def test_independent_detection_cusum(self, synthetic_node_telemetry):
        res = run_node_detection(
            synthetic_node_telemetry,
            detector_type="cusum",
            cusum_k=0.5,
            cusum_h=3.0,
        )
        assert res.node_id == "Test_Node_A"
        assert res.detector_name == "cusum"
        assert res.anomalous_count > 0
        assert len(res.event_records) >= 1

    def test_node_b_independence_when_node_a_anomalous(
        self, synthetic_node_telemetry, nominal_node_telemetry
    ):
        """CRITICAL: Node B must evaluate independently and NOT flag anomaly when nominal."""
        res_a = run_node_detection(synthetic_node_telemetry, detector_type="cusum", cusum_h=2.0)
        res_b = run_node_detection(nominal_node_telemetry, detector_type="cusum", cusum_h=10.0)

        assert res_a.anomalous_count > 0
        assert res_b.anomalous_count == 0  # Node B remains nominal

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.ANOMALY_AT_NODE_A
        assert analysis.is_eligible_for_evaluation is False
        assert "Node B (Test_Node_B) remained normal" in analysis.explanation

    def test_node_a_independence_when_node_b_anomalous(
        self, nominal_node_telemetry, synthetic_node_telemetry
    ):
        """Node B anomalous while Node A is nominal."""
        res_a = run_node_detection(nominal_node_telemetry, detector_type="cusum", cusum_h=10.0)
        res_b = run_node_detection(synthetic_node_telemetry, detector_type="cusum", cusum_h=2.0)

        assert res_a.anomalous_count == 0
        assert res_b.anomalous_count > 0

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.ANOMALY_AT_NODE_B
        assert analysis.is_eligible_for_evaluation is False

    def test_independent_detection_node_a_node_b(
        self, synthetic_node_telemetry, nominal_node_telemetry
    ):
        """Independent detection: Node A anomalous with Node B nominal, and vice-versa."""
        # Case 1: Node A anomalous, Node B nominal
        res_a1 = run_node_detection(
            synthetic_node_telemetry,
            detector_type="isolation_forest",
            contamination=0.1,
            window_size=10,
            step_size=5,
        )
        res_b1 = run_node_detection(nominal_node_telemetry, detector_type="cusum", cusum_h=10.0)
        assert res_a1.anomalous_count > 0
        assert res_b1.anomalous_count == 0
        eval1 = evaluate_cross_node_relationship(res_a1, res_b1)
        assert eval1.overall_status == PresentationStatus.ANOMALY_AT_NODE_A
        assert eval1.is_supported_relationship is False

        # Case 2: Node A nominal, Node B anomalous
        res_a2 = run_node_detection(nominal_node_telemetry, detector_type="cusum", cusum_h=10.0)
        res_b2 = run_node_detection(
            synthetic_node_telemetry,
            detector_type="isolation_forest",
            contamination=0.1,
            window_size=10,
            step_size=5,
        )
        assert res_a2.anomalous_count == 0
        assert res_b2.anomalous_count > 0
        eval2 = evaluate_cross_node_relationship(res_a2, res_b2)
        assert eval2.overall_status == PresentationStatus.ANOMALY_AT_NODE_B
        assert eval2.is_supported_relationship is False


class TestCrossNodeGatingAndStatus:
    """Tests covering Gate G0, operating states, and presentation statuses."""

    def test_gate_g0_disallowed_pair(self):
        """P101 -> FIT101 is refuted in Stage 3 and must be DISALLOWED by Gate G0."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord(
            machine_id="P101",
            modality=Modality.PRESSURE,
            onset_time=t0,
            detector="isolation_forest",
            score=-0.2,
            provenance=Provenance.PUBLIC_DATASET,
            end_time=t0 + timedelta(seconds=10),
            event_id="EVT_P101_1",
        )
        evt_b = EventRecord(
            machine_id="FIT101",
            modality=Modality.PRESSURE,
            onset_time=t0 + timedelta(seconds=5),
            detector="isolation_forest",
            score=-0.15,
            provenance=Provenance.PUBLIC_DATASET,
            end_time=t0 + timedelta(seconds=15),
            event_id="EVT_FIT101_1",
        )

        res_a = NodeDetectionResult("P101", "isolation_forest", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT101", "isolation_forest", [t0], [1.0], [-0.15], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.UNCONFIRMED
        g0 = next(g for g in analysis.gate_steps if g.gate_name == "GATE_G0_STRUCTURAL_MASK")
        assert g0.passed is False
        assert g0.status == "DISALLOWED"

    test_preservation_p101_fit101_g0_rejection = test_gate_g0_disallowed_pair

    def test_operating_state_s2_normal_supported(self):
        """P301 -> DPIT301 with MV302==1 (CLOSED) is validated State S2 normal startup."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P301", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("DPIT301", Modality.PRESSURE, t0 + timedelta(seconds=20), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=25))

        res_a = NodeDetectionResult("P301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b, operating_evidence={"MV302": 1})
        assert analysis.overall_status == PresentationStatus.RELATIONSHIP_SUPPORTED
        assert analysis.is_supported_relationship is True
        res_state = next(g for g in analysis.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert res_state.passed is True
        assert res_state.status == "STATE_S2_NORMAL"

    def test_operating_state_s3_quarantined(self):
        """CRITICAL: P301 -> DPIT301 with MV302==2 (OPEN) is State S3 and must be QUARANTINED."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P301", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("DPIT301", Modality.PRESSURE, t0 + timedelta(seconds=20), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=25))

        res_a = NodeDetectionResult("P301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b, operating_evidence={"MV302": 2})
        assert analysis.overall_status == PresentationStatus.UNKNOWN
        res_state = next(g for g in analysis.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert res_state.passed is False
        assert res_state.status == "QUARANTINED"
        assert "QUARANTINED_UNVALIDATED_REGIME" in res_state.reason

    test_preservation_p301_dpit301_s3_quarantine = test_operating_state_s3_quarantined

    def test_operating_state_unknown_missing_evidence(self):
        """P301 -> DPIT301 with missing MV302 must fail closed with UNKNOWN_OPERATING_STATE."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P301", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("DPIT301", Modality.PRESSURE, t0 + timedelta(seconds=20), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=25))

        res_a = NodeDetectionResult("P301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b, operating_evidence=None)
        assert analysis.overall_status == PresentationStatus.UNKNOWN
        res_state = next(g for g in analysis.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert res_state.passed is False
        assert res_state.status == "UNKNOWN_OPERATING_STATE"

    def test_p101_fit101_disallowed_with_simultaneous_anomalies(self):
        """Requirement A: P101 -> FIT101 is DISALLOWED even when both nodes have simultaneous anomalies (dt=0.0s)."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P101", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=10), event_id="EVT_P101_SIM")
        evt_b = EventRecord("FIT101", Modality.PRESSURE, t0, "if", -0.15, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=10), event_id="EVT_FIT101_SIM")

        res_a = NodeDetectionResult("P101", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT101", "if", [t0], [1.0], [-0.15], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.UNCONFIRMED
        assert analysis.is_eligible_for_evaluation is False
        assert analysis.is_supported_relationship is False

        # First gate evaluated must be G0, and it must be DISALLOWED
        assert len(analysis.gate_steps) == 1
        g0 = analysis.gate_steps[0]
        assert g0.gate_name == "GATE_G0_STRUCTURAL_MASK"
        assert g0.passed is False
        assert g0.status == "DISALLOWED"

    def test_p101_fit101_disallowed_with_feasible_delay(self):
        """Requirement B: P101 -> FIT101 remains DISALLOWED when the delay falls within configured window."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P101", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=10), event_id="EVT_P101_FEAS")
        evt_b = EventRecord("FIT101", Modality.PRESSURE, t0 + timedelta(seconds=10), "if", -0.15, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=20), event_id="EVT_FIT101_FEAS")

        res_a = NodeDetectionResult("P101", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT101", "if", [t0], [1.0], [-0.15], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.UNCONFIRMED
        assert analysis.is_eligible_for_evaluation is False
        assert analysis.is_supported_relationship is False

        assert len(analysis.gate_steps) == 1
        g0 = analysis.gate_steps[0]
        assert g0.gate_name == "GATE_G0_STRUCTURAL_MASK"
        assert g0.passed is False
        assert g0.status == "DISALLOWED"

    def test_structurally_allowed_simultaneous_events_rejected_by_temporal_ordering(self):
        """Requirement C: A valid, structurally permitted edge with simultaneous timestamps is rejected by G2."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("MV201", Modality.DIGITAL_STATE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5), event_id="EVT_MV201_SIM")
        evt_b = EventRecord("FIT201", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5), event_id="EVT_FIT201_SIM")

        res_a = NodeDetectionResult("MV201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.BOTH_NODES_ANOMALOUS
        assert analysis.is_eligible_for_evaluation is False
        assert analysis.is_supported_relationship is False

        # G0 was evaluated first and passed
        assert analysis.gate_steps[0].gate_name == "GATE_G0_STRUCTURAL_MASK"
        assert analysis.gate_steps[0].passed is True
        assert analysis.gate_steps[0].status == "ALLOWED"

        # G2 was evaluated next and rejected the simultaneous onset
        assert analysis.gate_steps[1].gate_name == "GATE_G2_ORDERING"
        assert analysis.gate_steps[1].passed is False
        assert analysis.gate_steps[1].status == "ORDERING_VIOLATION"

    def test_unknown_topology_rejected_even_if_simultaneous_or_feasible(self):
        """Requirement D: Unknown topology never becomes accepted, whether simultaneous or delayed."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Case 1: Plant tag pair not in register (P101 -> DPIT301) with feasible delay
        evt_a = EventRecord("P101", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("DPIT301", Modality.PRESSURE, t0 + timedelta(seconds=15), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=20))
        res_a = NodeDetectionResult("P101", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        eval_unk = evaluate_cross_node_relationship(res_a, res_b)
        assert eval_unk.overall_status == PresentationStatus.UNKNOWN
        assert eval_unk.is_eligible_for_evaluation is False
        assert eval_unk.gate_steps[0].gate_name == "GATE_G0_STRUCTURAL_MASK"
        assert eval_unk.gate_steps[0].status == "UNKNOWN"

        # Case 2: Unknown topology with simultaneous timestamps (dt = 0.0s)
        evt_b_sim = EventRecord("DPIT301", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        res_b_sim = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b_sim], t0, "")
        eval_unk_sim = evaluate_cross_node_relationship(res_a, res_b_sim)
        assert eval_unk_sim.overall_status == PresentationStatus.UNKNOWN
        assert eval_unk_sim.is_eligible_for_evaluation is False
        # G0 rejects before G2, ensuring it reports UNKNOWN rather than ORDERING_VIOLATION
        assert eval_unk_sim.gate_steps[0].gate_name == "GATE_G0_STRUCTURAL_MASK"
        assert eval_unk_sim.gate_steps[0].status == "UNKNOWN"

    def test_operating_state_fail_closed_invalid_and_stale_evidence(self):
        """Requirement F: P301 -> DPIT301 fails closed on invalid quality or stale evidence."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("P301", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("DPIT301", Modality.PRESSURE, t0 + timedelta(seconds=20), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=25))
        res_a = NodeDetectionResult("P301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("DPIT301", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        # 1. Invalid quality flag
        eval_bad = evaluate_cross_node_relationship(
            res_a, res_b, operating_evidence={"MV302": {"value": 1, "quality": "BAD"}}
        )
        assert eval_bad.overall_status == PresentationStatus.UNKNOWN
        g_bad = next(g for g in eval_bad.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert g_bad.passed is False
        assert g_bad.status == "UNKNOWN_OPERATING_STATE"
        assert "INVALID_QUALITY" in g_bad.reason

        # 2. Stale evidence
        eval_stale = evaluate_cross_node_relationship(
            res_a, res_b, operating_evidence={"MV302": {"value": 1, "is_stale": True}}
        )
        assert eval_stale.overall_status == PresentationStatus.UNKNOWN
        g_stale = next(g for g in eval_stale.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert g_stale.passed is False
        assert g_stale.status == "UNKNOWN_OPERATING_STATE"
        assert "STALE_STATE_EVIDENCE" in g_stale.reason

        # 3. Sentinel string
        eval_sentinel = evaluate_cross_node_relationship(
            res_a, res_b, operating_evidence={"MV302": "UNKNOWN"}
        )
        assert eval_sentinel.overall_status == PresentationStatus.UNKNOWN
        g_sentinel = next(g for g in eval_sentinel.gate_steps if g.gate_name == "OPERATING_STATE_RESOLVER")
        assert g_sentinel.passed is False
        assert g_sentinel.status == "UNKNOWN_OPERATING_STATE"

    def test_user_data_unvalidated_relationship(self):
        """User uploaded data without plant register must be reported as UNKNOWN."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("User_Node_A", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("User_Node_B", Modality.PRESSURE, t0 + timedelta(seconds=15), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=20))

        res_a = NodeDetectionResult("User_Node_A", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("User_Node_B", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b, is_user_data=True)
        assert analysis.overall_status == PresentationStatus.UNKNOWN
        g0 = next(g for g in analysis.gate_steps if g.gate_name == "GATE_G0_STRUCTURAL_MASK")
        assert g0.passed is False
        assert g0.status == "UNKNOWN"

    def test_temporal_ordering_violation(self):
        """Target fires before source (dt < 0) -> BOTH_NODES_ANOMALOUS with ordering failure."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("Node_A", Modality.PRESSURE, t0 + timedelta(seconds=20), "if", -0.2, Provenance.SYNTHETIC, end_time=t0 + timedelta(seconds=25))
        evt_b = EventRecord("Node_B", Modality.PRESSURE, t0, "if", -0.2, Provenance.SYNTHETIC, end_time=t0 + timedelta(seconds=5))

        res_a = NodeDetectionResult("Node_A", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("Node_B", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.BOTH_NODES_ANOMALOUS
        g2 = next(g for g in analysis.gate_steps if g.gate_name == "GATE_G2_ORDERING")
        assert g2.passed is False
        assert g2.status == "ORDERING_VIOLATION"

    def test_delay_out_of_bounds_unconfirmed(self):
        """Observed delay exceeds physical window -> UNCONFIRMED."""
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("MV201", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("FIT201", Modality.PRESSURE, t0 + timedelta(seconds=90), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=95))

        res_a = NodeDetectionResult("MV201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        assert analysis.overall_status == PresentationStatus.UNCONFIRMED
        g1 = next(g for g in analysis.gate_steps if g.gate_name == "GATE_G1_DELAY_FEASIBILITY")
        assert g1.passed is False
        assert g1.status == "OUT_OF_BOUNDS"


class TestExportSerialization:
    """Tests covering experiment records and CSV downloads."""

    def test_export_experiment_record(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        evt_a = EventRecord("MV201", Modality.PRESSURE, t0, "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=5))
        evt_b = EventRecord("FIT201", Modality.PRESSURE, t0 + timedelta(seconds=12), "if", -0.2, Provenance.PUBLIC_DATASET, end_time=t0 + timedelta(seconds=17))

        res_a = NodeDetectionResult("MV201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_a], t0, "")
        res_b = NodeDetectionResult("FIT201", "if", [t0], [1.0], [-0.2], 0.0, [True], 1, [evt_b], t0, "")

        analysis = evaluate_cross_node_relationship(res_a, res_b)
        json_str = export_experiment_record(analysis, res_a, res_b, {"test_run": True})

        data = json.loads(json_str)
        assert data["export_version"] == "1.0"
        assert data["overall_status"] == PresentationStatus.RELATIONSHIP_SUPPORTED.value
        assert data["source_node"]["node_id"] == "MV201"
        assert data["target_node"]["node_id"] == "FIT201"
        assert MANDATORY_DISCLAIMER in data["disclaimer"]

        # Verify gate trace ordering: G0 evaluated before G2
        gate_names = [g["gate"] for g in data["gate_execution_trace"]]
        assert gate_names[0] == "GATE_G0_STRUCTURAL_MASK"
        assert gate_names[1] == "GATE_G2_ORDERING"
        assert data["gate_execution_trace"][0]["passed"] is True
        assert data["gate_execution_trace"][0]["status"] == "ALLOWED"

    def test_export_observations_csv(self):
        t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        res_a = NodeDetectionResult("NodeA", "if", [t0], [10.5], [-0.2], 0.0, [True], 1, [], t0, "")
        res_b = NodeDetectionResult("NodeB", "if", [t0], [20.2], [0.1], 0.0, [False], 0, [], None, "")

        csv_str = export_observations_csv(res_a, res_b)
        assert "timestamp,NodeA_raw,NodeA_score,NodeA_is_anomaly,NodeB_raw,NodeB_score,NodeB_is_anomaly" in csv_str
        assert "10.5" in csv_str
        assert "20.2" in csv_str


class TestChannelModalityAndFeatureExtraction:
    """Tests covering channel modality resolution and feature extraction."""

    def test_channel_modality_mapping(self):
        """Verify tag-aware modality resolution for actuators and continuous sensors."""
        # MV201 actuator
        mod_mv, st_mv = get_channel_modality_and_state_map("MV201")
        assert mod_mv == Modality.DIGITAL_STATE
        assert st_mv == {1.0: 0, 2.0: 1}

        # P101 actuator
        mod_p, st_p = get_channel_modality_and_state_map("P101")
        assert mod_p == Modality.DIGITAL_STATE
        assert st_p == {1.0: 0, 2.0: 1}

        # FIT201 sensor (registered sensor with unknown modality in registry, no actuator mapping)
        mod_fit, st_fit = get_channel_modality_and_state_map("FIT201")
        assert mod_fit == Modality.UNKNOWN
        assert st_fit is None

        # DPIT301 differential pressure sensor
        mod_dpit, st_dpit = get_channel_modality_and_state_map("DPIT301")
        assert mod_dpit == Modality.PRESSURE
        assert st_dpit is None

        # Generic actuator prefix
        mod_act, st_act = get_channel_modality_and_state_map("MV_custom")
        assert mod_act == Modality.DIGITAL_STATE
        assert st_act == {1.0: 0, 2.0: 1}

        # Generic unknown channel fallback
        mod_unk, st_unk = get_channel_modality_and_state_map("Custom_Sensor_1")
        assert mod_unk == Modality.PRESSURE
        assert st_unk is None

    def test_nonempty_feature_extraction(self):
        """Verify FeatureExtractor computes valid non-empty samples without NaNs."""
        base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = [base_t + timedelta(seconds=i) for i in range(50)]
        vals = np.sin(np.linspace(0, 3.14, 50))

        df = pd.DataFrame({"FIT201": vals}, index=pd.to_datetime(ts))
        report = validate_dataframe(df)
        assert report.passed
        builder = WindowBuilder(window_seconds=10.0, overlap_frac=0.5)
        windows = builder.build(df, machine_id="FIT201", provenance=Provenance.PUBLIC_DATASET)
        assert len(windows) > 0

        mod, st = get_channel_modality_and_state_map("FIT201")
        extractor = FeatureExtractor(
            sampling_rate_hz=1.0,
            channel_modality_map={"FIT201": mod},
            channel_state_map={"FIT201": st} if st else None,
        )
        samples = extractor.extract_all(windows)
        assert len(samples) == len(windows)
        for s in samples:
            flat_features = {}
            for mod_feats in s.features.values():
                flat_features.update(mod_feats)
            assert len(flat_features) > 0
            for v in flat_features.values():
                assert not np.isnan(v)

    def test_handling_of_constant_and_non_finite_channels(self):
        """Verify graceful adaptation for constant actuators and fail-closed diagnostics for flat sensors."""
        base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = [base_t + timedelta(seconds=i) for i in range(100)]

        # 1. Discrete actuator constant in baseline then transitioning: adapts gracefully
        vals_act = np.ones(100) * 2.0
        vals_act[60:] = 1.0  # Valve closes at t=60
        tel_act = NodeTelemetry("MV201", ts, vals_act, Provenance.PUBLIC_DATASET, 1.0, "MV201")
        res_act = run_node_detection(tel_act, detector_type="isolation_forest", baseline_fraction=0.2)
        assert res_act.detector_name == "actuator_state_transition"
        assert res_act.anomalous_count > 0
        assert res_act.first_onset_time == ts[60]

        # 2. Continuous sensor flat throughout: raises clear diagnostic error
        vals_flat = np.ones(100) * 10.0
        tel_flat = NodeTelemetry("FlatPressure", ts, vals_flat, Provenance.SYNTHETIC, 1.0, "FlatPressure")
        with pytest.raises(ValueError, match="no usable features|No valid features remain"):
            run_node_detection(tel_flat, detector_type="isolation_forest")

    def test_insufficient_baseline_and_all_invalid_features(self):
        """Verify fail-closed error handling for short sequences or unparsable telemetry."""
        base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = [base_t + timedelta(seconds=i) for i in range(5)]
        tel_short = NodeTelemetry("ShortNode", ts, np.array([1.0, 2.0, 3.0, 4.0, 5.0]), Provenance.SYNTHETIC, 1.0, "Short")
        with pytest.raises(ValueError, match="Insufficient telemetry length"):
            run_node_detection(tel_short)

        with pytest.raises(ValueError, match="insufficient data rows"):
            load_user_csv_telemetry("ts,val\n2026-01-01T00:00:00Z,1.0", "U1")


class TestRealSWaTTelemetryLoading:
    """Tests confirming integration with real SWaT July 2019 Excel workbook."""

    def test_swat_node_telemetry_loading(self):
        wb_path = Path("data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx")
        if not wb_path.is_file():
            pytest.skip("SWaT workbook not found.")

        tel_mv = load_swat_node_telemetry("MV201", max_rows=300)
        tel_fit = load_swat_node_telemetry("FIT201", max_rows=300)

        assert len(tel_mv.values) == 300
        assert len(tel_fit.values) == 300
        assert tel_mv.channel_name == "MV201"
        assert tel_fit.channel_name == "FIT201"
        assert tel_mv.provenance == Provenance.PUBLIC_DATASET
        assert tel_fit.provenance == Provenance.PUBLIC_DATASET
        assert tel_mv.timestamps[0].tzinfo is not None

        # Verify missing tag error fail-closed behavior
        with pytest.raises(ValueError, match="Tag 'NONEXISTENT_TAG' not found in SWaT workbook"):
            load_swat_node_telemetry("NONEXISTENT_TAG", max_rows=50)

    test_swat_workbook_loading = test_swat_node_telemetry_loading

    def test_real_swat_mv201_fit201_end_to_end(self):
        """End-to-end execution of real SWaT MV201 -> FIT201 workflow with 1200 rows."""
        wb_path = Path("data/raw/SWAT_A4_A5_JULY_2019/SWaT_dataset_Jul 19 v2.xlsx")
        if not wb_path.is_file():
            pytest.skip("SWaT workbook not found.")

        tel_mv = load_swat_node_telemetry("MV201", max_rows=1200)
        tel_fit = load_swat_node_telemetry("FIT201", max_rows=1200)

        # Independent node detection
        res_mv = run_node_detection(
            tel_mv,
            detector_type="isolation_forest",
            contamination=0.05,
            threshold=0.0,
            window_size=30,
            step_size=10,
        )
        res_fit = run_node_detection(
            tel_fit,
            detector_type="isolation_forest",
            contamination=0.05,
            threshold=0.0,
            window_size=30,
            step_size=10,
        )

        assert res_mv.anomalous_count > 0
        assert len(res_mv.event_records) >= 1
        assert res_fit.anomalous_count > 0
        assert len(res_fit.event_records) >= 1

        # Cross-node propagation analysis
        analysis = evaluate_cross_node_relationship(res_mv, res_fit)
        assert analysis.overall_status == PresentationStatus.RELATIONSHIP_SUPPORTED
        assert analysis.is_supported_relationship is True
        assert analysis.is_eligible_for_evaluation is True
        assert analysis.delta_t_s is not None and 1.0 <= analysis.delta_t_s <= 25.0

        for gate in analysis.gate_steps:
            assert gate.passed is True
