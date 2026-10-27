"""
TCMIM — Core schemas (dataclasses).

All entities defined here match Section 6 of the PRD v2.
Fields are intentionally typed strictly; add new fields by
extending the dataclass, not by overloading existing ones.

Provenance enum enforces the three-class separation mandated by
Section 2 and FR-DA-2 / FR-DA-5:
  - HARDWARE        — real sensor data from physical hardware
  - PUBLIC_DATASET  — publicly released research datasets (e.g. MetroPT-3)
  - SYNTHETIC       — programmatically generated test fixtures

INTEGRITY RULES (cannot be relaxed by downstream code):
  1. SYNTHETIC provenance data must never appear in real-result reports.
  2. Temporal precedence != causality; never label an edge as "causal".
  3. EdgeState "CONFIRMED" means repeated, consistent evidence — not causality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

class Provenance(str, Enum):
    """Provenance class for every artefact in the pipeline.

    Maps to FR-DA-2. The str mixin lets instances serialise directly to JSON.
    """
    HARDWARE = "hardware"
    PUBLIC_DATASET = "public_dataset"
    SYNTHETIC = "synthetic_fixture"


# ---------------------------------------------------------------------------
# Modality
# ---------------------------------------------------------------------------

class Modality(str, Enum):
    """Sensor modality identifier (FR-DA-4 / FR-FE-1..5)."""
    VIBRATION = "vibration"
    PRESSURE = "pressure"
    TEMPERATURE = "temperature"
    CURRENT = "current"
    FLOW_PULSE = "flow_pulse"
    DIGITAL_STATE = "digital_state"
    ROTATION = "rotation"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# S0 — Raw acquisition
# ---------------------------------------------------------------------------

@dataclass
class SensorSample:
    """A single validated sensor reading (S0 output).

    Attributes
    ----------
    machine_id  : Logical machine identifier (e.g. "compressor_A").
    channel     : Physical channel name (e.g. "TP2", "Motor_current").
    modality    : Sensor modality.
    timestamp   : UTC timestamp of the measurement.
    value       : Scalar sensor reading (engineering units).
    provenance  : Provenance class (must never be mixed in reports).
    source_id   : Trace back to the originating file / serial session.
    sample_id   : Auto-generated UUID for deduplication.
    """
    machine_id: str
    channel: str
    modality: Modality
    timestamp: datetime
    value: float
    provenance: Provenance
    source_id: str
    sample_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.modality, Modality):
            self.modality = Modality(self.modality)
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)


# ---------------------------------------------------------------------------
# S2 — Features
# ---------------------------------------------------------------------------

@dataclass
class FeatureSample:
    """Feature vector for a single channel over one time window (S2 output).

    Attributes
    ----------
    machine_id   : Logical machine identifier.
    channel      : Physical channel name.
    modality     : Sensor modality.
    window_start : Start of the time window (inclusive).
    window_end   : End of the time window (exclusive).
    features     : Mapping from feature name to numeric value.
    provenance   : Must match the provenance of the raw samples used.
    feature_id   : Auto-generated UUID.
    """
    machine_id: str
    channel: str
    modality: Modality
    window_start: datetime
    window_end: datetime
    features: Dict[str, float]
    provenance: Provenance
    feature_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.modality, Modality):
            self.modality = Modality(self.modality)
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if self.window_end <= self.window_start:
            raise ValueError(
                f"window_end ({self.window_end}) must be after "
                f"window_start ({self.window_start})"
            )


@dataclass
class MultimodalFeatureSample:
    """Aggregated features across all modalities for one machine window.

    Attributes
    ----------
    machine_id   : Logical machine identifier.
    window_start : Start of the time window.
    window_end   : End of the time window.
    features     : {modality_name: {feature_name: value}}.
    provenance   : Provenance class.
    sample_id    : Auto-generated UUID.
    """
    machine_id: str
    window_start: datetime
    window_end: datetime
    features: Dict[str, Dict[str, float]]   # modality → feature_name → value
    provenance: Provenance
    sample_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if self.window_end <= self.window_start:
            raise ValueError(
                f"window_end ({self.window_end}) must be after "
                f"window_start ({self.window_start})"
            )


# ---------------------------------------------------------------------------
# S3 — Health
# ---------------------------------------------------------------------------

@dataclass
class HealthSample:
    """Normalised local health indicator for one machine window (S3 output).

    health_score is in [0.0, 1.0] where 1.0 = perfectly normal.
    The exact mapping from z-score to health_score is fixed and
    documented at M3 design review.

    Attributes
    ----------
    machine_id    : Logical machine identifier.
    window_start  : Start of the evaluation window.
    window_end    : End of the evaluation window.
    health_score  : Normalised health [0, 1].
    z_scores      : Per-feature z-scores used.
    provenance    : Must not be SYNTHETIC in real reports.
    baseline_id   : Reference to the baseline used.
    sample_id     : Auto-generated UUID.
    """
    machine_id: str
    window_start: datetime
    window_end: datetime
    health_score: float
    z_scores: Dict[str, float]
    provenance: Provenance
    baseline_id: str
    sample_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not (0.0 <= self.health_score <= 1.0):
            raise ValueError(
                f"health_score must be in [0, 1], got {self.health_score}"
            )


# ---------------------------------------------------------------------------
# S4 — Events
# ---------------------------------------------------------------------------

@dataclass
class EventRecord:
    """Onset of sustained abnormal behaviour (S4 output).

    Detection is explicitly non-causal: it marks when a change was
    first detected, not when it originated.

    Attributes
    ----------
    machine_id   : Machine where the event was detected.
    modality     : Modality of the originating signal.
    onset_time   : Timestamp of the event onset (window_start of first anomaly).
    detector     : Name of the detector used (e.g. "cusum", "isolation_forest").
    score        : Detector score at onset (or peak anomalous score).
    provenance   : Provenance class.
    end_time     : Optional end timestamp of the anomalous burst.
    window_count : Number of anomalous windows forming this burst (>= 1).
    event_id     : Auto-generated UUID.
    """
    machine_id: str
    modality: Modality
    onset_time: datetime
    detector: str
    score: float
    provenance: Provenance
    end_time: Optional[datetime] = None
    window_count: int = 1
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.modality, Modality):
            self.modality = Modality(self.modality)
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if self.end_time is not None and self.end_time < self.onset_time:
            raise ValueError(
                f"end_time ({self.end_time}) cannot be earlier than "
                f"onset_time ({self.onset_time})"
            )
        if self.window_count < 1:
            raise ValueError(
                f"window_count must be at least 1, got {self.window_count}"
            )


# ---------------------------------------------------------------------------
# S5–S6 — Event matching and delay
# ---------------------------------------------------------------------------

@dataclass
class PropagationObservation:
    """One candidate event pair across two machines (S5–S6 output).

    Attributes
    ----------
    obs_id        : Auto-generated UUID.
    source_event  : EventRecord ID of the earlier event.
    target_event  : EventRecord ID of the later event.
    source_machine: Machine ID of the source event.
    target_machine: Machine ID of the target event.
    delta_t_s     : t_target_onset − t_source_onset in seconds.
    gate_result   : "accepted" or "rejected".
    reject_reason : Human-readable reason if rejected; None if accepted.
    provenance    : Provenance class (from source event).
    """
    source_event: str        # EventRecord.event_id
    target_event: str        # EventRecord.event_id
    source_machine: str
    target_machine: str
    delta_t_s: float         # Δt = t_B − t_A in seconds
    gate_result: str         # "accepted" | "rejected"
    reject_reason: Optional[str]
    provenance: Provenance
    obs_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    structural_mask_status: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if self.gate_result not in ("accepted", "rejected"):
            raise ValueError(
                f"gate_result must be 'accepted' or 'rejected', "
                f"got '{self.gate_result}'"
            )


@dataclass
class DelayStatistics:
    """Aggregated delay statistics for a machine pair (S6 output).

    Attributes
    ----------
    source_machine : Machine ID of the source.
    target_machine : Machine ID of the target.
    n              : Number of accepted observations.
    mean_s         : Mean delay in seconds.
    std_s          : Standard deviation of delay.
    min_s          : Minimum observed delay.
    max_s          : Maximum observed delay.
    direction_consistency : Fraction of observations with Δt > 0.
    provenance     : Provenance class.
    stats_id       : Auto-generated UUID.
    """
    source_machine: str
    target_machine: str
    n: int
    mean_s: float
    std_s: float
    min_s: float
    max_s: float
    direction_consistency: float   # in [0, 1]
    provenance: Provenance
    stats_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    median_s: Optional[float] = None
    trimmed_mean_s: Optional[float] = None
    estimator: str = "mean"
    estimated_delay_s: Optional[float] = None
    trim_proportion: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not (0.0 <= self.direction_consistency <= 1.0):
            raise ValueError(
                f"direction_consistency must be in [0, 1], "
                f"got {self.direction_consistency}"
            )
        if self.estimated_delay_s is None:
            self.estimated_delay_s = self.mean_s


# ---------------------------------------------------------------------------
# S9 — Edge lifecycle
# ---------------------------------------------------------------------------

class EdgeState(str, Enum):
    """Deterministic 8-state edge lifecycle (FR-EL-1).

    Transitions are driven by evidence counts / consistency, never by a
    single observation. States are ordered conceptually; transitions are
    governed by configurable thresholds, not by this ordering.
    """
    NONE = "NONE"
    CANDIDATE = "CANDIDATE"
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    STRENGTHENING = "STRENGTHENING"
    STABLE = "STABLE"
    WEAKENING = "WEAKENING"
    EXPIRED = "EXPIRED"
    UNEXCITED_PRIOR = "UNEXCITED_PRIOR"


@dataclass
class EdgeRecord:
    """A directed propagation edge in the dynamic graph (S9 output).

    CONFIRMED means repeated, consistent evidence — NOT causality.
    See integrity rule 3.

    Attributes
    ----------
    source       : Source machine ID.
    target       : Target machine ID.
    state        : Current edge lifecycle state.
    evidence_count: Number of accepted observations supporting this edge.
    est_delay_s  : Estimated mean delay in seconds.
    confidence   : Evidence-derived confidence score in [0, 1].
    last_updated : Timestamp of last state change.
    modality     : Modality of the underlying events.
    provenance   : Provenance class.
    edge_id      : Auto-generated UUID.
    is_unexcited_actuator : True if edge originates from an unexcited actuator.
    baseline_identifiability: Categorical identifiability status.
    structural_prior_weight : Design prior weight W_prior (default 0.5).
    """
    source: str
    target: str
    state: EdgeState
    evidence_count: int
    est_delay_s: float
    confidence: float
    last_updated: datetime
    modality: Modality
    provenance: Provenance
    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    is_unexcited_actuator: bool = False
    baseline_identifiability: str = "IDENTIFIABLE"
    structural_prior_weight: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.state, EdgeState):
            self.state = EdgeState(self.state)
        if not isinstance(self.modality, Modality):
            self.modality = Modality(self.modality)
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be in [0, 1], got {self.confidence}"
            )


# ---------------------------------------------------------------------------
# S10 — Graph state
# ---------------------------------------------------------------------------

@dataclass
class PropagationGraphState:
    """Snapshot of the directed propagation graph at a point in time (S10).

    Attributes
    ----------
    timestamp : When this snapshot was taken.
    nodes     : List of machine IDs present in the graph.
    edges     : List of EdgeRecords with current states.
    version   : Monotonically increasing integer snapshot version.
    provenance: Provenance class (must match all constituent edges).
    """
    timestamp: datetime
    nodes: List[str]
    edges: List[EdgeRecord]
    version: int
    provenance: Provenance
    graph_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    min_active_state: EdgeState = EdgeState.CANDIDATE
    filtered_edges: List[EdgeRecord] = field(default_factory=list)
    transitive_edges: List[EdgeRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not isinstance(self.min_active_state, EdgeState):
            self.min_active_state = EdgeState(self.min_active_state)


# ---------------------------------------------------------------------------
# S12 — CRI
# ---------------------------------------------------------------------------

@dataclass
class CRIRecord:
    """Cascade Risk Index for a target node (S12 output).

    CRI is a deterministic, evidence-based index — NOT a validated
    predictor. See FR-CRI-2 and integrity rules.

    Attributes
    ----------
    timestamp      : When the CRI was computed.
    target_machine : Machine for which CRI is computed.
    cri            : Cascade Risk Index value in [0, 1].
    contributions  : Breakdown of CRI components.
    paths_used     : List of path descriptions contributing to CRI.
    provenance     : Must not be SYNTHETIC in real reports.
    record_id      : Auto-generated UUID.
    cri_status     : "VALIDATED_EMPIRICAL" or "UNCERTAIN_UNEXCITED".
    unexcited_sources : List of unexcited actuator IDs present in upstream paths.
    """
    timestamp: datetime
    target_machine: str
    cri: float
    contributions: Dict[str, float]
    paths_used: List[str]
    provenance: Provenance
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cri_status: str = "VALIDATED_EMPIRICAL"
    unexcited_sources: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not (0.0 <= self.cri <= 1.0):
            raise ValueError(f"cri must be in [0, 1], got {self.cri}")


# ---------------------------------------------------------------------------
# ML Stage 1 — Anomaly detection output
# ---------------------------------------------------------------------------

@dataclass
class AnomalyRecord:
    """Output of an unsupervised anomaly detector for one time window (ML-S1).

    INTEGRITY NOTE (consistent with FR-CRI-2 and Section 2 rule 1):
    ``is_anomaly = True`` means the window is statistically unusual relative
    to the fitted baseline.  It is NOT a confirmed machine failure.  Physical
    validation is required before any failure claim can be made.

    Attributes
    ----------
    timestamp    : window_start of the evaluated window (UTC).
    machine_id   : Logical machine identifier.
    anomaly_score: Detector-native score.
                   - IsolationForest : sklearn decision_function output.
                     Negative values are more anomalous; threshold ≈ 0.0.
                   - CUSUM           : S_t statistic (higher = more anomalous).
    is_anomaly   : True when the score passes the detector's alarm threshold.
    detector     : Identifier string, e.g. ``"isolation_forest"`` or
                   ``"cusum_health"``.
    provenance   : Provenance of the underlying feature data used.
                   Must not be SYNTHETIC in real-data reports.
    window_end   : End of the evaluated window (exclusive), optional.
    record_id    : Auto-generated UUID for deduplication.
    """
    timestamp: datetime          # = window_start of the scored window
    machine_id: str
    anomaly_score: float
    is_anomaly: bool
    detector: str
    provenance: Provenance
    window_end: Optional[datetime] = None
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if not isinstance(self.anomaly_score, float):
            self.anomaly_score = float(self.anomaly_score)


# ---------------------------------------------------------------------------
# Physical validation
# ---------------------------------------------------------------------------

@dataclass
class GroundTruthRecord:
    """Ground truth for a physical testbed experiment (M9 onward).

    Used only in VAL-tier evaluation; never generated synthetically.

    Attributes
    ----------
    experiment_id   : Matches ExperimentResult.experiment_id.
    source_machine  : Machine where disturbance was injected.
    target_machine  : Machine expected to show a response.
    coupling_type   : Physical coupling mechanism description.
    injected_events : Description of injected disturbances.
    ground_truth_source: Who/what recorded the ground truth.
    record_id       : Auto-generated UUID.
    """
    experiment_id: str
    source_machine: str
    target_machine: str
    coupling_type: str
    injected_events: List[Dict[str, Any]]
    ground_truth_source: str
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ExperimentResult:
    """Result of one physical experiment (M9–M10).

    Attributes
    ----------
    experiment_id : Unique identifier matching GroundTruthRecord.
    config        : Experiment configuration dictionary.
    metrics       : Computed metrics dictionary.
    provenance    : Always HARDWARE for physical experiments.
    status        : Status ladder value (PLANNED / IMPL / TEST / EXEC / VAL).
    notes         : Free-text observations (include negative results).
    result_id     : Auto-generated UUID.
    """
    experiment_id: str
    config: Dict[str, Any]
    metrics: Dict[str, float]
    provenance: Provenance
    status: str          # matches status ladder
    notes: str
    result_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        valid_statuses = {"PLANNED", "IMPL", "TEST", "EXEC", "VAL"}
        if self.status not in valid_statuses:
            raise ValueError(
                f"status must be one of {valid_statuses}, got '{self.status}'"
            )
