"""
Unit tests for AnomalyToEventAdapter (Stage 2 Step 1).

All fixtures use Provenance.SYNTHETIC — never mixed with real-data assertions.
No ML models are trained or invoked here.

Coverage
--------
1.  Empty / all-nominal input
2.  Single anomalous window -> single EventRecord
3.  Contiguous burst -> single EventRecord
4.  Gap > max_gap_s -> two separate EventRecords
5.  Gap == max_gap_s (boundary) -> single EventRecord
6.  min_burst_windows filtering
7.  Score aggregation: peak, onset, mean
8.  Modality override (call-level and config-level)
9.  Provenance integrity: mixed provenance raises ValueError
10. Multi-machine single-stream guard
11. Deduplication of (timestamp, machine_id) duplicates
12. adapt_all_machines grouping and modality_map routing
13. EventMatcher compatibility: adapter output accepted by EventMatcher
14. EventAdapterConfig validation
15. AnomalyBurst.to_event_record all score modes
16. Strict contiguity (tolerance=0) burst splitting
17. Tolerance=1 nominal-window absorption
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import List

import pytest

from tcmim.ml.event_adapter import (
    AnomalyBurst,
    AnomalyToEventAdapter,
    EventAdapterConfig,
)
from tcmim.propagation.matcher import EventMatcher
from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2021, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
_WIN_S = 100.0  # nominal window size in seconds


def _ts(offset_windows: float) -> datetime:
    """UTC datetime offset_windows * _WIN_S seconds from _BASE_TS."""
    return _BASE_TS + timedelta(seconds=offset_windows * _WIN_S)


def _anomaly(
    *,
    offset_windows: float,
    is_anomaly: bool = True,
    score: float = -0.15,
    machine_id: str = "compressor_A",
    provenance: Provenance = Provenance.SYNTHETIC,
    detector: str = "isolation_forest",
    win_s: float = _WIN_S,
) -> AnomalyRecord:
    ts = _ts(offset_windows)
    return AnomalyRecord(
        timestamp=ts,
        machine_id=machine_id,
        anomaly_score=score,
        is_anomaly=is_anomaly,
        detector=detector,
        provenance=provenance,
        window_end=ts + timedelta(seconds=win_s),
    )


def _default_adapter(**kwargs) -> AnomalyToEventAdapter:
    return AnomalyToEventAdapter(config=EventAdapterConfig(**kwargs))


# ---------------------------------------------------------------------------
# 1. Empty / all-nominal input
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_list_returns_empty(self):
        assert AnomalyToEventAdapter().adapt([]) == []

    def test_single_non_anomalous_returns_empty(self):
        rec = _anomaly(offset_windows=0, is_anomaly=False, score=0.1)
        assert AnomalyToEventAdapter().adapt([rec]) == []

    def test_all_non_anomalous_returns_empty(self):
        records = [_anomaly(offset_windows=i, is_anomaly=False) for i in range(5)]
        assert AnomalyToEventAdapter().adapt(records) == []


# ---------------------------------------------------------------------------
# 2. Single anomalous window -> single EventRecord
# ---------------------------------------------------------------------------

class TestSingleAnomaly:
    def test_single_anomaly_produces_one_event(self):
        events = AnomalyToEventAdapter().adapt([_anomaly(offset_windows=0)])
        assert len(events) == 1

    def test_event_fields_match_record(self):
        rec = _anomaly(offset_windows=0, score=-0.20, machine_id="compressor_A")
        ev = AnomalyToEventAdapter().adapt([rec])[0]
        assert isinstance(ev, EventRecord)
        assert ev.machine_id == "compressor_A"
        assert ev.onset_time == rec.timestamp
        assert ev.detector == "isolation_forest"
        assert ev.provenance == Provenance.SYNTHETIC
        assert ev.window_count == 1

    def test_event_has_valid_event_id(self):
        ev = AnomalyToEventAdapter().adapt([_anomaly(offset_windows=0)])[0]
        assert ev.event_id  # non-empty UUID string


# ---------------------------------------------------------------------------
# 3. Contiguous burst -> single EventRecord
# ---------------------------------------------------------------------------

class TestContiguousBurst:
    def test_three_contiguous_anomalies_one_event(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=i, score=-0.1 - i * 0.02) for i in range(3)]
        assert len(adapter.adapt(records)) == 1

    def test_burst_onset_is_first_window(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=i) for i in range(5)]
        assert adapter.adapt(records)[0].onset_time == _ts(0)

    def test_burst_window_count_equals_burst_size(self):
        n = 7
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=i) for i in range(n)]
        assert adapter.adapt(records)[0].window_count == n

    def test_burst_end_time_is_last_window_end(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=i) for i in range(4)]
        ev = adapter.adapt(records)[0]
        assert ev.end_time == records[-1].window_end

    def test_onset_never_moves_backward(self):
        """A later worse-score window must not shift onset_time earlier."""
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [
            _anomaly(offset_windows=0, score=-0.10),
            _anomaly(offset_windows=1, score=-0.50),  # most anomalous
            _anomaly(offset_windows=2, score=-0.30),
        ]
        assert adapter.adapt(records)[0].onset_time == _ts(0)


# ---------------------------------------------------------------------------
# 4. Gap > max_gap_s -> two separate EventRecords
# ---------------------------------------------------------------------------

class TestGapSeparation:
    def test_large_gap_produces_two_events(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=0), _anomaly(offset_windows=10)]
        assert len(adapter.adapt(records)) == 2

    def test_two_events_sorted_chronologically(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=0), _anomaly(offset_windows=10)]
        events = adapter.adapt(records)
        assert events[0].onset_time < events[1].onset_time

    def test_three_clusters_three_events(self):
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = (
            [_anomaly(offset_windows=i) for i in range(0, 3)]
            + [_anomaly(offset_windows=i) for i in range(20, 23)]
            + [_anomaly(offset_windows=i) for i in range(40, 42)]
        )
        assert len(adapter.adapt(records)) == 3


# ---------------------------------------------------------------------------
# 5. Gap boundary
# ---------------------------------------------------------------------------

class TestGapBoundary:
    def test_gap_equal_to_max_gap_s_is_one_burst(self):
        # Window A ends at base+30s; Window B starts at base+80s => gap=50s == max_gap
        max_gap = 50.0
        base = _BASE_TS
        rec_a = AnomalyRecord(
            timestamp=base, machine_id="M",
            anomaly_score=-0.1, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=30),
        )
        rec_b = AnomalyRecord(
            timestamp=base + timedelta(seconds=80), machine_id="M",
            anomaly_score=-0.1, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=110),
        )
        assert len(_default_adapter(max_gap_s=max_gap).adapt([rec_a, rec_b])) == 1

    def test_gap_just_over_max_gap_s_splits_bursts(self):
        # gap = 51s > max_gap of 50s -> split
        max_gap = 50.0
        base = _BASE_TS
        rec_a = AnomalyRecord(
            timestamp=base, machine_id="M",
            anomaly_score=-0.1, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=30),
        )
        rec_b = AnomalyRecord(
            timestamp=base + timedelta(seconds=81), machine_id="M",
            anomaly_score=-0.1, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=111),
        )
        assert len(_default_adapter(max_gap_s=max_gap).adapt([rec_a, rec_b])) == 2


# ---------------------------------------------------------------------------
# 6. min_burst_windows filtering
# ---------------------------------------------------------------------------

class TestMinBurstWindows:
    def test_single_window_filtered_by_min_2(self):
        adapter = _default_adapter(min_burst_windows=2, max_gap_s=_WIN_S * 2)
        assert adapter.adapt([_anomaly(offset_windows=0)]) == []

    def test_two_windows_pass_min_2(self):
        adapter = _default_adapter(min_burst_windows=2, max_gap_s=_WIN_S * 2)
        records = [_anomaly(offset_windows=i) for i in range(2)]
        assert len(adapter.adapt(records)) == 1

    def test_small_burst_filtered_large_survives(self):
        adapter = _default_adapter(min_burst_windows=2, max_gap_s=_WIN_S)
        records = (
            [_anomaly(offset_windows=0)]                           # 1-window burst -> filtered
            + [_anomaly(offset_windows=i) for i in range(20, 23)] # 3-window burst -> passes
        )
        events = adapter.adapt(records)
        assert len(events) == 1
        assert events[0].window_count == 3


# ---------------------------------------------------------------------------
# 7. Score aggregation modes
# ---------------------------------------------------------------------------

class TestScoreAggregation:
    # IsolationForest convention: more negative = more anomalous
    _SCORES = [-0.10, -0.30, -0.20]  # onset=-0.10, peak=-0.30, mean=-0.20

    def _make_records(self) -> List[AnomalyRecord]:
        return [_anomaly(offset_windows=i, score=s) for i, s in enumerate(self._SCORES)]

    def test_peak_aggregation(self):
        adapter = _default_adapter(score_aggregation="peak", max_gap_s=_WIN_S * 2)
        events = adapter.adapt(self._make_records())
        assert events[0].score == pytest.approx(min(self._SCORES))

    def test_onset_aggregation(self):
        adapter = _default_adapter(score_aggregation="onset", max_gap_s=_WIN_S * 2)
        events = adapter.adapt(self._make_records())
        assert events[0].score == pytest.approx(self._SCORES[0])

    def test_mean_aggregation(self):
        adapter = _default_adapter(score_aggregation="mean", max_gap_s=_WIN_S * 2)
        events = adapter.adapt(self._make_records())
        assert events[0].score == pytest.approx(sum(self._SCORES) / len(self._SCORES))


# ---------------------------------------------------------------------------
# 8. Modality override
# ---------------------------------------------------------------------------

class TestModalityOverride:
    def test_default_modality_is_unknown(self):
        ev = AnomalyToEventAdapter().adapt([_anomaly(offset_windows=0)])[0]
        assert ev.modality == Modality.UNKNOWN

    def test_modality_override_at_call_level(self):
        ev = AnomalyToEventAdapter().adapt(
            [_anomaly(offset_windows=0)], modality=Modality.PRESSURE
        )[0]
        assert ev.modality == Modality.PRESSURE

    def test_config_default_modality_respected(self):
        adapter = _default_adapter(default_modality=Modality.VIBRATION)
        ev = adapter.adapt([_anomaly(offset_windows=0)])[0]
        assert ev.modality == Modality.VIBRATION

    def test_call_modality_overrides_config_default(self):
        adapter = _default_adapter(default_modality=Modality.VIBRATION)
        ev = adapter.adapt([_anomaly(offset_windows=0)], modality=Modality.TEMPERATURE)[0]
        assert ev.modality == Modality.TEMPERATURE


# ---------------------------------------------------------------------------
# 9. Provenance integrity
# ---------------------------------------------------------------------------

class TestProvenanceIntegrity:
    def test_mixed_provenance_raises_value_error(self):
        records = [
            _anomaly(offset_windows=0, provenance=Provenance.SYNTHETIC),
            _anomaly(offset_windows=1, provenance=Provenance.PUBLIC_DATASET),
        ]
        with pytest.raises(ValueError, match="Mixed provenance"):
            AnomalyToEventAdapter().adapt(records)

    def test_uniform_synthetic_provenance_ok(self):
        records = [
            _anomaly(offset_windows=i, provenance=Provenance.SYNTHETIC) for i in range(3)
        ]
        events = AnomalyToEventAdapter().adapt(records)
        assert all(ev.provenance == Provenance.SYNTHETIC for ev in events)

    def test_uniform_public_dataset_provenance_ok(self):
        records = [
            _anomaly(offset_windows=i, provenance=Provenance.PUBLIC_DATASET) for i in range(3)
        ]
        events = AnomalyToEventAdapter().adapt(records)
        assert all(ev.provenance == Provenance.PUBLIC_DATASET for ev in events)


# ---------------------------------------------------------------------------
# 10. Multi-machine single-stream guard
# ---------------------------------------------------------------------------

class TestMultiMachineStreamGuard:
    def test_mixed_machine_ids_raise_value_error(self):
        records = [
            _anomaly(offset_windows=0, machine_id="M1"),
            _anomaly(offset_windows=1, machine_id="M2"),
        ]
        with pytest.raises(ValueError, match="Multiple machine IDs"):
            AnomalyToEventAdapter().adapt(records)

    def test_explicit_machine_id_with_uniform_stream(self):
        records = [
            _anomaly(offset_windows=0, machine_id="M1"),
            _anomaly(offset_windows=1, machine_id="M1"),
        ]
        events = AnomalyToEventAdapter().adapt(records, machine_id="M1")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# 11. Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_duplicate_records_produce_single_event(self):
        rec = _anomaly(offset_windows=0)
        events = AnomalyToEventAdapter().adapt([rec, rec])
        assert len(events) == 1
        assert events[0].window_count == 1

    def test_distinct_timestamps_not_deduplicated(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 2)
        records = [_anomaly(offset_windows=i) for i in range(2)]
        assert adapter.adapt(records)[0].window_count == 2


# ---------------------------------------------------------------------------
# 12. adapt_all_machines
# ---------------------------------------------------------------------------

class TestAdaptAllMachines:
    def test_two_machines_produce_separate_lists(self):
        records = [
            _anomaly(offset_windows=0, machine_id="A"),
            _anomaly(offset_windows=1, machine_id="A"),
            _anomaly(offset_windows=0, machine_id="B"),
        ]
        result = AnomalyToEventAdapter().adapt_all_machines(records)
        assert set(result.keys()) == {"A", "B"}

    def test_events_belong_to_correct_machine(self):
        records = [
            _anomaly(offset_windows=0, machine_id="A"),
            _anomaly(offset_windows=0, machine_id="B"),
        ]
        result = AnomalyToEventAdapter().adapt_all_machines(records)
        assert all(ev.machine_id == "A" for ev in result["A"])
        assert all(ev.machine_id == "B" for ev in result["B"])

    def test_modality_map_applied_per_machine(self):
        records = [
            _anomaly(offset_windows=0, machine_id="A"),
            _anomaly(offset_windows=0, machine_id="B"),
        ]
        result = AnomalyToEventAdapter().adapt_all_machines(
            records,
            modality_map={"A": Modality.PRESSURE, "B": Modality.VIBRATION},
        )
        assert result["A"][0].modality == Modality.PRESSURE
        assert result["B"][0].modality == Modality.VIBRATION

    def test_empty_records_returns_empty_dict(self):
        assert AnomalyToEventAdapter().adapt_all_machines([]) == {}


# ---------------------------------------------------------------------------
# 13. EventMatcher compatibility
# ---------------------------------------------------------------------------

class TestEventMatcherCompatibility:
    def _make_events(self, machine_id: str, offsets: list) -> List[EventRecord]:
        adapter = _default_adapter(max_gap_s=_WIN_S)
        records = [_anomaly(offset_windows=o, machine_id=machine_id) for o in offsets]
        return adapter.adapt(records, machine_id=machine_id)

    def test_matcher_accepts_adapter_output_without_exception(self):
        src = self._make_events("S", [0, 1, 2, 20, 21])
        tgt = self._make_events("T", [0, 1, 2, 20, 21])
        obs = EventMatcher(max_delay_s=3600.0).match(src, tgt, "S", "T")
        assert isinstance(obs, list)

    def test_event_records_carry_required_fields(self):
        for ev in self._make_events("M", [0, 1, 2]):
            for attr in ("onset_time", "event_id", "machine_id", "modality",
                         "provenance", "detector", "score"):
                assert hasattr(ev, attr)

    def test_overlapping_windows_produce_candidate_pairs(self):
        # Source burst at window 0, target burst at window 3 -> 300s apart
        src = self._make_events("S", [0, 1, 2])
        tgt = self._make_events("T", [3, 4, 5])
        obs = EventMatcher(max_delay_s=400.0).match(src, tgt, "S", "T")
        assert len(obs) >= 1


# ---------------------------------------------------------------------------
# 14. EventAdapterConfig validation
# ---------------------------------------------------------------------------

class TestEventAdapterConfigValidation:
    def test_min_burst_windows_zero_raises(self):
        with pytest.raises(ValueError):
            EventAdapterConfig(min_burst_windows=0)

    def test_negative_max_gap_s_raises(self):
        with pytest.raises(ValueError):
            EventAdapterConfig(max_gap_s=-1.0)

    def test_invalid_score_aggregation_raises(self):
        with pytest.raises(ValueError, match="score_aggregation"):
            EventAdapterConfig(score_aggregation="median")

    def test_valid_config_no_exception(self):
        cfg = EventAdapterConfig(
            min_burst_windows=2,
            max_gap_s=60.0,
            score_aggregation="mean",
            default_modality=Modality.PRESSURE,
        )
        assert cfg.score_aggregation == "mean"

    def test_modality_string_is_coerced_to_enum(self):
        cfg = EventAdapterConfig(default_modality="vibration")  # type: ignore[arg-type]
        assert cfg.default_modality == Modality.VIBRATION


# ---------------------------------------------------------------------------
# 15. AnomalyBurst.to_event_record
# ---------------------------------------------------------------------------

class TestAnomalyBurstToEventRecord:
    def _burst(self) -> AnomalyBurst:
        return AnomalyBurst(
            machine_id="M",
            onset_time=_BASE_TS,
            end_time=_BASE_TS + timedelta(seconds=300),
            window_count=3,
            peak_score=-0.30,
            mean_score=-0.20,
            onset_score=-0.10,
            detector="isolation_forest",
            modality=Modality.PRESSURE,
            provenance=Provenance.SYNTHETIC,
        )

    def test_peak_mode(self):
        assert self._burst().to_event_record("peak").score == pytest.approx(-0.30)

    def test_onset_mode(self):
        assert self._burst().to_event_record("onset").score == pytest.approx(-0.10)

    def test_mean_mode(self):
        assert self._burst().to_event_record("mean").score == pytest.approx(-0.20)

    def test_end_time_preserved(self):
        burst = self._burst()
        assert burst.to_event_record().end_time == burst.end_time

    def test_window_count_preserved(self):
        burst = self._burst()
        assert burst.to_event_record().window_count == burst.window_count


# ---------------------------------------------------------------------------
# 16. Strict contiguity (tolerance=0)
# ---------------------------------------------------------------------------

class TestStrictContiguity:
    def test_nominal_window_closes_burst(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 10, max_tolerance_nominal_windows=0)
        records = [
            _anomaly(offset_windows=0),
            _anomaly(offset_windows=1),
            _anomaly(offset_windows=2, is_anomaly=False),  # closes first burst
            _anomaly(offset_windows=3),
            _anomaly(offset_windows=4),
        ]
        events = adapter.adapt(records)
        assert len(events) == 2
        assert events[0].window_count == 2
        assert events[1].window_count == 2

    def test_all_anomalous_stream_stays_single_burst(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 2)
        records = [_anomaly(offset_windows=i) for i in range(6)]
        assert len(adapter.adapt(records)) == 1

    def test_interleaved_nominal_creates_three_bursts(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 5, max_tolerance_nominal_windows=0)
        records = [
            _anomaly(offset_windows=0),
            _anomaly(offset_windows=1, is_anomaly=False),
            _anomaly(offset_windows=2),
            _anomaly(offset_windows=3, is_anomaly=False),
            _anomaly(offset_windows=4),
        ]
        assert len(adapter.adapt(records)) == 3


# ---------------------------------------------------------------------------
# 17. Tolerance=1 nominal-window absorption
# ---------------------------------------------------------------------------

class TestToleranceOneWindow:
    def test_one_nominal_window_absorbed_into_burst(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 10, max_tolerance_nominal_windows=1)
        records = [
            _anomaly(offset_windows=0),
            _anomaly(offset_windows=1, is_anomaly=False),  # tolerated
            _anomaly(offset_windows=2),
        ]
        events = adapter.adapt(records)
        assert len(events) == 1

    def test_two_consecutive_nominal_windows_close_burst(self):
        adapter = _default_adapter(max_gap_s=_WIN_S * 10, max_tolerance_nominal_windows=1)
        records = [
            _anomaly(offset_windows=0),
            _anomaly(offset_windows=1, is_anomaly=False),
            _anomaly(offset_windows=2, is_anomaly=False),  # exceeds tolerance -> close
            _anomaly(offset_windows=3),
        ]
        events = adapter.adapt(records)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# 18. Edge Cases: CUSUM peak score, NaN/Inf handling, Overlapping Windows
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_cusum_peak_score_takes_maximum(self):
        """In CUSUM, positive values are anomalous, so peak should be max."""
        records = [
            _anomaly(offset_windows=0, score=2.5, detector="cusum_health"),
            _anomaly(offset_windows=1, score=7.8, detector="cusum_health"),
            _anomaly(offset_windows=2, score=4.1, detector="cusum_health"),
        ]
        adapter = _default_adapter(score_aggregation="peak", max_gap_s=_WIN_S * 2)
        events = adapter.adapt(records)
        assert len(events) == 1
        assert events[0].score == pytest.approx(7.8)

    def test_nan_and_inf_scores_handled_safely(self):
        """NaN or Inf in anomaly scores should not crash or produce corrupt outputs."""
        import math
        records = [
            _anomaly(offset_windows=0, score=float("nan")),
            _anomaly(offset_windows=1, score=-0.45),
            _anomaly(offset_windows=2, score=float("-inf")),
        ]
        adapter = _default_adapter(score_aggregation="peak", max_gap_s=_WIN_S * 2)
        events = adapter.adapt(records)
        assert len(events) == 1
        assert math.isfinite(events[0].score)
        assert events[0].score == pytest.approx(-0.45)

    def test_overlapping_windows_contiguity(self):
        """Overlapping windows (gap < 0) are treated as contiguous."""
        base = _BASE_TS
        rec_a = AnomalyRecord(
            timestamp=base, machine_id="M",
            anomaly_score=-0.2, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=100),
        )
        rec_b = AnomalyRecord(
            timestamp=base + timedelta(seconds=50), machine_id="M",
            anomaly_score=-0.4, is_anomaly=True,
            detector="isolation_forest", provenance=Provenance.SYNTHETIC,
            window_end=base + timedelta(seconds=150),
        )
        adapter = _default_adapter(max_gap_s=50.0)
        events = adapter.adapt([rec_a, rec_b])
        assert len(events) == 1
        assert events[0].window_count == 2
        assert events[0].onset_time == base
        assert events[0].end_time == base + timedelta(seconds=150)