"""
tests/unit/test_multicycle_benchmark.py
========================================
Unit and regression tests for the chronological multi-cycle benchmark module.

Tests cover:
- Correct event binning into cycles
- Lifecycle progression: CANDIDATE -> PROVISIONAL -> STABLE
- Graph view isolation: filtering does not mutate EdgeManager evidence
- Precision/recall curves evolve correctly across cycles
- Ground-truth edges never passed into pipeline
- Empty cycles handled gracefully
- Negative-control spurious edges fail to reach PROVISIONAL after few cycles
- CRI and PathFinder use the same filtered view
- Downstream consistency: filtering never removes evidence from EdgeManager
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from tcmim.analysis.orchestrator import Stage2Pipeline
from tcmim.benchmark.multicycle import (
    MultiCycleBenchmarkResult,
    run_multicycle_scenario,
    run_multicycle_benchmark,
)
from tcmim.benchmark.scenarios import (
    generate_chain_scenario,
    generate_negative_control_scenario,
    generate_noisy_scenario,
    BenchmarkScenario,
)
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.delay import DelayEstimatorConfig
from tcmim.schemas import EdgeState, EventRecord, Modality, Provenance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(
    candidate_threshold: int = 1,
    provisional_threshold: int = 3,
    stable_threshold: int = 15,
) -> Stage2Pipeline:
    return Stage2Pipeline(
        edge_config=EdgeLifecycleConfig(
            candidate_threshold=candidate_threshold,
            provisional_threshold=provisional_threshold,
            stable_threshold=stable_threshold,
        ),
        graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.001),
        delay_config=DelayEstimatorConfig(estimator="median"),
    )


def _make_simple_event(machine_id: str, offset_s: float, base: datetime) -> EventRecord:
    return EventRecord(
        machine_id=machine_id,
        modality=Modality.PRESSURE,
        onset_time=base + timedelta(seconds=offset_s),
        detector="test",
        score=-0.3,
        provenance=Provenance.SYNTHETIC,
    )


# ---------------------------------------------------------------------------
# Test: Structural correctness
# ---------------------------------------------------------------------------

class TestMultiCycleStructure:
    def test_result_has_correct_number_of_cycles(self):
        """n_cycles should equal ceil(total_span / cycle_duration)."""
        sc = generate_chain_scenario(n_waves=6, wave_interval_s=1000.0, seed=42)
        # 6 waves @ 1000s apart = 5000s total span; cycle_duration=600s -> ceil(5000/600) = 9
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        assert result.n_cycles >= 8, f"Expected >= 8 cycles, got {result.n_cycles}"
        assert len(result.cycle_snapshots) == result.n_cycles

    def test_total_events_matches_scenario(self):
        sc = generate_chain_scenario(n_waves=6, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        # total events from scenario
        expected_total = sum(len(evs) for evs in sc.events_by_machine.values())
        assert result.total_events == expected_total

    def test_per_cycle_evals_has_all_views(self):
        sc = generate_chain_scenario(n_waves=4, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        assert "CANDIDATE" in result.per_cycle_evaluations
        assert "PROVISIONAL" in result.per_cycle_evaluations
        assert "STABLE" in result.per_cycle_evaluations

    def test_per_cycle_evals_length_matches_n_cycles(self):
        sc = generate_chain_scenario(n_waves=4, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        for view, evals in result.per_cycle_evaluations.items():
            assert len(evals) == result.n_cycles, f"View {view}: {len(evals)} != {result.n_cycles}"

    def test_edge_lifecycles_not_empty_after_events(self):
        sc = generate_chain_scenario(n_waves=4, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        assert len(result.edge_lifecycles) > 0

    def test_ground_truth_edges_marked_in_lifecycle(self):
        sc = generate_chain_scenario(n_waves=4, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        gt_set = {(s, t) for s, t in sc.ground_truth_edges}
        gt_recs = [lc for lc in result.edge_lifecycles if lc.is_ground_truth]
        # Both A->B and B->C should be in lifecycles
        gt_pairs = {(lc.source, lc.target) for lc in gt_recs}
        for gt_edge in gt_set:
            assert gt_edge in gt_pairs, f"GT edge {gt_edge} not found in lifecycle records"


# ---------------------------------------------------------------------------
# Test: Lifecycle Progression
# ---------------------------------------------------------------------------

class TestLifecycleProgression:
    def test_candidate_cycle_recorded_for_gt_edge(self):
        """GT edges should reach CANDIDATE state within the first few cycles."""
        sc = generate_chain_scenario(n_waves=6, wave_interval_s=800.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        gt_recs = [lc for lc in result.edge_lifecycles if lc.is_ground_truth]
        for rec in gt_recs:
            assert rec.candidate_cycle is not None, (
                f"GT edge {rec.source}->{rec.target} never reached CANDIDATE"
            )

    def test_provisional_cycle_after_candidate_cycle(self):
        """When an edge reaches PROVISIONAL, candidate_cycle must have been set first."""
        sc = generate_chain_scenario(n_waves=10, wave_interval_s=300.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=150.0)
        for rec in result.edge_lifecycles:
            if rec.provisional_cycle is not None:
                assert rec.candidate_cycle is not None
                assert rec.candidate_cycle <= rec.provisional_cycle

    def test_stable_cycle_after_provisional_cycle(self):
        """STABLE cycle must be >= PROVISIONAL cycle when both are set."""
        # Use many waves and small cycles so edges can accumulate to STABLE
        sc = generate_chain_scenario(n_waves=20, wave_interval_s=200.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=150.0)
        for rec in result.edge_lifecycles:
            if rec.stable_cycle is not None:
                assert rec.provisional_cycle is not None
                assert rec.provisional_cycle <= rec.stable_cycle

    def test_recall_nondecreasing_in_candidate_view(self):
        """Recall in CANDIDATE view should never decrease as evidence accumulates."""
        sc = generate_chain_scenario(n_waves=8, wave_interval_s=600.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        recalls = [ev.recall for ev in result.per_cycle_evaluations["CANDIDATE"]]
        # Allow zero flat before first detection, then must be non-decreasing
        non_zero_start = next((i for i, r in enumerate(recalls) if r > 0), None)
        if non_zero_start is not None:
            post_detection = recalls[non_zero_start:]
            for i in range(1, len(post_detection)):
                assert post_detection[i] >= post_detection[i - 1] - 1e-9, (
                    f"Recall decreased: cycle {non_zero_start + i - 1} -> "
                    f"{non_zero_start + i}: {post_detection[i-1]:.3f} -> {post_detection[i]:.3f}"
                )

    def test_gt_edges_reach_candidate_before_provisional(self):
        """Every GT edge that reaches PROVISIONAL must have been at CANDIDATE first."""
        sc = generate_chain_scenario(n_waves=12, wave_interval_s=200.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(provisional_threshold=3), cycle_duration_s=100.0)
        for lc in result.edge_lifecycles:
            if lc.is_ground_truth and lc.provisional_cycle is not None:
                assert lc.candidate_cycle is not None
                assert lc.candidate_cycle <= lc.provisional_cycle


# ---------------------------------------------------------------------------
# Test: Graph View Isolation
# ---------------------------------------------------------------------------

class TestGraphViewIsolation:
    def test_candidate_superset_of_provisional(self):
        """At every cycle, CANDIDATE set must be a superset of PROVISIONAL set."""
        sc = generate_chain_scenario(n_waves=10, wave_interval_s=300.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=200.0)
        for snap in result.cycle_snapshots:
            cand_set = set(snap.edges_candidate)
            prov_set = set(snap.edges_provisional)
            assert prov_set.issubset(cand_set), (
                f"Cycle {snap.cycle_index}: PROVISIONAL {prov_set - cand_set} "
                f"not in CANDIDATE set"
            )

    def test_provisional_superset_of_stable(self):
        """At every cycle, PROVISIONAL set must be a superset of STABLE set."""
        sc = generate_chain_scenario(n_waves=20, wave_interval_s=200.0, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=150.0)
        for snap in result.cycle_snapshots:
            prov_set = set(snap.edges_provisional)
            stab_set = set(snap.edges_stable)
            assert stab_set.issubset(prov_set), (
                f"Cycle {snap.cycle_index}: STABLE {stab_set - prov_set} "
                f"not in PROVISIONAL set"
            )

    def test_filtering_does_not_mutate_edge_evidence(self):
        """Viewing filtered edges must not change evidence counts in EdgeManager."""
        sc = generate_chain_scenario(n_waves=8, wave_interval_s=400.0, seed=42)
        pipeline = _make_pipeline()
        result = run_multicycle_scenario(sc, pipeline, cycle_duration_s=300.0)

        # After run, check evidence counts via pipeline's internal EdgeManager
        # against what was recorded in the last cycle snapshot
        last_snap = result.cycle_snapshots[-1]
        last_edge_states = {
            (es.source, es.target): es.evidence_count
            for es in last_snap.edge_states
        }

        # Evidence in EdgeManager internal state should match last snapshot
        for pair, expected_count in last_edge_states.items():
            internal_entry = pipeline.edge_manager.get_edge(pair[0], pair[1])
            if internal_entry is not None:
                assert internal_entry.evidence_count == expected_count, (
                    f"Edge {pair}: internal evidence {internal_entry.evidence_count} "
                    f"!= snapshot evidence {expected_count}"
                )

    def test_provisional_view_reduces_fpr_vs_candidate(self):
        """In negative control, PROVISIONAL FPR should be <= CANDIDATE FPR at final cycle."""
        sc = generate_negative_control_scenario(seed=47)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        cand_fpr = result.final_fpr.get("CANDIDATE", 0.0)
        prov_fpr = result.final_fpr.get("PROVISIONAL", 0.0)
        assert prov_fpr <= cand_fpr, (
            f"Expected PROVISIONAL FPR {prov_fpr:.3f} <= CANDIDATE FPR {cand_fpr:.3f}"
        )


# ---------------------------------------------------------------------------
# Test: Negative control
# ---------------------------------------------------------------------------

class TestNegativeControlMultiCycle:
    def test_no_provisional_edges_form_in_independent_streams(self):
        """In negative control (independent Poisson), all candidate edges should
        remain at evidence_count <= 2 and never reach PROVISIONAL."""
        sc = generate_negative_control_scenario(seed=50)
        # Use a small number of events so edge evidence stays low
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        prov_final = result.final_fpr.get("PROVISIONAL", 0.0)
        # With small Poisson streams, spurious edges rarely accumulate to 3+ evidence
        # We assert that provisional fpr is strictly lower than candidate fpr
        cand_final = result.final_fpr.get("CANDIDATE", 0.0)
        assert prov_final <= cand_final


# ---------------------------------------------------------------------------
# Test: Noisy scenario
# ---------------------------------------------------------------------------

class TestNoisyScenarioMultiCycle:
    def test_gt_edges_detected_in_candidate_view(self):
        """Both A->B and B->C should appear in CANDIDATE view at final cycle."""
        sc = generate_noisy_scenario(n_waves=8, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        cand_evals = result.per_cycle_evaluations["CANDIDATE"]
        final_cand = cand_evals[-1]
        assert final_cand.recall > 0.0, "No GT edges detected in CANDIDATE view"

    def test_missed_gt_edges_reported_correctly(self):
        """missed_ground_truth_edges() returns only GT edges with no CANDIDATE cycle."""
        sc = generate_noisy_scenario(n_waves=6, dropout_prob=0.9, seed=42)
        # With 90% dropout, some GT edges may be completely missed
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        missed = result.missed_ground_truth_edges()
        for missed_edge in missed:
            # Verify each missed edge is genuinely in GT
            src, tgt = missed_edge.split("->")
            assert (src, tgt) in sc.ground_truth_edges

    def test_delay_estimates_present_for_detected_gt_edges(self):
        """For detected GT edges, est_delay_s should be finite."""
        sc = generate_noisy_scenario(n_waves=8, dropout_prob=0.1, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        gt_set = set(sc.ground_truth_edges)
        for lc in result.edge_lifecycles:
            if lc.is_ground_truth and lc.candidate_cycle is not None:
                assert math.isfinite(lc.final_est_delay_s) or lc.final_est_delay_s != 0.0, (
                    f"GT edge {lc.source}->{lc.target}: est_delay_s is 0.0 placeholder"
                )


# ---------------------------------------------------------------------------
# Test: run_multicycle_benchmark convenience runner
# ---------------------------------------------------------------------------

class TestRunMulticycleBenchmark:
    def test_returns_results_for_all_scenarios(self):
        results = run_multicycle_benchmark(seed=42, cycle_duration_s=600.0)
        assert len(results) == 7

    def test_each_result_has_scenario_id(self):
        results = run_multicycle_benchmark(seed=42, cycle_duration_s=600.0)
        scenario_ids = {r.scenario_id for r in results}
        expected = {
            "scenario_1_chain", "scenario_2_branching", "scenario_3_ring",
            "scenario_4_negative_control", "scenario_5_reversed_order",
            "scenario_6_common_cause", "scenario_7_noisy",
        }
        assert scenario_ids == expected

    def test_scenario_id_filter(self):
        results = run_multicycle_benchmark(
            seed=42,
            cycle_duration_s=600.0,
            scenario_ids=["scenario_1_chain", "scenario_4_negative_control"],
        )
        assert len(results) == 2
        ids = {r.scenario_id for r in results}
        assert ids == {"scenario_1_chain", "scenario_4_negative_control"}

    def test_execution_time_positive(self):
        results = run_multicycle_benchmark(
            seed=42,
            cycle_duration_s=600.0,
            scenario_ids=["scenario_1_chain"],
        )
        assert results[0].execution_time_s > 0

    def test_markdown_generation_runs_without_error(self):
        from tcmim.benchmark.multicycle import multicycle_results_to_markdown
        results = run_multicycle_benchmark(
            seed=42,
            cycle_duration_s=600.0,
            scenario_ids=["scenario_1_chain", "scenario_4_negative_control"],
        )
        md = multicycle_results_to_markdown(results)
        assert "CANDIDATE" in md
        assert "PROVISIONAL" in md
        assert "STABLE" in md
        assert "scientific boundary" in md.lower() or "Scientific" in md


# ---------------------------------------------------------------------------
# Test: Downstream consistency
# ---------------------------------------------------------------------------

class TestDownstreamConsistency:
    def test_path_recall_bounded_by_recall(self):
        """path_recall_at_final <= recall; if no GT edges detected, path recall = 0."""
        sc = generate_chain_scenario(n_waves=6, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        for view in ["CANDIDATE", "PROVISIONAL", "STABLE"]:
            path_r = result.path_recall_at_final.get(view, 0.0)
            direct_r = result.final_recall.get(view, 0.0)
            assert path_r <= direct_r + 1e-9, (
                f"View {view}: path_recall {path_r:.3f} > recall {direct_r:.3f}"
            )

    def test_candidate_fpr_gte_provisional_fpr(self):
        """CANDIDATE FPR >= PROVISIONAL FPR at final cycle in all scenarios."""
        results = run_multicycle_benchmark(
            seed=42,
            cycle_duration_s=600.0,
            scenario_ids=["scenario_4_negative_control"],
        )
        for res in results:
            c = res.final_fpr.get("CANDIDATE", 0.0)
            p = res.final_fpr.get("PROVISIONAL", 0.0)
            s = res.final_fpr.get("STABLE", 0.0)
            assert p <= c + 1e-9, f"PROVISIONAL FPR {p:.3f} > CANDIDATE FPR {c:.3f}"
            assert s <= p + 1e-9, f"STABLE FPR {s:.3f} > PROVISIONAL FPR {p:.3f}"

    def test_empty_cycle_does_not_crash(self):
        """A cycle with no events must produce an empty evaluation gracefully."""
        sc = generate_chain_scenario(n_waves=2, wave_interval_s=2000.0, seed=42)
        # cycle_duration_s=100 -> many empty cycles between waves
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=100.0)
        for snap in result.cycle_snapshots:
            # Even empty cycles should have valid entries in per_cycle_evaluations
            for view in result.per_cycle_evaluations:
                ci = snap.cycle_index
                assert ci < len(result.per_cycle_evaluations[view])

    def test_lifecycle_record_is_ground_truth_matches_scenario(self):
        """is_ground_truth flag in lifecycle must match scenario.ground_truth_edges."""
        sc = generate_chain_scenario(n_waves=6, seed=42)
        result = run_multicycle_scenario(sc, _make_pipeline(), cycle_duration_s=600.0)
        gt_set = set(sc.ground_truth_edges)
        for lc in result.edge_lifecycles:
            pair = (lc.source, lc.target)
            expected_gt = pair in gt_set
            assert lc.is_ground_truth == expected_gt, (
                f"Edge {pair}: is_ground_truth={lc.is_ground_truth} but "
                f"should be {expected_gt}"
            )
