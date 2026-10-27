"""
TCMIM — Integration test: M6 edge lifecycle progression and OC-CCD.

PRD STATUS: TEST (synthetic fixture — NOT real experimental data)

Scenario 1 — Lifecycle progression
------------------------------------
Build a synthetic scenario where machine A drives machine B with a
known 47s delay.  Feed 15+ observations across multiple cycles and verify:
  - Edge progresses through CANDIDATE → PROVISIONAL → CONFIRMED → STABLE
  - FR-EL-2: the edge is not CONFIRMED after a single observation
  - Confidence increases monotonically with evidence

Scenario 2 — Common-cause rejection
-------------------------------------
Build a scenario where events on A and B are nearly simultaneous (Δt ≈ 3s).
Verify that OC-CCD flags these as COMMON_CAUSE_CANDIDATE, not
PROPAGATION_CANDIDATE.

INTEGRITY NOTES
---------------
- Provenance is SYNTHETIC throughout.
- These are algorithm-correctness tests, not claims about real machines.
- "CONFIRMED" in the lifecycle means repeated consistent evidence.
  It does NOT mean propagation is confirmed or causal.
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import List

from tcmim.config import EdgeLifecycleConfig
from tcmim.edge.lifecycle import EdgeLifecycleStateMachine
from tcmim.edge.manager import EdgeManager
from tcmim.propagation.occ_ccd import OCCCDAnalyser, OCCCDConfig, OCCCDLabel
from tcmim.schemas import EdgeState, PropagationObservation, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)
KNOWN_DELAY_S = 47.0


def _make_obs(
    delta_t_s: float,
    src: str = "A",
    tgt: str = "B",
    gate_result: str = "accepted",
) -> PropagationObservation:
    return PropagationObservation(
        source_event="e_src",
        target_event="e_tgt",
        source_machine=src,
        target_machine=tgt,
        delta_t_s=delta_t_s,
        gate_result=gate_result,
        reject_reason=None if gate_result == "accepted" else "test",
        provenance=Provenance.SYNTHETIC,
    )


# ============================================================
# Scenario 1 — Lifecycle progression
# ============================================================

class TestLifecycleProgression:
    @pytest.fixture(scope="class")
    def lifecycle_result(self):
        """Simulate 5 cycles delivering 3 obs each = 15 total → expect STABLE."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=3,
            confirmed_threshold=6,
            strengthening_threshold=10,
            stable_threshold=15,
            weakening_threshold=5,
            expired_threshold=10,
            min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)

        # 5 cycles × 3 observations each
        state_log: List[EdgeState] = []
        confidence_log: List[float] = []

        for cycle in range(5):
            obs_batch = [_make_obs(KNOWN_DELAY_S) for _ in range(3)]
            records = mgr.update(obs_batch)
            ab = next((r for r in records if r.source == "A" and r.target == "B"), None)
            if ab:
                state_log.append(ab.state)
                confidence_log.append(ab.confidence)

        return {
            "state_log": state_log,
            "confidence_log": confidence_log,
            "final_records": records,
        }

    def test_reaches_stable_after_15_obs(self, lifecycle_result):
        """After 15 total observations, edge must be STABLE."""
        final_ab = next(
            r for r in lifecycle_result["final_records"]
            if r.source == "A" and r.target == "B"
        )
        assert final_ab.state == EdgeState.STABLE, (
            f"Expected STABLE after 15 obs, got {final_ab.state}"
        )

    def test_state_progresses_monotonically(self, lifecycle_result):
        """State should never go backward during a clean accumulation run."""
        _ORDER = [
            EdgeState.NONE, EdgeState.CANDIDATE, EdgeState.PROVISIONAL,
            EdgeState.CONFIRMED, EdgeState.STRENGTHENING, EdgeState.STABLE,
        ]
        states = lifecycle_result["state_log"]
        for i in range(1, len(states)):
            prev_rank = _ORDER.index(states[i - 1]) if states[i - 1] in _ORDER else 0
            curr_rank = _ORDER.index(states[i]) if states[i] in _ORDER else 0
            assert curr_rank >= prev_rank, (
                f"State went backward: {states[i-1]} → {states[i]}"
            )

    def test_confidence_non_decreasing(self, lifecycle_result):
        """Confidence should not decrease as evidence accumulates."""
        conf = lifecycle_result["confidence_log"]
        for i in range(1, len(conf)):
            assert conf[i] >= conf[i - 1] - 1e-9, (
                f"Confidence decreased at step {i}: {conf[i-1]:.3f} → {conf[i]:.3f}"
            )

    def test_fr_el2_not_confirmed_after_one_obs(self):
        """FR-EL-2: a single accepted observation must not produce CONFIRMED."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=3,
            confirmed_threshold=6, strengthening_threshold=10, stable_threshold=15,
            weakening_threshold=5, expired_threshold=10, min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)
        records = mgr.update([_make_obs(KNOWN_DELAY_S)])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state not in (
            EdgeState.CONFIRMED, EdgeState.STRENGTHENING, EdgeState.STABLE
        ), f"FR-EL-2 violated: single obs produced state {ab.state}"

    def test_silence_causes_weakening(self):
        """After building up, silence moves the edge to WEAKENING."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=3,
            confirmed_threshold=6, strengthening_threshold=10, stable_threshold=15,
            weakening_threshold=2, expired_threshold=7,
            min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)
        # Build to PROVISIONAL
        for _ in range(4):
            mgr.update([_make_obs(KNOWN_DELAY_S)])
        # Two cycles of silence
        mgr.update([])
        records = mgr.update([])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state == EdgeState.WEAKENING


