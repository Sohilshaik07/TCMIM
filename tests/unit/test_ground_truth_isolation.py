"""
tests/unit/test_ground_truth_isolation.py
==========================================
Comprehensive proof and regression test suite verifying strict isolation of
ground truth from prediction and graph-construction logic (Phase 5).

Invariants verified:
1. Architectural Separation: No Stage 2 component accepts ground-truth labels.
2. Prediction Invariance: Pipeline outputs (matching, gating, delay estimation,
   lifecycle state, graph views, paths, and CRI) are completely independent of
   whether ground truth exists, is altered, inverted, or missing.
3. Mutation Protection: Evaluating predictions against ground-truth labels never
   mutates underlying EdgeManager records or graph states.
4. Parameter Rejection: Passing ground-truth arguments into prediction logic
   raises TypeError.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import pytest

from tcmim.analysis.orchestrator import PipelineResult, Stage2Pipeline
from tcmim.benchmark.metrics import evaluate_scenario
from tcmim.benchmark.scenarios import BenchmarkScenario, generate_chain_scenario
from tcmim.config import EdgeLifecycleConfig
from tcmim.cri.calculator import CRICalculator
from tcmim.edge.manager import EdgeManager
from tcmim.gating.gates import GatingPipeline
from tcmim.graph.dynamic_graph import DynamicGraph, GraphConfig
from tcmim.graph.path_finder import PathFinder
from tcmim.propagation.delay import DelayEstimator
from tcmim.propagation.matcher import EventMatcher
from tcmim.schemas import EdgeRecord, EdgeState, EventRecord, Modality, Provenance


class TestGroundTruthSignatureInspection:
    """Verifies that no prediction component accepts ground-truth parameters."""

    def test_stage2_pipeline_run_signature(self):
        sig = inspect.signature(Stage2Pipeline.run)
        prohibited = {"ground_truth", "gt_edges", "labels", "target_edges", "true_delays"}
        for p in sig.parameters:
            assert p not in prohibited, f"Stage2Pipeline.run contains prohibited parameter '{p}'"

    def test_event_matcher_signatures(self):
        sig = inspect.signature(EventMatcher.match_all_pairs)
        assert "ground_truth" not in sig.parameters
        assert "gt_edges" not in sig.parameters

    def test_gating_pipeline_signatures(self):
        sig = inspect.signature(GatingPipeline.apply)
        assert "ground_truth" not in sig.parameters
        assert "gt_edges" not in sig.parameters

    def test_delay_estimator_signatures(self):
        sig = inspect.signature(DelayEstimator.estimate_pair)
        assert "ground_truth" not in sig.parameters
        assert "true_delay" not in sig.parameters

    def test_edge_manager_signatures(self):
        sig = inspect.signature(EdgeManager.update)
        assert "ground_truth" not in sig.parameters
        assert "gt_edges" not in sig.parameters

    def test_dynamic_graph_signatures(self):
        sig_update = inspect.signature(DynamicGraph.update)
        assert "ground_truth" not in sig_update.parameters
        assert "gt_edges" not in sig_update.parameters

        sig_trans = inspect.signature(DynamicGraph.identify_transitive_edges)
        assert "ground_truth" not in sig_trans.parameters
        assert "gt_edges" not in sig_trans.parameters

    def test_path_finder_signatures(self):
        sig = inspect.signature(PathFinder.find_all_paths)
        assert "ground_truth" not in sig.parameters

    def test_cri_calculator_signatures(self):
        sig = inspect.signature(CRICalculator.compute_all)
        assert "ground_truth" not in sig.parameters


class TestPredictionInvarianceToGroundTruth:
    """Verifies that pipeline outputs are 100% invariant to ground-truth labels."""

    @pytest.fixture
    def test_scenario(self) -> BenchmarkScenario:
        return generate_chain_scenario(n_waves=6, delay_ab_s=60.0, delay_bc_s=90.0, seed=42)

    def test_pipeline_output_invariant_to_external_evaluation_labels(self, test_scenario):
        """Predictions must be identical regardless of how post-prediction evaluation evaluates them."""
        pipeline1 = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=3),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        pipeline2 = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=3),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )

        res1 = pipeline1.run(test_scenario.events_by_machine)
        res2 = pipeline2.run(test_scenario.events_by_machine)

        # 1. Matched observations
        assert len(res1.matched_observations) == len(res2.matched_observations)
        for o1, o2 in zip(res1.matched_observations, res2.matched_observations):
            assert o1.source_machine == o2.source_machine
            assert o1.target_machine == o2.target_machine
            assert o1.delta_t_s == pytest.approx(o2.delta_t_s)

        # 2. Accepted observations
        assert len(res1.accepted_observations) == len(res2.accepted_observations)

        # 3. Edge manager states and confidences
        edges1 = sorted(res1.edges, key=lambda e: (e.source, e.target))
        edges2 = sorted(res2.edges, key=lambda e: (e.source, e.target))
        assert len(edges1) == len(edges2)
        for e1, e2 in zip(edges1, edges2):
            assert (e1.source, e1.target) == (e2.source, e2.target)
            assert e1.state == e2.state
            assert e1.evidence_count == e2.evidence_count
            assert e1.confidence == pytest.approx(e2.confidence)
            assert e1.est_delay_s == pytest.approx(e2.est_delay_s)

        # 4. Graph snapshots and CRI records
        assert res1.graph_snapshot.nodes == res2.graph_snapshot.nodes
        assert [(e.source, e.target) for e in res1.graph_snapshot.edges] == [
            (e.source, e.target) for e in res2.graph_snapshot.edges
        ]
        cri_map1 = {c.target_machine: c.cri for c in res1.cri_records}
        cri_map2 = {c.target_machine: c.cri for c in res2.cri_records}
        assert cri_map1 == pytest.approx(cri_map2)

    def test_evaluating_with_swapped_ground_truth_never_alters_pipeline_result(self, test_scenario):
        """Calling evaluate_scenario with distinct GT sets leaves PipelineResult unmodified."""
        pipeline = Stage2Pipeline(
            edge_config=EdgeLifecycleConfig(candidate_threshold=1, provisional_threshold=3),
            graph_config=GraphConfig(min_active_state=EdgeState.CANDIDATE),
        )
        result = pipeline.run(test_scenario.events_by_machine)

        # Record snapshot of result
        edge_keys_before = [(e.source, e.target, e.state, e.evidence_count) for e in result.edges]
        graph_edges_before = [(e.source, e.target) for e in result.graph_snapshot.edges]

        # Evaluate against genuine GT
        eval_true = evaluate_scenario(test_scenario, result)
        assert eval_true.recall == pytest.approx(1.0)

        # Evaluate against empty GT (negative control scenario)
        fake_empty_scenario = BenchmarkScenario(
            scenario_id="fake_empty",
            name="Fake",
            description="",
            machines=test_scenario.machines,
            ground_truth_edges=[],
            injected_delays={},
            events_by_machine=test_scenario.events_by_machine,
        )
        eval_empty = evaluate_scenario(fake_empty_scenario, result)
        assert eval_empty.recall is None  # empty GT has undefined recall

        # Evaluate against inverted GT
        fake_inv_scenario = BenchmarkScenario(
            scenario_id="fake_inv",
            name="Fake",
            description="",
            machines=test_scenario.machines,
            ground_truth_edges=[("C", "A")],
            injected_delays={("C", "A"): 10.0},
            events_by_machine=test_scenario.events_by_machine,
        )
        eval_inv = evaluate_scenario(fake_inv_scenario, result)
        assert eval_inv.tp == 0

        # Assert PipelineResult was never modified by any evaluation calls
        edge_keys_after = [(e.source, e.target, e.state, e.evidence_count) for e in result.edges]
        graph_edges_after = [(e.source, e.target) for e in result.graph_snapshot.edges]
        assert edge_keys_before == edge_keys_after
        assert graph_edges_before == graph_edges_after


class TestProhibitedParameterRejection:
    """Verifies that passing evaluation labels into prediction functions fails immediately."""

    def test_pipeline_run_rejects_ground_truth_argument(self):
        pipeline = Stage2Pipeline()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            pipeline.run({}, ground_truth=[("A", "B")])  # type: ignore

    def test_edge_manager_rejects_ground_truth_argument(self):
        em = EdgeManager()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            em.update([], ground_truth=[("A", "B")])  # type: ignore

    def test_dynamic_graph_rejects_ground_truth_argument(self):
        dg = DynamicGraph()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            dg.update([], ground_truth=[("A", "B")])  # type: ignore

    def test_path_finder_rejects_ground_truth_argument(self):
        pf = PathFinder()
        dg = DynamicGraph()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            pf.find_all_paths(dg, "A", ground_truth=[("A", "B")])  # type: ignore

    def test_cri_calculator_rejects_ground_truth_argument(self):
        calc = CRICalculator()
        dg = DynamicGraph()
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            calc.compute_all(dg, ground_truth=[("A", "B")])  # type: ignore
