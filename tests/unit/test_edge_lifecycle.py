"""
TCMIM — Unit tests for edge lifecycle state machine (M6, FR-EL-1, FR-EL-2).

Tests verify:
- All 8 states are reachable via the correct evidence counts
- direction_consistency gate is enforced for CONFIRMED
- Downward transitions (WEAKENING, EXPIRED) fire correctly
- FR-EL-2: one observation never creates a CONFIRMED or higher edge
- WEAKENING can recover when new evidence arrives
- All transitions produce a TransitionEvent with reason
"""

import pytest
from tcmim.edge.lifecycle import EdgeLifecycleStateMachine, TransitionEvent
from tcmim.config import EdgeLifecycleConfig
from tcmim.edge.manager import EdgeManager
from tcmim.schemas import EdgeState, PropagationObservation, Provenance


def _sm(
    candidate=1, provisional=3, confirmed=6,
    strengthening=10, stable=15,
    weakening=3, expired=7,
    min_dir=0.7,
) -> EdgeLifecycleStateMachine:
    cfg = EdgeLifecycleConfig(
        candidate_threshold=candidate,
        provisional_threshold=provisional,
        confirmed_threshold=confirmed,
        strengthening_threshold=strengthening,
        stable_threshold=stable,
        weakening_threshold=weakening,
        expired_threshold=expired,
        min_direction_consistency=min_dir,
    )
    return EdgeLifecycleStateMachine(cfg)


class TestUpwardTransitions:
    def test_none_to_candidate(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.NONE, evidence_count=1,
                                     direction_consistency=1.0, consecutive_silence=0)
        assert state == EdgeState.CANDIDATE
        assert event is not None

    def test_candidate_to_provisional(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.CANDIDATE, evidence_count=3,
                                     direction_consistency=1.0, consecutive_silence=0)
        assert state == EdgeState.PROVISIONAL

    def test_provisional_to_confirmed_with_consistency(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.PROVISIONAL, evidence_count=6,
                                     direction_consistency=0.8, consecutive_silence=0)
        assert state == EdgeState.CONFIRMED

    def test_provisional_NOT_confirmed_without_consistency(self):
        """direction_consistency < threshold → stays PROVISIONAL (FR-EL-2)."""
        sm = _sm(min_dir=0.7)
        state, event = sm.transition(EdgeState.PROVISIONAL, evidence_count=6,
                                     direction_consistency=0.5, consecutive_silence=0)
        assert state == EdgeState.PROVISIONAL
        assert event is None

    def test_confirmed_to_strengthening(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.CONFIRMED, evidence_count=10,
                                     direction_consistency=0.8, consecutive_silence=0)
        assert state == EdgeState.STRENGTHENING

    def test_strengthening_to_stable(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.STRENGTHENING, evidence_count=15,
                                     direction_consistency=0.8, consecutive_silence=0)
        assert state == EdgeState.STABLE

    def test_no_transition_below_threshold(self):
        """Evidence count below threshold → no upward transition."""
        sm = _sm()
        state, event = sm.transition(EdgeState.CANDIDATE, evidence_count=2,
                                     direction_consistency=1.0, consecutive_silence=0)
        assert state == EdgeState.CANDIDATE
        assert event is None

    def test_expired_can_restart_as_candidate(self):
        """New evidence on an EXPIRED edge restarts the lifecycle."""
        sm = _sm()
        state, event = sm.transition(EdgeState.EXPIRED, evidence_count=1,
                                     direction_consistency=1.0, consecutive_silence=0)
        assert state == EdgeState.CANDIDATE


