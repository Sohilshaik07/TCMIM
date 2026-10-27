"""
TCMIM — Unit tests for the gating pipeline (M5, FR-GT-1, FR-GT-2).

All fixtures are SYNTHETIC. Tests verify:
- Each individual gate rejects the correct inputs
- Each gate passes valid inputs
- The pipeline accumulates accepted candidates for G3
- Rejected observations carry a meaningful reject_reason
- All gates have correct priority ordering

Integrity note: "accepted" here means passed all configured gates.
It does NOT mean propagation is confirmed.
"""

import numpy as np
import pytest
from copy import copy
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.gating.gates import (
    GatingConfig,
    GatingPipeline,
    gate_delay_feasibility,
    gate_direction_consistency,
    gate_health_consistency,
    gate_ordering,
    gate_relationship_consistency,
)
from tcmim.schemas import (
    EventRecord,
    HealthSample,
    Modality,
    PropagationObservation,
    Provenance,
)

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


# ---- Fixture helpers -------------------------------------------------------

def _make_obs(
    delta_t_s: float,
    src: str = "A",
    tgt: str = "B",
    gate_result: str = "accepted",
) -> PropagationObservation:
    return PropagationObservation(
        source_event="ev_src",
        target_event="ev_tgt",
        source_machine=src,
        target_machine=tgt,
        delta_t_s=delta_t_s,
        gate_result=gate_result,
        reject_reason=None,
        provenance=Provenance.SYNTHETIC,
    )


def _make_event(
    machine_id: str,
    modality: Modality = Modality.PRESSURE,
    event_id: str = "ev_src",
) -> EventRecord:
    return EventRecord(
        machine_id=machine_id,
        modality=modality,
        onset_time=NOW,
        detector="cusum",
        score=7.0,
        provenance=Provenance.SYNTHETIC,
        event_id=event_id,
    )


def _make_health(machine_id: str, score: float) -> HealthSample:
    return HealthSample(
        machine_id=machine_id,
        window_start=NOW - timedelta(minutes=1),
        window_end=NOW,
        health_score=score,
        z_scores={},
        provenance=Provenance.SYNTHETIC,
        baseline_id="b1",
    )


# ============================================================
# G1 — Delay feasibility
# ============================================================

class TestGateDelayFeasibility:
    def test_within_window_passes(self):
        obs = _make_obs(60.0)
        result = gate_delay_feasibility(obs, 0.0, 120.0)
        assert result.passed is True

    def test_below_min_fails(self):
        obs = _make_obs(-5.0)
        result = gate_delay_feasibility(obs, 0.0, 120.0)
        assert result.passed is False
        assert "Δt" in result.reason

    def test_above_max_fails(self):
        obs = _make_obs(200.0)
        result = gate_delay_feasibility(obs, 0.0, 120.0)
        assert result.passed is False

    def test_exactly_at_boundaries(self):
        obs_min = _make_obs(0.0)
        obs_max = _make_obs(120.0)
        assert gate_delay_feasibility(obs_min, 0.0, 120.0).passed is True
        assert gate_delay_feasibility(obs_max, 0.0, 120.0).passed is True

    def test_gate_name(self):
        obs = _make_obs(60.0)
        result = gate_delay_feasibility(obs, 0.0, 120.0)
        assert result.gate == "G1_DELAY_FEASIBILITY"


# ============================================================
# G2 — Ordering
# ============================================================

class TestGateOrdering:
    def test_positive_delta_passes(self):
        obs = _make_obs(30.0)
        result = gate_ordering(obs)
        assert result.passed is True

    def test_zero_delta_fails(self):
        obs = _make_obs(0.0)
        result = gate_ordering(obs)
        assert result.passed is False

    def test_negative_delta_fails(self):
        obs = _make_obs(-10.0)
        result = gate_ordering(obs)
        assert result.passed is False
        assert "≤ 0" in result.reason

    def test_gate_name(self):
        obs = _make_obs(30.0)
        result = gate_ordering(obs)
        assert result.gate == "G2_ORDERING"


# ============================================================
# G3 — Direction consistency
# ============================================================

