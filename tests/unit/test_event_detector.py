"""
TCMIM — Unit tests for the high-level EventDetector (M3, FR-ED-2).

All fixtures are SYNTHETIC.
"""

import numpy as np
import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.events.detector import EventDetector
from tcmim.config import CUSUMConfig
from tcmim.schemas import HealthSample, Provenance, Modality, EventRecord

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _make_health_samples(
    scores: List[float],
    machine_id: str = "m1",
) -> List[HealthSample]:
    """Create synthetic HealthSamples from a list of health scores."""
    samples = []
    for i, score in enumerate(scores):
        ws = NOW + timedelta(minutes=i)
        we = ws + timedelta(minutes=1)
        samples.append(
            HealthSample(
                machine_id=machine_id,
                window_start=ws,
                window_end=we,
                health_score=score,
                z_scores={"feat": 1.0 - score},
                provenance=Provenance.SYNTHETIC,
                baseline_id="baseline_001",
            )
        )
    return samples


class TestEventDetector:
    def test_no_events_on_healthy_signal(self):
        """Constantly healthy signal (h=1.0) → no events."""
        cfg = CUSUMConfig(k=0.5, h=5.0)
        det = EventDetector(cusum_config=cfg)
        samples = _make_health_samples([1.0] * 100)
        events = det.detect(samples, modality=Modality.PRESSURE)
        assert events == []

    def test_event_on_degraded_signal(self):
        """Signal degrading to 0 should trigger at least one event."""
        cfg = CUSUMConfig(k=0.1, h=2.0)
        det = EventDetector(cusum_config=cfg)
        # Start healthy, then drop to 0.1 (degradation = 0.9)
        scores = [1.0] * 20 + [0.1] * 80
        samples = _make_health_samples(scores)
        events = det.detect(samples, modality=Modality.PRESSURE)
        assert len(events) >= 1

    def test_event_onset_is_after_degradation_starts(self):
        """Event onset_time must be after the health drop starts."""
        cfg = CUSUMConfig(k=0.1, h=2.0)
        det = EventDetector(cusum_config=cfg)
        scores = [1.0] * 30 + [0.05] * 70
        samples = _make_health_samples(scores)
        events = det.detect(samples)
        # onset_time must be >= the 30th window's start
        degradation_start = samples[30].window_start
        for event in events:
            assert event.onset_time >= degradation_start

    def test_event_is_event_record(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg)
        scores = [1.0] * 10 + [0.0] * 50
        samples = _make_health_samples(scores)
        events = det.detect(samples, modality=Modality.CURRENT)
        assert all(isinstance(e, EventRecord) for e in events)

    def test_event_machine_id_correct(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg)
        scores = [1.0] * 10 + [0.0] * 50
        samples = _make_health_samples(scores, machine_id="compressor_A")
        events = det.detect(samples)
        for event in events:
            assert event.machine_id == "compressor_A"

    def test_event_provenance_preserved(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg)
        scores = [1.0] * 10 + [0.0] * 50
        samples = _make_health_samples(scores)
        events = det.detect(samples)
        for event in events:
            assert event.provenance == Provenance.SYNTHETIC

    def test_event_detector_label(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg, detector_type="cusum")
        scores = [1.0] * 10 + [0.0] * 50
        samples = _make_health_samples(scores)
        events = det.detect(samples)
        for event in events:
            assert event.detector == "cusum"

    def test_page_hinkley_detector_type(self):
        det = EventDetector(detector_type="page_hinkley")
        scores = [1.0] * 20 + [0.05] * 80
        samples = _make_health_samples(scores)
        events = det.detect(samples)
        for event in events:
            assert event.detector == "page_hinkley"

    def test_invalid_detector_type_raises(self):
        with pytest.raises(ValueError, match="detector_type"):
            EventDetector(detector_type="random_forest")

    def test_empty_samples_returns_empty(self):
        det = EventDetector()
        assert det.detect([]) == []

    def test_detect_with_scores_returns_tuple(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg)
        scores = [1.0] * 10 + [0.0] * 50
        samples = _make_health_samples(scores)
        result = det.detect_with_scores(samples)
        assert isinstance(result, tuple)
        events, score_trace = result
        assert len(score_trace) == len(samples)

    def test_detect_with_scores_empty(self):
        det = EventDetector()
        events, trace = det.detect_with_scores([])
        assert events == []
        assert len(trace) == 0

    def test_event_score_is_positive(self):
        cfg = CUSUMConfig(k=0.1, h=1.5)
        det = EventDetector(cusum_config=cfg)
        scores = [0.0] * 60
        samples = _make_health_samples(scores)
        events = det.detect(samples)
        for event in events:
            assert event.score > 0
