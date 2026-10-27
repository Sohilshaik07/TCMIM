"""
TCMIM — SWaT (Secure Water Treatment) dataset loader and schema adapter.

The SWaT dataset (iTrust, SUTD) contains continuous telemetry from a 6-stage
water treatment testbed with 51 physical sensor and actuator tags logged at
nominal 1 Hz intervals.

SCIENTIFIC INTEGRITY AND BOUNDARIES
-----------------------------------
1. LOGICAL PROCESS ENTITIES: SWaT process stages (P1 to P6) are modeled as
   logical process entities coupled via fluid pipelines. They are not
   automatically independent machines in the mechanical sense.
2. DISTURBANCE LABELS != PHYSICAL ANOMALY ONSET: Documented attack windows
   indicate cyber-physical actuation/manipulation intervals. Physical process
   deviations depend on system capacitance, tank volumes, and pipe transit lags.
   Ground-truth labels must NEVER be used as model input features.
3. PRECEDENCE != CAUSALITY: An empirical detection lag between stages (Δt > 0)
   reflects consistent temporal ordering across thresholds, NOT mathematical
   proof of physical causality.
4. ESTIMATED DELAY != PHYSICAL TRANSIT TIME: Inferred delay Δt is an empirical
   detection lag unless validated against hydrodynamic flow parameters (V/Q).
5. PROVENANCE INTEGRITY: Real SWaT records carry Provenance.PUBLIC_DATASET.
   Synthetic test fixtures must carry Provenance.SYNTHETIC.

SCIENTIFIC EVALUATION PROTOCOLS
-------------------------------
1. PROTOCOL A — Normal-File Baseline (Recommended Primary):
   - Baseline fitting is executed strictly on the initial chronological segment of
     SWaT_Dataset_Normal_v1.csv (7 days of unattacked operational telemetry).
   - Evaluation is conducted on SWaT_Dataset_Attack_v0.csv.
   - Preserves genuine unsupervised baseline assumptions without consulting attack labels.
2. PROTOCOL B — Single-File Chronological Baseline (Autonomous Baseline):
   - Baseline is fit strictly on the initial chronological segment (e.g. initial 20%)
     of SWaT_Dataset_Attack_v0.csv without filtering or consulting labels.
   - Acknowledges potential baseline contamination; contamination sensitivity must be audited.
3. PROTOCOL C — Label-Filtered Baseline (Supervised Comparison Baseline):
   - Baseline is selected by explicitly filtering for Normal/Attack == 'Normal'
     within the attack file.
   - MUST be classified as a supervised/label-informed evaluation protocol; never
     misrepresented as an unsupervised baseline.

WINDOW-LEVEL GROUND-TRUTH ALIGNMENT SEMANTICS
----------------------------------------------
- Method 'any': Conservative / early warning. Window is labeled 1.0 (Attack) if >= 1
  timestamp within [ws, we) carries an attack flag.
- Method 'majority': Balanced overlap. Window is labeled 1.0 (Attack) if > 50% of
  timestamps within [ws, we) carry an attack flag. Exact 50% overlap evaluates to 0.0 (Normal).
- Transition windows: When attacks start or end mid-window, 'any' captures attack onset immediately,
  while 'majority' suppresses transient boundary overlap until sustained. Both metrics must be reported.
- Detection delay vs. Propagation delay: Delay from attack onset to detector alarm is an
  empirical detection lag, NOT true hydrodynamic fluid transit time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from tcmim.schemas import Modality, Provenance, SensorSample

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# SWaT Process Stages and Tag Classification Enums
# --------------------------------------------------------------------------

class SWaTProcessStage(str, Enum):
    """Verified process stages of the SWaT physical testbed.

    Each stage represents a logical process section controlled by a dedicated
    PLC and connected via physical piping.
    """
    P1 = "P1_raw_water"
    P2 = "P2_chemical_dosing"
    P3 = "P3_ultrafiltration"
    P4 = "P4_dechlorination"
    P5 = "P5_reverse_osmosis"
    P6 = "P6_distribution"


class SWaTTagType(str, Enum):
    """Classification of SWaT telemetry channels."""
    SENSOR = "sensor"                 # Continuous physical measurement feedback
    ACTUATOR = "actuator"             # Commanded mechanism (valve, pump, lamp)
    CONTROL_SIGNAL = "control_signal" # Control status/command
    UNKNOWN = "unknown"               # Unrecognized tag


@dataclass(frozen=True)
class SWaTTagInfo:
    """Metadata describing a single SWaT telemetry tag.

    Attributes
    ----------
    tag         : Channel / tag name (e.g. 'FIT101', 'P101').
    tag_type    : SENSOR, ACTUATOR, or CONTROL_SIGNAL.
    stage       : Verified SWaTProcessStage, or None if unmapped.
    modality    : Assigned TCMIM Modality enum.
    description : Brief human-readable description.
    """
    tag: str
    tag_type: SWaTTagType
    stage: Optional[SWaTProcessStage]
    modality: Modality
    description: str


# --------------------------------------------------------------------------
# Verified SWaT 2015 Tag Registry (51 Physical Instruments)
#
# Modality Assignment Rules:
# - Pressure / DP sensors -> Modality.PRESSURE
# - Commanded actuators (MV, P, UV) -> Modality.DIGITAL_STATE
# - Continuous sensors without specific TCMIM hardware modality (FIT, LIT, AIT)
#   -> Modality.UNKNOWN (causes FeatureExtractor to compute standard continuous
#      statistical features: mean, std, etc. without inventing physical assumptions).
# --------------------------------------------------------------------------

SWAT_TAG_REGISTRY: Dict[str, SWaTTagInfo] = {
    # --- Stage 1: Raw Water Storage ---
    "FIT101": SWaTTagInfo("FIT101", SWaTTagType.SENSOR, SWaTProcessStage.P1, Modality.UNKNOWN, "Raw water inflow flow transmitter"),
    "LIT101": SWaTTagInfo("LIT101", SWaTTagType.SENSOR, SWaTProcessStage.P1, Modality.UNKNOWN, "Raw water tank level transmitter"),
    "MV101":  SWaTTagInfo("MV101",  SWaTTagType.ACTUATOR, SWaTProcessStage.P1, Modality.DIGITAL_STATE, "Raw water inlet motorized valve"),
    "P101":   SWaTTagInfo("P101",   SWaTTagType.ACTUATOR, SWaTProcessStage.P1, Modality.DIGITAL_STATE, "Raw water supply pump 1"),
    "P102":   SWaTTagInfo("P102",   SWaTTagType.ACTUATOR, SWaTProcessStage.P1, Modality.DIGITAL_STATE, "Raw water supply pump 2"),

    # --- Stage 2: Chemical Dosing ---
    "AIT201": SWaTTagInfo("AIT201", SWaTTagType.SENSOR, SWaTProcessStage.P2, Modality.UNKNOWN, "Raw water conductivity analyzer (NaCl)"),
    "AIT202": SWaTTagInfo("AIT202", SWaTTagType.SENSOR, SWaTProcessStage.P2, Modality.UNKNOWN, "Chemical dosing pH analyzer"),
    "AIT203": SWaTTagInfo("AIT203", SWaTTagType.SENSOR, SWaTProcessStage.P2, Modality.UNKNOWN, "Chemical dosing ORP analyzer"),
    "FIT201": SWaTTagInfo("FIT201", SWaTTagType.SENSOR, SWaTProcessStage.P2, Modality.UNKNOWN, "Chemical dosing flow transmitter"),
    "MV201":  SWaTTagInfo("MV201",  SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "Chemical dosing motorized valve"),
    "P201":   SWaTTagInfo("P201",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "NaOCl dosing pump 1"),
    "P202":   SWaTTagInfo("P202",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "NaOCl dosing pump 2"),
    "P203":   SWaTTagInfo("P203",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "HCl dosing pump 1"),
    "P204":   SWaTTagInfo("P204",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "HCl dosing pump 2"),
    "P205":   SWaTTagInfo("P205",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "NaHSO3 dosing pump 1"),
    "P206":   SWaTTagInfo("P206",   SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "NaHSO3 dosing pump 2"),

    # --- Stage 3: Ultrafiltration (UF) ---
    "DPIT301": SWaTTagInfo("DPIT301", SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.PRESSURE, "UF membrane differential pressure"),
    "FIT301":  SWaTTagInfo("FIT301",  SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.UNKNOWN, "UF feed flow transmitter"),
    "LIT301":  SWaTTagInfo("LIT301",  SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.UNKNOWN, "UF feed tank level transmitter"),
    "MV301":   SWaTTagInfo("MV301",   SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF feed motorized valve"),
    "MV302":   SWaTTagInfo("MV302",   SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF permeate motorized valve"),
    "MV303":   SWaTTagInfo("MV303",   SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF drain motorized valve"),
    "MV304":   SWaTTagInfo("MV304",   SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF backwash motorized valve"),
    "P301":    SWaTTagInfo("P301",    SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF feed pump 1"),
    "P302":    SWaTTagInfo("P302",    SWaTTagType.ACTUATOR, SWaTProcessStage.P3, Modality.DIGITAL_STATE, "UF feed pump 2"),

    # --- Stage 4: Dechlorination & UV ---
    "AIT401": SWaTTagInfo("AIT401", SWaTTagType.SENSOR, SWaTProcessStage.P4, Modality.UNKNOWN, "Free chlorine analyzer"),
    "AIT402": SWaTTagInfo("AIT402", SWaTTagType.SENSOR, SWaTProcessStage.P4, Modality.UNKNOWN, "Total chlorine / ORP analyzer"),
    "FIT401": SWaTTagInfo("FIT401", SWaTTagType.SENSOR, SWaTProcessStage.P4, Modality.UNKNOWN, "RO feed flow transmitter"),
    "LIT401": SWaTTagInfo("LIT401", SWaTTagType.SENSOR, SWaTProcessStage.P4, Modality.UNKNOWN, "RO feed tank level transmitter"),
    "P401":   SWaTTagInfo("P401",   SWaTTagType.ACTUATOR, SWaTProcessStage.P4, Modality.DIGITAL_STATE, "RO feed pump 1"),
    "P402":   SWaTTagInfo("P402",   SWaTTagType.ACTUATOR, SWaTProcessStage.P4, Modality.DIGITAL_STATE, "RO feed pump 2"),
    "P403":   SWaTTagInfo("P403",   SWaTTagType.ACTUATOR, SWaTProcessStage.P4, Modality.DIGITAL_STATE, "NaHSO3 dosing pump 1"),
    "P404":   SWaTTagInfo("P404",   SWaTTagType.ACTUATOR, SWaTProcessStage.P4, Modality.DIGITAL_STATE, "NaHSO3 dosing pump 2"),
    "UV401":  SWaTTagInfo("UV401",  SWaTTagType.ACTUATOR, SWaTProcessStage.P4, Modality.DIGITAL_STATE, "Dechlorination UV lamp"),

    # --- Stage 5: Reverse Osmosis (RO) ---
    "AIT501": SWaTTagInfo("AIT501", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO feed conductivity analyzer"),
    "AIT502": SWaTTagInfo("AIT502", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO permeate conductivity analyzer"),
    "AIT503": SWaTTagInfo("AIT503", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO feed pH analyzer"),
    "AIT504": SWaTTagInfo("AIT504", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO permeate ORP analyzer"),
    "FIT501": SWaTTagInfo("FIT501", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO feed flow transmitter"),
    "FIT502": SWaTTagInfo("FIT502", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO permeate flow transmitter"),
    "FIT503": SWaTTagInfo("FIT503", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO concentrate flow transmitter"),
    "FIT504": SWaTTagInfo("FIT504", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.UNKNOWN, "RO recycle flow transmitter"),
    "PIT501": SWaTTagInfo("PIT501", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.PRESSURE, "RO pump suction pressure transmitter"),
    "PIT502": SWaTTagInfo("PIT502", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.PRESSURE, "RO pump discharge pressure transmitter"),
    "PIT503": SWaTTagInfo("PIT503", SWaTTagType.SENSOR, SWaTProcessStage.P5, Modality.PRESSURE, "RO membrane pressure transmitter"),
    "MV501":  SWaTTagInfo("MV501",  SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "RO reject motorized valve"),
    "MV502":  SWaTTagInfo("MV502",  SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "RO permeate motorized valve"),
    "MV503":  SWaTTagInfo("MV503",  SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "RO flush motorized valve"),
    "MV504":  SWaTTagInfo("MV504",  SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "RO drain motorized valve"),
    "P501":   SWaTTagInfo("P501",   SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "High-pressure RO pump 1"),
    "P502":   SWaTTagInfo("P502",   SWaTTagType.ACTUATOR, SWaTProcessStage.P5, Modality.DIGITAL_STATE, "High-pressure RO pump 2"),

    # --- Stage 6: Distribution & Backwash ---
    "FIT601": SWaTTagInfo("FIT601", SWaTTagType.SENSOR, SWaTProcessStage.P6, Modality.UNKNOWN, "Distribution flow transmitter"),
    "LIT601": SWaTTagInfo("LIT601", SWaTTagType.SENSOR, SWaTProcessStage.P6, Modality.UNKNOWN, "Backwash tank level transmitter"),
    "P601":   SWaTTagInfo("P601",   SWaTTagType.ACTUATOR, SWaTProcessStage.P6, Modality.DIGITAL_STATE, "Distribution pump 1"),
    "P602":   SWaTTagInfo("P602",   SWaTTagType.ACTUATOR, SWaTProcessStage.P6, Modality.DIGITAL_STATE, "Distribution pump 2"),
    "P603":   SWaTTagInfo("P603",   SWaTTagType.ACTUATOR, SWaTProcessStage.P6, Modality.DIGITAL_STATE, "Backwash recycle pump"),
}

# Derived lookup maps
SWAT_MODALITY_MAP: Dict[str, Modality] = {
    tag: info.modality for tag, info in SWAT_TAG_REGISTRY.items()
}

SWAT_TAG_TYPE_MAP: Dict[str, SWaTTagType] = {
    tag: info.tag_type for tag, info in SWAT_TAG_REGISTRY.items()
}

SWAT_STAGE_MAP: Dict[str, SWaTProcessStage] = {
    tag: info.stage for tag, info in SWAT_TAG_REGISTRY.items() if info.stage is not None
}

SWAT_SENSOR_COLUMNS: List[str] = [
    tag for tag, info in SWAT_TAG_REGISTRY.items() if info.tag_type == SWaTTagType.SENSOR
]

SWAT_ACTUATOR_COLUMNS: List[str] = [
    tag for tag, info in SWAT_TAG_REGISTRY.items() if info.tag_type == SWaTTagType.ACTUATOR
]

# --------------------------------------------------------------------------
# SWaT Actuator State Encodings and Normalization
#
# In standard iTrust SWaT 2015 testbed documentation, PLC digital actuators are logged as:
# - Motorized Valves (MV): 1 = Closed (Inactive / 0), 2 = Open (Active / 1)
# - Pumps (P): 1 = Off / Stopped (Inactive / 0), 2 = On / Running (Active / 1)
# - UV Lamp (UV): 1 = Off (Inactive / 0), 2 = On (Active / 1)
#
# State 0 or any other unlisted integer represents an intermediate/transition/fault state,
# which is classified as UNKNOWN according to explicit policy (never silently forced to 0 or 1).
# --------------------------------------------------------------------------

SWAT_DEFAULT_ACTUATOR_STATE_MAP: Dict[float, int] = {
    1.0: 0,  # OFF / CLOSED
    2.0: 1,  # ON / OPEN
}

SWAT_ACTUATOR_STATE_MAP: Dict[str, Dict[float, int]] = {
    tag: dict(SWAT_DEFAULT_ACTUATOR_STATE_MAP) for tag in SWAT_ACTUATOR_COLUMNS
}


def get_swat_actuator_state_mapping(tag: str) -> Optional[Dict[float, int]]:
    """Return explicit binary state mapping for a SWaT actuator tag.

    Returns {1.0: 0, 2.0: 1} for verified SWaT pumps, valves, and lamps.
    Returns None if tag is not recognized as an actuator.
    """
    cleaned = tag.strip()
    if cleaned in SWAT_ACTUATOR_STATE_MAP:
        return dict(SWAT_ACTUATOR_STATE_MAP[cleaned])
    info = parse_swat_tag(cleaned)
    if info.tag_type == SWaTTagType.ACTUATOR:
        return dict(SWAT_DEFAULT_ACTUATOR_STATE_MAP)
    return None


def normalize_swat_actuator_signal(
    signal: np.ndarray,
    tag: Optional[str] = None,
) -> np.ndarray:
    """Normalize discrete SWaT actuator states to binary active flags.

    Mapping policy:
      - State 1 -> 0.0 (Inactive / Closed / Off)
      - State 2 -> 1.0 (Active / Open / On)
      - State 0 or unmapped -> np.nan (Intermediate / Transition / Fault / Unknown)

    Parameters
    ----------
    signal : 1-D numpy array of raw actuator values. Original array is preserved.
    tag    : Optional channel name for tag-specific lookup.

    Returns
    -------
    1-D numpy array of normalized floats (0.0, 1.0, or np.nan).
    """
    mapping = get_swat_actuator_state_mapping(tag) if tag else SWAT_DEFAULT_ACTUATOR_STATE_MAP
    if mapping is None:
        mapping = SWAT_DEFAULT_ACTUATOR_STATE_MAP

    arr = np.asarray(signal, dtype=float)
    normalized = np.full(len(arr), np.nan, dtype=float)

    for k_val, binary_val in mapping.items():
        mask = np.isclose(arr, k_val, atol=1e-6)
        normalized[mask] = float(binary_val)

    return normalized


# Supported explicit timestamp formats in SWaT CSV releases
SUPPORTED_TIMESTAMP_FORMATS: Tuple[str, ...] = (
    "%d/%m/%Y %I:%M:%S %p",    # e.g. "22/12/2015 4:00:00 PM" (standard SWaT 2015)
    "%d/%m/%Y %H:%M:%S",       # e.g. "22/12/2015 16:00:00"
    "%Y-%m-%d %H:%M:%S",       # ISO standard e.g. "2015-12-22 16:00:00"
    "%Y-%m-%dT%H:%M:%S",      # ISO 8601 with T
    "%m/%d/%Y %I:%M:%S %p",    # US order with AM/PM
    "%Y/%m/%d %H:%M:%S",       # Year-first slash
    "%d-%m-%Y %H:%M:%S",       # Hyphenated day-first
)

# Label column candidates (case-insensitive, whitespace-trimmed, normalized)
LABEL_COLUMN_CANDIDATES: Tuple[str, ...] = (
    "normal/attack",
    "normal / attack",
    "attack",
    "label",
    "status",
    "class",
    "ground_truth",
    "groundtruth",
    "ground truth",
    "target",
    "is_attack",
    "isattack",
    "is attack",
    "anomaly",
    "anomaly_label",
    "fault",
    "fault_label",
)


def _normalize_label_token(col: str) -> str:
    """Normalize column header for robust ground-truth detection."""
    return re.sub(r"[\s_\-/]+", "", str(col).strip().lower())


_NORMALIZED_LABEL_CANDIDATES: Set[str] = {
    _normalize_label_token(c) for c in LABEL_COLUMN_CANDIDATES
}

# Timestamp column candidates (case-insensitive, whitespace-trimmed)
TIMESTAMP_COLUMN_CANDIDATES: Tuple[str, ...] = (
    "timestamp",
    "time",
    "date_time",
    "datetime",
)


# --------------------------------------------------------------------------
# Tag Classification Functions
# --------------------------------------------------------------------------

_STAGE_REGEX = re.compile(r"^([A-Za-z]+)([1-6])(\d+)$")


def parse_swat_tag(tag: str) -> SWaTTagInfo:
    """Classify a tag name into instrument type, process stage, and modality.

    Checks the verified static registry first. If not found, inspects tag naming
    conventions (e.g. prefix and stage digit). If pattern does not match, returns
    an UNKNOWN tag info without guessing.

    Parameters
    ----------
    tag : Telemetry channel name (e.g. 'FIT101', 'P301').

    Returns
    -------
    SWaTTagInfo describing the tag.
    """
    cleaned = tag.strip()
    if cleaned in SWAT_TAG_REGISTRY:
        return SWAT_TAG_REGISTRY[cleaned]

    match = _STAGE_REGEX.match(cleaned)
    if not match:
        return SWaTTagInfo(
            tag=cleaned,
            tag_type=SWaTTagType.UNKNOWN,
            stage=None,
            modality=Modality.UNKNOWN,
            description="Unrecognized SWaT tag",
        )

    prefix, stage_digit, _ = match.groups()
    prefix_upper = prefix.upper()
    stage_key = f"P{stage_digit}"
    stage = SWaTProcessStage[stage_key] if stage_key in SWaTProcessStage.__members__ else None

    if prefix_upper in ("FIT", "LIT", "AIT"):
        return SWaTTagInfo(
            tag=cleaned,
            tag_type=SWaTTagType.SENSOR,
            stage=stage,
            modality=Modality.UNKNOWN,
            description=f"Inferred {prefix_upper} sensor",
        )
    elif prefix_upper in ("PIT", "DPIT"):
        return SWaTTagInfo(
            tag=cleaned,
            tag_type=SWaTTagType.SENSOR,
            stage=stage,
            modality=Modality.PRESSURE,
            description=f"Inferred {prefix_upper} pressure sensor",
        )
    elif prefix_upper in ("MV", "P", "UV"):
        return SWaTTagInfo(
            tag=cleaned,
            tag_type=SWaTTagType.ACTUATOR,
            stage=stage,
            modality=Modality.DIGITAL_STATE,
            description=f"Inferred {prefix_upper} actuator",
        )
    elif prefix_upper in ("STATUS", "ALARM", "SETPOINT", "SP", "CMD"):
        return SWaTTagInfo(
            tag=cleaned,
            tag_type=SWaTTagType.CONTROL_SIGNAL,
            stage=stage,
            modality=Modality.DIGITAL_STATE,
            description=f"Inferred {prefix_upper} control signal",
        )

    return SWaTTagInfo(
        tag=cleaned,
        tag_type=SWaTTagType.UNKNOWN,
        stage=stage,
        modality=Modality.UNKNOWN,
        description="Unknown tag prefix",
    )


def partition_swat_by_stage(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Partition a SWaT DataFrame into per-stage DataFrames.

    Columns are assigned to a process stage only where the stage mapping
    is verified. Columns with unverified stages are excluded from stage
    partitions.

    Parameters
    ----------
    df : DataFrame whose columns are SWaT tag names.

    Returns
    -------
    Dict mapping stage identifier (e.g. 'P1_raw_water') to the subset DataFrame.
    """
    stage_cols: Dict[str, List[str]] = {
        stage.value: [] for stage in SWaTProcessStage
    }
    unmapped_cols: List[str] = []

    for col in df.columns:
        info = parse_swat_tag(str(col))
        if info.stage is not None:
            stage_cols[info.stage.value].append(col)
        else:
            unmapped_cols.append(col)

    if unmapped_cols:
        logger.info(
            "partition_swat_by_stage: %d column(s) unmapped to process stages: %s",
            len(unmapped_cols), unmapped_cols,
        )

    # Return only stages that contain at least one column
    return {
        stage_name: df[cols].copy()
        for stage_name, cols in stage_cols.items()
        if cols
    }