class TestGateDirectionConsistency:
    def test_skipped_when_history_too_small(self):
        """G3 should skip if fewer than min_n prior observations exist."""
        obs = _make_obs(-30.0)   # negative delta — would fail if applied
        prior = [_make_obs(10.0)]  # only 1 obs < min_n=3
        result = gate_direction_consistency(obs, prior, min_consistency=0.7, min_n=3)
        assert result.passed is True
        assert "skip" in result.reason

    def test_passes_when_consistency_met(self):
        obs = _make_obs(30.0)
        # 4 positive observations → consistency = 1.0
        prior = [_make_obs(10.0 * i) for i in range(1, 5)]
        result = gate_direction_consistency(obs, prior, min_consistency=0.7, min_n=3)
        assert result.passed is True

    def test_fails_when_consistency_not_met(self):
        obs = _make_obs(30.0)
        # Only 1 of 4 prior obs is positive → consistency = 0.25 < 0.7
        prior = [
            _make_obs(10.0),    # positive
            _make_obs(-5.0),    # negative
            _make_obs(-8.0),    # negative
            _make_obs(-15.0),   # negative
        ]
        result = gate_direction_consistency(obs, prior, min_consistency=0.7, min_n=3)
        assert result.passed is False
        assert "direction_consistency" in result.reason

    def test_pair_filtering(self):
        """G3 should only consider observations for the same machine pair."""
        obs = _make_obs(-5.0, src="A", tgt="B")
        # Prior obs with a different pair (C→D) — should not count
        prior_different_pair = [_make_obs(10.0, src="C", tgt="D") for _ in range(5)]
        result = gate_direction_consistency(
            obs, prior_different_pair, min_consistency=0.7, min_n=3
        )
        # History for A→B is 0 < min_n=3 → gate skipped
        assert result.passed is True
        assert "skip" in result.reason


# ============================================================
# G4 — Health consistency
# ============================================================

class TestGateHealthConsistency:
    def test_skipped_when_no_health_data(self):
        obs = _make_obs(30.0)
        result = gate_health_consistency(obs, health_map={}, degradation_threshold=0.7)
        assert result.passed is True
        assert "skip" in result.reason

    def test_passes_when_source_degraded(self):
        obs = _make_obs(30.0, src="A")
        # health_score = 0.3 < threshold = 0.7 → degraded → passes
        health_map = {"A": [_make_health("A", 0.3)]}
        result = gate_health_consistency(obs, health_map, degradation_threshold=0.7)
        assert result.passed is True

    def test_fails_when_source_healthy(self):
        obs = _make_obs(30.0, src="A")
        # health_score = 0.9 ≥ threshold = 0.7 → healthy → fails
        health_map = {"A": [_make_health("A", 0.9)]}
        result = gate_health_consistency(obs, health_map, degradation_threshold=0.7)
        assert result.passed is False
        assert "healthy" in result.reason

    def test_gate_name(self):
        obs = _make_obs(30.0, src="A")
        result = gate_health_consistency(obs, {}, 0.7)
        assert result.gate == "G4_HEALTH_CONSISTENCY"


# ============================================================
# G5 — Relationship (modality) consistency
# ============================================================

class TestGateRelationshipConsistency:
    def test_same_modality_passes(self):
        obs = _make_obs(30.0)
        src_evt = _make_event("A", Modality.PRESSURE, event_id="ev_src")
        tgt_evt = _make_event("B", Modality.PRESSURE, event_id="ev_tgt")
        result = gate_relationship_consistency(obs, src_evt, tgt_evt)
        assert result.passed is True

    def test_different_modality_fails(self):
        obs = _make_obs(30.0)
        src_evt = _make_event("A", Modality.PRESSURE, event_id="ev_src")
        tgt_evt = _make_event("B", Modality.CURRENT, event_id="ev_tgt")
        result = gate_relationship_consistency(obs, src_evt, tgt_evt)
        assert result.passed is False
        assert "modality mismatch" in result.reason

    def test_skipped_when_events_not_provided(self):
        obs = _make_obs(30.0)
        result = gate_relationship_consistency(obs, None, None)
        assert result.passed is True
        assert "skip" in result.reason

    def test_gate_name(self):
        obs = _make_obs(30.0)
        result = gate_relationship_consistency(obs, None, None)
        assert result.gate == "G5_RELATIONSHIP_CONSISTENCY"


