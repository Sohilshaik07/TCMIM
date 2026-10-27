"""
src/tcmim/benchmark/__init__.py
===============================
TCMIM Synthetic Multi-Machine Benchmark Suite.

Provides deterministic benchmark scenario generation, ground-truth evaluation
metrics, and execution runners for the Stage 2 propagation analysis pipeline.
"""

from tcmim.benchmark.metrics import (
    BenchmarkMetrics,
    ScenarioEvaluation,
    evaluate_scenario,
)
from tcmim.benchmark.runner import (
    BenchmarkSuiteResult,
    MultiSeedBenchmarkResult,
    MultiSeedScenarioStats,
    run_benchmark,
    run_benchmark_multi_seed,
)
from tcmim.benchmark.scenarios import (
    BenchmarkScenario,
    generate_all_scenarios,
    generate_branching_scenario,
    generate_chain_scenario,
    generate_coexisting_direct_indirect_scenario,
    generate_common_cause_scenario,
    generate_negative_control_scenario,
    generate_noisy_scenario,
    generate_reversed_temporal_order_scenario,
    generate_ring_scenario,
)
from tcmim.benchmark.multicycle import (
    CycleSnapshot,
    EdgeLifecycleRecord,
    MultiCycleBenchmarkResult,
    MultiCycleEvaluation,
    multicycle_results_to_markdown,
    run_multicycle_benchmark,
    run_multicycle_scenario,
)

__all__ = [
    "BenchmarkMetrics",
    "BenchmarkScenario",
    "BenchmarkSuiteResult",
    "CycleSnapshot",
    "EdgeLifecycleRecord",
    "MultiCycleBenchmarkResult",
    "MultiCycleEvaluation",
    "MultiSeedBenchmarkResult",
    "MultiSeedScenarioStats",
    "ScenarioEvaluation",
    "evaluate_scenario",
    "generate_all_scenarios",
    "generate_branching_scenario",
    "generate_chain_scenario",
    "generate_coexisting_direct_indirect_scenario",
    "generate_common_cause_scenario",
    "generate_negative_control_scenario",
    "generate_noisy_scenario",
    "generate_reversed_temporal_order_scenario",
    "generate_ring_scenario",
    "multicycle_results_to_markdown",
    "run_benchmark",
    "run_benchmark_multi_seed",
    "run_multicycle_benchmark",
    "run_multicycle_scenario",
]
