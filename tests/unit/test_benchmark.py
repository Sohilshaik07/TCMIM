"""
tests/unit/test_benchmark.py
============================
Unit and integration test suite for the Synthetic Multi-Machine Benchmark Suite.

Tests verify:
- Deterministic scenario generation with fixed seeds
- Correct ground-truth topology across all 7 benchmark scenarios
- Metric calculations on hand-constructed examples (TP, FP, FN, TN)
- Zero-denominator handling and documented conventions
- NaN and missing-delay accounting (never treated as 0.0)
- Directed-edge orientation enforcement
- Full execution of scenarios through real Stage2Pipeline
- OC-CCD common-cause diagnosis on shared disturbance scenario
- Provenance preservation throughout benchmark pipeline
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import pytest

from tcmim.analysis.orchestrator import PipelineResult, Stage2Pipeline
from tcmim.benchmark.metrics import (
    ScenarioEvaluation,
    evaluate_scenario,
)
from tcmim.benchmark.runner import run_benchmark
from tcmim.benchmark.scenarios import (
    BenchmarkScenario,
    generate_all_scenarios,
    generate_branching_scenario,
    generate_chain_scenario,
    generate_common_cause_scenario,
    generate_negative_control_scenario,
    generate_noisy_scenario,
    generate_reversed_temporal_order_scenario,
    generate_ring_scenario,
)
from tcmim.config import EdgeLifecycleConfig
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinderConfig
from tcmim.propagation.occ_ccd import OCCCDLabel
from tcmim.schemas import (
    EdgeRecord,
    EdgeState,
    EventRecord,
    Modality,
    PropagationGraphState,
    Provenance,
)

_NOW = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Scenario Generation & Topology
# ---------------------------------------------------------------------------

class TestScenarioGeneration:
    def test_chain_topology(self):
        sc = generate_chain_scenario(n_waves=5, delay_ab_s=60.0, delay_bc_s=90.0, seed=42)
        assert sc.scenario_id == "scenario_1_chain"
        assert sc.machines == ["A", "B", "C"]
        assert sc.ground_truth_edges == [("A", "B"), ("B", "C")]
        assert sc.injected_delays[("A", "B")] == 60.0
        assert sc.injected_delays[("B", "C")] == 90.0
        assert len(sc.events_by_machine["A"]) == 5
        assert len(sc.events_by_machine["B"]) == 5
        assert len(sc.events_by_machine["C"]) == 5
        assert all(ev.provenance == Provenance.SYNTHETIC for evs in sc.events_by_machine.values() for ev in evs)

    def test_branching_topology(self):
        sc = generate_branching_scenario(n_waves=4, delay_ab_s=45.0, delay_ac_s=80.0, seed=42)
        assert sc.scenario_id == "scenario_2_branching"
        assert set(sc.ground_truth_edges) == {("A", "B"), ("A", "C")}
        assert sc.injected_delays[("A", "B")] == 45.0
        assert sc.injected_delays[("A", "C")] == 80.0

    def test_ring_topology(self):
        sc = generate_ring_scenario(n_cycles=3, delay_s=50.0, seed=42)
        assert sc.scenario_id == "scenario_3_ring"
        assert set(sc.ground_truth_edges) == {("A", "B"), ("B", "C"), ("C", "A")}
        # In ring feedback, A receives 2 events per cycle (start + arrival)
        assert len(sc.events_by_machine["A"]) == 6
        assert len(sc.events_by_machine["B"]) == 3
        assert len(sc.events_by_machine["C"]) == 3

    def test_negative_control_topology(self):
        sc = generate_negative_control_scenario(n_events_per_machine=5, seed=42)
        assert sc.scenario_id == "scenario_4_negative_control"
        assert sc.ground_truth_edges == []
        assert sc.injected_delays == {}
        assert len(sc.machines) == 4
        assert sc.total_events == 20

    def test_reversed_temporal_order_topology(self):
        sc = generate_reversed_temporal_order_scenario(n_waves=5, delay_s=60.0, seed=42)
        assert sc.scenario_id == "scenario_5_reversed_order"
        assert sc.ground_truth_edges == []
        # Target B fires before source A
        ev_b = sc.events_by_machine["B"][0]
        ev_a = sc.events_by_machine["A"][0]
        assert (ev_b.onset_time - ev_a.onset_time).total_seconds() == pytest.approx(-60.0)

    def test_common_cause_topology(self):
        sc = generate_common_cause_scenario(n_events=4, seed=42)
        assert sc.scenario_id == "scenario_6_common_cause"
        assert sc.ground_truth_edges == []
        # All machines fire within 10s of disturbance
        for k in range(4):
            t1 = sc.events_by_machine["M1"][k].onset_time
            t2 = sc.events_by_machine["M2"][k].onset_time
            t3 = sc.events_by_machine["M3"][k].onset_time
            assert (t2 - t1).total_seconds() < 10.0
            assert (t3 - t1).total_seconds() < 10.0

    def test_noisy_scenario_topology(self):
        sc = generate_noisy_scenario(seed=42)
        assert sc.scenario_id == "scenario_7_noisy"
        assert sc.ground_truth_edges == [("A", "B"), ("B", "C")]
        assert "jitter_std_s" in sc.noise_params
        assert "dropout_prob" in sc.noise_params

    def test_reproducibility_with_fixed_seed(self):
        sc1 = generate_noisy_scenario(seed=12345)
        sc2 = generate_noisy_scenario(seed=12345)
        sc3 = generate_noisy_scenario(seed=99999)

        times1 = [ev.onset_time.isoformat() for ev in sc1.events_by_machine["A"]]
        times2 = [ev.onset_time.isoformat() for ev in sc2.events_by_machine["A"]]
        times3 = [ev.onset_time.isoformat() for ev in sc3.events_by_machine["A"]]

        assert times1 == times2
        assert times1 != times3

    def test_generate_all_scenarios_returns_seven_scenarios(self):
        scenarios = generate_all_scenarios(seed=42)
        assert len(scenarios) == 7
        assert {sc.scenario_id for sc in scenarios} == {
            "scenario_1_chain",
            "scenario_2_branching",
            "scenario_3_ring",
            "scenario_4_negative_control",
            "scenario_5_reversed_order",
            "scenario_6_common_cause",
            "scenario_7_noisy",
        }


# ---------------------------------------------------------------------------
# 2. Metric Calculations on Hand-Constructed Examples
# ---------------------------------------------------------------------------

class TestMetricCalculations:
    def _mock_result(self, edge_specs: List[Tuple[str, str, float]]) -> PipelineResult:
        """Helper to create a PipelineResult with specified edges and delays."""
        edges = []
        for src, tgt, delay in edge_specs:
            edges.append(
                EdgeRecord(
                    source=src,
                    target=tgt,
                    state=EdgeState.CANDIDATE,
                    evidence_count=5,
                    est_delay_s=delay,
                    confidence=0.5,
                    last_updated=_NOW,
                    modality=Modality.PRESSURE,
                    provenance=Provenance.SYNTHETIC,
                )
            )
        snapshot = PropagationGraphState(
            timestamp=_NOW,
            nodes=list(set([s for s, _, _ in edge_specs] + [t for _, t, _ in edge_specs])),
            edges=edges,
            version=1,
            provenance=Provenance.SYNTHETIC,
        )
        return PipelineResult(
            matched_observations=[],
            accepted_observations=[],
            rejected_observations=[],
            occcd_results=[],
            delay_statistics=[],
            edges=edges,
            graph_snapshot=snapshot,
            paths=[],
            cri_records=[],
            event_index={},
        )

    def test_perfect_recovery_metrics(self):
        sc = BenchmarkScenario(
            scenario_id="mock",
            name="Mock",
            description="",
            machines=["A", "B", "C"],
            ground_truth_edges=[("A", "B"), ("B", "C")],
            injected_delays={("A", "B"): 60.0, ("B", "C"): 90.0},
            events_by_machine={},
        )
        res = self._mock_result([("A", "B", 60.0), ("B", "C", 90.0)])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 2
        assert eval_res.fp == 0
        assert eval_res.fn == 0
        assert eval_res.tn == 4  # 6 possible pairs - 2 edges = 4
        assert eval_res.precision == pytest.approx(1.0)
        assert eval_res.recall == pytest.approx(1.0)
        assert eval_res.f1_score == pytest.approx(1.0)
        assert eval_res.fpr == pytest.approx(0.0)
        assert eval_res.lag_mae_s == pytest.approx(0.0)
        assert eval_res.lag_rmse_s == pytest.approx(0.0)
        assert eval_res.missing_lag_rate == pytest.approx(0.0)

    def test_directed_edge_orientation_enforced(self):
        """("A", "B") does NOT match ("B", "A")."""
        sc = BenchmarkScenario(
            scenario_id="mock",
            name="Mock",
            description="",
            machines=["A", "B"],
            ground_truth_edges=[("A", "B")],
            injected_delays={("A", "B"): 60.0},
            events_by_machine={},
        )
        # Pipeline predicted reversed edge B -> A
        res = self._mock_result([("B", "A", 60.0)])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 0
        assert eval_res.fp == 1
        assert eval_res.fn == 1
        assert eval_res.tn == 0
        assert eval_res.precision == pytest.approx(0.0)
        assert eval_res.recall == pytest.approx(0.0)

    def test_case1_gt_nonempty_pred_empty(self):
        """Case 1: Ground truth nonempty, predictions empty -> P=None, R=0.0, F1=None, FPR=0.0."""
        sc = BenchmarkScenario(
            scenario_id="case1",
            name="Case 1",
            description="",
            machines=["A", "B"],
            ground_truth_edges=[("A", "B")],
            injected_delays={("A", "B"): 60.0},
            events_by_machine={},
        )
        res = self._mock_result([])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 0
        assert eval_res.fp == 0
        assert eval_res.fn == 1
        assert eval_res.tn == 1
        assert eval_res.precision is None
        assert eval_res.recall == pytest.approx(0.0)
        assert eval_res.f1_score is None
        assert eval_res.fpr == pytest.approx(0.0)

    def test_case2_gt_empty_pred_nonempty(self):
        """Case 2: Ground truth empty, predictions nonempty -> P=0.0, R=None, F1=None, FPR > 0.0."""
        sc = BenchmarkScenario(
            scenario_id="case2",
            name="Case 2",
            description="",
            machines=["A", "B"],
            ground_truth_edges=[],
            injected_delays={},
            events_by_machine={},
        )
        res = self._mock_result([("A", "B", 60.0)])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 0
        assert eval_res.fp == 1
        assert eval_res.fn == 0
        assert eval_res.tn == 1
        assert eval_res.precision == pytest.approx(0.0)
        assert eval_res.recall is None
        assert eval_res.f1_score is None
        assert eval_res.fpr == pytest.approx(0.5)

    def test_case3_both_gt_and_pred_empty(self):
        """Case 3: Both ground truth and predictions empty -> P=None, R=None, F1=None, FPR=0.0."""
        sc = BenchmarkScenario(
            scenario_id="case3",
            name="Case 3",
            description="",
            machines=["A", "B"],
            ground_truth_edges=[],
            injected_delays={},
            events_by_machine={},
        )
        res = self._mock_result([])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 0
        assert eval_res.fp == 0
        assert eval_res.fn == 0
        assert eval_res.tn == 2
        assert eval_res.precision is None
        assert eval_res.recall is None
        assert eval_res.f1_score is None
        assert eval_res.fpr == pytest.approx(0.0)

    def test_case4_gt_nonempty_pred_nonempty_entirely_incorrect(self):
        """Case 4: Ground truth nonempty, predictions nonempty but entirely incorrect -> P=0.0, R=0.0, F1=0.0, FPR > 0.0."""
        sc = BenchmarkScenario(
            scenario_id="case4",
            name="Case 4",
            description="",
            machines=["A", "B", "C"],
            ground_truth_edges=[("A", "B")],
            injected_delays={("A", "B"): 60.0},
            events_by_machine={},
        )
        # Predicts C -> B, which is entirely false
        res = self._mock_result([("C", "B", 30.0)])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 0
        assert eval_res.fp == 1
        assert eval_res.fn == 1
        assert eval_res.tn == 4  # 6 pairs - 1 GT - 1 FP = 4
        assert eval_res.precision == pytest.approx(0.0)
        assert eval_res.recall == pytest.approx(0.0)
        assert eval_res.f1_score == pytest.approx(0.0)
        assert eval_res.fpr == pytest.approx(1 / 5)  # 1 FP / (1 FP + 4 TN)

    def test_nan_missing_delay_never_treated_as_zero(self):
        sc = BenchmarkScenario(
            scenario_id="mock_nan",
            name="Mock",
            description="",
            machines=["A", "B"],
            ground_truth_edges=[("A", "B")],
            injected_delays={("A", "B"): 60.0},
            events_by_machine={},
        )
        # Recovered edge has est_delay_s = NaN
        res = self._mock_result([("A", "B", float("nan"))])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 1
        assert eval_res.eligible_lag_edges == 1
        assert eval_res.finite_lag_estimates == 0
        assert eval_res.missing_lag_estimates == 1
        assert eval_res.missing_lag_rate == pytest.approx(1.0)
        assert math.isnan(eval_res.lag_mae_s)
        assert math.isnan(eval_res.lag_rmse_s)

    def test_lag_mae_rmse_calculation(self):
        sc = BenchmarkScenario(
            scenario_id="mock_lag",
            name="Mock",
            description="",
            machines=["A", "B", "C"],
            ground_truth_edges=[("A", "B"), ("B", "C")],
            injected_delays={("A", "B"): 60.0, ("B", "C"): 100.0},
            events_by_machine={},
        )
        # A->B error = +4.0s, B->C error = -4.0s
        res = self._mock_result([("A", "B", 64.0), ("B", "C", 96.0)])
        eval_res = evaluate_scenario(sc, res)

        assert eval_res.tp == 2
        assert eval_res.finite_lag_estimates == 2
        assert eval_res.missing_lag_rate == 0.0
        assert eval_res.lag_mae_s == pytest.approx(4.0)
        assert eval_res.lag_rmse_s == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 3. Real Pipeline Execution on Benchmark Scenarios
# ---------------------------------------------------------------------------

class TestRealPipelineBenchmarkExecution:
    @pytest.fixture
    def benchmark_pipeline(self) -> Stage2Pipeline:
        return Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
            path_finder_config=PathFinderConfig(max_hops=3, min_confidence=0.001),
        )

    def test_chain_execution_recovers_all_ground_truth(self, benchmark_pipeline):
        sc = generate_chain_scenario(n_waves=6, delay_ab_s=60.0, delay_bc_s=90.0, seed=42)
        result = benchmark_pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, result)

        # Asserts: 100% recall on ground truth edges
        assert eval_res.recall == pytest.approx(1.0)
        assert ("A", "B") in eval_res.true_positives
        assert ("B", "C") in eval_res.true_positives
        # Direct lag accuracy is perfect in zero-noise chain
        assert eval_res.lag_mae_s == pytest.approx(0.0, abs=1e-3)
        # Transitive association A -> C is detected (known pairwise behavior)
        assert ("A", "C") in eval_res.false_positives

    def test_branching_execution_recovers_all_ground_truth(self, benchmark_pipeline):
        sc = generate_branching_scenario(n_waves=6, delay_ab_s=45.0, delay_ac_s=80.0, seed=42)
        result = benchmark_pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, result)

        assert eval_res.recall == pytest.approx(1.0)
        assert ("A", "B") in eval_res.true_positives
        assert ("A", "C") in eval_res.true_positives
        assert eval_res.lag_mae_s == pytest.approx(0.0, abs=1e-3)

    def test_common_cause_diagnostics_flagged(self, benchmark_pipeline):
        sc = generate_common_cause_scenario(n_events=6, seed=42)
        result = benchmark_pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, result)

        # OC-CCD should flag all accepted pairs as common cause candidates
        assert len(result.occcd_results) >= 1
        assert all(res.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE for res in result.occcd_results)
        assert eval_res.occcd_summary.get(OCCCDLabel.COMMON_CAUSE_CANDIDATE, 0) == len(result.occcd_results)

    def test_negative_control_properly_accounts_false_positives(self, benchmark_pipeline):
        sc = generate_negative_control_scenario(n_events_per_machine=6, seed=42)
        result = benchmark_pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, result)

        # Ground truth has 0 edges
        assert eval_res.fn == 0
        # Any edges produced are cleanly counted as FP
        assert eval_res.fp == len(eval_res.predicted_edges)
        assert eval_res.tp == 0

    def test_provenance_synthetic_across_all_scenarios(self):
        for sc in generate_all_scenarios(seed=42):
            for m, evs in sc.events_by_machine.items():
                for ev in evs:
                    assert ev.provenance == Provenance.SYNTHETIC

    def test_full_benchmark_runner_reproducibility(self):
        res1 = run_benchmark(seed=42)
        res2 = run_benchmark(seed=42)

        assert res1.metrics.total_scenarios == 7
        assert res1.metrics.overall_tp == res2.metrics.overall_tp
        assert res1.metrics.overall_fp == res2.metrics.overall_fp
        assert res1.metrics.overall_fn == res2.metrics.overall_fn
        assert res1.metrics.overall_tn == res2.metrics.overall_tn
        assert res1.metrics.overall_precision == pytest.approx(res2.metrics.overall_precision)
        assert res1.metrics.overall_recall == pytest.approx(res2.metrics.overall_recall)
        assert len(res1.to_markdown()) > 500


# ---------------------------------------------------------------------------
# 4. Audit Regression Tests (from independent benchmark audit)
# ---------------------------------------------------------------------------

class TestAuditRegressions:
    """Regression tests encoding confirmed audit findings.

    These tests document known algorithmic behaviors identified during the
    independent audit of the synthetic benchmark suite. They are NOT
    assertions that the pipeline is correct in all cases — they are
    explicit records of what the pipeline currently does and why.
    """

    def test_noisy_lag_mean_inflated_by_spurious_cross_wave_matches(self):
        """Confirmed root cause: noisy lag MAE is inflated because spurious events
        create valid cross-wave matches within max_delay_s=600s.

        In the noisy cascade scenario (seed=48), spurious A events (planted randomly
        across the observation window) fall within 600s of valid B events from a
        different propagation wave, producing accepted A->B observations with delta_t
        ~400-460s instead of the true ~65s. The mean aggregator absorbs these outliers,
        inflating est_delay_s well above the nominal delay.

        This is a genuine algorithmic limitation of mean-based delay estimation
        without outlier filtering. It is NOT a metric implementation bug.
        """
        sc = generate_noisy_scenario(seed=48)  # benchmark uses seed 42+6=48
        pipeline = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        res = pipeline.run(sc.events_by_machine)

        # A->B should have multiple accepted observations due to spurious cross-wave pairs
        ab_obs = [
            o for o in res.accepted_observations
            if o.source_machine == "A" and o.target_machine == "B"
        ]
        assert len(ab_obs) >= 2, "A->B must have more than just direct-lag observations"

        # At least one A->B pair should have delta_t >> nominal (> 200s) due to spurious matches
        large_delta_t_obs = [o for o in ab_obs if o.delta_t_s > 200.0]
        assert len(large_delta_t_obs) >= 1, (
            "Expected at least one spurious-cross-wave A->B match with delta_t > 200s"
        )

        # The mean delay estimate must be inflated above the nominal 65s
        ab_stat = next(
            (ds for ds in res.delay_statistics if ds.source_machine == "A" and ds.target_machine == "B"),
            None,
        )
        assert ab_stat is not None
        assert ab_stat.mean_s > 100.0, (
            f"Expected inflated A->B mean delay > 100s due to spurious matches, got {ab_stat.mean_s:.2f}s"
        )

        # Verify the lag MAE is reported correctly (metric is correct, mean is inflated)
        eval_res = evaluate_scenario(sc, res)
        assert ("A", "B") in eval_res.true_positives
        assert eval_res.lag_mae_s > 50.0, (
            "Noisy lag MAE should exceed 50s due to spurious-inflated mean delay"
        )

    def test_negative_control_fpr_zero_at_provisional_threshold(self):
        """Confirmed: raising min_active_state from CANDIDATE to PROVISIONAL
        eliminates all false-positive edges in the negative control scenario.

        With candidate_threshold=1, any single coincidental event pair creates a
        CANDIDATE edge. With 4 machines, 8 events each, and max_delay_s=600s over
        30,000s, ~1 spurious match per pair is expected by chance (FPR≈0.667).

        Raising min_active_state to PROVISIONAL (requiring ≥5 observations) eliminates
        all coincidental edges, reducing FPR to 0.0. This demonstrates that the FPR
        is a threshold sensitivity artifact, not a pipeline defect.
        """
        sc = generate_negative_control_scenario(seed=45)  # benchmark uses 42+3=45

        pipeline_candidate = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=5),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        pipeline_provisional = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=5),
            graph_config=GraphConfig(min_active_state=EdgeState.PROVISIONAL),
        )

        res_cand = pipeline_candidate.run(sc.events_by_machine)
        res_prov = pipeline_provisional.run(sc.events_by_machine)

        eval_cand = evaluate_scenario(sc, res_cand)
        eval_prov = evaluate_scenario(sc, res_prov)

        # At CANDIDATE threshold: spurious edges should appear
        assert eval_cand.fp > 0, "Expected spurious CANDIDATE edges in negative control"

        # At PROVISIONAL threshold: no edges should appear (all coincidental single-obs edges pruned)
        assert eval_prov.fp == 0, (
            f"Expected 0 FP edges at PROVISIONAL threshold, got {eval_prov.fp}"
        )
        assert eval_prov.fpr == pytest.approx(0.0)

    def test_reversed_order_scenario_produces_b_to_a_false_positive(self):
        """Confirmed: reversed order scenario injects B before A (B precedes A by 60s).

        The temporal matcher correctly identifies B→A as a valid temporal association
        (delta_t = 60s, within [1s, 600s]). Since the ground truth has no edges
        (the scenario specifically injects reversed causality), this produces a FP.

        This test documents that:
        (1) The pipeline does recover temporal associations from reversed-injection data.
        (2) The ground truth is correctly set to empty (no A→B causal edge exists).
        (3) B→A is correctly classified as FP under the documented evaluation protocol.
        """
        sc = generate_reversed_temporal_order_scenario(seed=46)  # benchmark 42+4=46
        assert sc.ground_truth_edges == [], "Reversed order GT must be empty"

        pipeline = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        res = pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, res)

        # B→A should be in predicted edges (temporal matcher sees B before A)
        assert ("B", "A") in eval_res.predicted_edges, (
            "Pipeline should detect B→A temporal association in reversed scenario"
        )
        # This makes it a FP
        assert eval_res.tp == 0
        assert eval_res.fp >= 1
        assert ("B", "A") in eval_res.false_positives

    def test_common_cause_occcd_flags_do_not_block_edge_manager(self):
        """Confirmed: OCCCD flags are diagnostic-only and do NOT prevent EdgeManager
        from creating edges in the common-cause scenario.

        When all observations are flagged as COMMON_CAUSE_CANDIDATE, EdgeManager
        still creates edges because OC-CCD is a diagnostic layer, not a gate.
        The resulting false-positive edges reflect this intentional architecture.

        The audit finding: this behavior is by design. To suppress FP edges from
        common-cause scenarios, an architectural gate would need to be added that
        actively rejects accepted observations flagged by OCCCD — which would change
        the production pipeline behavior.
        """
        sc = generate_common_cause_scenario(seed=47)  # benchmark 42+5=47
        pipeline = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        res = pipeline.run(sc.events_by_machine)
        eval_res = evaluate_scenario(sc, res)

        from tcmim.propagation.occ_ccd import OCCCDLabel

        # All OCCCD results should be COMMON_CAUSE_CANDIDATE
        assert len(res.occcd_results) > 0
        assert all(r.label == OCCCDLabel.COMMON_CAUSE_CANDIDATE for r in res.occcd_results)

        # But edges are still created (OCCCD does not gate EdgeManager)
        assert len(res.graph_snapshot.edges) > 0, (
            "EdgeManager should still create edges even when OCCCD flags them as common cause"
        )

        # Ground truth is empty so these edges are all FP
        assert eval_res.tp == 0
        assert eval_res.fp > 0

    def test_json_csv_consistency(self):
        """Regression test: JSON and CSV outputs must report identical confusion counts."""
        import json, csv
        from pathlib import Path
        results_dir = Path("experiments/results/stage2")
        json_path = results_dir / "stage2_benchmark_results.json"
        csv_path = results_dir / "stage2_benchmark_summary.csv"

        if not json_path.exists() or not csv_path.exists():
            pytest.skip("Benchmark output files not present — run experiments/stage2_benchmark.py first")

        with open(json_path, encoding="utf-8") as f:
            jdata = json.load(f)
        with open(csv_path, encoding="utf-8") as f:
            csv_rows = {r["scenario_id"]: r for r in csv.DictReader(f)}

        for sc in jdata["scenarios"]:
            sc_id = sc["scenario_id"]
            assert sc_id in csv_rows, f"Scenario {sc_id} missing from CSV"
            row = csv_rows[sc_id]
            assert sc["tp"] == int(row["tp"]), f"{sc_id}: TP mismatch"
            assert sc["fp"] == int(row["fp"]), f"{sc_id}: FP mismatch"
            assert sc["fn"] == int(row["fn"]), f"{sc_id}: FN mismatch"
            assert sc["tn"] == int(row["tn"]), f"{sc_id}: TN mismatch"


# ---------------------------------------------------------------------------
# 5. Multi-Seed Robustness Tests
# ---------------------------------------------------------------------------

class TestMultiSeedRobustness:
    """Tests for the multi-seed robustness runner."""

    def test_multi_seed_returns_one_run_per_seed(self):
        from tcmim.benchmark.runner import run_benchmark_multi_seed
        seeds = [42, 43]
        result = run_benchmark_multi_seed(seeds=seeds)
        assert len(result.per_run_results) == 2
        assert result.seeds == [42, 43]

    def test_multi_seed_per_scenario_stats_count(self):
        from tcmim.benchmark.runner import run_benchmark_multi_seed
        result = run_benchmark_multi_seed(seeds=[42, 43])
        assert len(result.per_scenario_stats) == 7  # 7 benchmark scenarios

    def test_deterministic_scenarios_have_zero_std(self):
        """Chain, branching, ring, reversed, and common cause scenarios are
        deterministic — their statistics should have std=0.0 across seeds."""
        from tcmim.benchmark.runner import run_benchmark_multi_seed
        result = run_benchmark_multi_seed(seeds=[42, 43, 44])

        deterministic_ids = {
            "scenario_1_chain",
            "scenario_2_branching",
            "scenario_3_ring",
            "scenario_5_reversed_order",
            "scenario_6_common_cause",
        }
        for st in result.per_scenario_stats:
            if st.scenario_id in deterministic_ids:
                if st.mean_precision is not None:
                    assert st.std_precision == pytest.approx(0.0), (
                        f"{st.scenario_id}: expected std_precision=0 for deterministic scenario"
                    )
                else:
                    assert st.std_precision is None
                if st.mean_recall is not None:
                    assert st.std_recall == pytest.approx(0.0), (
                        f"{st.scenario_id}: expected std_recall=0 for deterministic scenario"
                    )
                else:
                    assert st.std_recall is None

    def test_multi_seed_markdown_renders(self):
        from tcmim.benchmark.runner import run_benchmark_multi_seed
        result = run_benchmark_multi_seed(seeds=[42, 43])
        md = result.to_markdown()
        assert "## Multi-Seed Robustness Results" in md
        assert "Seeds evaluated" in md

    def test_empty_seeds_raises(self):
        from tcmim.benchmark.runner import run_benchmark_multi_seed
        with pytest.raises(ValueError, match="seeds list must not be empty"):
            run_benchmark_multi_seed(seeds=[])