# ============================================================
# Full GatingPipeline
# ============================================================

class TestGatingPipeline:
    def _default_pipeline(self) -> GatingPipeline:
        cfg = GatingConfig(
            min_delay_s=0.0,
            max_delay_s=300.0,
            require_positive_dt=True,
            min_direction_consistency=0.6,
            min_direction_n=3,
            health_degradation_threshold=0.7,
            require_same_modality=False,  # simplify for basic tests
        )
        return GatingPipeline(cfg)

    def test_all_valid_accepted(self):
        pipeline = self._default_pipeline()
        obs = [_make_obs(60.0), _make_obs(90.0), _make_obs(120.0)]
        accepted, rejected = pipeline.apply(obs)
        assert len(accepted) == 3
        assert len(rejected) == 0

    def test_negative_delta_rejected(self):
        pipeline = self._default_pipeline()
        obs = [_make_obs(-30.0)]
        accepted, rejected = pipeline.apply(obs)
        assert len(accepted) == 0
        assert len(rejected) == 1
        assert rejected[0].gate_result == "rejected"
        assert rejected[0].reject_reason is not None

    def test_outside_max_delay_rejected(self):
        pipeline = self._default_pipeline()
        obs = [_make_obs(400.0)]  # > 300s limit
        accepted, rejected = pipeline.apply(obs)
        assert len(rejected) == 1
        # The rejection reason must mention the delay being outside the window
        assert "outside feasible window" in rejected[0].reject_reason

    def test_reject_reason_set_on_rejected(self):
        """All rejected observations must carry a non-empty reject_reason."""
        pipeline = self._default_pipeline()
        obs = [_make_obs(-5.0), _make_obs(400.0), _make_obs(60.0)]
        _, rejected = pipeline.apply(obs)
        for r in rejected:
            assert r.reject_reason is not None
            assert len(r.reject_reason) > 0

    def test_accepted_gate_result_correct(self):
        pipeline = self._default_pipeline()
        obs = [_make_obs(60.0)]
        accepted, _ = pipeline.apply(obs)
        assert accepted[0].gate_result == "accepted"
        assert accepted[0].reject_reason is None

    def test_mixed_batch(self):
        pipeline = self._default_pipeline()
        obs = [
            _make_obs(60.0),    # ✓
            _make_obs(-10.0),   # ✗ G2
            _make_obs(90.0),    # ✓
            _make_obs(500.0),   # ✗ G1
        ]
        accepted, rejected = pipeline.apply(obs)
        assert len(accepted) == 2
        assert len(rejected) == 2

    def test_g3_accumulates_across_batch(self):
        """G3 should use the running accepted list, not the full batch."""
        cfg = GatingConfig(
            min_delay_s=-500.0,  # allow negative deltas through G1
            max_delay_s=300.0,
            require_positive_dt=False,  # disable G2 so negative obs can pass
            min_direction_consistency=0.8,
            min_direction_n=3,
            require_same_modality=False,
        )
        pipeline = GatingPipeline(cfg)
        # First 3 obs are negative (wrong direction) -> accepted (G3 skipped,
        # history < min_n=3). 4th obs triggers G3: consistency = 0/3 = 0.0 < 0.8
        obs = [_make_obs(-t) for t in [10.0, 20.0, 30.0, 40.0]]
        accepted, rejected = pipeline.apply(obs)
        assert len(accepted) == 3
        assert len(rejected) == 1

    def test_empty_input(self):
        pipeline = self._default_pipeline()
        accepted, rejected = pipeline.apply([])
        assert accepted == []
        assert rejected == []

    def test_original_obs_not_mutated(self):
        """Pipeline must not mutate the original observations."""
        pipeline = self._default_pipeline()
        obs_orig = _make_obs(60.0)
        original_gate = obs_orig.gate_result
        pipeline.apply([obs_orig])
        assert obs_orig.gate_result == original_gate
