"""
dashboard/backend.py
====================
TCMIM Two-Node Research Dashboard Backend Engine.

Encapsulates headless, testable workflows for:
1. Telemetry ingestion (SWaT testbed, synthetic scenarios, user CSVs).
2. Independent anomaly detection at Node A and Node B.
3. Cross-node propagation analysis (Gate G0, Operating-State Resolver, Gate G1, Gate G2, OC-CCD).
4. Status classification into research-grade presentation labels.
5. Experiment serialization and export.

SCIENTIFIC INTEGRITY SAFEGUARDS:
- Node B is evaluated strictly independently of Node A.
- Actual model scores and thresholds are displayed; no probabilities are fabricated.
- Operating state S3 for P301 -> DPIT301 remains strictly quarantined.
- P101 -> FIT101 is strictly disallowed by Gate G0.
- Mandatory disclaimer: "Temporal association alone does not constitute mathematical proof of causal propagation."
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

# Add project root and experiments to path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_project_root / "src") not in sys.path:
    sys.path.insert(0, str(_project_root / "src"))
if str(_project_root / "experiments") not in sys.path:
    sys.path.insert(0, str(_project_root / "experiments"))

from tcmim.data.swat_a4a5 import (
    A4A5_ACTUATOR_STATE_MAP,
    A4A5_MODALITY_MAP,
    SWAT_DEFAULT_ACTUATOR_STATE_MAP,
    SWAT_TAG_REGISTRY,
    SWaTTagType,
    load_swat_a4a5_dataframe,
)
from tcmim.data.validator import validate_dataframe
from tcmim.data.windower import WindowBuilder, WindowedData
from tcmim.events.cusum import CUSUMDetector
from tcmim.features.extractor import FeatureExtractor
from tcmim.gating.gates import GateOutcome, GatingConfig, gate_delay_feasibility, gate_ordering
from tcmim.gating.structural_mask import PhysicalStructuralMask, StructuralStatus
from tcmim.ml.anomaly_detector import IsolationForestAnomalyDetector
from tcmim.ml.event_adapter import AnomalyToEventAdapter, EventAdapterConfig
from tcmim.propagation.matcher import EventMatcher
from tcmim.propagation.occ_ccd import OCCCDAnalyser, OCCCDConfig
from tcmim.schemas import (
    AnomalyRecord,
    EventRecord,
    Modality,
    MultimodalFeatureSample,
    PropagationObservation,
    Provenance,
)

# Import Stage 4 operating state resolver from experimental evaluation layer
try:
    from stage4_experimental_gating import (
        OperatingRegime,
        OperatingStateResolver,
        RegimeResolutionResult,
        StateAwareExperimentalGatingPipeline,
    )
except ImportError:
    # Fallback import using full module path if run from subdirectories
    from experiments.stage4_experimental_gating import (
        OperatingRegime,
        OperatingStateResolver,
        RegimeResolutionResult,
        StateAwareExperimentalGatingPipeline,
    )

logger = logging.getLogger(__name__)

MANDATORY_DISCLAIMER: str = (
    "Temporal association alone does not constitute mathematical proof of causal propagation. "
    "Demonstration conducted under bounded experimental protocols without claiming plantwide propagation."
)


# ---------------------------------------------------------------------------
# Status and Data Models
# ---------------------------------------------------------------------------

class PresentationStatus(str, Enum):
    """Authoritative dashboard presentation statuses."""
    NORMAL = "NORMAL"
    ANOMALY_AT_NODE_A = "ANOMALY_AT_NODE_A"
    ANOMALY_AT_NODE_B = "ANOMALY_AT_NODE_B"
    BOTH_NODES_ANOMALOUS = "BOTH_NODES_ANOMALOUS"
    TEMPORAL_ASSOCIATION_OBSERVED = "TEMPORAL_ASSOCIATION_OBSERVED"
    RESPONSE_POSSIBLE = "RESPONSE_POSSIBLE"
    RESPONSE_OBSERVED = "RESPONSE_OBSERVED"
    RELATIONSHIP_SUPPORTED = "RELATIONSHIP_SUPPORTED"
    UNCONFIRMED = "UNCONFIRMED"
    UNKNOWN = "UNKNOWN"


@dataclass
class NodeTelemetry:
    """Standardized node telemetry container."""
    node_id: str
    timestamps: List[datetime]
    values: np.ndarray
    provenance: Provenance
    sampling_interval_s: float
    channel_name: str
    quality: str = "GOOD"
    is_stale: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dataframe(self) -> pd.DataFrame:
        """Convert telemetry to DataFrame indexed by timestamp."""
        return pd.DataFrame(
            {self.channel_name: self.values},
            index=pd.to_datetime(self.timestamps),
        )


@dataclass
class NodeDetectionResult:
    """Detailed detection result for a single node."""
    node_id: str
    detector_name: str
    timestamps: List[datetime]
    raw_values: List[float]
    anomaly_scores: List[float]
    threshold: float
    is_anomaly: List[bool]
    anomalous_count: int
    event_records: List[EventRecord]
    first_onset_time: Optional[datetime]
    summary: str
    detector_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GateStepOutcome:
    """Step-by-step audit record for cross-node gating checks."""
    gate_name: str
    passed: bool
    status: str  # e.g., "PASSED", "REJECTED", "QUARANTINED", "NOT_APPLICABLE"
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrossNodeAnalysisResult:
    """Complete evaluation report for the candidate pair."""
    source_node: str
    target_node: str
    source_event: Optional[EventRecord]
    target_event: Optional[EventRecord]
    delta_t_s: Optional[float]
    gate_steps: List[GateStepOutcome]
    overall_status: PresentationStatus
    is_eligible_for_evaluation: bool
    is_supported_relationship: bool
    explanation: str
    scientific_disclaimer: str = MANDATORY_DISCLAIMER
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Telemetry Ingestion Helpers
# ---------------------------------------------------------------------------

def get_channel_modality_and_state_map(
    channel_name: str,
) -> Tuple[Modality, Optional[Dict[float, int]]]:
    """Resolve channel modality and actuator state mapping using authoritative registries."""
    clean_name = channel_name.strip()
    if clean_name in A4A5_MODALITY_MAP:
        mod = A4A5_MODALITY_MAP[clean_name]
        st_map = A4A5_ACTUATOR_STATE_MAP.get(clean_name)
        return mod, st_map
    if clean_name in SWAT_TAG_REGISTRY:
        info = SWAT_TAG_REGISTRY[clean_name]
        if info.tag_type == SWaTTagType.ACTUATOR:
            return Modality.DIGITAL_STATE, SWAT_DEFAULT_ACTUATOR_STATE_MAP
        return info.modality, None
    if clean_name.startswith(("MV", "P", "UV")):
        return Modality.DIGITAL_STATE, SWAT_DEFAULT_ACTUATOR_STATE_MAP
    return Modality.PRESSURE, None


def load_swat_node_telemetry(
    node_id: str,
    max_rows: Optional[int] = 1500,
    start_row: int = 0,
) -> NodeTelemetry:
    """Load real telemetry for a specific SWaT sensor/actuator tag."""
    wb_path = _project_root / "data" / "raw" / "SWAT_A4_A5_JULY_2019" / "SWaT_dataset_Jul 19 v2.xlsx"
    if not wb_path.is_file():
        raise FileNotFoundError(f"SWaT dataset workbook not found at: {wb_path}")

    # Load dataframe using validated loader
    df, meta = load_swat_a4a5_dataframe(wb_path, max_rows=max_rows + start_row if max_rows else None)

    if start_row > 0:
        df = df.iloc[start_row:].copy()
    if max_rows is not None and len(df) > max_rows:
        df = df.iloc[:max_rows].copy()

    clean_id = node_id.strip()
    if clean_id not in df.columns:
        raise ValueError(
            f"Tag '{clean_id}' not found in SWaT workbook. Available columns: {list(df.columns[:15])}..."
        )

    ts_list = [
        t.floor("us").to_pydatetime()
        if hasattr(t, "floor")
        else (t.to_pydatetime() if hasattr(t, "to_pydatetime") else t)
        for t in df.index
    ]
    vals = df[clean_id].astype(float).to_numpy()

    return NodeTelemetry(
        node_id=clean_id,
        timestamps=ts_list,
        values=vals,
        provenance=Provenance.PUBLIC_DATASET,
        sampling_interval_s=1.0,
        channel_name=clean_id,
        metadata={"source": "SWaT_dataset_Jul 19 v2.xlsx", "rows": len(vals)},
    )


def load_synthetic_benchmark_telemetry(
    scenario_id: str = "scenario_1_chain",
    node_id: str = "Node_A",
    n_samples: int = 300,
    sampling_interval_s: float = 1.0,
) -> NodeTelemetry:
    """Generate controlled synthetic telemetry for benchmarking."""
    np.random.seed(42 if node_id == "Node_A" else 43)
    base_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_list = [base_time + timedelta(seconds=i * sampling_interval_s) for i in range(n_samples)]

    # Generate nominal baseline with an anomaly burst
    vals = np.random.normal(loc=10.0, scale=0.5, size=n_samples)

    if scenario_id == "scenario_1_chain":
        if node_id == "Node_A":
            # Anomaly starts at t=50s
            vals[50:90] += 4.5
        elif node_id == "Node_B":
            # Response follows at t=65s (delay = 15s)
            vals[65:105] += 3.8
    elif scenario_id == "scenario_4_negative_control":
        if node_id == "Node_A":
            vals[50:90] += 4.5
        # Node_B has NO response (uncoupled negative control)
    elif scenario_id == "scenario_5_reversed":
        if node_id == "Node_A":
            vals[70:110] += 4.5
        elif node_id == "Node_B":
            # Target fires BEFORE source (t=30s)
            vals[30:70] += 3.8

    return NodeTelemetry(
        node_id=node_id,
        timestamps=ts_list,
        values=vals,
        provenance=Provenance.SYNTHETIC,
        sampling_interval_s=sampling_interval_s,
        channel_name=f"{node_id}_val",
        metadata={"scenario_id": scenario_id},
    )


def load_user_csv_telemetry(
    file_content: Union[str, bytes],
    node_id: str,
    value_column: Optional[str] = None,
    timestamp_column: Optional[str] = None,
) -> NodeTelemetry:
    """Parse and validate user-supplied CSV telemetry with strict schema checks."""
    if isinstance(file_content, bytes):
        df_raw = pd.read_csv(io.BytesIO(file_content))
    else:
        df_raw = pd.read_csv(io.StringIO(file_content))

    if len(df_raw) < 5:
        raise ValueError(f"CSV contains insufficient data rows ({len(df_raw)} < 5).")

    # Locate timestamp or sample index column
    ts_col = timestamp_column
    if ts_col is None:
        for c in df_raw.columns:
            if c.lower() in ("timestamp", "datetime", "time", "date", "ts", "gmt +0"):
                ts_col = c
                break

    if ts_col is not None and ts_col in df_raw.columns:
        try:
            ts_series = pd.to_datetime(df_raw[ts_col], utc=True)
            ts_list = [t.to_pydatetime() for t in ts_series]
        except Exception:
            # Fallback to synthetic timestamps if timestamp parsing fails
            base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            ts_list = [base_t + timedelta(seconds=i) for i in range(len(df_raw))]
    else:
        # Sample index mode
        base_t = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts_list = [base_t + timedelta(seconds=i) for i in range(len(df_raw))]

    # Locate value column
    val_col = value_column
    if val_col is None or val_col not in df_raw.columns:
        numeric_cols = [c for c in df_raw.columns if c != ts_col and pd.api.types.is_numeric_dtype(df_raw[c])]
        if not numeric_cols:
            raise ValueError("No numeric telemetry columns found in the uploaded CSV.")
        val_col = numeric_cols[0]

    vals = pd.to_numeric(df_raw[val_col], errors="coerce").ffill().fillna(0.0).to_numpy(dtype=float)

    # Calculate nominal sampling interval
    dt_s = 1.0
    if len(ts_list) > 1:
        diffs = [(ts_list[i+1] - ts_list[i]).total_seconds() for i in range(min(50, len(ts_list)-1))]
        pos_diffs = [d for d in diffs if d > 0]
        if pos_diffs:
            dt_s = float(np.median(pos_diffs))

    return NodeTelemetry(
        node_id=node_id,
        timestamps=ts_list,
        values=vals,
        provenance=Provenance.PUBLIC_DATASET,
        sampling_interval_s=dt_s,
        channel_name=str(val_col),
        metadata={"user_uploaded": True, "value_column": val_col},
    )


# ---------------------------------------------------------------------------
# Independent Node Detection Pipeline
# ---------------------------------------------------------------------------

def run_node_detection(
    telemetry: NodeTelemetry,
    detector_type: str = "isolation_forest",
    contamination: float = 0.05,
    threshold: float = 0.0,
    cusum_k: float = 0.5,
    cusum_h: float = 5.0,
    window_size: int = 30,
    step_size: int = 10,
    baseline_fraction: float = 0.2,
) -> NodeDetectionResult:
    """Run independent anomaly detection on a single node's telemetry.

    Parameters
    ----------
    telemetry         : Single-node telemetry.
    detector_type     : 'isolation_forest' or 'cusum'.
    contamination     : Expected proportion of outliers for Isolation Forest.
    threshold         : Anomaly score threshold (IF: score < threshold is anomalous).
    cusum_k           : CUSUM reference slack value.
    cusum_h           : CUSUM decision boundary threshold.
    window_size       : Sliding window length in samples.
    step_size         : Window step stride in samples.
    baseline_fraction : Fraction of windows used for baseline fitting.

    Returns
    -------
    NodeDetectionResult with chronological anomaly scores and EventRecords.
    """
    n_points = len(telemetry.values)
    if n_points < 10:
        raise ValueError(f"Insufficient telemetry length ({n_points} < 10) for node {telemetry.node_id}.")

    node_modality, state_mapping = get_channel_modality_and_state_map(telemetry.channel_name)

    if detector_type == "cusum":
        # Two-sided CUSUM sequential degradation detector
        n_base = max(5, int(n_points * baseline_fraction))
        base_vals = telemetry.values[:n_base]
        mu = float(np.mean(base_vals))
        sigma = float(np.std(base_vals))
        if sigma < 1e-12:
            sigma = 1.0

        # Standardize signal
        z = (telemetry.values - mu) / sigma

        s_pos = 0.0
        s_neg = 0.0
        scores = []
        alarms_idx = []
        for i, val in enumerate(z):
            s_pos = max(0.0, s_pos + val - cusum_k)
            s_neg = max(0.0, s_neg - val - cusum_k)
            s_max = max(s_pos, s_neg)
            scores.append(s_max)
            if s_max > cusum_h:
                alarms_idx.append(i)
                s_pos = 0.0
                s_neg = 0.0

        is_anom = [False] * n_points
        for idx in alarms_idx:
            if idx < n_points:
                is_anom[idx] = True

        event_records: List[EventRecord] = []
        if len(alarms_idx) > 0:
            first_idx = alarms_idx[0]
            last_idx = alarms_idx[-1]
            first_onset = telemetry.timestamps[first_idx]
            event_records.append(
                EventRecord(
                    machine_id=telemetry.node_id,
                    modality=node_modality,
                    onset_time=first_onset,
                    detector="cusum",
                    score=float(scores[first_idx]),
                    provenance=telemetry.provenance,
                    end_time=telemetry.timestamps[last_idx],
                    window_count=len(alarms_idx),
                    event_id=f"EVT_{telemetry.node_id}_{first_idx}",
                )
            )
        else:
            first_onset = None

        return NodeDetectionResult(
            node_id=telemetry.node_id,
            detector_name="cusum",
            timestamps=telemetry.timestamps,
            raw_values=telemetry.values.tolist(),
            anomaly_scores=scores,
            threshold=cusum_h,
            is_anomaly=is_anom,
            anomalous_count=int(sum(is_anom)),
            event_records=event_records,
            first_onset_time=first_onset,
            summary=f"CUSUM detected {len(alarms_idx)} alarms (first onset: {first_onset})",
            detector_metadata={"k": cusum_k, "h": cusum_h, "mu": mu, "sigma": sigma},
        )

    # Default: Isolation Forest Detector
    df_node = telemetry.to_dataframe()
    w_secs = max(1.0, float(window_size * telemetry.sampling_interval_s))
    step_secs = max(1.0, float(step_size * telemetry.sampling_interval_s))
    overlap = max(0.0, min(0.9, 1.0 - (step_secs / w_secs)))

    builder = WindowBuilder(
        window_seconds=w_secs,
        overlap_frac=overlap,
    )
    windows = builder.build(df_node, machine_id=telemetry.node_id, provenance=telemetry.provenance)

    if len(windows) < 5:
        # If too few windows, build point-wise synthetic windows
        w_size = max(2, min(window_size, n_points // 4))
        windows = []
        for i in range(0, n_points - w_size + 1, step_size):
            sub_df = df_node.iloc[i : i + w_size]
            windows.append(
                WindowedData(
                    window_id=f"W_{telemetry.node_id}_{i}",
                    window_start=sub_df.index[0].to_pydatetime(),
                    window_end=sub_df.index[-1].to_pydatetime(),
                    machine_id=telemetry.node_id,
                    data=sub_df,
                    provenance=telemetry.provenance,
                )
            )

    extraction_modality = Modality.PRESSURE if node_modality == Modality.UNKNOWN else node_modality
    extractor = FeatureExtractor(
        sampling_rate_hz=1.0 / telemetry.sampling_interval_s,
        channel_modality_map={telemetry.channel_name: extraction_modality},
        channel_state_map={telemetry.channel_name: state_mapping} if state_mapping else None,
    )
    feature_samples = extractor.extract_all(windows)

    if not feature_samples:
        raise ValueError(f"Feature extraction yielded 0 samples for node {telemetry.node_id}.")

    detector = IsolationForestAnomalyDetector(
        contamination=contamination,
        baseline_frac=baseline_fraction,
        threshold=threshold,
        min_baseline_windows=max(2, min(5, int(len(feature_samples) * baseline_fraction))),
        random_state=42,
    )

    try:
        anomaly_records = detector.fit(feature_samples).predict_score(feature_samples)

        # Adapt window-level anomalies to discrete EventRecords
        adapter = AnomalyToEventAdapter(
            config=EventAdapterConfig(
                min_burst_windows=1,
                max_gap_s=300.0,
                score_aggregation="peak",
            )
        )
        event_records = adapter.adapt(anomaly_records)

        # Refine onset timestamp within anomalous windows to exact physical deviation onset
        if event_records:
            n_base = max(1, int(len(telemetry.values) * baseline_fraction))
            b_med = float(np.median(telemetry.values[:n_base]))
            b_std = float(np.std(telemetry.values[:n_base]))
            thresh_dev = max(1e-4, 3.0 * b_std) if b_std > 1e-12 else 1e-4

            refined_events: List[EventRecord] = []
            for ev in event_records:
                sub_indices = [
                    idx for idx, ts in enumerate(telemetry.timestamps)
                    if ev.onset_time <= ts <= (ev.end_time or ev.onset_time + timedelta(seconds=w_secs))
                ]
                dev_indices = [idx for idx in sub_indices if abs(telemetry.values[idx] - b_med) > thresh_dev]
                onset_ts = telemetry.timestamps[dev_indices[0]] if dev_indices else ev.onset_time
                refined_events.append(
                    EventRecord(
                        machine_id=ev.machine_id,
                        modality=ev.modality,
                        onset_time=onset_ts,
                        detector=ev.detector,
                        score=ev.score,
                        provenance=ev.provenance,
                        end_time=ev.end_time,
                        window_count=ev.window_count,
                        event_id=ev.event_id,
                    )
                )
            event_records = refined_events

        first_onset = event_records[0].onset_time if event_records else None
        eval_ts = [r.timestamp for r in anomaly_records]
        scores = [r.anomaly_score for r in anomaly_records]
        is_anoms = [r.is_anomaly for r in anomaly_records]

        return NodeDetectionResult(
            node_id=telemetry.node_id,
            detector_name="isolation_forest",
            timestamps=eval_ts,
            raw_values=[telemetry.values[min(i * step_size, n_points - 1)] for i in range(len(eval_ts))],
            anomaly_scores=scores,
            threshold=threshold,
            is_anomaly=is_anoms,
            anomalous_count=int(sum(is_anoms)),
            event_records=event_records,
            first_onset_time=first_onset,
            summary=(
                f"Isolation Forest flagged {sum(is_anoms)}/{len(anomaly_records)} windows "
                f"({len(event_records)} event bursts, first onset: {first_onset})"
            ),
            detector_metadata={
                "contamination": contamination,
                "threshold": threshold,
                "baseline_frac": baseline_fraction,
            },
        )
    except ValueError as exc:
        if "No valid features remain" in str(exc):
            if node_modality == Modality.DIGITAL_STATE:
                # Physical Actuator Transition Adapter:
                # Stationary discrete actuators naturally exhibit zero variance in the baseline.
                # Detect discrete departures/transitions from baseline state.
                n_base = max(1, int(len(telemetry.values) * baseline_fraction))
                base_state = float(np.median(telemetry.values[:n_base]))
                departures = np.abs(telemetry.values - base_state) > 1e-6
                dep_indices = np.where(departures)[0]
                first_idx = int(dep_indices[0]) if len(dep_indices) > 0 else None
                first_onset = telemetry.timestamps[first_idx] if first_idx is not None else None

                eval_ts = [w.window_start for w in windows]
                scores = []
                is_anoms = []
                for w in windows:
                    w_vals = w.data[telemetry.channel_name].dropna().to_numpy()
                    is_w_anom = np.any(np.abs(w_vals - base_state) > 1e-6)
                    is_anoms.append(bool(is_w_anom))
                    scores.append(-1.0 if is_w_anom else 0.5)

                event_records = []
                if first_idx is not None:
                    last_idx = int(dep_indices[-1])
                    event_records.append(
                        EventRecord(
                            machine_id=telemetry.node_id,
                            modality=Modality.DIGITAL_STATE,
                            onset_time=first_onset,
                            detector="actuator_state_transition",
                            score=-1.0,
                            provenance=telemetry.provenance,
                            end_time=telemetry.timestamps[last_idx],
                            window_count=int(sum(is_anoms)),
                            event_id=f"EVT_{telemetry.node_id}_{first_idx}",
                        )
                    )

                return NodeDetectionResult(
                    node_id=telemetry.node_id,
                    detector_name="actuator_state_transition",
                    timestamps=eval_ts,
                    raw_values=[telemetry.values[min(i * step_size, n_points - 1)] for i in range(len(eval_ts))],
                    anomaly_scores=scores,
                    threshold=0.0,
                    is_anomaly=is_anoms,
                    anomalous_count=int(sum(is_anoms)),
                    event_records=event_records,
                    first_onset_time=first_onset,
                    summary=(
                        f"Actuator {telemetry.node_id} (DIGITAL_STATE): stationary baseline state "
                        f"({base_state:.0f}) has zero variance; discrete state-transition detector adapted "
                        f"(first onset: {first_onset})."
                    ),
                    detector_metadata={
                        "baseline_state": base_state,
                        "adapter": "actuator_state_transition",
                        "reason": "zero_baseline_variance_actuator",
                    },
                )
            else:
                # Continuous sensor channel genuinely lacks usable features (flat / non-finite)
                raise ValueError(
                    f"Telemetry channel '{telemetry.channel_name}' has no usable features: all features in the "
                    f"chronological baseline split are constant or non-finite. Isolation Forest requires non-constant "
                    f"telemetry to construct splitting trees."
                )
        raise


# ---------------------------------------------------------------------------
# Cross-Node Response and Gating Evaluation
# ---------------------------------------------------------------------------

def evaluate_cross_node_relationship(
    source_result: NodeDetectionResult,
    target_result: NodeDetectionResult,
    operating_evidence: Optional[Dict[str, Any]] = None,
    is_user_data: bool = False,
    override_delay_bounds: Optional[Tuple[float, float]] = None,
) -> CrossNodeAnalysisResult:
    """Evaluate candidate propagation between Node A and Node B through TCMIM gates.

    Enforces:
    1. Independent detection check.
    2. Temporal delta estimation.
    3. Gate G0 (Physical Structural Mask).
    4. Operating-State Resolution (Fail-closed on unvalidated/quarantined regimes).
    5. Gate G1 (Delay feasibility).
    6. Gate G2 (Temporal ordering dt > 0).
    7. OC-CCD Common cause check.
    8. Authoritative status assignment.
    """
    src_id = source_result.node_id
    tgt_id = target_result.node_id
    gate_steps: List[GateStepOutcome] = []

    evt_a = source_result.event_records[0] if source_result.event_records else None
    evt_b = None
    if evt_a is not None and target_result.event_records:
        # Match candidate target burst covering or following source event
        candidates = [
            e for e in target_result.event_records
            if (e.end_time and e.end_time >= evt_a.onset_time) or e.onset_time >= evt_a.onset_time
        ]
        if candidates:
            matched_burst = candidates[0]
            t_b_onset = matched_burst.onset_time
            # If burst began before evt_a because of coarse windowing, resolve the actual response onset after evt_a
            if t_b_onset <= evt_a.onset_time and target_result.raw_values and len(target_result.timestamps) > 1:
                t_arr = target_result.timestamps
                v_arr = np.array(target_result.raw_values, dtype=float)
                after_mask = [ts >= evt_a.onset_time for ts in t_arr]
                if any(after_mask):
                    idx_start = after_mask.index(True)
                    base_v = float(np.median(v_arr[max(0, idx_start - 10):idx_start])) if idx_start > 0 else v_arr[0]
                    sub_v = v_arr[idx_start:min(len(v_arr), idx_start + 60)]
                    span_v = float(np.ptp(sub_v)) if len(sub_v) > 0 else 0.0
                    thresh_drop = max(1e-4, 0.10 * span_v)
                    dev_idx = np.where(np.abs(sub_v - base_v) >= thresh_drop)[0]
                    if len(dev_idx) > 0:
                        t_b_onset = t_arr[idx_start + int(dev_idx[0])]

            evt_b = EventRecord(
                machine_id=matched_burst.machine_id,
                modality=matched_burst.modality,
                onset_time=t_b_onset,
                detector=matched_burst.detector,
                score=matched_burst.score,
                provenance=matched_burst.provenance,
                end_time=matched_burst.end_time,
                window_count=matched_burst.window_count,
                event_id=matched_burst.event_id,
            )
        else:
            evt_b = target_result.event_records[0]
    elif target_result.event_records:
        evt_b = target_result.event_records[0]

    # Step 1: Check independent anomaly detections
    has_anom_a = source_result.anomalous_count > 0 and evt_a is not None
    has_anom_b = target_result.anomalous_count > 0 and evt_b is not None

    if not has_anom_a and not has_anom_b:
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=None,
            target_event=None,
            delta_t_s=None,
            gate_steps=[
                GateStepOutcome(
                    gate_name="DETECTION_STATUS",
                    passed=True,
                    status="NORMAL",
                    reason="Both Node A and Node B are operating within nominal baseline parameters.",
                )
            ],
            overall_status=PresentationStatus.NORMAL,
            is_eligible_for_evaluation=False,
            is_supported_relationship=False,
            explanation="Nominal operation across both observation points. No anomalies detected.",
        )

    if has_anom_a and not has_anom_b:
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=evt_a,
            target_event=None,
            delta_t_s=None,
            gate_steps=[
                GateStepOutcome(
                    gate_name="DETECTION_STATUS",
                    passed=False,
                    status="ANOMALY_AT_NODE_A",
                    reason=f"Anomaly detected at Node A ({src_id}), but Node B ({tgt_id}) shows no response.",
                )
            ],
            overall_status=PresentationStatus.ANOMALY_AT_NODE_A,
            is_eligible_for_evaluation=False,
            is_supported_relationship=False,
            explanation=f"Node A ({src_id}) produced an anomaly onset, but Node B ({tgt_id}) remained normal. No cascade response observed.",
        )

    if not has_anom_a and has_anom_b:
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=None,
            target_event=evt_b,
            delta_t_s=None,
            gate_steps=[
                GateStepOutcome(
                    gate_name="DETECTION_STATUS",
                    passed=False,
                    status="ANOMALY_AT_NODE_B",
                    reason=f"Anomaly detected at Node B ({tgt_id}), but Node A ({src_id}) is normal.",
                )
            ],
            overall_status=PresentationStatus.ANOMALY_AT_NODE_B,
            is_eligible_for_evaluation=False,
            is_supported_relationship=False,
            explanation=f"Node B ({tgt_id}) experienced an independent anomaly without antecedent activity at Node A ({src_id}).",
        )

    # Both nodes detected an anomaly
    assert evt_a is not None and evt_b is not None
    delta_t = (evt_b.onset_time - evt_a.onset_time).total_seconds()

    # Step 2: Gate G0 (Physical Structural Mask - evaluated first)
    # Established physical topology register
    swat_register = {
        "MV201": ["FIT201"],
        "P301": ["DPIT301"],
    }
    # Explicitly refuted pairs
    refuted_pairs = {("P101", "FIT101")}

    is_g0_allowed = False
    g0_status_code = "ALLOWED"

    if (src_id, tgt_id) in refuted_pairs:
        is_g0_allowed = False
        g0_status_code = "DISALLOWED"
        g0_reason = f"Physically REFUTED: Hydraulic edge {src_id} -> {tgt_id} is blocked by check valve/control logic."
    elif is_user_data:
        is_g0_allowed = False
        g0_status_code = "UNKNOWN"
        g0_reason = f"UNVALIDATED: User-provided relationship {src_id} -> {tgt_id} lacks a certified physical topology register."
    elif src_id in swat_register and tgt_id in swat_register[src_id]:
        is_g0_allowed = True
        g0_status_code = "ALLOWED"
        g0_reason = f"ALLOWED: Verified direct physical connection between {src_id} and {tgt_id}."
    elif "Node_A" in src_id and "Node_B" in tgt_id:
        # Synthetic benchmark pair
        is_g0_allowed = True
        g0_status_code = "ALLOWED"
        g0_reason = "ALLOWED: Ground-truth synthetic benchmark connection."
    else:
        is_g0_allowed = False
        g0_status_code = "UNKNOWN"
        g0_reason = f"UNKNOWN: No physical connectivity recorded for {src_id} -> {tgt_id} in plant register."

    gate_steps.append(
        GateStepOutcome(
            gate_name="GATE_G0_STRUCTURAL_MASK",
            passed=is_g0_allowed,
            status=g0_status_code,
            reason=g0_reason,
        )
    )

    if not is_g0_allowed:
        # Rejected fail-closed by Gate G0
        status_verdict = (
            PresentationStatus.UNKNOWN if g0_status_code == "UNKNOWN" else PresentationStatus.UNCONFIRMED
        )
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=evt_a,
            target_event=evt_b,
            delta_t_s=delta_t,
            gate_steps=gate_steps,
            overall_status=status_verdict,
            is_eligible_for_evaluation=False,
            is_supported_relationship=False,
            explanation=f"Temporal association observed (Δt = {delta_t:.2f}s), but physical connection was rejected by Gate G0 ({g0_reason}).",
        )

    # Step 3: Gate G2 (Temporal Ordering Gate)
    if delta_t <= 0.0:
        gate_steps.append(
            GateStepOutcome(
                gate_name="GATE_G2_ORDERING",
                passed=False,
                status="ORDERING_VIOLATION",
                reason=f"Temporal ordering violated: Node B onset ({evt_b.onset_time}) did not follow Node A ({evt_a.onset_time}). Δt = {delta_t:.2f}s <= 0.",
                details={"delta_t_s": delta_t},
            )
        )
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=evt_a,
            target_event=evt_b,
            delta_t_s=delta_t,
            gate_steps=gate_steps,
            overall_status=PresentationStatus.BOTH_NODES_ANOMALOUS,
            is_eligible_for_evaluation=False,
            is_supported_relationship=False,
            explanation=f"Both nodes are anomalous, but Node B alarmed simultaneously with or prior to Node A (Δt = {delta_t:.2f}s).",
        )

    gate_steps.append(
        GateStepOutcome(
            gate_name="GATE_G2_ORDERING",
            passed=True,
            status="PASSED",
            reason=f"Positive temporal order verified: Node B alarmed {delta_t:.2f}s after Node A.",
            details={"delta_t_s": delta_t},
        )
    )

    # Step 4: Operating-State Resolution (P301 -> DPIT301)
    effective_bounds = (1.0, 120.0)
    is_state_validated = True

    if src_id == "P301" and tgt_id == "DPIT301":
        # Resolve operating regime using Stage 4 OperatingStateResolver
        res = OperatingStateResolver.resolve(src_id, tgt_id, operating_evidence)
        if res.regime == OperatingRegime.STATE_S3_UNVALIDATED:
            gate_steps.append(
                GateStepOutcome(
                    gate_name="OPERATING_STATE_RESOLVER",
                    passed=False,
                    status="QUARANTINED",
                    reason=f"QUARANTINED_UNVALIDATED_REGIME: MV302==2 (OPEN). Permeate open startup lacks held-out validation.",
                    details={"regime": res.regime.value, "actuator": "MV302", "value": res.actuator_value},
                )
            )
            return CrossNodeAnalysisResult(
                source_node=src_id,
                target_node=tgt_id,
                source_event=evt_a,
                target_event=evt_b,
                delta_t_s=delta_t,
                gate_steps=gate_steps,
                overall_status=PresentationStatus.UNKNOWN,
                is_eligible_for_evaluation=False,
                is_supported_relationship=False,
                explanation="P301 -> DPIT301 observed in unvalidated State S3 (Attack A6 regime). Quarantined fail-closed from delay gating.",
            )
        elif res.regime == OperatingRegime.STATE_S2_NORMAL:
            effective_bounds = (5.0, 55.0)
            gate_steps.append(
                GateStepOutcome(
                    gate_name="OPERATING_STATE_RESOLVER",
                    passed=True,
                    status="STATE_S2_NORMAL",
                    reason="STATE_S2_NORMAL: MV302==1 (CLOSED). Validated startup regime with bound [5.0, 55.0]s.",
                    details={"regime": res.regime.value, "bounds": effective_bounds},
                )
            )
        else:
            gate_steps.append(
                GateStepOutcome(
                    gate_name="OPERATING_STATE_RESOLVER",
                    passed=False,
                    status="UNKNOWN_OPERATING_STATE",
                    reason=f"UNKNOWN_OPERATING_STATE: {res.reason}",
                    details={"regime": res.regime.value},
                )
            )
            return CrossNodeAnalysisResult(
                source_node=src_id,
                target_node=tgt_id,
                source_event=evt_a,
                target_event=evt_b,
                delta_t_s=delta_t,
                gate_steps=gate_steps,
                overall_status=PresentationStatus.UNKNOWN,
                is_eligible_for_evaluation=False,
                is_supported_relationship=False,
                explanation=f"Operating state could not be confirmed fail-closed ({res.reason}).",
            )
    elif src_id == "MV201" and tgt_id == "FIT201":
        effective_bounds = (1.0, 25.0)  # Validated actuator stroke delay window encompassing opening (~13s) & closing (~3.7s)
        gate_steps.append(
            GateStepOutcome(
                gate_name="OPERATING_STATE_RESOLVER",
                passed=True,
                status="NOT_RESTRICTED",
                reason="Unconditioned actuator valve stroke with validated FOPDT bounds [1.0, 25.0]s.",
                details={"bounds": effective_bounds},
            )
        )
    elif override_delay_bounds is not None:
        effective_bounds = override_delay_bounds
        gate_steps.append(
            GateStepOutcome(
                gate_name="OPERATING_STATE_RESOLVER",
                passed=True,
                status="OVERRIDE_BOUNDS",
                reason=f"Custom configured delay bounds applied [{effective_bounds[0]}, {effective_bounds[1]}]s.",
                details={"bounds": effective_bounds},
            )
        )

    # Step 5: Gate G1 (Delay Feasibility)
    min_d, max_d = effective_bounds
    is_g1_passed = min_d <= delta_t <= max_d

    gate_steps.append(
        GateStepOutcome(
            gate_name="GATE_G1_DELAY_FEASIBILITY",
            passed=is_g1_passed,
            status="PASSED" if is_g1_passed else "OUT_OF_BOUNDS",
            reason=(
                f"Observed lag Δt = {delta_t:.2f}s is WITHIN validated window [{min_d:.1f}, {max_d:.1f}]s."
                if is_g1_passed
                else f"Observed lag Δt = {delta_t:.2f}s is OUTSIDE feasible window [{min_d:.1f}, {max_d:.1f}]s."
            ),
            details={"min_s": min_d, "max_s": max_d, "observed_s": delta_t},
        )
    )

    # Step 6: OC-CCD Common Cause Diagnostic
    is_common_cause = delta_t < 1.0  # Near-simultaneous firing
    gate_steps.append(
        GateStepOutcome(
            gate_name="OCC_CCD_DIAGNOSTIC",
            passed=not is_common_cause,
            status="FLAGGED_COMMON_CAUSE" if is_common_cause else "INDEPENDENT_RESPONSE",
            reason=(
                "Near-simultaneous onset (< 1.0s) suggests external disturbance or common power/network cause."
                if is_common_cause
                else "Sufficient temporal separation confirms distinct propagation offset."
            ),
        )
    )

    # Step 7: Final Status Classification
    if not is_g1_passed:
        return CrossNodeAnalysisResult(
            source_node=src_id,
            target_node=tgt_id,
            source_event=evt_a,
            target_event=evt_b,
            delta_t_s=delta_t,
            gate_steps=gate_steps,
            overall_status=PresentationStatus.UNCONFIRMED,
            is_eligible_for_evaluation=True,
            is_supported_relationship=False,
            explanation=(
                f"Temporal association observed (Δt = {delta_t:.2f}s), but delay exceeds physical limits "
                f"[{min_d:.1f}, {max_d:.1f}]s. Relationship unconfirmed."
            ),
        )

    # Both G0 and G1 passed
    is_real_swat_validated = (src_id, tgt_id) in [("MV201", "FIT201"), ("P301", "DPIT301")]
    if is_real_swat_validated:
        final_status = PresentationStatus.RELATIONSHIP_SUPPORTED
        explanation = (
            f"Physical connection allowed (Gate G0) and observed lag Δt = {delta_t:.2f}s is within validated "
            f"physical dynamics [{min_d:.1f}, {max_d:.1f}]s. Criteria satisfied under experimental protocol."
        )
    else:
        final_status = PresentationStatus.RESPONSE_OBSERVED
        explanation = (
            f"Response criteria met (Δt = {delta_t:.2f}s within bounds [{min_d:.1f}, {max_d:.1f}]s). "
            f"Controlled software response demonstrated."
        )

    return CrossNodeAnalysisResult(
        source_node=src_id,
        target_node=tgt_id,
        source_event=evt_a,
        target_event=evt_b,
        delta_t_s=delta_t,
        gate_steps=gate_steps,
        overall_status=final_status,
        is_eligible_for_evaluation=True,
        is_supported_relationship=is_real_swat_validated,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Serialization and Export
# ---------------------------------------------------------------------------

def export_experiment_record(
    analysis: CrossNodeAnalysisResult,
    source_det: NodeDetectionResult,
    target_det: NodeDetectionResult,
    config: Dict[str, Any],
) -> str:
    """Serialize the experiment run into a reproducible JSON string."""
    data = {
        "export_version": "1.0",
        "timestamp_utc": analysis.timestamp_utc,
        "disclaimer": analysis.scientific_disclaimer,
        "overall_status": analysis.overall_status.value,
        "is_supported_relationship": analysis.is_supported_relationship,
        "delta_t_seconds": analysis.delta_t_s,
        "explanation": analysis.explanation,
        "source_node": {
            "node_id": source_det.node_id,
            "detector": source_det.detector_name,
            "anomalous_points": source_det.anomalous_count,
            "first_onset": source_det.first_onset_time.isoformat() if source_det.first_onset_time else None,
            "event_count": len(source_det.event_records),
        },
        "target_node": {
            "node_id": target_det.node_id,
            "detector": target_det.detector_name,
            "anomalous_points": target_det.anomalous_count,
            "first_onset": target_det.first_onset_time.isoformat() if target_det.first_onset_time else None,
            "event_count": len(target_det.event_records),
        },
        "gate_execution_trace": [
            {
                "gate": g.gate_name,
                "passed": g.passed,
                "status": g.status,
                "reason": g.reason,
                "details": g.details,
            }
            for g in analysis.gate_steps
        ],
        "experiment_configuration": config,
    }
    return json.dumps(data, indent=2)


def export_observations_csv(
    source_det: NodeDetectionResult,
    target_det: NodeDetectionResult,
) -> str:
    """Export time series observations and anomaly scores into CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp",
        f"{source_det.node_id}_raw",
        f"{source_det.node_id}_score",
        f"{source_det.node_id}_is_anomaly",
        f"{target_det.node_id}_raw",
        f"{target_det.node_id}_score",
        f"{target_det.node_id}_is_anomaly",
    ])

    n = min(len(source_det.timestamps), len(target_det.timestamps))
    for i in range(n):
        writer.writerow([
            source_det.timestamps[i].isoformat(),
            round(source_det.raw_values[i], 4),
            round(source_det.anomaly_scores[i], 4),
            source_det.is_anomaly[i],
            round(target_det.raw_values[i], 4),
            round(target_det.anomaly_scores[i], 4),
            target_det.is_anomaly[i],
        ])

    return output.getvalue()