class TestDownwardTransitions:
    def test_active_to_weakening(self):
        """Enough silence on an active edge → WEAKENING."""
        sm = _sm(weakening=3)
        state, event = sm.transition(EdgeState.STABLE, evidence_count=20,
                                     direction_consistency=0.9, consecutive_silence=3)
        assert state == EdgeState.WEAKENING

    def test_weakening_to_expired(self):
        """Extended silence on WEAKENING → EXPIRED."""
        sm = _sm(expired=7)
        state, event = sm.transition(EdgeState.WEAKENING, evidence_count=5,
                                     direction_consistency=0.8, consecutive_silence=7)
        assert state == EdgeState.EXPIRED

    def test_expired_wins_over_upward(self):
        """Expired threshold beats upward transition."""
        sm = _sm(expired=7, stable=15)
        state, event = sm.transition(EdgeState.STABLE, evidence_count=20,
                                     direction_consistency=0.9, consecutive_silence=8)
        assert state == EdgeState.EXPIRED

    def test_none_no_weakening(self):
        """NONE state does not enter WEAKENING on silence."""
        sm = _sm(weakening=2)
        state, event = sm.transition(EdgeState.NONE, evidence_count=0,
                                     direction_consistency=0.0, consecutive_silence=10)
        assert state == EdgeState.NONE

    def test_weakening_recovers_with_evidence(self):
        """New evidence on WEAKENING edge → recovers to PROVISIONAL."""
        sm = _sm()
        state, event = sm.transition(EdgeState.WEAKENING, evidence_count=4,
                                     direction_consistency=0.8, consecutive_silence=0)
        assert state == EdgeState.PROVISIONAL


class TestFREL2Constraint:
    def test_one_observation_cannot_confirm(self):
        """FR-EL-2: single observation → max CANDIDATE, never CONFIRMED."""
        sm = _sm(candidate=1, provisional=3, confirmed=6)
        state, _ = sm.transition(EdgeState.NONE, evidence_count=1,
                                  direction_consistency=1.0, consecutive_silence=0)
        assert state != EdgeState.CONFIRMED
        assert state == EdgeState.CANDIDATE

    def test_must_pass_through_states(self):
        """Cannot jump from NONE directly to CONFIRMED."""
        sm = _sm(candidate=1, provisional=3, confirmed=6)
        # Simulate incremental accumulation
        state = EdgeState.NONE
        for n in [1, 2, 3, 4, 5, 6]:
            state, _ = sm.transition(state, n, 0.9, 0)
        assert state == EdgeState.CONFIRMED


class TestTransitionEvent:
    def test_transition_event_produced(self):
        sm = _sm()
        state, event = sm.transition(EdgeState.NONE, 1, 1.0, 0, edge_key="A→B")
        assert isinstance(event, TransitionEvent)
        assert event.from_state == EdgeState.NONE
        assert event.to_state == EdgeState.CANDIDATE
        assert event.edge_key == "A→B"
        assert len(event.reason) > 0

    def test_no_event_on_stable_state(self):
        """When no transition occurs, event must be None."""
        sm = _sm()
        _, event = sm.transition(EdgeState.CANDIDATE, 2, 1.0, 0)
        assert event is None


