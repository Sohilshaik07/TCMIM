"""
TCMIM — Unit tests for schemas (M0).

Tests cover:
- Provenance enum values and str mixin
- Modality enum values
- SensorSample construction and validation
- FeatureSample window validation
- HealthSample range enforcement
- EventRecord construction
- PropagationObservation gate_result validation
- EdgeRecord confidence range
- CRIRecord cri range
- ExperimentResult status validation
"""

import uuid
from datetime import datetime, timezone

import pytest

from tcmim.schemas import (
    AnomalyRecord,
    CRIRecord,
    DelayStatistics,
    EdgeRecord,
    EdgeState,
    EventRecord,
    ExperimentResult,
    FeatureSample,
    GroundTruthRecord,
    HealthSample,
    Modality,
    MultimodalFeatureSample,
    PropagationObservation,
    Provenance,
    SensorSample,
)

# ---- Fixtures -----------------------------------------------------------

NOW = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2020, 2, 1, 0, 1, 0, tzinfo=timezone.utc)


def make_sensor_sample(**kwargs) -> SensorSample:
    defaults = dict(
        machine_id="test_machine",
        channel="TP2",
        modality=Modality.PRESSURE,
        timestamp=NOW,
        value=5.0,
        provenance=Provenance.PUBLIC_DATASET,
        source_id="test_source",
    )
    defaults.update(kwargs)
    return SensorSample(**defaults)


# ---- Provenance tests ---------------------------------------------------

class TestProvenance:
    def test_enum_values(self):
        assert Provenance.HARDWARE == "hardware"
        assert Provenance.PUBLIC_DATASET == "public_dataset"
        assert Provenance.SYNTHETIC == "synthetic_fixture"

    def test_str_mixin(self):
        """Provenance must be JSON-serialisable as a plain string."""
        import json
        data = {"prov": Provenance.HARDWARE}
        serialised = json.dumps(data)
        assert "hardware" in serialised

    def test_from_string(self):
        p = Provenance("hardware")
        assert p == Provenance.HARDWARE


# ---- Modality tests -----------------------------------------------------

class TestModality:
    def test_all_modalities_exist(self):
        expected = {
            "vibration", "pressure", "temperature",
            "current", "flow_pulse", "digital_state", "rotation", "unknown",
        }
        actual = {m.value for m in Modality}
        assert actual == expected


# ---- SensorSample tests -------------------------------------------------

class TestSensorSample:
    def test_basic_construction(self):
        s = make_sensor_sample()
        assert s.machine_id == "test_machine"
        assert s.channel == "TP2"
        assert s.modality == Modality.PRESSURE
        assert s.provenance == Provenance.PUBLIC_DATASET
        assert isinstance(s.sample_id, str)
        # sample_id should be a valid UUID
        uuid.UUID(s.sample_id)

    def test_unique_sample_ids(self):
        s1 = make_sensor_sample()
        s2 = make_sensor_sample()
        assert s1.sample_id != s2.sample_id

    def test_modality_coercion_from_string(self):
        s = make_sensor_sample(modality="pressure")
        assert s.modality == Modality.PRESSURE

    def test_provenance_coercion_from_string(self):
        s = make_sensor_sample(provenance="public_dataset")
        assert s.provenance == Provenance.PUBLIC_DATASET

    def test_hardware_provenance(self):
        s = make_sensor_sample(provenance=Provenance.HARDWARE)
        assert s.provenance == Provenance.HARDWARE

    def test_synthetic_provenance(self):
        s = make_sensor_sample(provenance=Provenance.SYNTHETIC)
        assert s.provenance == Provenance.SYNTHETIC


# ---- FeatureSample tests ------------------------------------------------

class TestFeatureSample:
    def test_valid_window(self):
        fs = FeatureSample(
            machine_id="m1",
            channel="TP2",
            modality=Modality.PRESSURE,
            window_start=NOW,
            window_end=LATER,
            features={"mean": 5.0, "std": 0.1},
            provenance=Provenance.PUBLIC_DATASET,
        )
        assert fs.features["mean"] == pytest.approx(5.0)

    def test_invalid_window_raises(self):
        with pytest.raises(ValueError, match="window_end"):
            FeatureSample(
                machine_id="m1",
                channel="TP2",
                modality=Modality.PRESSURE,
                window_start=LATER,
                window_end=NOW,   # end before start
                features={},
                provenance=Provenance.PUBLIC_DATASET,
            )

    def test_equal_window_raises(self):
        with pytest.raises(ValueError, match="window_end"):
            FeatureSample(
                machine_id="m1",
                channel="TP2",
                modality=Modality.PRESSURE,
                window_start=NOW,
                window_end=NOW,   # equal timestamps
                features={},
                provenance=Provenance.PUBLIC_DATASET,
            )


