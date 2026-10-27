"""
TCMIM — Unit tests for OC-CCD (M6, FR-CC-1, FR-CC-2).

All fixtures are SYNTHETIC. Tests verify:
- Each check fires correctly on crafted inputs
- The AMBIGUOUS / COMMON_CAUSE / PROPAGATION_CANDIDATE labels are correct
- The FR-CC-2 disclaimer is always present in result notes
- analyse_all correctly skips rejected observations
"""

import numpy as np
import pytest
from datetime import datetime, timezone
from typing import List

from tcmim.propagation.occ_ccd import (
    OCCCDAnalyser,
    OCCCDConfig,
    OCCCDLabel,
    OCCCDResult,
)
from tcmim.schemas import PropagationObservation, Provenance

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)
DISCLAIMER_FRAGMENT = "[FR-CC-2:"


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
        reject_reason=None if gate_result == "accepted" else "test_reject",
        provenance=Provenance.SYNTHETIC,
    )


class TestOCCCDT1Simultaneity:
    def test_t1_flags_small_delta(self):
        """Δt well below threshold → T1 fires → COMMON_CAUSE_CANDIDATE."""
        cfg = OCCCDConfig(simultaneity_threshold_s=30.0)
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(5.0)   # 5s << 30s threshold
        result = analyser.analyse(obs)
        assert result.checks["T1_SIMULTANEITY"] is True
        assert result.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE

    def test_t1_does_not_flag_large_delta(self):
        """Δt well above threshold → T1 should not fire."""
        cfg = OCCCDConfig(simultaneity_threshold_s=30.0)
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(120.0)   # 120s >> 30s
        result = analyser.analyse(obs)
        assert result.checks["T1_SIMULTANEITY"] is False

    def test_t1_boundary_exactly_at_threshold(self):
        """Δt == threshold-1 → T1 fires; Δt == threshold → does not."""
        cfg = OCCCDConfig(simultaneity_threshold_s=30.0)
        analyser = OCCCDAnalyser(cfg)
        obs_just_below = _make_obs(29.9)
        obs_at         = _make_obs(30.0)
        assert analyser.analyse(obs_just_below).checks["T1_SIMULTANEITY"] is True
        assert analyser.analyse(obs_at).checks["T1_SIMULTANEITY"] is False

    def test_t1_uses_abs_corrected_delta(self):
        """T1 uses |corrected_dt|, so negative Δt also fires."""
        cfg = OCCCDConfig(simultaneity_threshold_s=30.0, detector_lag_s=0.0)
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(-10.0)   # |Δt| = 10 < 30
        result = analyser.analyse(obs)
        assert result.checks["T1_SIMULTANEITY"] is True


class TestOCCCDT2OnsetBias:
    def test_t2_fires_when_mean_near_zero(self):
        """Mean Δt ≈ 0 → T2 onset bias → AMBIGUOUS."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,   # avoid T1
            bias_threshold_s=15.0,
            min_observations_for_bias=3,
        )
        analyser = OCCCDAnalyser(cfg)
        # Create 5 observations with mean Δt ≈ 0 (some + some -)
        all_obs = [
            _make_obs(8.0), _make_obs(-7.0), _make_obs(3.0),
            _make_obs(-4.0), _make_obs(2.0),
        ]
        obs = all_obs[0]
        result = analyser.analyse(obs, all_observations=all_obs)
        assert result.checks["T2_ONSET_BIAS"] is True

    def test_t2_skipped_when_too_few_obs(self):
        """T2 requires min_observations_for_bias=5; fewer → no flag."""
        cfg = OCCCDConfig(min_observations_for_bias=5)
        analyser = OCCCDAnalyser(cfg)
        all_obs = [_make_obs(2.0), _make_obs(3.0)]  # only 2
        result = analyser.analyse(all_obs[0], all_observations=all_obs)
        assert result.checks["T2_ONSET_BIAS"] is False

    def test_t2_does_not_fire_for_large_mean(self):
        """Large mean Δt → T2 does not flag."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,
            bias_threshold_s=10.0,
            min_observations_for_bias=3,
        )
        analyser = OCCCDAnalyser(cfg)
        all_obs = [_make_obs(100.0), _make_obs(110.0), _make_obs(120.0)]
        result = analyser.analyse(all_obs[0], all_observations=all_obs)
        assert result.checks["T2_ONSET_BIAS"] is False