class TestEdgeManager:
    """Smoke tests for EdgeManager via batch updates."""

    def _make_obs(self, src, tgt, delta=60.0, gate="accepted"):
        from tcmim.schemas import PropagationObservation, Provenance
        return PropagationObservation(
            source_event="e1", target_event="e2",
            source_machine=src, target_machine=tgt,
            delta_t_s=delta, gate_result=gate,
            reject_reason=None, provenance=Provenance.SYNTHETIC,
        )

    def test_first_obs_creates_candidate_edge(self):
        from tcmim.edge.manager import EdgeManager
        mgr = EdgeManager()
        obs = [self._make_obs("A", "B")]
        records = mgr.update(obs)
        assert len(records) == 1
        assert records[0].state == EdgeState.CANDIDATE

    def test_accumulation_advances_state(self):
        from tcmim.edge.manager import EdgeManager
        from tcmim.config import EdgeLifecycleConfig
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=2,
            confirmed_threshold=4, strengthening_threshold=8, stable_threshold=12,
            weakening_threshold=5, expired_threshold=10,
            min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)
        for _ in range(4):
            mgr.update([self._make_obs("A", "B")])
        records = mgr.update([self._make_obs("A", "B")])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state in (EdgeState.PROVISIONAL, EdgeState.CONFIRMED)

    def test_silence_moves_to_weakening(self):
        from tcmim.edge.manager import EdgeManager
        from tcmim.config import EdgeLifecycleConfig
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1, provisional_threshold=2,
            confirmed_threshold=4, strengthening_threshold=8, stable_threshold=12,
            weakening_threshold=2, expired_threshold=5,
            min_direction_consistency=0.6,
        )
        mgr = EdgeManager(config=cfg)
        # Build up the edge to PROVISIONAL
        for _ in range(3):
            mgr.update([self._make_obs("A", "B")])
        # Now silence for 2 cycles
        mgr.update([])
        records = mgr.update([])
        ab = next(r for r in records if r.source == "A" and r.target == "B")
        assert ab.state == EdgeState.WEAKENING

    def test_confidence_in_range(self):
        from tcmim.edge.manager import EdgeManager
        mgr = EdgeManager()
        mgr.update([self._make_obs("A", "B")])
        records = mgr.update([self._make_obs("A", "B")])
        for r in records:
            assert 0.0 <= r.confidence <= 1.0

    def test_reset_clears_all_edges(self):
        from tcmim.edge.manager import EdgeManager
        mgr = EdgeManager()
        mgr.update([self._make_obs("A", "B")])
        mgr.reset()
        records = mgr.update([])
        assert records == []

    def test_multiple_pairs_tracked_independently(self):
        from tcmim.edge.manager import EdgeManager
        mgr = EdgeManager()
        mgr.update([self._make_obs("A", "B"), self._make_obs("C", "D")])
        records = mgr.update([])
        pairs = {(r.source, r.target) for r in records}
        assert ("A", "B") in pairs
        assert ("C", "D") in pairs


# --------------------------------------------------------------------------
# Regression: EXPIRED edge restart behavior during silence vs fresh evidence
# --------------------------------------------------------------------------

