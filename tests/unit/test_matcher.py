"""
TCMIM — Unit tests for event matcher (M5, FR-EM-1).

All fixtures are SYNTHETIC.
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List
import uuid

from tcmim.propagation.matcher import EventMatcher, _merge_provenance
from tcmim.schemas import EventRecord, Modality, Provenance


NOW = datetime(2020, 2, 1, 0, 0, 0, tzinfo=timezone.utc)


def _make_event(
    machine_id: str,
    onset_offset_s: float,
    modality: Modality = Modality.PRESSURE,
    provenance: Provenance = Provenance.SYNTHETIC,
) -> EventRecord:
    return EventRecord(
        machine_id=machine_id,
        modality=modality,
        onset_time=NOW + timedelta(seconds=onset_offset_s),
        detector="cusum",
        score=7.0,
        provenance=provenance,
    )


class TestEventMatcher:
    def test_basic_match_within_window(self):
        """Events within the window should produce one candidate."""
        matcher = EventMatcher(max_delay_s=120.0, min_delay_s=0.0)
        src = [_make_event("A", 0.0)]
        tgt = [_make_event("B", 60.0)]
        obs = matcher.match(src, tgt, "A", "B")
        assert len(obs) == 1
        assert abs(obs[0].delta_t_s - 60.0) < 1e-6

    def test_no_match_outside_window(self):
        """Events outside the window must not be paired."""
        matcher = EventMatcher(max_delay_s=30.0, min_delay_s=0.0)
        src = [_make_event("A", 0.0)]
        tgt = [_make_event("B", 60.0)]   # 60 s > 30 s limit
        obs = matcher.match(src, tgt, "A", "B")
        assert obs == []

    def test_negative_delta_not_matched(self):
        """Target fires before source → Δt < 0 → outside [0, max]."""
        matcher = EventMatcher(max_delay_s=120.0, min_delay_s=0.0)
        src = [_make_event("A", 100.0)]
        tgt = [_make_event("B", 50.0)]   # B fires before A
        obs = matcher.match(src, tgt, "A", "B")
        assert obs == []

    def test_min_delay_excludes_simultaneous(self):
        """With min_delay_s=10, simultaneous events (Δt=0) must be excluded."""
        matcher = EventMatcher(max_delay_s=120.0, min_delay_s=10.0)
        src = [_make_event("A", 0.0)]
        tgt = [_make_event("B", 0.0)]   # simultaneous
        obs = matcher.match(src, tgt, "A", "B")
        assert obs == []

    def test_multiple_source_events(self):
        """Each source event independently matched against all target events."""
        matcher = EventMatcher(max_delay_s=120.0, min_delay_s=0.0)
        src = [_make_event("A", 0.0), _make_event("A", 200.0)]
        tgt = [_make_event("B", 60.0), _make_event("B", 250.0)]
        obs = matcher.match(src, tgt, "A", "B")
        # A@0 → B@60 (Δt=60 ✓), A@0 → B@250 (Δt=250 ✗), A@200 → B@250 (Δt=50 ✓)
        assert len(obs) == 2

    def test_one_source_many_targets(self):
        """One source event can match multiple target events."""
        matcher = EventMatcher(max_delay_s=300.0, min_delay_s=0.0)
        src = [_make_event("A", 0.0)]
        tgt = [_make_event("B", 30.0), _make_event("B", 90.0), _make_event("B", 200.0)]
        obs = matcher.match(src, tgt, "A", "B")
        assert len(obs) == 3

    def test_empty_source(self):
        matcher = EventMatcher(max_delay_s=120.0)
        tgt = [_make_event("B", 60.0)]
        assert matcher.match([], tgt, "A", "B") == []

    def test_empty_target(self):
        matcher = EventMatcher(max_delay_s=120.0)
        src = [_make_event("A", 0.0)]
        assert matcher.match(src, [], "A", "B") == []

    def test_delta_t_sign_correct(self):
        """Δt must equal t_target - t_source."""
        matcher = EventMatcher(max_delay_s=200.0)
        src = [_make_event("A", 100.0)]
        tgt = [_make_event("B", 175.0)]
        obs = matcher.match(src, tgt, "A", "B")
        assert len(obs) == 1
        assert obs[0].delta_t_s == pytest.approx(75.0)

    def test_machine_ids_set_correctly(self):
        matcher = EventMatcher(max_delay_s=200.0)
        src = [_make_event("compressor_A", 0.0)]
        tgt = [_make_event("compressor_B", 90.0)]
        obs = matcher.match(src, tgt, "compressor_A", "compressor_B")
        assert obs[0].source_machine == "compressor_A"
        assert obs[0].target_machine == "compressor_B"

    def test_provenance_weakest_wins(self):
        """SYNTHETIC overrides PUBLIC_DATASET in merged provenance."""
        matcher = EventMatcher(max_delay_s=200.0)
        src = [_make_event("A", 0.0, provenance=Provenance.PUBLIC_DATASET)]
        tgt = [_make_event("B", 60.0, provenance=Provenance.SYNTHETIC)]
        obs = matcher.match(src, tgt, "A", "B")
        assert obs[0].provenance == Provenance.SYNTHETIC

    def test_both_real_provenance_preserved(self):
        matcher = EventMatcher(max_delay_s=200.0)
        src = [_make_event("A", 0.0, provenance=Provenance.HARDWARE)]
        tgt = [_make_event("B", 60.0, provenance=Provenance.PUBLIC_DATASET)]
        obs = matcher.match(src, tgt, "A", "B")
        assert obs[0].provenance == Provenance.PUBLIC_DATASET  # weaker of the two

    def test_invalid_max_delay_raises(self):
        with pytest.raises(ValueError, match="max_delay_s"):
            EventMatcher(max_delay_s=0.0)

    def test_invalid_min_delay_raises(self):
        with pytest.raises(ValueError, match="min_delay_s"):
            EventMatcher(max_delay_s=120.0, min_delay_s=-1.0)

    def test_min_ge_max_raises(self):
        with pytest.raises(ValueError, match="min_delay_s must be less"):
            EventMatcher(max_delay_s=60.0, min_delay_s=60.0)

    def test_match_all_pairs(self):
        """match_all_pairs should produce candidates for all ordered pairs."""
        matcher = EventMatcher(max_delay_s=200.0)
        events_by_machine = {
            "A": [_make_event("A", 0.0)],
            "B": [_make_event("B", 90.0)],
        }
        obs = matcher.match_all_pairs(events_by_machine)
        # A→B (Δt=90 ✓) and B→A (Δt=-90, outside [0, 200] ✗)
        assert len(obs) == 1
        assert obs[0].source_machine == "A"
        assert obs[0].target_machine == "B"

    def test_known_delay_recovered(self):
        """Fixture: inject known 45-second delay and verify recovery."""
        KNOWN_DELAY_S = 45.0
        matcher = EventMatcher(max_delay_s=120.0, min_delay_s=0.0)
        src = [_make_event("A", 0.0), _make_event("A", 300.0)]
        tgt = [
            _make_event("B", KNOWN_DELAY_S),
            _make_event("B", 300.0 + KNOWN_DELAY_S),
        ]
        obs = matcher.match(src, tgt, "A", "B")
        delays = [o.delta_t_s for o in obs]
        assert all(abs(d - KNOWN_DELAY_S) < 1e-6 for d in delays)


class TestMergeProvenance:
    def test_hardware_public(self):
        assert _merge_provenance(Provenance.HARDWARE, Provenance.PUBLIC_DATASET) == Provenance.PUBLIC_DATASET

    def test_hardware_synthetic(self):
        assert _merge_provenance(Provenance.HARDWARE, Provenance.SYNTHETIC) == Provenance.SYNTHETIC

    def test_public_synthetic(self):
        assert _merge_provenance(Provenance.PUBLIC_DATASET, Provenance.SYNTHETIC) == Provenance.SYNTHETIC

    def test_same_provenance(self):
        assert _merge_provenance(Provenance.HARDWARE, Provenance.HARDWARE) == Provenance.HARDWARE