# --------------------------------------------------------------------------
# Sampling Continuity and Frequency Inference
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class SamplingContinuityReport:
    """Report detailing timestamp monotonicity, continuity, and frequency."""
    total_timestamps: int
    median_interval_s: float
    min_interval_s: float
    max_interval_s: float
    duplicate_count: int
    negative_step_count: int
    gap_count: int
    is_strictly_uniform: bool
    inferred_frequency_hz: Optional[float]


def analyze_sampling_continuity(
    timestamps: Union[pd.DatetimeIndex, pd.Series, pd.DataFrame],
    *,
    gap_threshold_factor: float = 1.5,
) -> SamplingContinuityReport:
    """Analyze timestamp continuity without modifying, interpolating, or resampling.

    Parameters
    ----------
    timestamps           : DatetimeIndex, Series of datetimes, or DataFrame with DatetimeIndex.
    gap_threshold_factor : Factor above median delta considered a missing interval / gap.

    Returns
    -------
    SamplingContinuityReport with exact interval statistics.
    """
    idx = _extract_datetime_index(timestamps)
    n = len(idx)
    if n < 2:
        return SamplingContinuityReport(
            total_timestamps=n,
            median_interval_s=0.0,
            min_interval_s=0.0,
            max_interval_s=0.0,
            duplicate_count=0,
            negative_step_count=0,
            gap_count=0,
            is_strictly_uniform=False,
            inferred_frequency_hz=None,
        )

    deltas_s = idx.to_series().diff().iloc[1:].dt.total_seconds().to_numpy()
    n_negative = int(np.sum(deltas_s < 0))
    n_duplicate = int(np.sum(deltas_s == 0))

    valid_deltas = deltas_s[deltas_s > 0]
    if len(valid_deltas) == 0:
        return SamplingContinuityReport(
            total_timestamps=n,
            median_interval_s=0.0,
            min_interval_s=float(np.min(deltas_s)),
            max_interval_s=float(np.max(deltas_s)),
            duplicate_count=n_duplicate,
            negative_step_count=n_negative,
            gap_count=0,
            is_strictly_uniform=False,
            inferred_frequency_hz=None,
        )

    median_dt = float(np.median(valid_deltas))
    min_dt = float(np.min(deltas_s))
    max_dt = float(np.max(deltas_s))
    gap_thresh = median_dt * gap_threshold_factor
    n_gaps = int(np.sum(deltas_s > gap_thresh))

    is_uniform = (n_negative == 0) and (n_duplicate == 0) and (n_gaps == 0) and np.allclose(deltas_s, median_dt, rtol=1e-3)
    inferred_hz = 1.0 / median_dt if median_dt > 0 else None

    return SamplingContinuityReport(
        total_timestamps=n,
        median_interval_s=median_dt,
        min_interval_s=min_dt,
        max_interval_s=max_dt,
        duplicate_count=n_duplicate,
        negative_step_count=n_negative,
        gap_count=n_gaps,
        is_strictly_uniform=is_uniform,
        inferred_frequency_hz=inferred_hz,
    )


