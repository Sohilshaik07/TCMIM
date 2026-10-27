"""
src/tcmim/benchmark/scenarios.py
================================
Deterministic synthetic benchmark scenario generators for TCMIM Stage 2.

All scenarios produce EventRecord instances with Provenance.SYNTHETIC.
Randomness is strictly controlled via explicit random seeds.

Scenarios implemented:
1. Chain: A -> B -> C
2. Branching: A -> B and A -> C
3. Ring: A -> B -> C -> A
4. Negative Control: Independent random event streams (no propagation)
5. Reversed Temporal Order: Target fires before source
6. Common Cause: External disturbance causing near-simultaneous responses
7. Noisy: Chain with lag jitter, observation dropouts, and spurious events
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from tcmim.schemas import EventRecord, Modality, Provenance

_BASE_DATETIME = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


@dataclass
class BenchmarkScenario:
    """Benchmark scenario container with ground truth and synthetic event streams.

    Attributes
    ----------
    scenario_id        : Unique short identifier (e.g. 'scenario_1_chain').
    name               : Human-readable title.
    description        : Detailed scientific description of scenario topology.
    machines           : List of all participating machine IDs.
    ground_truth_edges : Directed edges representing genuine propagation (source, target).
    injected_delays    : Nominal propagation delay in seconds for each ground-truth edge.
    events_by_machine  : Mapping of machine_id -> List of EventRecord.
    noise_params       : Configuration dictionary of noise, jitter, and dropout settings.
    random_seed        : Seed used for deterministic generation.
    """
    scenario_id: str
    name: str
    description: str
    machines: List[str]
    ground_truth_edges: List[Tuple[str, str]]
    injected_delays: Dict[Tuple[str, str], float]
    events_by_machine: Dict[str, List[EventRecord]]
    noise_params: Dict[str, Any] = field(default_factory=dict)
    random_seed: int = 42

    @property
    def total_events(self) -> int:
        return sum(len(evs) for evs in self.events_by_machine.values())

    @property
    def possible_directed_edges(self) -> List[Tuple[str, str]]:
        """All possible directed pairs (u, v) with u != v."""
        return [(u, v) for u in self.machines for v in self.machines if u != v]


def _create_event(
    machine_id: str,
    onset_s: float,
    modality: Modality = Modality.PRESSURE,
    score: float = -0.25,
    detector: str = "synthetic_benchmark",
    base_ts: Optional[datetime] = None,
) -> EventRecord:
    ts = (base_ts or _BASE_DATETIME) + timedelta(seconds=onset_s)
    return EventRecord(
        machine_id=machine_id,
        modality=modality,
        onset_time=ts,
        detector=detector,
        score=score,
        provenance=Provenance.SYNTHETIC,
    )


# ---------------------------------------------------------------------------
# 1. Chain: A -> B -> C
# ---------------------------------------------------------------------------

def generate_chain_scenario(
    n_waves: int = 6,
    wave_interval_s: float = 2500.0,
    delay_ab_s: float = 60.0,
    delay_bc_s: float = 90.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate linear cascade chain scenario: A -> B -> C."""
    machines = ["A", "B", "C"]
    ground_truth_edges = [("A", "B"), ("B", "C")]
    injected_delays = {("A", "B"): delay_ab_s, ("B", "C"): delay_bc_s}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_waves):
        t_a = k * wave_interval_s
        t_b = t_a + delay_ab_s
        t_c = t_b + delay_bc_s

        events["A"].append(_create_event("A", t_a))
        events["B"].append(_create_event("B", t_b))
        events["C"].append(_create_event("C", t_c))

    return BenchmarkScenario(
        scenario_id="scenario_1_chain",
        name="Linear Chain (A -> B -> C)",
        description=(
            "Linear 3-machine cascade where A propagates to B with 60s delay, "
            "and B propagates to C with 90s delay across 6 periodic waves."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"wave_interval_s": wave_interval_s, "n_waves": n_waves},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 2. Branching: A -> B and A -> C
# ---------------------------------------------------------------------------

def generate_branching_scenario(
    n_waves: int = 6,
    wave_interval_s: float = 2500.0,
    delay_ab_s: float = 45.0,
    delay_ac_s: float = 80.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate 1-to-many branching scenario: A -> B and A -> C."""
    machines = ["A", "B", "C"]
    ground_truth_edges = [("A", "B"), ("A", "C")]
    injected_delays = {("A", "B"): delay_ab_s, ("A", "C"): delay_ac_s}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_waves):
        t_a = k * wave_interval_s
        t_b = t_a + delay_ab_s
        t_c = t_a + delay_ac_s

        events["A"].append(_create_event("A", t_a))
        events["B"].append(_create_event("B", t_b))
        events["C"].append(_create_event("C", t_c))

    return BenchmarkScenario(
        scenario_id="scenario_2_branching",
        name="Branching Fork (A -> B and A -> C)",
        description=(
            "Single-source branching topology where machine A independently "
            "propagates to B (45s delay) and C (80s delay)."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"wave_interval_s": wave_interval_s, "n_waves": n_waves},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 3. Ring: A -> B -> C -> A
# ---------------------------------------------------------------------------

def generate_ring_scenario(
    n_cycles: int = 4,
    cycle_period_s: float = 1200.0,
    delay_s: float = 50.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate cyclic feedback ring scenario: A -> B -> C -> A."""
    machines = ["A", "B", "C"]
    ground_truth_edges = [("A", "B"), ("B", "C"), ("C", "A")]
    injected_delays = {
        ("A", "B"): delay_s,
        ("B", "C"): delay_s,
        ("C", "A"): delay_s,
    }

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_cycles):
        t_base = k * cycle_period_s
        t_a1 = t_base
        t_b = t_a1 + delay_s
        t_c = t_b + delay_s
        t_a2 = t_c + delay_s  # propagation feedback arrives back at A

        events["A"].append(_create_event("A", t_a1))
        events["B"].append(_create_event("B", t_b))
        events["C"].append(_create_event("C", t_c))
        events["A"].append(_create_event("A", t_a2))

    return BenchmarkScenario(
        scenario_id="scenario_3_ring",
        name="Feedback Ring (A -> B -> C -> A)",
        description=(
            "Cyclic feedback topology where A -> B -> C -> A propagates in closed loop "
            "with 50s delays per leg."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"cycle_period_s": cycle_period_s, "n_cycles": n_cycles},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 4. Negative Control: Independent Random Streams
# ---------------------------------------------------------------------------

def generate_negative_control_scenario(
    n_events_per_machine: int = 8,
    duration_s: float = 30000.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate negative-control scenario with independent Poisson-distributed events."""
    rng = random.Random(seed)
    machines = ["M1", "M2", "M3", "M4"]
    ground_truth_edges: List[Tuple[str, str]] = []
    injected_delays: Dict[Tuple[str, str], float] = {}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for m in machines:
        # Generate independent random event timestamps
        # Use spacing that avoids systematic cross-machine alignments
        offsets = sorted(rng.uniform(0.0, duration_s) for _ in range(n_events_per_machine))
        for t in offsets:
            events[m].append(_create_event(m, t))

    return BenchmarkScenario(
        scenario_id="scenario_4_negative_control",
        name="Negative Control (Independent Streams)",
        description=(
            "Four independent machines with randomly distributed events across 30,000s. "
            "Zero genuine cross-machine propagation edges exist."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"duration_s": duration_s, "n_events_per_machine": n_events_per_machine},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 5. Reversed Temporal Order
# ---------------------------------------------------------------------------

def generate_reversed_temporal_order_scenario(
    n_waves: int = 6,
    wave_interval_s: float = 2500.0,
    delay_s: float = 60.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate reversed temporal order scenario where target fires before source."""
    machines = ["A", "B"]
    # Ground-truth: NO valid forward propagation edge A -> B exists because B strictly precedes A
    ground_truth_edges: List[Tuple[str, str]] = []
    injected_delays: Dict[Tuple[str, str], float] = {("A", "B"): -delay_s}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_waves):
        t_b = k * wave_interval_s
        t_a = t_b + delay_s  # A fires AFTER B

        events["B"].append(_create_event("B", t_b))
        events["A"].append(_create_event("A", t_a))

    return BenchmarkScenario(
        scenario_id="scenario_5_reversed_order",
        name="Reversed Temporal Order (Target Precedes Source)",
        description=(
            "Machines A and B where machine B consistently fires 60s before A. "
            "Evaluates whether A -> B is rejected by temporal direction gating."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"wave_interval_s": wave_interval_s, "delay_s": -delay_s},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 6. Common Cause (Shared External Disturbance)
# ---------------------------------------------------------------------------

def generate_common_cause_scenario(
    n_events: int = 6,
    interval_s: float = 2500.0,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate common-cause scenario where multiple machines fire near-simultaneously."""
    machines = ["M1", "M2", "M3"]
    # Ground truth: no machine-to-machine propagation (all driven by external common disturbance)
    ground_truth_edges: List[Tuple[str, str]] = []
    injected_delays: Dict[Tuple[str, str], float] = {}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_events):
        t_disturb = k * interval_s
        # Near-simultaneous offsets within the 30s simultaneity window
        events["M1"].append(_create_event("M1", t_disturb + 0.0))
        events["M2"].append(_create_event("M2", t_disturb + 4.0))
        events["M3"].append(_create_event("M3", t_disturb + 7.0))

    return BenchmarkScenario(
        scenario_id="scenario_6_common_cause",
        name="Common Cause Disturbance (Shared Environmental Shock)",
        description=(
            "Three machines responding near-simultaneously (<10s delta) to shared external disturbances. "
            "Evaluates whether OC-CCD flags common-cause candidates and avoids false propagation claims."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"interval_s": interval_s, "simultaneity_window_s": 10.0},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 7. Noisy Scenario (Lag Jitter, Dropout, Spurious Events)
# ---------------------------------------------------------------------------

def generate_noisy_scenario(
    n_waves: int = 8,
    wave_interval_s: float = 2500.0,
    nominal_delay_ab_s: float = 65.0,
    nominal_delay_bc_s: float = 85.0,
    jitter_std_s: float = 6.0,
    dropout_prob: float = 0.15,
    n_spurious_per_machine: int = 3,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate noisy propagation scenario with lag jitter, dropouts, and spurious events."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)

    machines = ["A", "B", "C"]
    ground_truth_edges = [("A", "B"), ("B", "C")]
    injected_delays = {("A", "B"): nominal_delay_ab_s, ("B", "C"): nominal_delay_bc_s}

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}

    for k in range(n_waves):
        t_a = k * wave_interval_s
        # Sample jittered delays (ensuring delay > 5s)
        jitter_ab = float(np_rng.normal(0.0, jitter_std_s))
        jitter_bc = float(np_rng.normal(0.0, jitter_std_s))

        d_ab = max(5.0, nominal_delay_ab_s + jitter_ab)
        d_bc = max(5.0, nominal_delay_bc_s + jitter_bc)

        t_b = t_a + d_ab
        t_c = t_b + d_bc

        # Probabilistic dropout per wave
        if rng.random() >= dropout_prob:
            events["A"].append(_create_event("A", t_a))
        if rng.random() >= dropout_prob:
            events["B"].append(_create_event("B", t_b))
        if rng.random() >= dropout_prob:
            events["C"].append(_create_event("C", t_c))

    # Add random spurious noise events
    max_duration = n_waves * wave_interval_s
    for m in machines:
        for _ in range(n_spurious_per_machine):
            t_spur = rng.uniform(0.0, max_duration)
            events[m].append(_create_event(m, t_spur))
        events[m].sort(key=lambda e: e.onset_time)

    return BenchmarkScenario(
        scenario_id="scenario_7_noisy",
        name="Noisy Cascade (Jitter, Dropout, Spurious Events)",
        description=(
            f"Cascade chain A -> B -> C with Gaussian delay jitter (std={jitter_std_s}s), "
            f"{dropout_prob*100:.0f}% observation dropout probability, and spurious noise events."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={
            "jitter_std_s": jitter_std_s,
            "dropout_prob": dropout_prob,
            "n_spurious_per_machine": n_spurious_per_machine,
        },
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# 8. Coexisting Direct and Indirect Pathway: A -> B -> C and A -> C
# ---------------------------------------------------------------------------

def generate_coexisting_direct_indirect_scenario(
    n_waves: int = 6,
    wave_interval_s: float = 2500.0,
    delay_ab_s: float = 40.0,
    delay_bc_s: float = 50.0,
    delay_ac_direct_s: float = 30.0,
    scenario_id: Optional[str] = None,
    name: Optional[str] = None,
    seed: int = 42,
) -> BenchmarkScenario:
    """Generate scenario with coexisting direct (A -> C) and indirect (A -> B -> C) paths.

    Both the direct relationship A -> C and the two-hop indirect chain
    A -> B -> C represent genuine ground-truth propagation pathways.
    Crucial for testing that transitive-reduction filters do not naively discard
    genuine direct connections.
    """
    machines = ["A", "B", "C"]
    ground_truth_edges = [("A", "B"), ("B", "C"), ("A", "C")]
    injected_delays = {
        ("A", "B"): delay_ab_s,
        ("B", "C"): delay_bc_s,
        ("A", "C"): delay_ac_direct_s,
    }

    events: Dict[str, List[EventRecord]] = {m: [] for m in machines}
    for k in range(n_waves):
        t_a = k * wave_interval_s
        t_b = t_a + delay_ab_s
        t_c_direct = t_a + delay_ac_direct_s
        t_c_indirect = t_b + delay_bc_s

        events["A"].append(_create_event("A", t_a))
        events["B"].append(_create_event("B", t_b))
        events["C"].append(_create_event("C", t_c_direct))
        events["C"].append(_create_event("C", t_c_indirect))

    for m in machines:
        events[m].sort(key=lambda e: e.onset_time)

    sc_id = scenario_id or "scenario_coexisting_direct_indirect"
    sc_name = name or "Coexisting Direct & Indirect Cascade (A->B->C and A->C)"

    return BenchmarkScenario(
        scenario_id=sc_id,
        name=sc_name,
        description=(
            f"Dual-pathway scenario where A triggers B ({delay_ab_s}s), B triggers C ({delay_bc_s}s), "
            f"and A also directly triggers C ({delay_ac_direct_s}s). Both direct edge and multi-hop path are ground truth."
        ),
        machines=machines,
        ground_truth_edges=ground_truth_edges,
        injected_delays=injected_delays,
        events_by_machine=events,
        noise_params={"wave_interval_s": wave_interval_s, "n_waves": n_waves},
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# Benchmark Suite Generator
# ---------------------------------------------------------------------------

def generate_all_scenarios(seed: int = 42) -> List[BenchmarkScenario]:
    """Generate all 7 deterministic benchmark scenarios with a unified seed."""
    return [
        generate_chain_scenario(seed=seed),
        generate_branching_scenario(seed=seed + 1),
        generate_ring_scenario(seed=seed + 2),
        generate_negative_control_scenario(seed=seed + 3),
        generate_reversed_temporal_order_scenario(seed=seed + 4),
        generate_common_cause_scenario(seed=seed + 5),
        generate_noisy_scenario(seed=seed + 6),
    ]
