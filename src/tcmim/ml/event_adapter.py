"""
TCMIM — Anomaly-to-Event Adapter (Stage 2 Step 1, FR-ED-2, FR-EM-1).

Bridges Stage 1 unsupervised anomaly detection (window-level AnomalyRecords)
with Stage 2 cross-machine propagation and event matching (discrete EventRecords).

Design Principles & Integrity Rules
------------------------------------
1. Non-Causal Onset: The onset timestamp (t_onset) is defined strictly as the
   window_start timestamp of the first anomalous window in a burst.
   Future observations in the burst never move t_onset backward.
2. Contiguity & Gap Isolation: Consecutive anomalous windows are merged into
   a single burst if their inter-window time gap is <= max_gap_s.
   Anomalies separated by missing data or shutdowns (> max_gap_s) are NEVER merged.
3. Metadata & Provenance Preservation:
   - Provenance is strictly preserved (e.g. PUBLIC_DATASET for MetroPT-3;
     SYNTHETIC for unit fixtures). Mixed provenance within a machine stream raises ValueError.
   - Detector name is preserved from the underlying AnomalyRecord (e.g. "isolation_forest").
   - Modality defaults to Modality.UNKNOWN unless explicitly provided; missing modality
     is never fabricated.
4. Statistical Anomaly != Failure:
   The resulting EventRecord represents an onset of a statistically unusual burst,
   NOT a confirmed component failure.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np

from tcmim.schemas import AnomalyRecord, EventRecord, Modality, Provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class EventAdapterConfig:
    """Configuration for AnomalyToEventAdapter.

    Attributes
    ----------
    min_burst_windows : Minimum number of consecutive anomalous windows required
                        to emit an EventRecord. Default 1 (allows single-window events).
    max_gap_s         : Maximum allowed time gap in seconds between consecutive
                        anomalous windows to consider them part of the same burst.
                        Default 300.0s (nominal window duration for MetroPT-3).
    max_tolerance_nominal_windows : Number of non-anomalous windows allowed within
                                    a burst before closing it. Default 0 (strict contiguity).
    score_aggregation : Method to aggregate window scores into EventRecord.score:
                        - "peak"  : Most anomalous score (minimum for Isolation Forest).
                        - "onset" : Anomaly score at the onset window.
                        - "mean"  : Mean anomaly score across constituent windows.
                        Default "peak".
    default_modality  : Modality assigned when AnomalyRecord lacks modality.
                        Default Modality.UNKNOWN.
    """
    min_burst_windows: int = 1
    max_gap_s: float = 300.0
    max_tolerance_nominal_windows: int = 0
    score_aggregation: str = "peak"
    default_modality: Modality = Modality.UNKNOWN

    def __post_init__(self) -> None:
        if self.min_burst_windows < 1:
            raise ValueError(f"min_burst_windows must be >= 1, got {self.min_burst_windows}")
        if self.max_gap_s < 0:
            raise ValueError(f"max_gap_s must be non-negative, got {self.max_gap_s}")
        if self.max_tolerance_nominal_windows < 0:
            raise ValueError(
                f"max_tolerance_nominal_windows must be >= 0, "
                f"got {self.max_tolerance_nominal_windows}"
            )
        valid_aggs = ("peak", "onset", "mean")
        if self.score_aggregation not in valid_aggs:
            raise ValueError(
                f"score_aggregation must be one of {valid_aggs}, "
                f"got '{self.score_aggregation}'"
            )
        if not isinstance(self.default_modality, Modality):
            self.default_modality = Modality(self.default_modality)


# ---------------------------------------------------------------------------
# Rich Anomaly Burst Representation
# ---------------------------------------------------------------------------

@dataclass
class AnomalyBurst:
    """Rich intermediate representation of a clustered anomalous event burst.

    Attributes
    ----------
    burst_id     : Unique identifier.
    machine_id   : Machine identifier.
    onset_time   : Timestamp of first anomalous window (window_start).
    end_time     : Timestamp of last anomalous window (window_end or window_start).
    window_count : Number of anomalous windows in the burst.
    peak_score   : Most extreme anomaly score (minimum score for IsolationForest).
    mean_score   : Mean anomaly score across the burst.
    onset_score  : Anomaly score at the onset window.
    detector     : Detector string (e.g. 'isolation_forest').
    modality     : Sensor modality (e.g. Modality.UNKNOWN).
    provenance   : Data provenance.
    records      : List of underlying AnomalyRecords.
    """
    machine_id: str
    onset_time: datetime
    end_time: datetime
    window_count: int
    peak_score: float
    mean_score: float
    onset_score: float
    detector: str
    modality: Modality
    provenance: Provenance
    records: List[AnomalyRecord] = field(default_factory=list)
    burst_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_event_record(self, score_metric: str = "peak") -> EventRecord:
        """Convert this burst into a standard TCMIM EventRecord."""
        if score_metric == "onset":
            rep_score = self.onset_score
        elif score_metric == "mean":
            rep_score = self.mean_score
        else:  # "peak"
            rep_score = self.peak_score

        return EventRecord(
            machine_id=self.machine_id,
            modality=self.modality,
            onset_time=self.onset_time,
            detector=self.detector,
            score=rep_score,
            provenance=self.provenance,
            end_time=self.end_time,
            window_count=self.window_count,
        )


# ---------------------------------------------------------------------------
# Adapter Implementation
# ---------------------------------------------------------------------------

class AnomalyToEventAdapter:
    """Converts continuous/window-level AnomalyRecords to discrete EventRecords.

    Parameters
    ----------
    config : Configuration parameters. Uses EventAdapterConfig defaults if None.
    """

    def __init__(self, config: Optional[EventAdapterConfig] = None) -> None:
        self.config = config or EventAdapterConfig()

    def adapt(
        self,
        records: Sequence[AnomalyRecord],
        modality: Optional[Modality] = None,
        machine_id: Optional[str] = None,
    ) -> List[EventRecord]:
        """Convert a sequence of AnomalyRecords for a machine into EventRecords.

        Parameters
        ----------
        records    : List/sequence of AnomalyRecord objects for one machine.
        modality   : Optional modality override. Defaults to config.default_modality.
        machine_id : Optional machine_id override.

        Returns
        -------
        List of EventRecord objects sorted chronologically by onset_time.
        """
        bursts = self.adapt_to_bursts(records, modality=modality, machine_id=machine_id)
        return [b.to_event_record(score_metric=self.config.score_aggregation) for b in bursts]

    def adapt_to_bursts(
        self,
        records: Sequence[AnomalyRecord],
        modality: Optional[Modality] = None,
        machine_id: Optional[str] = None,
    ) -> List[AnomalyBurst]:
        """Cluster AnomalyRecords into rich AnomalyBurst objects.

        Parameters
        ----------
        records    : Sequence of AnomalyRecord objects.
        modality   : Optional modality override.
        machine_id : Optional machine_id override.

        Returns
        -------
        List of AnomalyBurst objects.
        """
        if not records:
            return []

        # 1. Deterministic deduplication & chronological sorting
        unique_records = self._deduplicate_and_sort(records)
        if not unique_records:
            return []

        target_machine = machine_id or unique_records[0].machine_id
        target_modality = modality or self.config.default_modality
        if not isinstance(target_modality, Modality):
            target_modality = Modality(target_modality)

        # 2. Provenance verification (FR-DA-2: no mixed provenance within stream)
        stream_provenance = unique_records[0].provenance
        for r in unique_records:
            if r.machine_id != target_machine and machine_id is None:
                raise ValueError(
                    f"Multiple machine IDs detected in single stream: "
                    f"'{target_machine}' vs '{r.machine_id}'. Use adapt_all_machines() instead."
                )
            if r.provenance != stream_provenance:
                raise ValueError(
                    f"Mixed provenance detected in stream for '{target_machine}': "
                    f"'{stream_provenance}' vs '{r.provenance}'. "
                    "FR-DA-2 forbids mixing synthetic and real records."
                )

        # 3. Cluster into bursts
        bursts: List[AnomalyBurst] = []
        current_burst_records: List[AnomalyRecord] = []
        consecutive_nominal_count = 0

        for r in unique_records:
            if r.is_anomaly:
                if not current_burst_records:
                    # Start a new burst
                    current_burst_records = [r]
                    consecutive_nominal_count = 0
                else:
                    # Check gap contiguity with previous anomalous window
                    prev_r = current_burst_records[-1]
                    prev_end = prev_r.window_end or prev_r.timestamp
                    gap_s = (r.timestamp - prev_end).total_seconds()

                    # Two conditions can close the burst:
                    # A) Nominal windows exceeded tolerance
                    # B) Time gap exceeded max_gap_s (e.g. overnight shutdown)
                    gap_exceeded = gap_s > self.config.max_gap_s
                    nominal_exceeded = consecutive_nominal_count > self.config.max_tolerance_nominal_windows

                    if gap_exceeded or nominal_exceeded:
                        # Close current burst
                        self._maybe_append_burst(
                            bursts, current_burst_records, target_machine, target_modality, stream_provenance
                        )
                        current_burst_records = [r]
                        consecutive_nominal_count = 0
                    else:
                        # Append to current burst
                        current_burst_records.append(r)
                        consecutive_nominal_count = 0
            else:
                # Non-anomalous window encountered
                if current_burst_records:
                    consecutive_nominal_count += 1
                    if consecutive_nominal_count > self.config.max_tolerance_nominal_windows:
                        # Close current burst
                        self._maybe_append_burst(
                            bursts, current_burst_records, target_machine, target_modality, stream_provenance
                        )
                        current_burst_records = []
                        consecutive_nominal_count = 0

        # Close any lingering burst at the end of the stream
        if current_burst_records:
            self._maybe_append_burst(
                bursts, current_burst_records, target_machine, target_modality, stream_provenance
            )

        logger.debug(
            "AnomalyToEventAdapter: clustered %d anomaly records into %d bursts for machine '%s'.",
            len([r for r in unique_records if r.is_anomaly]),
            len(bursts),
            target_machine,
        )
        return bursts

    def adapt_all_machines(
        self,
        records: Sequence[AnomalyRecord],
        modality_map: Optional[Dict[str, Modality]] = None,
    ) -> Dict[str, List[EventRecord]]:
        """Group AnomalyRecords by machine_id and convert each stream into EventRecords.

        Parameters
        ----------
        records      : Sequence of AnomalyRecord objects (may span multiple machines).
        modality_map : Optional mapping from machine_id to Modality.

        Returns
        -------
        Dict mapping machine_id -> List of EventRecord objects (sorted by onset_time).
        """
        mod_map = modality_map or {}
        records_by_machine: Dict[str, List[AnomalyRecord]] = {}
        for r in records:
            records_by_machine.setdefault(r.machine_id, []).append(r)

        result: Dict[str, List[EventRecord]] = {}
        for mid, m_records in records_by_machine.items():
            mod = mod_map.get(mid, self.config.default_modality)
            result[mid] = self.adapt(m_records, modality=mod, machine_id=mid)
        return result

    def _maybe_append_burst(
        self,
        bursts: List[AnomalyBurst],
        burst_records: List[AnomalyRecord],
        machine_id: str,
        modality: Modality,
        provenance: Provenance,
    ) -> None:
        """Create and append an AnomalyBurst if it satisfies min_burst_windows."""
        if len(burst_records) < self.config.min_burst_windows:
            return

        scores = [r.anomaly_score for r in burst_records]
        onset_time = burst_records[0].timestamp
        last_rec = burst_records[-1]
        end_time = last_rec.window_end or last_rec.timestamp
        detector_name = burst_records[0].detector

        valid_scores = [s for s in scores if math.isfinite(s)]
        if not valid_scores:
            peak_score = 0.0
            mean_score = 0.0
            onset_score = 0.0
        else:
            if "cusum" in detector_name.lower():
                peak_score = float(max(valid_scores))
            else:
                peak_score = float(min(valid_scores))
            mean_score = float(np.mean(valid_scores))
            onset_score = float(scores[0]) if math.isfinite(scores[0]) else float(valid_scores[0])

        burst = AnomalyBurst(
            machine_id=machine_id,
            onset_time=onset_time,
            end_time=end_time,
            window_count=len(burst_records),
            peak_score=peak_score,
            mean_score=mean_score,
            onset_score=onset_score,
            detector=detector_name,
            modality=modality,
            provenance=provenance,
            records=list(burst_records),
        )
        bursts.append(burst)

    @staticmethod
    def _deduplicate_and_sort(records: Sequence[AnomalyRecord]) -> List[AnomalyRecord]:
        """Deduplicate records by (timestamp, machine_id) and sort chronologically."""
        seen: set = set()
        unique: List[AnomalyRecord] = []
        for r in records:
            key = (r.timestamp, r.machine_id)
            if key not in seen:
                seen.add(key)
                unique.append(r)

        unique.sort(key=lambda r: (r.timestamp, r.record_id))
        return unique