class TestOCCCDT3MultiPair:
    def test_t3_fires_when_many_coinciding_pairs(self):
        """Multiple other pairs with similar Δt → T3 → COMMON_CAUSE_CANDIDATE."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,   # avoid T1
            coincidence_pair_threshold=2,
            coincidence_window_s=30.0,
        )
        analyser = OCCCDAnalyser(cfg)
        obs_main = _make_obs(60.0, src="A", tgt="B")
        all_obs = [
            obs_main,
            _make_obs(65.0, src="C", tgt="D"),   # similar Δt → coinciding pair 1
            _make_obs(70.0, src="E", tgt="F"),   # similar Δt → coinciding pair 2
        ]
        result = analyser.analyse(obs_main, all_observations=all_obs)
        assert result.checks["T3_MULTI_PAIR_COINCIDENCE"] is True
        assert result.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE

    def test_t3_does_not_fire_when_few_coinciding(self):
        """Only one other coinciding pair → T3 does not fire (threshold=2)."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,
            coincidence_pair_threshold=2,
            coincidence_window_s=30.0,
        )
        analyser = OCCCDAnalyser(cfg)
        obs_main = _make_obs(60.0, src="A", tgt="B")
        all_obs = [obs_main, _make_obs(65.0, src="C", tgt="D")]  # only 1 other
        result = analyser.analyse(obs_main, all_observations=all_obs)
        assert result.checks["T3_MULTI_PAIR_COINCIDENCE"] is False


class TestOCCCDT4OnsetCorrection:
    def test_t4_shifts_corrected_delta(self):
        """Corrected Δt = raw Δt - detector_lag_s."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,
            detector_lag_s=10.0,
        )
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(12.0)   # raw Δt = 12, corrected = 12 - 10 = 2
        result = analyser.analyse(obs)
        assert result.corrected_delta_t_s == pytest.approx(2.0)

    def test_t4_correction_can_trigger_t1(self):
        """After correction, if corrected Δt < threshold, T1 fires."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,
            detector_lag_s=8.0,   # lag = 8, raw = 12 → corrected = 4 < threshold
        )
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(12.0)   # corrected = 4 < 5 → T1 fires
        result = analyser.analyse(obs)
        assert result.checks["T1_SIMULTANEITY"] is True


class TestOCCCDLabels:
    def test_propagation_candidate_when_all_clear(self):
        """No flags → PROPAGATION_CANDIDATE."""
        cfg = OCCCDConfig(
            simultaneity_threshold_s=5.0,
            bias_threshold_s=5.0,
            coincidence_pair_threshold=10,
        )
        analyser = OCCCDAnalyser(cfg)
        obs = _make_obs(120.0)   # large Δt, well away from any threshold
        result = analyser.analyse(obs, all_observations=[obs])
        assert result.label == OCCCDLabel.PROPAGATION_CANDIDATE

    def test_fr_cc2_disclaimer_always_present(self):
        """FR-CC-2: every result note must contain the disclaimer."""
        analyser = OCCCDAnalyser()
        for delta in [1.0, 5.0, 60.0, 300.0]:
            obs = _make_obs(delta)
            result = analyser.analyse(obs)
            assert DISCLAIMER_FRAGMENT in result.note, (
                f"FR-CC-2 disclaimer missing for Δt={delta}: {result.note}"
            )

    def test_analyse_all_skips_rejected(self):
        """Rejected observations should get AMBIGUOUS with skip note."""
        analyser = OCCCDAnalyser()
        obs_accepted = _make_obs(120.0, gate_result="accepted")
        obs_rejected = _make_obs(5.0, gate_result="rejected")
        results = analyser.analyse_all([obs_accepted, obs_rejected])
        assert len(results) == 2
        rejected_result = results[1]
        assert rejected_result.label == OCCCDLabel.AMBIGUOUS
        assert "Skipped" in rejected_result.reasons[0]

    def test_analyse_all_counts_logged(self):
        """analyse_all must return one result per input observation."""
        analyser = OCCCDAnalyser(OCCCDConfig(simultaneity_threshold_s=200.0))
        obs = [_make_obs(float(50 * i)) for i in range(1, 6)]
        results = analyser.analyse_all(obs)
        assert len(results) == len(obs)

    def test_result_has_obs_id(self):
        """OCCCDResult.obs_id must match the observation's obs_id."""
        analyser = OCCCDAnalyser()
        obs = _make_obs(120.0)
        result = analyser.analyse(obs)
        assert result.obs_id == obs.obs_id