# ---- HealthSample tests -------------------------------------------------

class TestHealthSample:
    def test_valid_health(self):
        hs = HealthSample(
            machine_id="m1",
            window_start=NOW,
            window_end=LATER,
            health_score=0.85,
            z_scores={"TP2__mean": 0.5},
            provenance=Provenance.PUBLIC_DATASET,
            baseline_id="baseline_001",
        )
        assert hs.health_score == pytest.approx(0.85)

    def test_health_out_of_range_high(self):
        with pytest.raises(ValueError, match="health_score"):
            HealthSample(
                machine_id="m1",
                window_start=NOW,
                window_end=LATER,
                health_score=1.1,
                z_scores={},
                provenance=Provenance.PUBLIC_DATASET,
                baseline_id="b1",
            )

    def test_health_out_of_range_low(self):
        with pytest.raises(ValueError, match="health_score"):
            HealthSample(
                machine_id="m1",
                window_start=NOW,
                window_end=LATER,
                health_score=-0.1,
                z_scores={},
                provenance=Provenance.PUBLIC_DATASET,
                baseline_id="b1",
            )

    def test_boundary_values(self):
        """Health score of exactly 0.0 and 1.0 must be accepted."""
        for val in (0.0, 1.0):
            hs = HealthSample(
                machine_id="m1",
                window_start=NOW,
                window_end=LATER,
                health_score=val,
                z_scores={},
                provenance=Provenance.PUBLIC_DATASET,
                baseline_id="b1",
            )
            assert hs.health_score == val


# ---- EventRecord tests --------------------------------------------------

class TestEventRecord:
    def test_basic_construction(self):
        er = EventRecord(
            machine_id="m1",
            modality=Modality.PRESSURE,
            onset_time=NOW,
            detector="cusum",
            score=7.3,
            provenance=Provenance.PUBLIC_DATASET,
        )
        assert er.detector == "cusum"
        assert er.end_time is None
        assert er.window_count == 1
        uuid.UUID(er.event_id)

    def test_extended_burst_fields(self):
        er = EventRecord(
            machine_id="m1",
            modality=Modality.PRESSURE,
            onset_time=NOW,
            detector="isolation_forest",
            score=-0.25,
            provenance=Provenance.PUBLIC_DATASET,
            end_time=LATER,
            window_count=3,
        )
        assert er.end_time == LATER
        assert er.window_count == 3

    def test_invalid_end_time_raises(self):
        with pytest.raises(ValueError, match="end_time"):
            EventRecord(
                machine_id="m1",
                modality=Modality.PRESSURE,
                onset_time=LATER,
                detector="isolation_forest",
                score=-0.25,
                provenance=Provenance.PUBLIC_DATASET,
                end_time=NOW,  # earlier than onset_time
            )

    def test_invalid_window_count_raises(self):
        with pytest.raises(ValueError, match="window_count"):
            EventRecord(
                machine_id="m1",
                modality=Modality.PRESSURE,
                onset_time=NOW,
                detector="isolation_forest",
                score=-0.25,
                provenance=Provenance.PUBLIC_DATASET,
                window_count=0,
            )



# ---- PropagationObservation tests ---------------------------------------

class TestPropagationObservation:
    def test_valid_accepted(self):
        obs = PropagationObservation(
            source_event="e1",
            target_event="e2",
            source_machine="A",
            target_machine="B",
            delta_t_s=45.0,
            gate_result="accepted",
            reject_reason=None,
            provenance=Provenance.SYNTHETIC,
        )
        assert obs.gate_result == "accepted"

    def test_valid_rejected(self):
        obs = PropagationObservation(
            source_event="e1",
            target_event="e2",
            source_machine="A",
            target_machine="B",
            delta_t_s=-10.0,
            gate_result="rejected",
            reject_reason="negative delay",
            provenance=Provenance.SYNTHETIC,
        )
        assert obs.reject_reason == "negative delay"

    def test_invalid_gate_result(self):
        with pytest.raises(ValueError, match="gate_result"):
            PropagationObservation(
                source_event="e1",
                target_event="e2",
                source_machine="A",
                target_machine="B",
                delta_t_s=10.0,
                gate_result="maybe",   # invalid
                reject_reason=None,
                provenance=Provenance.SYNTHETIC,
            )