def infer_sampling_frequency(
    timestamps: Union[pd.DatetimeIndex, pd.Series, pd.DataFrame],
    *,
    allow_gaps: bool = False,
    gap_threshold_factor: float = 1.5,
) -> float:
    """Infer sampling frequency in Hz from timestamp differences.

    Handles duplicate timestamps, negative steps, and gaps explicitly.
    Does NOT silently resample, forward-fill, or interpolate.

    Parameters
    ----------
    timestamps           : DatetimeIndex, Series of datetimes, or DataFrame.
    allow_gaps           : If True, calculates frequency from median delta despite
                           occasional missing intervals. If False, raises ValueError.
    gap_threshold_factor : Factor above median delta considered a gap.

    Returns
    -------
    Inferred sampling frequency in Hz.

    Raises
    ------
    ValueError : If data is insufficient, non-monotonic, contains duplicates, or
                 contains gaps when allow_gaps=False.
    """
    report = analyze_sampling_continuity(
        timestamps, gap_threshold_factor=gap_threshold_factor
    )

    if report.total_timestamps < 2:
        raise ValueError(
            f"Insufficient data: at least 2 timestamps required to infer "
            f"sampling frequency (got {report.total_timestamps})."
        )
    if report.negative_step_count > 0:
        raise ValueError(
            f"Cannot infer sampling frequency: index contains "
            f"{report.negative_step_count} non-monotonic (negative) time step(s)."
        )
    if report.duplicate_count > 0:
        raise ValueError(
            f"Cannot infer sampling frequency: index contains "
            f"{report.duplicate_count} duplicate timestamp(s) (zero delta). "
            f"Duplicate timestamps must be resolved explicitly."
        )
    if report.median_interval_s <= 0:
        raise ValueError(
            f"Cannot infer sampling frequency: computed median interval "
            f"({report.median_interval_s}s) is not strictly positive."
        )
    if report.gap_count > 0 and not allow_gaps:
        raise ValueError(
            f"Cannot infer sampling frequency: index contains {report.gap_count} "
            f"gap(s) exceeding {gap_threshold_factor}x the median interval "
            f"({report.median_interval_s:.3f}s). Set allow_gaps=True to proceed."
        )

    if report.gap_count > 0:
        logger.warning(
            "infer_sampling_frequency: %d gap(s) detected (> %.1fx median interval). "
            "Proceeding with median-derived rate (%.3f Hz).",
            report.gap_count, gap_threshold_factor, report.inferred_frequency_hz,
        )

    return float(report.inferred_frequency_hz)