# ============================================================
# Scenario 2 — Common-cause rejection
# ============================================================

class TestOCCCDIntegration:
    def test_near_simultaneous_flagged_as_common_cause(self):
        """Δt ≈ 3s → OC-CCD T1 fires → COMMON_CAUSE_CANDIDATE."""
        cfg = OCCCDConfig(simultaneity_threshold_s=10.0)
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(delta_t_s=3.0)   # near-simultaneous
        result = analyser.analyse(obs)
        assert result.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE
        assert result.checks["T1_SIMULTANEITY"] is True

    def test_large_delay_not_flagged_as_common_cause(self):
        """Δt = 47s >> simultaneity_threshold → PROPAGATION_CANDIDATE."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=10.0,
            coincidence_pair_threshold=99,  # effectively disable T3
        )
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(delta_t_s=KNOWN_DELAY_S)
        result = analyser.analyse(obs, all_observations=[obs])
        assert result.label == OCCCDLabel.PROPAGATION_CANDIDATE

    def test_common_cause_obs_still_counted_but_labelled(self):
        """OC-CCD does not remove observations — it labels them.
        The EdgeManager sees them as accepted observations.
        This is correct: gating already accepted them; OC-CCD adds labels."""
        obs = [_make_obs(3.0) for _ in range(5)]  # all near-simultaneous
        cfg = OCCCDConfig(simultaneity_threshold_s=10.0)
        analyser = OCCCDAnalyser(cfg)
        results = analyser.analyse_all(obs)
        # All 5 should be labelled COMMON_CAUSE_CANDIDATE
        assert all(r.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE for r in results)
        # Their obs_ids should match the original observations
        original_ids = {o.obs_id for o in obs}
        result_ids = {r.obs_id for r in results}
        assert original_ids == result_ids

    def test_fr_cc2_disclaimer_in_all_results(self):
        """FR-CC-2: every result note must contain the disclaimer fragment."""
        analyser = OCCCDAnalyser()
        obs_list = [_make_obs(float(t)) for t in [3, 15, 47, 90, 200]]
        results = analyser.analyse_all(obs_list)
        for result in results:
            assert "[FR-CC-2:" in result.note, (
                f"FR-CC-2 disclaimer missing in result for {result.obs_id}"
            )

    def test_combined_occ_ccd_and_edge_lifecycle(self):
        """Only PROPAGATION_CANDIDATE observations should advance the edge."""
        occ_cfg = OCCCDConfig(simultaneity_threshold_s=10.0, coincidence_pair_threshold=99)
        analyser = OCCCDAnalyser(occ_cfg)

        lc_cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=3, confirmed_threshold=6,
            strengthening_threshold=10, stable_threshold=15,
            weakening_threshold=5, expired_threshold=10, min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=lc_cfg)

        # Mix of propagation candidates and common-cause candidates
        propagation_obs = [_make_obs(KNOWN_DELAY_S) for _ in range(7)]
        common_cause_obs = [_make_obs(3.0) for _ in range(10)]
        all_obs = propagation_obs + common_cause_obs

        # Label all
        results = analyser.analyse_all(all_obs)

        # Only feed PROPAGATION_CANDIDATE observations to the edge manager
        filtered_obs = [
            obs for obs, res in zip(all_obs, results)
            if res.label == OCCCDLabel.PROPAGATION_CANDIDATE
        ]
        assert len(filtered_obs) == 7

        # Feed one observation per cycle so state machine advances
        # incrementally (EdgeManager advances one step per update() call)
        records = None
        for obs in filtered_obs:
            records = mgr.update([obs])

        ab = next((r for r in records if r.source == "A" and r.target == "B"), None)
        assert ab is not None
        assert ab.state in (EdgeState.CONFIRMED, EdgeState.STRENGTHENING), (
            f"Expected CONFIRMED or STRENGTHENING after 7 propagation obs, "
            f"got {ab.state} (evidence_count={ab.evidence_count})"
        )
