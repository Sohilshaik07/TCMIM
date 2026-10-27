"""
TCMIM — Integration test: M5 synthetic propagation fixture.

PRD STATUS: TEST (synthetic fixture — NOT real experimental data)

This test validates S5–S7 on a controlled synthetic fixture with a
KNOWN propagation delay.  The key assertion is:

  "Given events on machine A and events on machine B that are generated
   with a known delay of K seconds, does the pipeline:
     (a) Match the correct pairs?
     (b) Recover the known delay accurately?
     (c) Correctly reject pairs outside the plausible window?
     (d) Log rejected pairs with a reason?"

This is algorithm correctness testing — it proves the code matches the
spec on controlled inputs.  It makes NO claim about real propagation.

SYNTHETIC FIXTURE DESIGN
------------------------
Machine A: events at t = 0, 300, 600, 900 seconds
Machine B: events at t = KNOWN_DELAY + {0, 300, 600, 900} seconds
           (exact known delay, no noise in this basic fixture)

Expected: 4 matched pairs, each with Δt = KNOWN_DELAY
          Direction consistency = 1.0
          All 4 pairs accepted by gating
"""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.propagation.matcher import EventMatcher
from tcmim.propagation.delay import aggregate_delay_stats, cross_correlation_lag
from tcmim.gating.gates import GatingPipeline, GatingConfig
from tcmim.schemas import EventRecord, Modality, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)
KNOWN_DELAY_S = 47.0     # Chosen to be non-trivial (not a round number)
PLAUSIBLE_WINDOW_S = 120.0


def _make_events(
    machine_id: str,
    onset_offsets_s: List[float],
    modality: Modality = Modality.PRESSURE,
) -> List[EventRecord]:
    """Synthetic event fixture — provenance ALWAYS SYNTHETIC."""
    return [
        EventRecord(
            machine_id=machine_id,
            modality=modality,
            onset_time=NOW + timedelta(seconds=t),
            detector="cusum",
            score=8.0,
            provenance=Provenance.SYNTHETIC,
        )
        for t in onset_offsets_s
    ]