def _extract_datetime_index(
    timestamps: Union[pd.DatetimeIndex, pd.Series, pd.DataFrame]
) -> pd.DatetimeIndex:
    """Extract a validated pd.DatetimeIndex from various input formats."""
    if isinstance(timestamps, pd.DatetimeIndex):
        return timestamps
    elif isinstance(timestamps, pd.DataFrame):
        if isinstance(timestamps.index, pd.DatetimeIndex):
            return timestamps.index
        raise TypeError("DataFrame index must be a pd.DatetimeIndex.")
    elif isinstance(timestamps, pd.Series):
        if isinstance(timestamps.index, pd.DatetimeIndex):
            return timestamps.index
        # Try converting Series values if it holds datetimes
        if pd.api.types.is_datetime64_any_dtype(timestamps):
            return pd.DatetimeIndex(timestamps)
        raise TypeError("Series must have a DatetimeIndex or datetime64 values.")
    else:
        raise TypeError(
            f"Expected DatetimeIndex, Series, or DataFrame; got {type(timestamps).__name__}."
        )


# --------------------------------------------------------------------------
# Label Extraction and Binarization
# --------------------------------------------------------------------------

def binarize_swat_labels(labels: pd.Series) -> pd.Series:
    """Convert SWaT label strings to integer binary flags (0 = Normal, 1 = Attack).

    Parameters
    ----------
    labels : Series of label strings (e.g. 'Normal', 'Attack', 'A T T A C K').

    Returns
    -------
    pd.Series of int (0 or 1), preserving the original index.

    Raises
    ------
    ValueError : If unrecognized label strings are encountered.
    """
    cleaned = labels.astype(str).str.strip().str.upper()
    # Normalize variations such as 'A T T A C K' to 'ATTACK'
    normalized = cleaned.str.replace(" ", "", regex=False)

    unrecognized = set(normalized.unique()) - {"NORMAL", "ATTACK"}
    if unrecognized:
        raise ValueError(
            f"Unrecognized SWaT label value(s): {unrecognized}. "
            f"Expected 'Normal', 'Attack', or 'A T T A C K'."
        )

    return (normalized == "ATTACK").astype(int)