# ---- DelayStatistics tests ----------------------------------------------

class TestDelayStatistics:
    def test_direction_consistency_bounds(self):
        with pytest.raises(ValueError, match="direction_consistency"):
            DelayStatistics(
                source_machine="A",
                target_machine="B",
                n=5,
                mean_s=30.0,
                std_s=5.0,
                min_s=10.0,
                max_s=60.0,
                direction_consistency=1.5,  # out of range
                provenance=Provenance.SYNTHETIC,
            )


# ---- EdgeRecord tests ---------------------------------------------------

class TestEdgeRecord:
    def test_valid_edge(self):
        er = EdgeRecord(
            source="A",
            target="B",
            state=EdgeState.CANDIDATE,
            evidence_count=2,
            est_delay_s=30.0,
            confidence=0.6,
            last_updated=NOW,
            modality=Modality.PRESSURE,
            provenance=Provenance.SYNTHETIC,
        )
        assert er.state == EdgeState.CANDIDATE

    def test_confidence_out_of_range(self):
        with pytest.raises(ValueError, match="confidence"):
            EdgeRecord(
                source="A",
                target="B",
                state=EdgeState.CANDIDATE,
                evidence_count=1,
                est_delay_s=30.0,
                confidence=1.5,   # invalid
                last_updated=NOW,
                modality=Modality.PRESSURE,
                provenance=Provenance.SYNTHETIC,
            )


# ---- CRIRecord tests ----------------------------------------------------

class TestCRIRecord:
    def test_cri_out_of_range(self):
        with pytest.raises(ValueError, match="cri"):
            CRIRecord(
                timestamp=NOW,
                target_machine="B",
                cri=-0.1,   # invalid
                contributions={},
                paths_used=[],
                provenance=Provenance.SYNTHETIC,
            )


# ---- ExperimentResult tests ---------------------------------------------

class TestExperimentResult:
    def test_invalid_status(self):
        with pytest.raises(ValueError, match="status"):
            ExperimentResult(
                experiment_id="E1",
                config={},
                metrics={},
                provenance=Provenance.HARDWARE,
                status="DONE",   # not in the ladder
                notes="",
            )

    def test_valid_statuses(self):
        for s in ("PLANNED", "IMPL", "TEST", "EXEC", "VAL"):
            er = ExperimentResult(
                experiment_id="E1",
                config={},
                metrics={},
                provenance=Provenance.HARDWARE,
                status=s,
                notes="",
            )
            assert er.status == s


# ---- AnomalyRecord tests (ML-S1) ----------------------------------------

class TestAnomalyRecord:
    def test_construction_and_defaults(self):
        rec = AnomalyRecord(
            timestamp=NOW,
            machine_id="compressor_1",
            anomaly_score=-0.42,
            is_anomaly=True,
            detector="isolation_forest",
            provenance=Provenance.PUBLIC_DATASET,
        )
        assert rec.timestamp == NOW
        assert rec.machine_id == "compressor_1"
        assert rec.anomaly_score == -0.42
        assert rec.is_anomaly is True
        assert rec.detector == "isolation_forest"
        assert rec.provenance == Provenance.PUBLIC_DATASET
        assert isinstance(rec.record_id, str)
        assert len(rec.record_id) > 0
        assert rec.window_end is None

    def test_provenance_coercion(self):
        rec = AnomalyRecord(
            timestamp=NOW,
            machine_id="compressor_1",
            anomaly_score=0.15,
            is_anomaly=False,
            detector="cusum_health",
            provenance="public_dataset",  # string coerced to Enum
        )
        assert rec.provenance == Provenance.PUBLIC_DATASET

    def test_invalid_provenance_raises(self):
        with pytest.raises(ValueError):
            AnomalyRecord(
                timestamp=NOW,
                machine_id="compressor_1",
                anomaly_score=0.15,
                is_anomaly=False,
                detector="cusum_health",
                provenance="unknown_provenance",
            )