class TestM5KnownDelayFixture:
    """Validate S5–S7 against a synthetic fixture with known 47-second delay."""

    @pytest.fixture(scope="class")
    def pipeline_result(self):
        base_times = [0.0, 300.0, 600.0, 900.0]
        events_A = _make_events("machine_A", base_times)
        events_B = _make_events("machine_B", [t + KNOWN_DELAY_S for t in base_times])

        # S5 — Matching
        matcher = EventMatcher(
            max_delay_s=PLAUSIBLE_WINDOW_S, min_delay_s=0.0
        )
        candidates = matcher.match(events_A, events_B, "machine_A", "machine_B")

        # S7 — Gating (no health data, no event index for simplicity)
        cfg = GatingConfig(
            min_delay_s=0.0,
            max_delay_s=PLAUSIBLE_WINDOW_S,
            require_positive_dt=True,
            min_direction_consistency=0.6,
            min_direction_n=3,
            require_same_modality=False,
        )
        pipeline = GatingPipeline(cfg)
        accepted, rejected = pipeline.apply(candidates)

        # S6 — Delay statistics
        stats = aggregate_delay_stats(accepted, "machine_A", "machine_B")

        return {
            "events_A": events_A,
            "events_B": events_B,
            "candidates": candidates,
            "accepted": accepted,
            "rejected": rejected,
            "stats": stats,
        }

    # ---- Matching correctness -------------------------------------------

    def test_correct_number_of_candidates(self, pipeline_result):
        """All 4 event pairs should be matched (each A matches exactly one B)."""
        assert len(pipeline_result["candidates"]) == 4

    def test_known_delay_recovered_in_all_candidates(self, pipeline_result):
        """Every candidate must have Δt ≈ KNOWN_DELAY_S."""
        for obs in pipeline_result["candidates"]:
            assert obs.delta_t_s == pytest.approx(KNOWN_DELAY_S, abs=1e-6), (
                f"Expected Δt≈{KNOWN_DELAY_S}, got {obs.delta_t_s}"
            )

    def test_all_candidates_accepted_by_gating(self, pipeline_result):
        """Clean fixture → all 4 candidates should pass gating."""
        assert len(pipeline_result["accepted"]) == 4
        assert len(pipeline_result["rejected"]) == 0

    # ---- Delay statistics -----------------------------------------------

    def test_delay_stats_not_none(self, pipeline_result):
        assert pipeline_result["stats"] is not None

    def test_delay_stats_n_correct(self, pipeline_result):
        assert pipeline_result["stats"].n == 4

    def test_delay_stats_mean_correct(self, pipeline_result):
        assert pipeline_result["stats"].mean_s == pytest.approx(KNOWN_DELAY_S, abs=1e-6)

    def test_delay_stats_std_zero(self, pipeline_result):
        """No noise in fixture → std should be 0."""
        assert pipeline_result["stats"].std_s == pytest.approx(0.0, abs=1e-6)

    def test_direction_consistency_one(self, pipeline_result):
        """All Δt > 0 → direction_consistency = 1.0."""
        assert pipeline_result["stats"].direction_consistency == pytest.approx(1.0)

    def test_provenance_synthetic(self, pipeline_result):
        """All outputs from a synthetic fixture must carry SYNTHETIC provenance."""
        for obs in pipeline_result["accepted"]:
            assert obs.provenance == Provenance.SYNTHETIC
        assert pipeline_result["stats"].provenance == Provenance.SYNTHETIC

    # ---- Rejection of pairs outside the window --------------------------

    def test_too_large_delay_rejected(self):
        """Events with delay > max_delay_s must not be matched."""
        events_A = _make_events("machine_A", [0.0])
        events_B = _make_events("machine_B", [PLAUSIBLE_WINDOW_S + 10.0])  # too late
        matcher = EventMatcher(max_delay_s=PLAUSIBLE_WINDOW_S, min_delay_s=0.0)
        candidates = matcher.match(events_A, events_B, "machine_A", "machine_B")
        assert candidates == []

    def test_reversed_order_not_matched(self):
        """If B fires before A (Δt < 0), matcher should not produce a candidate."""
        events_A = _make_events("machine_A", [100.0])
        events_B = _make_events("machine_B", [50.0])  # B fires before A
        matcher = EventMatcher(max_delay_s=PLAUSIBLE_WINDOW_S, min_delay_s=0.0)
        candidates = matcher.match(events_A, events_B, "machine_A", "machine_B")
        assert candidates == []

    def test_reject_reason_logged_for_rejected(self):
        """Any rejected observation must carry a non-empty reject_reason."""
        cfg = GatingConfig(
            max_delay_s=30.0,  # tight window → all 47s delays rejected by G1
            require_positive_dt=True,
            require_same_modality=False,
        )
        events_A = _make_events("machine_A", [0.0, 300.0])
        events_B = _make_events("machine_B", [KNOWN_DELAY_S, 300.0 + KNOWN_DELAY_S])

        # Match with wider window first, then gate with narrow config
        matcher = EventMatcher(max_delay_s=120.0)
        candidates = matcher.match(events_A, events_B, "machine_A", "machine_B")
        pipeline = GatingPipeline(cfg)
        _, rejected = pipeline.apply(candidates)
        for r in rejected:
            assert r.reject_reason is not None
            assert len(r.reject_reason) > 0

    # ---- Noisy delay fixture --------------------------------------------

    def test_noisy_delay_mean_recovered(self):
        """With Gaussian noise on delay, mean should be near KNOWN_DELAY_S."""
        np.random.seed(99)
        noise = np.random.normal(0, 5.0, 20)  # std = 5 s
        base_times = [float(i * 300) for i in range(20)]
        events_A = _make_events("machine_A", base_times)
        events_B = _make_events(
            "machine_B",
            [t + KNOWN_DELAY_S + float(n) for t, n in zip(base_times, noise)],
        )
        matcher = EventMatcher(max_delay_s=PLAUSIBLE_WINDOW_S, min_delay_s=0.0)
        candidates = matcher.match(events_A, events_B, "machine_A", "machine_B")

        cfg = GatingConfig(
            min_delay_s=0.0,
            max_delay_s=PLAUSIBLE_WINDOW_S,
            require_positive_dt=True,
            min_direction_n=5,
            min_direction_consistency=0.7,
            require_same_modality=False,
        )
        pipeline = GatingPipeline(cfg)
        accepted, _ = pipeline.apply(candidates)
        stats = aggregate_delay_stats(accepted, "machine_A", "machine_B")

        assert stats is not None
        assert stats.mean_s == pytest.approx(KNOWN_DELAY_S, abs=3.0), (
            f"Mean delay {stats.mean_s:.2f}s should be near {KNOWN_DELAY_S}s "
            f"(within 3s tolerance given noise std=5s)"
        )