# --------------------------------------------------------------------------
# SWaT CSV Loader
# --------------------------------------------------------------------------

def load_swat_dataframe(
    csv_path: Union[str, Path],
    *,
    max_rows: Optional[int] = None,
    timestamp_col: Optional[str] = None,
    label_col: Optional[str] = None,
    timestamp_format: Optional[str] = None,
    sort_timestamps: bool = True,
) -> Tuple[pd.DataFrame, Optional[pd.Series]]:
    """Load SWaT CSV data into features DataFrame and isolated ground-truth labels.

    Parameters
    ----------
    csv_path         : Path to the SWaT CSV file.
    max_rows         : Optional maximum number of rows to read.
    timestamp_col    : Name of the timestamp column (detected automatically if None).
    label_col        : Explicit name of the ground-truth label column. If supplied,
                       that column is always removed from feature data. If omitted,
                       auto-detection is applied against LABEL_COLUMN_CANDIDATES.
                       Multiple recognized label candidates without an explicit
                       selection raise a ValueError to prevent silent leakage.
    timestamp_format : Explicit strptime format string. If None, tested against
                       SUPPORTED_TIMESTAMP_FORMATS. Does NOT silently guess.
    sort_timestamps  : If True, ensures monotonic DatetimeIndex by sorting.

    Returns
    -------
    (features_df, labels_series)
      - features_df: DataFrame with monotonic UTC DatetimeIndex and strictly numeric
        sensor/actuator columns. Never contains the label column.
      - labels_series: Optional pd.Series containing raw label strings, or None if
        no label column was present.

    Raises
    ------
    FileNotFoundError : If csv_path does not exist.
    ValueError        : On ambiguous or missing label columns, unparseable timestamps,
                        or non-numeric feature columns.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"SWaT CSV file not found at: {csv_path}")

    # Read raw CSV
    df = pd.read_csv(csv_path, nrows=max_rows)
    if df.empty:
        raise ValueError(f"SWaT CSV at {csv_path} is empty.")

    # Handle whitespace in column headers
    df.columns = [str(c).strip() for c in df.columns]

    # --- 1. Identify Timestamp Column ---
    if timestamp_col is not None:
        ts_col = timestamp_col.strip()
        if ts_col not in df.columns:
            raise ValueError(
                f"Specified timestamp column '{ts_col}' not found. "
                f"Available columns: {list(df.columns)}"
            )
    else:
        ts_candidates = [
            c for c in df.columns if c.lower() in TIMESTAMP_COLUMN_CANDIDATES
        ]
        if len(ts_candidates) == 1:
            ts_col = ts_candidates[0]
        elif len(ts_candidates) == 0:
            raise ValueError(
                f"No timestamp column detected. Looked for {TIMESTAMP_COLUMN_CANDIDATES}. "
                f"Available columns: {list(df.columns)}. Specify 'timestamp_col'."
            )
        else:
            raise ValueError(
                f"Multiple timestamp column candidates found: {ts_candidates}. "
                f"Specify 'timestamp_col' explicitly."
            )

    # --- 2. Parse Timestamps Using Explicit Formats ---
    raw_ts = df[ts_col].astype(str).str.strip()
    parsed_index = _parse_timestamps_explicit(
        raw_ts, explicit_format=timestamp_format, col_name=ts_col
    )
    df = df.drop(columns=[ts_col])
    df.index = parsed_index
    df.index.name = "timestamp"

    # --- 2b. Warn on Duplicate Timestamps (Fix 2) ---
    # Duplicate timestamps pass is_monotonic_increasing (weakly non-decreasing)
    # but represent data integrity anomalies that callers must be aware of.
    # Rows are preserved unchanged; no merging, dropping, or interpolation is done.
    if df.index.has_duplicates:
        n_dups = int(df.index.duplicated().sum())
        logger.warning(
            "SWaT DataFrame index contains %d duplicate timestamp(s). "
            "Rows are preserved without modification. "
            "Call infer_sampling_frequency() to detect and reject duplicates.",
            n_dups,
        )

    # --- 3. Ensure Monotonic DatetimeIndex ---
    if not df.index.is_monotonic_increasing:
        if sort_timestamps:
            logger.warning(
                "SWaT timestamps are not monotonically increasing; sorting by DatetimeIndex."
            )
            df = df.sort_index()
        else:
            raise ValueError(
                "SWaT timestamps are not monotonically increasing and sort_timestamps=False."
            )

    # --- 4. Identify and Isolate Label Column (Fix 1) ---
    # Policy:
    #   a) If label_col is explicitly provided, verify it exists, extract it,
    #      then raise an error if any other recognized candidates remain (guard
    #      against inadvertent multi-label leakage).
    #   b) If label_col is omitted and exactly one candidate is detected, extract it.
    #   c) If label_col is omitted and multiple candidates exist, raise ValueError
    #      so the caller must make an explicit selection.
    #   d) If no candidate exists and no label_col is provided, labels = None.
    #
    # In all cases, recognized label candidates that survive into the feature
    # DataFrame are rejected by the numeric validation step below, but we raise
    # early here to provide a more actionable error message.
    auto_candidates = [
        c for c in df.columns
        if c.lower().strip() in LABEL_COLUMN_CANDIDATES
        or _normalize_label_token(c) in _NORMALIZED_LABEL_CANDIDATES
    ]
    labels: Optional[pd.Series] = None

    if label_col is not None:
        # Explicit selection — verify existence
        lc = label_col.strip()
        if lc not in df.columns:
            raise ValueError(
                f"Explicitly requested label column '{lc}' not found. "
                f"Available columns: {list(df.columns)}"
            )
        labels = df[lc].astype(str).str.strip()
        df = df.drop(columns=[lc])
        logger.info("Isolated ground-truth label column (explicit): '%s'", lc)

        # Check for residual recognized label candidates that were NOT selected
        residual = [
            c for c in df.columns
            if (c.lower().strip() in LABEL_COLUMN_CANDIDATES or _normalize_label_token(c) in _NORMALIZED_LABEL_CANDIDATES)
            and c != lc
        ]
        if residual:
            raise ValueError(
                f"After removing explicitly specified label column '{lc}', "
                f"the following additional recognized label column(s) remain in the "
                f"feature DataFrame: {residual}. Remove them explicitly to prevent "
                f"ground-truth leakage. Specify each column to drop or supply "
                f"label_col with the intended column and update the CSV accordingly."
            )
    elif len(auto_candidates) == 1:
        # Unambiguous auto-detection
        lc = auto_candidates[0]
        labels = df[lc].astype(str).str.strip()
        df = df.drop(columns=[lc])
        logger.info("Isolated ground-truth label column (auto-detected): '%s'", lc)
    elif len(auto_candidates) > 1:
        # Ambiguous: multiple recognized label candidates — caller must select
        raise ValueError(
            f"Multiple recognized label column candidates found: {auto_candidates}. "
            f"Specify the correct column via the 'label_col' parameter to prevent "
            f"accidental ground-truth leakage into the feature matrix."
        )
    # else: no candidates, no explicit label_col → labels = None (unlabelled data)

    # --- 5. Validate Numerical Integrity of Model Features ---
    # Model features must be numeric. Ensure ground-truth strings or other
    # text columns are never included among features.
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Feature column '{col}' contains non-numeric values and was not "
                f"recognized as a label column: {exc}. "
                f"Model inputs must be strictly numeric."
            ) from exc

    return df, labels


def _parse_timestamps_explicit(
    raw_series: pd.Series,
    explicit_format: Optional[str],
    col_name: str,
) -> pd.DatetimeIndex:
    """Parse timestamps with explicit validation and UTC localization.

    Does not guess ambiguous day/month orders silently.
    """
    if explicit_format is not None:
        try:
            parsed = pd.to_datetime(
                raw_series, format=explicit_format, errors="raise"
            )
        except Exception as exc:
            raise ValueError(
                f"Failed to parse column '{col_name}' using specified format "
                f"'{explicit_format}': {exc}"
            ) from exc
    else:
        sample_subset = raw_series.iloc[:min(100, len(raw_series))]
        matched_format: Optional[str] = None

        for fmt in SUPPORTED_TIMESTAMP_FORMATS:
            try:
                # Test on sample
                pd.to_datetime(sample_subset, format=fmt, errors="raise")
                matched_format = fmt
                break
            except (ValueError, TypeError):
                continue

        if matched_format is None:
            samples = raw_series.iloc[:3].tolist()
            raise ValueError(
                f"Could not parse timestamps in column '{col_name}' using any "
                f"supported formats: {SUPPORTED_TIMESTAMP_FORMATS}. "
                f"Sample values: {samples}. Please specify 'timestamp_format'."
            )

        parsed = pd.to_datetime(raw_series, format=matched_format, errors="raise")

    # Localize or convert to UTC
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(timezone.utc)
    else:
        parsed = parsed.dt.tz_convert(timezone.utc)

    return pd.DatetimeIndex(parsed)


# --------------------------------------------------------------------------
# SensorSample Adapter
# --------------------------------------------------------------------------

def load_swat_samples(
    csv_path: Union[str, Path],
    *,
    stage: Optional[Union[str, SWaTProcessStage]] = None,
    max_rows: Optional[int] = None,
    provenance: Provenance = Provenance.PUBLIC_DATASET,
    source_id: str = "swat_itrust",
    timestamp_format: Optional[str] = None,
) -> List[SensorSample]:
    """Load SWaT data into a flat list of SensorSample objects.

    Labels are strictly excluded from output samples.

    Parameters
    ----------
    csv_path         : Path to the SWaT CSV file.
    stage            : Optional filter to a single SWaT process stage.
    max_rows         : Optional row limit for loading.
    provenance       : Provenance class (default: PUBLIC_DATASET; test fixtures
                       must pass SYNTHETIC).
    source_id        : Data source identifier string.
    timestamp_format : Explicit strptime format string.

    Returns
    -------
    List of SensorSample objects.
    """
    df, _ = load_swat_dataframe(
        csv_path, max_rows=max_rows, timestamp_format=timestamp_format
    )

    stage_filter: Optional[str] = None
    if stage is not None:
        stage_filter = stage.value if isinstance(stage, SWaTProcessStage) else str(stage)

    samples: List[SensorSample] = []

    for col in df.columns:
        tag_info = parse_swat_tag(str(col))

        if stage_filter is not None:
            tag_stage_val = tag_info.stage.value if tag_info.stage is not None else None
            if tag_stage_val != stage_filter:
                continue

        machine_id = tag_info.stage.value if tag_info.stage is not None else "swat_unassigned"
        modality = tag_info.modality

        col_series = df[col].dropna()
        for ts, val in col_series.items():
            ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            samples.append(
                SensorSample(
                    machine_id=machine_id,
                    channel=str(col),
                    modality=modality,
                    timestamp=ts_dt,
                    value=float(val),
                    provenance=provenance,
                    source_id=source_id,
                )
            )

    logger.info(
        "load_swat_samples: Loaded %d samples from %s (stage filter: %s, provenance: %s)",
        len(samples), csv_path, stage_filter, provenance,
    )
    return samples


# --------------------------------------------------------------------------
# Fix 4 — Tag-Type Filtering Helper
# --------------------------------------------------------------------------

def filter_stage_by_tag_type(
    stage_df: pd.DataFrame,
    tag_type: SWaTTagType,
) -> pd.DataFrame:
    """Return a copy of *stage_df* retaining only columns of the requested SWaTTagType.

    Tag-type classification is based on `parse_swat_tag`, which consults the
    static `SWAT_TAG_REGISTRY` first and then applies prefix-based heuristics.
    Tags not recognized by either mechanism have `SWaTTagType.UNKNOWN` and are
    excluded when filtering for SENSOR or ACTUATOR.

    This function filters by *instrument classification* (sensor vs. actuator vs.
    control signal), NOT by `Modality`. A pressure sensor (Modality.PRESSURE) and
    a flow sensor (Modality.UNKNOWN) are both SWaTTagType.SENSOR and will both be
    retained when ``tag_type=SWaTTagType.SENSOR``. The Modality is not altered.

    Parameters
    ----------
    stage_df : DataFrame whose columns are SWaT tag names (e.g. from
               `partition_swat_by_stage`).
    tag_type : The `SWaTTagType` to retain.

    Returns
    -------
    pd.DataFrame — copy of *stage_df* with only the matching-type columns,
    preserving the original column order.
    """
    matching_cols = [
        col for col in stage_df.columns
        if parse_swat_tag(str(col)).tag_type == tag_type
    ]
    return stage_df[matching_cols].copy()


# --------------------------------------------------------------------------
# Post-Prediction Evaluation and Ground-Truth Isolation Helpers
# --------------------------------------------------------------------------

def align_swat_labels_to_windows(
    labels: pd.Series,
    windows: Sequence[Any],
    *,
    method: str = "any",
) -> np.ndarray:
    """Align ground-truth sample-level labels to time windows for post-prediction evaluation.

    CRITICAL ISOLATION RULE:
    This function MUST only be called AFTER predictions (AnomalyRecords) have been
    generated. Ground-truth labels must NEVER be supplied to window construction,
    feature extraction, detector fitting, or Stage 2 propagation.

    Parameters
    ----------
    labels  : Series of ground-truth labels with DatetimeIndex (in UTC or timezone-naive).
              Can be raw strings ('Normal', 'Attack') or binarized integers (0, 1).
    windows : Sequence of WindowedData or AnomalyRecord objects with window_start/timestamp
              and window_end.
    method  : Aggregation method within each window:
              - 'any'      : 1.0 if any timestamp in [start, end) has label == 1, else 0.0.
              - 'majority' : 1.0 if >50% of timestamps in [start, end) have label == 1, else 0.0.

    Returns
    -------
    np.ndarray of shape (len(windows),) with float values (1.0, 0.0, or np.nan for empty windows).
    """
    if method not in ("any", "majority"):
        raise ValueError(f"Aggregation method must be 'any' or 'majority', got '{method}'")

    if not isinstance(labels.index, pd.DatetimeIndex):
        raise TypeError("labels Series must have a pd.DatetimeIndex.")

    # Ensure labels are binary integers
    if labels.dtype == object or isinstance(labels.iloc[0] if len(labels) > 0 else "", str):
        binary_labels = binarize_swat_labels(labels)
    else:
        binary_labels = (labels > 0).astype(int)

    # Align timezone
    if binary_labels.index.tz is None:
        binary_labels.index = binary_labels.index.tz_localize(timezone.utc)
    else:
        binary_labels.index = binary_labels.index.tz_convert(timezone.utc)

    aligned = np.full(len(windows), np.nan, dtype=float)

    for i, w in enumerate(windows):
        ws = getattr(w, "window_start", getattr(w, "timestamp", None))
        we = getattr(w, "window_end", None)

        if ws is None:
            continue
        if ws.tzinfo is None:
            ws = ws.replace(tzinfo=timezone.utc)

        if we is None:
            # Single timestamp without window_end — look up exact timestamp or 1s step
            sub = binary_labels.loc[ws:ws]
        else:
            if we.tzinfo is None:
                we = we.replace(tzinfo=timezone.utc)
            # Slice [ws, we)
            mask = (binary_labels.index >= ws) & (binary_labels.index < we)
            sub = binary_labels.loc[mask]

        if len(sub) == 0:
            aligned[i] = np.nan
        elif method == "any":
            aligned[i] = 1.0 if (sub == 1).any() else 0.0
        elif method == "majority":
            aligned[i] = 1.0 if (sub == 1).mean() > 0.5 else 0.0

    return aligned


def evaluate_swat_window_predictions(
    ground_truth_windows: np.ndarray,
    predictions: Sequence[Any],
) -> Dict[str, Any]:
    """Compute standard classification evaluation metrics for window-level anomaly predictions.

    Calculates:
      - Confusion matrix: TP, FP, TN, FN
      - Precision, Recall, F1 score
      - False Positive Rate (FPR)
      - Explicit handling of undefined metrics (e.g. division by zero when no attacks occur)

    SCIENTIFIC NOTE:
    SWaT attack labels indicate when an attack was actively executing on the
    cyber-physical testbed. They do NOT establish true physical anomaly onset or
    physical component failure. An undetected attack window may reflect physical latency
    or capacitance; a false alarm may reflect legitimate operational transients.

    Parameters
    ----------
    ground_truth_windows : 1-D array of binary ground-truth labels (0, 1, or np.nan).
    predictions          : Sequence of AnomalyRecord objects or boolean/int predictions.

    Returns
    -------
    Dict containing confusion counts, rate metrics, and audit documentation.
    """
    if len(ground_truth_windows) != len(predictions):
        raise ValueError(
            f"Length mismatch: {len(ground_truth_windows)} ground truth windows vs "
            f"{len(predictions)} predictions."
        )

    pred_flags = np.array([
        bool(getattr(p, "is_anomaly", p)) for p in predictions
    ], dtype=int)

    # Exclude windows with missing/NaN ground truth
    valid_mask = np.isfinite(ground_truth_windows)
    n_total = len(ground_truth_windows)
    n_valid = int(np.sum(valid_mask))
    n_missing = n_total - n_valid

    if n_valid == 0:
        return {
            "total_windows": n_total,
            "valid_windows": 0,
            "missing_windows": n_missing,
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
            "precision": np.nan,
            "recall": np.nan,
            "f1": np.nan,
            "fpr": np.nan,
            "warning": "No windows had valid ground-truth labels to evaluate.",
        }

    y_true = ground_truth_windows[valid_mask].astype(int)
    y_pred = pred_flags[valid_mask]

    tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    # Precision: TP / (TP + FP)
    precision = (tp / (tp + fp)) if (tp + fp) > 0 else (np.nan if tp == 0 and fp == 0 else 0.0)

    # Recall: TP / (TP + FN)
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else (np.nan if tp == 0 and fn == 0 else 0.0)

    # F1 score: harmonic mean
    if np.isnan(precision) or np.isnan(recall):
        f1 = np.nan
    elif precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * (precision * recall) / (precision + recall)

    # False Positive Rate: FP / (FP + TN)
    fpr = (fp / (fp + tn)) if (fp + tn) > 0 else (np.nan if fp == 0 and tn == 0 else 0.0)

    return {
        "total_windows": n_total,
        "valid_windows": n_valid,
        "missing_windows": n_missing,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fpr": fpr,
        "ground_truth_attack_count": int(np.sum(y_true == 1)),
        "ground_truth_normal_count": int(np.sum(y_true == 0)),
        "predicted_anomaly_count": int(np.sum(y_pred == 1)),
    }


def verify_no_ground_truth_leakage(
    df: Optional[pd.DataFrame] = None,
    samples: Optional[Sequence[Any]] = None,
    records: Optional[Sequence[Any]] = None,
    detector: Optional[Any] = None,
) -> bool:
    """Verify that zero ground-truth label columns or values leaked into pipeline artifacts.

    Audits:
    1. DataFrame columns against normalized candidate label names.
    2. MultimodalFeatureSample feature keys across all modalities.
    3. AnomalyDetector fitted feature names.
    4. AnomalyRecord detector and machine_id metadata strings.

    SCIENTIFIC LIMITATION NOTE:
    This function verifies that columns and metadata matching recognized target
    names are absent. It does NOT provide a cryptographic or statistical guarantee
    against unlabeled, adversarial, or arbitrarily obfuscated target columns.
    Schema auditing, numeric validation, and strict provenance control remain required.

    Raises
    ------
    ValueError : If any label column or feature matching LABEL_COLUMN_CANDIDATES is detected.

    Returns
    -------
    True if audit passes.
    """
    candidate_tokens = _NORMALIZED_LABEL_CANDIDATES

    def is_leaked(name: str) -> bool:
        cleaned = str(name).strip().lower()
        if cleaned in LABEL_COLUMN_CANDIDATES:
            return True
        norm = _normalize_label_token(name)
        return norm in candidate_tokens

    # 1. Audit DataFrame columns
    if df is not None:
        leaked_cols = [c for c in df.columns if is_leaked(str(c))]
        if leaked_cols:
            raise ValueError(
                f"Ground-truth leakage detected in DataFrame columns: {leaked_cols}"
            )

    # 2. Audit MultimodalFeatureSample feature keys
    if samples is not None:
        for s in samples:
            features_dict = getattr(s, "features", {})
            for mod_name, mod_feats in features_dict.items():
                for feat_key in mod_feats.keys():
                    base_channel = feat_key.split("__")[0]
                    if is_leaked(base_channel):
                        raise ValueError(
                            f"Ground-truth leakage detected in MultimodalFeatureSample feature: {feat_key}"
                        )

    # 3. Audit AnomalyDetector fitted feature names
    if detector is not None:
        feature_names = getattr(detector, "feature_names_", [])
        for feat in feature_names:
            base_channel = feat.split("__")[0]
            if is_leaked(base_channel):
                raise ValueError(
                    f"Ground-truth leakage detected in fitted detector feature: {feat}"
                )

    # 4. Audit AnomalyRecords metadata
    if records is not None:
        for r in records:
            det = str(getattr(r, "detector", ""))
            mid = str(getattr(r, "machine_id", ""))
            norm_det = _normalize_label_token(det)
            norm_mid = _normalize_label_token(mid)
            for cand in candidate_tokens:
                if len(cand) >= 4 and cand in norm_det:
                    raise ValueError(
                        f"Ground-truth leakage detected in AnomalyRecord.detector: '{det}' contains '{cand}'"
                    )
                if len(cand) >= 4 and cand in norm_mid:
                    raise ValueError(
                        f"Ground-truth leakage detected in AnomalyRecord.machine_id: '{mid}' contains '{cand}'"
                    )

    return True