class TestExpiredRestartRegression:
    """Regression test suite for lifecycle restart behavior after expiration."""

    def _make_obs(self, src: str = "A", tgt: str = "B", dt: float = 60.0) -> PropagationObservation:
        return PropagationObservation(
            source_event=f"{src}_ev",
            target_event=f"{tgt}_ev",
            source_machine=src,
            target_machine=tgt,
            delta_t_s=dt,
            gate_result="accepted",
            reject_reason=None,
            provenance=Provenance.SYNTHETIC,
        )

    def test_normal_edge_progression(self):
        """1. Normal edge progression through active states."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            confirmed_threshold=3,
            strengthening_threshold=4,
            stable_threshold=5,
            min_direction_consistency=0.7,
        )
        mgr = EdgeManager(config=cfg)
        states = []
        for _ in range(5):
            records = mgr.update([self._make_obs()])
            states.append(records[0].state)
        assert states == [
            EdgeState.CANDIDATE,
            EdgeState.PROVISIONAL,
            EdgeState.CONFIRMED,
            EdgeState.STRENGTHENING,
            EdgeState.STABLE,
        ]

    def test_transition_to_weakening_and_then_expired(self):
        """2. Transition to WEAKENING and then EXPIRED on consecutive silence."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            weakening_threshold=2,
            expired_threshold=4,
        )
        mgr = EdgeManager(config=cfg)
        # Build to PROVISIONAL
        mgr.update([self._make_obs()])
        r = mgr.update([self._make_obs()])[0]
        assert r.state == EdgeState.PROVISIONAL

        # Silence cycle 1: still provisional
        r = mgr.update([])[0]
        assert r.state == EdgeState.PROVISIONAL

        # Silence cycle 2: reaches weakening_threshold -> WEAKENING
        r = mgr.update([])[0]
        assert r.state == EdgeState.WEAKENING

        # Silence cycle 3: weakening
        r = mgr.update([])[0]
        assert r.state == EdgeState.WEAKENING

        # Silence cycle 4: reaches expired_threshold -> EXPIRED
        r = mgr.update([])[0]
        assert r.state == EdgeState.EXPIRED

    def test_multiple_silent_cycles_after_expiration(self):
        """3. Multiple silent cycles after expiration must stay EXPIRED."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            weakening_threshold=1,
            expired_threshold=2,
        )
        mgr = EdgeManager(config=cfg)
        mgr.update([self._make_obs()])
        mgr.update([self._make_obs()])

        # Reach EXPIRED
        mgr.update([])
        r = mgr.update([])[0]
        assert r.state == EdgeState.EXPIRED

        # 15 additional silent cycles must all remain EXPIRED with zero confidence
        for _ in range(15):
            r = mgr.update([])[0]
            assert r.state == EdgeState.EXPIRED
            assert r.confidence == 0.0

    def test_no_expired_to_candidate_restart_without_fresh_evidence(self):
        """4. No EXPIRED-to-CANDIDATE restart without fresh evidence in state machine."""
        sm = EdgeLifecycleStateMachine(EdgeLifecycleConfig(candidate_threshold=1))
        # Even with high evidence_count, silence > 0 prevents restart
        for silence in [1, 2, 5, 10, 50]:
            state, event = sm.transition(
                current_state=EdgeState.EXPIRED,
                evidence_count=25,
                direction_consistency=1.0,
                consecutive_silence=silence,
            )
            assert state == EdgeState.EXPIRED
            assert event is None

    def test_fresh_observations_after_expiration(self):
        """5. Fresh observations after expiration restart the edge to CANDIDATE."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            weakening_threshold=1,
            expired_threshold=2,
        )
        mgr = EdgeManager(config=cfg)
        mgr.update([self._make_obs()])
        mgr.update([self._make_obs()])
        mgr.update([])
        mgr.update([])  # EXPIRED

        # Fresh observation arrives
        records = mgr.update([self._make_obs()])
        assert len(records) == 1
        assert records[0].state == EdgeState.CANDIDATE
        assert records[0].confidence > 0.0

    def test_correct_behavior_when_new_observation_legitimately_permits_reactivation(self):
        """6. Re-progression to PROVISIONAL and CONFIRMED after reactivation."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            confirmed_threshold=3,
            weakening_threshold=1,
            expired_threshold=2,
            min_direction_consistency=0.7,
        )
        mgr = EdgeManager(config=cfg)
        # Advance and expire
        mgr.update([self._make_obs()])
        mgr.update([])
        mgr.update([])  # EXPIRED

        # Reactivate with fresh observation -> CANDIDATE
        r = mgr.update([self._make_obs()])[0]
        assert r.state == EdgeState.CANDIDATE

        # Additional fresh observations advance to PROVISIONAL then CONFIRMED
        r = mgr.update([self._make_obs()])[0]
        assert r.state == EdgeState.PROVISIONAL

        r = mgr.update([self._make_obs()])[0]
        assert r.state == EdgeState.CONFIRMED

    def test_deterministic_transitions_across_repeated_executions(self):
        """7. Deterministic transitions across repeated executions."""
        cfg = EdgeLifecycleConfig(
            candidate_threshold=1,
            provisional_threshold=2,
            weakening_threshold=1,
            expired_threshold=2,
        )

        def _run_sequence():
            mgr = EdgeManager(config=cfg)
            seq = []
            seq.append(mgr.update([self._make_obs()])[0].state)
            seq.append(mgr.update([self._make_obs()])[0].state)
            seq.append(mgr.update([])[0].state)
            seq.append(mgr.update([])[0].state)
            seq.append(mgr.update([])[0].state)
            seq.append(mgr.update([self._make_obs()])[0].state)
            seq.append(mgr.update([self._make_obs()])[0].state)
            return seq

        run1 = _run_sequence()
        run2 = _run_sequence()
        assert run1 == run2
        assert run1 == [
            EdgeState.CANDIDATE,
            EdgeState.PROVISIONAL,
            EdgeState.WEAKENING,
            EdgeState.EXPIRED,
            EdgeState.EXPIRED,
            EdgeState.CANDIDATE,
            EdgeState.PROVISIONAL,
        ]

