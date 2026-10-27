"""SWaT A4/A5 July 2019 Dataset Adapter and Experimental Pipeline Components.

This module provides a dedicated, scientifically defensible adapter for the
SWaT A4/A5 (July 2019) operational dataset.

Source Dataset Context:
- Recording date: 20 July 2019
- Testbed: iTrust Secure Water Treatment (SWaT) Testbed, Singapore
- Operating span: 04:30:00 UTC to 08:39:59.004013 UTC (~4.17 hours)
- Nominal cadence: 1 Hz (highly irregular with observed gaps up to 1801 s)
- Documented normal operation: 12:35 to 14:50 GMT+8 (04:35 to 06:50 UTC, 135 min)
- Telemetry format: Excel workbook (.xlsx), single sheet 'MST v2'
- Header structure: 3-row composite header (Stage Group, Tag Name, Measurement Type)
- Timestamps: ISO 8601 UTC with optional fractional seconds (e.g. '2019-07-20T04:30:02.004013Z')
- Attack schedule: 6 cyber-physical attack episodes documented in accompanying PDF (in GMT+8)
- Ground-truth labels: NOT present in the workbook; constructed post-prediction from schedule.

Scientific Ground Rules:
- Labels must NEVER leak into feature extraction, detector training, or prediction.
- Attacks occurring during telemetry gaps (A1, A2, A4) have 0 recorded rows and are unobservable.
  They must NEVER be counted as true negatives.
- Windows spanning large telemetry gaps must be excluded with explicit reasons.
- Actuator state semantics for novel registers (P1_STATE..P6_STATE) must not be invented.
  Where undocumented in source releases, states are preserved as unknown/unmapped.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd
import openpyxl

from tcmim.schemas import Modality, Provenance
from tcmim.data.swat import (
    SWAT_TAG_REGISTRY,
    SWAT_DEFAULT_ACTUATOR_STATE_MAP,
    SWaTProcessStage,
    SWaTTagInfo,
    SWaTTagType,
    _NORMALIZED_LABEL_CANDIDATES,
    _normalize_label_token,
)
from tcmim.data.windower import WindowedData


# ==============================================================================
# 1. Official Attack Ground Truth and Plant Operation Schedule (from PDF)
# ==============================================================================

SGT_OFFSET_HOURS: int = 8  # GMT+8 (Singapore Time) to UTC offset


@dataclass(frozen=True)
class A4A5Attack:
    """Official SWaT A4/A5 attack definition extracted from source documentation."""
    attack_id: str
    target_tags: Tuple[str, ...]
    target_stages: Tuple[str, ...]
    action: str
    intent: str
    start_sgt: str
    end_sgt: str
    start_utc: datetime
    end_utc: datetime
    duration_seconds: float
    boundary_convention: str = "closed [start, end]"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attack_id": self.attack_id,
            "target_tags": list(self.target_tags),
            "target_stages": list(self.target_stages),
            "action": self.action,
            "intent": self.intent,
            "start_sgt": self.start_sgt,
            "end_sgt": self.end_sgt,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "duration_seconds": self.duration_seconds,
            "boundary_convention": self.boundary_convention,
        }


# Verified against: "SWaT data collection_20-07-2019 v2.pdf"
SWAT_A4A5_ATTACK_SCHEDULE: Dict[str, A4A5Attack] = {
    "A1": A4A5Attack(
        attack_id="A1",
        target_tags=("FIT401",),
        target_stages=("P4",),
        action="Spoof value from 0.8 to 0.5",
        intent="To stop de-chlorination by switching off UV401",
        start_sgt="15:08:46",
        end_sgt="15:10:31",
        start_utc=datetime(2019, 7, 20, 7, 8, 46, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 7, 10, 31, tzinfo=timezone.utc),
        duration_seconds=105.0,
    ),
    "A2": A4A5Attack(
        attack_id="A2",
        target_tags=("LIT301",),
        target_stages=("P3",),
        action="Spoof value from 835 to 1024",
        intent="To eventually lead to underflow in T301",
        start_sgt="15:15:00",
        end_sgt="15:19:32",
        start_utc=datetime(2019, 7, 20, 7, 15, 0, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 7, 19, 32, tzinfo=timezone.utc),
        duration_seconds=272.0,
    ),
    "A3": A4A5Attack(
        attack_id="A3",
        target_tags=("P601",),
        target_stages=("P6",),
        action="Switch from OFF to ON",
        intent="To increase water in raw water tank",
        start_sgt="15:26:57",
        end_sgt="15:30:48",
        start_utc=datetime(2019, 7, 20, 7, 26, 57, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 7, 30, 48, tzinfo=timezone.utc),
        duration_seconds=231.0,
    ),
    "A4": A4A5Attack(
        attack_id="A4",
        target_tags=("MV201", "P101"),
        target_stages=("P2", "P1"),
        action="Switch from CLOSE to OPEN (MV201) and OFF to ON (P101)",
        intent="To overflow tank T301",
        start_sgt="15:38:50",
        end_sgt="15:46:20",
        start_utc=datetime(2019, 7, 20, 7, 38, 50, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 7, 46, 20, tzinfo=timezone.utc),
        duration_seconds=450.0,
    ),
    "A5": A4A5Attack(
        attack_id="A5",
        target_tags=("MV501",),
        target_stages=("P5",),
        action="Switch from OPEN to CLOSE",
        intent="To drain water from RO",
        start_sgt="15:54:00",
        end_sgt="15:56:00",
        start_utc=datetime(2019, 7, 20, 7, 54, 0, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 7, 56, 0, tzinfo=timezone.utc),
        duration_seconds=120.0,
    ),
    "A6": A4A5Attack(
        attack_id="A6",
        target_tags=("P301",),
        target_stages=("P3",),
        action="Switch from ON to OFF",
        intent="To halt stage 3 (UF process)",
        start_sgt="16:02:56",
        end_sgt="16:16:18",
        start_utc=datetime(2019, 7, 20, 8, 2, 56, tzinfo=timezone.utc),
        end_utc=datetime(2019, 7, 20, 8, 16, 18, tzinfo=timezone.utc),
        duration_seconds=802.0,
    ),
}

# Documented operational periods (verified from PDF)
SWAT_A4A5_PLANT_START_UTC: datetime = datetime(2019, 7, 20, 4, 35, 0, tzinfo=timezone.utc)
SWAT_A4A5_NORMAL_END_UTC: datetime = datetime(2019, 7, 20, 6, 50, 0, tzinfo=timezone.utc)
SWAT_A4A5_PLANT_STOP_UTC: datetime = datetime(2019, 7, 20, 8, 35, 0, tzinfo=timezone.utc)
SWAT_A4A5_PRE_START_BUFFER_UTC: Tuple[datetime, datetime] = (
    datetime(2019, 7, 20, 4, 30, 0, tzinfo=timezone.utc),
    datetime(2019, 7, 20, 4, 35, 0, tzinfo=timezone.utc),
)


# ==============================================================================
# 2. Tag Name Normalization and Channel Registry for A4/A5
# ==============================================================================

# Explicit mapping from row 2 workbook column names to standard compact tag names.
# Tested and verified against all 78 columns in SWaT_dataset_Jul 19 v2.xlsx.
A4A5_TAG_RENAME_MAP: Dict[str, str] = {
    # Timestamp
    "GMT +0": "timestamp",
    # Stage 1
    "FIT 101": "FIT101",
    "LIT 101": "LIT101",
    "MV 101": "MV101",
    "P1_STATE": "P1_STATE",
    "P101 Status": "P101",
    "P102 Status": "P102",
    # Stage 2
    "AIT 201": "AIT201",
    "AIT 202": "AIT202",
    "AIT 203": "AIT203",
    "FIT 201": "FIT201",
    "LS 201": "LS201",
    "LS 202": "LS202",
    "LSL 203": "LSL203",
    "LSLL 203": "LSLL203",
    "MV201": "MV201",
    "P2_STATE": "P2_STATE",
    "P201 Status": "P201",
    "P202 Status": "P202",
    "P203 Status": "P203",
    "P204 Status": "P204",
    "P205 Status": "P205",
    "P206 Status": "P206",
    "P207 Status": "P207",
    "P208 Status": "P208",
    # Stage 3
    "AIT 301": "AIT301",
    "AIT 302": "AIT302",
    "AIT 303": "AIT303",
    "DPIT 301": "DPIT301",
    "FIT 301": "FIT301",
    "LIT 301": "LIT301",
    "MV 301": "MV301",
    "MV 302": "MV302",
    "MV 303": "MV303",
    "MV 304": "MV304",
    "P3_STATE": "P3_STATE",
    "P301 Status": "P301",
    "P302 Status": "P302",
    # Stage 4
    "AIT 401": "AIT401",
    "AIT 402": "AIT402",
    "FIT 401": "FIT401",
    "LIT 401": "LIT401",
    "LS 401": "LS401",
    "P4_STATE": "P4_STATE",
    "P401 Status": "P401",
    "P402 Status": "P402",
    "P403 Status": "P403",
    "P404 Status": "P404",
    "UV401": "UV401",
    # Stage 5
    "AIT 501": "AIT501",
    "AIT 502": "AIT502",
    "AIT 503": "AIT503",
    "AIT 504": "AIT504",
    "FIT 501": "FIT501",
    "FIT 502": "FIT502",
    "FIT 503": "FIT503",
    "FIT 504": "FIT504",
    "MV 501": "MV501",
    "MV 502": "MV502",
    "MV 503": "MV503",
    "MV 504": "MV504",
    "P5_STATE": "P5_STATE",
    "P501 Status": "P501",
    "P502 Status": "P502",
    "PIT 501": "PIT501",
    "PIT 502": "PIT502",
    "PIT 503": "PIT503",
    # Stage 6
    "FIT 601": "FIT601",
    "LSH 601": "LSH601",
    "LSH 602": "LSH602",
    "LSH 603": "LSH603",
    "LSL 601": "LSL601",
    "LSL 602": "LSL602",
    "LSL 603": "LSL603",
    "P6 STATE": "P6_STATE",
    "P601 Status": "P601",
    "P602 Status": "P602",
    "P603 Status": "P603",
}

# Reverse lookup: compact name -> original workbook name
A4A5_REVERSE_TAG_MAP: Dict[str, str] = {
    v: k for k, v in A4A5_TAG_RENAME_MAP.items()
}

# 11 Categorical Level Switch Channels (Active / Inactive strings)
A4A5_LEVEL_SWITCH_TAGS: Tuple[str, ...] = (
    "LS201", "LS202", "LSL203", "LSLL203",
    "LS401",
    "LSH601", "LSH602", "LSH603", "LSL601", "LSL602", "LSL603",
)

# Documented Level-Switch Binary Encoding (readme.docx)
# In v1: Inactive=0, Active=1.
# Meaning: Active = condition triggered (e.g., LSH=Tank High, LSL=Tank Low).
A4A5_LEVEL_SWITCH_BINARY_MAP: Dict[str, float] = {
    "Active": 1.0,
    "Inactive": 0.0,
}

# 6 PLC State Registers (P1_STATE..P6_STATE)
A4A5_PLC_STATE_TAGS: Tuple[str, ...] = (
    "P1_STATE", "P2_STATE", "P3_STATE", "P4_STATE", "P5_STATE", "P6_STATE",
)

# Extended tag registry for A4/A5 instruments not in original SWaT 2015 51-tag registry
A4A5_EXTENDED_TAG_REGISTRY: Dict[str, SWaTTagInfo] = dict(SWAT_TAG_REGISTRY)

# Add stage 2 dosing pumps (expanded testbed)
A4A5_EXTENDED_TAG_REGISTRY.update({
    "P207": SWaTTagInfo("P207", SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "NaOCl dosing pump 3"),
    "P208": SWaTTagInfo("P208", SWaTTagType.ACTUATOR, SWaTProcessStage.P2, Modality.DIGITAL_STATE, "HCl dosing pump 3"),
})

# Add stage 3 analyzers (expanded testbed)
A4A5_EXTENDED_TAG_REGISTRY.update({
    "AIT301": SWaTTagInfo("AIT301", SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.UNKNOWN, "UF feed conductivity analyzer"),
    "AIT302": SWaTTagInfo("AIT302", SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.UNKNOWN, "UF feed pH analyzer"),
    "AIT303": SWaTTagInfo("AIT303", SWaTTagType.SENSOR, SWaTProcessStage.P3, Modality.UNKNOWN, "UF feed ORP analyzer"),
})

# Add 11 level switches (Modality.DIGITAL_STATE contact sensors)
for ls_tag in A4A5_LEVEL_SWITCH_TAGS:
    stage_match = re.search(r"(\d)", ls_tag)
    stage_num = stage_match.group(1) if stage_match else "0"
    stage_enum = SWaTProcessStage[f"P{stage_num}"] if f"P{stage_num}" in SWaTProcessStage.__members__ else None
    A4A5_EXTENDED_TAG_REGISTRY[ls_tag] = SWaTTagInfo(
        tag=ls_tag,
        tag_type=SWaTTagType.SENSOR,
        stage=stage_enum,
        modality=Modality.DIGITAL_STATE,
        description=f"Level switch {ls_tag}",
    )

# Add 6 PLC state registers (Modality.UNKNOWN: multi-step state registers, not binary actuators)
for state_tag in A4A5_PLC_STATE_TAGS:
    stage_num = state_tag[1]
    stage_enum = SWaTProcessStage[f"P{stage_num}"] if f"P{stage_num}" in SWaTProcessStage.__members__ else None
    A4A5_EXTENDED_TAG_REGISTRY[state_tag] = SWaTTagInfo(
        tag=state_tag,
        tag_type=SWaTTagType.CONTROL_SIGNAL,
        stage=stage_enum,
        modality=Modality.UNKNOWN,
        description=f"PLC Stage {stage_num} sequential state register",
    )

# Derived modality map for A4/A5
A4A5_MODALITY_MAP: Dict[str, Modality] = {
    tag: info.modality for tag, info in A4A5_EXTENDED_TAG_REGISTRY.items()
}

# Derived stage map for A4/A5
A4A5_STAGE_MAP: Dict[str, SWaTProcessStage] = {
    tag: info.stage for tag, info in A4A5_EXTENDED_TAG_REGISTRY.items() if info.stage is not None
}

# Actuator state map for A4/A5:
# Standard actuators: {1.0: 0, 2.0: 1} (1=OFF/CLOSED, 2=ON/OPEN)
# Novel state registers (P1_STATE..P6_STATE): mapped to {} (unknown) because their semantics
# are NOT defined in source documentation. Preserved as unknown, never invented!
A4A5_ACTUATOR_STATE_MAP: Dict[str, Dict[float, int]] = {}
for tag, info in A4A5_EXTENDED_TAG_REGISTRY.items():
    if info.tag_type == SWaTTagType.ACTUATOR:
        A4A5_ACTUATOR_STATE_MAP[tag] = dict(SWAT_DEFAULT_ACTUATOR_STATE_MAP)
    elif tag in A4A5_PLC_STATE_TAGS:
        # Documented policy: preserve unknown states as unknown.
        A4A5_ACTUATOR_STATE_MAP[tag] = {}


# ==============================================================================
# 3. Header Parsing and Workbook Loading
# ==============================================================================

@dataclass
class A4A5HeaderInfo:
    """Structure storing parsed 3-row composite header information."""
    stage_row: List[Optional[str]]
    tag_row: List[str]
    type_row: List[str]
    timestamp_col: str
    column_renames: Dict[str, str]
    original_columns: List[str]
    normalized_columns: List[str]


def parse_a4a5_composite_header(
    raw_header_rows: List[Tuple[Any, ...]],
) -> A4A5HeaderInfo:
    """Parse the 3-row composite header structure from raw Excel rows.

    Parameters
    ----------
    raw_header_rows : List of 3 tuples (row 1, row 2, row 3) from the Excel sheet.

    Returns
    -------
    A4A5HeaderInfo with parsed column identities and renaming mappings.

    Raises
    ------
    ValueError if header rows are malformed or missing required columns.
    """
    if len(raw_header_rows) < 3:
        raise ValueError(
            f"Expected at least 3 header rows for composite header parsing, got {len(raw_header_rows)}."
        )

    stage_row = [str(x).strip() if x is not None else None for x in raw_header_rows[0]]
    tag_row = [str(x).strip() if x is not None else "" for x in raw_header_rows[1]]
    type_row = [str(x).strip() if x is not None else "" for x in raw_header_rows[2]]

    n_cols = len(tag_row)
    if len(stage_row) != n_cols or len(type_row) != n_cols:
        raise ValueError(
            f"Header row length mismatch: stages={len(stage_row)}, tags={n_cols}, types={len(type_row)}."
        )

    # Identify timestamp column
    ts_col = None
    for i, (tag, ttype) in enumerate(zip(tag_row, type_row)):
        if "GMT" in tag.upper() or ttype.lower() == "timestamp":
            ts_col = tag
            break

    if ts_col is None:
        raise ValueError("Could not locate timestamp column in row 2/3 of workbook.")

    # Build renaming and check collisions
    renames: Dict[str, str] = {}
    normalized: List[str] = []
    seen_norm: Set[str] = set()

    for tag in tag_row:
        if tag in A4A5_TAG_RENAME_MAP:
            norm = A4A5_TAG_RENAME_MAP[tag]
        else:
            # Fallback for unrecognized tag: normalize whitespace
            norm = re.sub(r"\s+", "", tag)

        if norm in seen_norm:
            raise ValueError(f"Tag normalization collision detected for '{tag}' -> '{norm}'.")
        seen_norm.add(norm)
        renames[tag] = norm
        normalized.append(norm)

    return A4A5HeaderInfo(
        stage_row=stage_row,
        tag_row=tag_row,
        type_row=type_row,
        timestamp_col=ts_col,
        column_renames=renames,
        original_columns=list(tag_row),
        normalized_columns=normalized,
    )


def load_swat_a4a5_dataframe(
    xlsx_path: Union[str, Path],
    sheet_name: Union[str, int] = 0,
    encode_level_switches: bool = True,
    max_rows: Optional[int] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Load the SWaT A4/A5 July 2019 Excel workbook into a validated DataFrame.

    Enforces:
    - Direct .xlsx loading via openpyxl/pandas.
    - Correct parsing of 3-row composite header.
    - Strict UTC-aware datetime parsing of ISO 8601 timestamps (including 'Z' and fractions).
    - Monotonicity and duplicate timestamp validation.
    - Explicit channel renaming using A4A5_TAG_RENAME_MAP.
    - Preservation of original raw column names in metadata.
    - Preservation of raw data without silent row dropping.
    - Binarization of level-switch channels (Active=1.0, Inactive=0.0).
    - Ground-truth leakage prevention: raises if any label column is found.

    Parameters
    ----------
    xlsx_path : Path to SWaT_dataset_Jul 19 v2.xlsx.
    sheet_name : Name or index of sheet (default 0 / 'MST v2').
    encode_level_switches : If True, converts Active/Inactive strings to 1.0/0.0.
    max_rows : Optional cap on rows loaded (useful for fast testing).

    Returns
    -------
    df : Cleaned telemetry DataFrame indexed by UTC datetime.
    metadata : Comprehensive dictionary of load provenance and header info.
    """
    path = Path(xlsx_path)
    if not path.is_file():
        raise FileNotFoundError(f"SWaT A4/A5 workbook not found at: {path}")

    # Inspect first 3 rows using openpyxl for header inspection
    wb = openpyxl.load_workbook(str(path), read_only=True)
    try:
        sheet = wb[sheet_name] if isinstance(sheet_name, str) else wb.worksheets[sheet_name]
        raw_header = list(sheet.iter_rows(min_row=1, max_row=3, values_only=True))
    finally:
        wb.close()

    header_info = parse_a4a5_composite_header(raw_header)

    # Read the data body: header=1 uses row 2 (0-indexed 1) as column headers
    # Row 3 (descriptor row) is row 0 of the returned DataFrame and must be dropped.
    df_raw = pd.read_excel(
        str(path),
        sheet_name=sheet_name,
        header=1,
        nrows=max_rows + 1 if max_rows is not None else None,
    )

    if len(df_raw) < 1:
        raise ValueError(f"Workbook {path} contains no data rows.")

    # Drop descriptor row (e.g. 'timestamp', 'value', 'value'...)
    df_data = df_raw.iloc[1:].copy().reset_index(drop=True)

    # Validate timestamp column presence
    ts_col = header_info.timestamp_col
    if ts_col not in df_data.columns:
        # Try case-insensitive matching
        for c in df_data.columns:
            if str(c).strip().upper() == ts_col.upper():
                ts_col = c
                break
        else:
            raise ValueError(f"Timestamp column '{ts_col}' not found in workbook.")

    # Parse ISO 8601 UTC timestamps (handles 'Z' and microsecond fractions)
    try:
        ts_series = pd.to_datetime(df_data[ts_col], format="ISO8601", utc=True)
    except Exception as exc:
        raise ValueError(f"Failed to parse ISO 8601 timestamps in '{ts_col}': {exc}") from exc

    if ts_series.isnull().any():
        n_nat = int(ts_series.isnull().sum())
        raise ValueError(f"Timestamp parsing produced {n_nat} NaT values.")

    # Check duplicates and monotonicity
    n_duplicates = int(ts_series.duplicated().sum())
    if n_duplicates > 0:
        raise ValueError(f"Found {n_duplicates} duplicate timestamps in dataset.")

    is_monotonic = ts_series.is_monotonic_increasing
    if not is_monotonic:
        raise ValueError("Timestamps are not strictly monotonically increasing.")

    # Set datetime index
    df_data.index = pd.DatetimeIndex(ts_series, name="timestamp")
    df_data.drop(columns=[ts_col], inplace=True)

    # Rename columns using verified mapping
    df_data.rename(columns=header_info.column_renames, inplace=True)

    # Leakage check: ensure no label column exists in the dataset
    for col in df_data.columns:
        norm_col = _normalize_label_token(col)
        if norm_col in _NORMALIZED_LABEL_CANDIDATES:
            raise ValueError(
                f"Ground-truth leakage detected: Column '{col}' resembles an attack label."
            )

    # Process level-switch categorical columns
    level_switch_conversions: Dict[str, Dict[str, int]] = {}
    if encode_level_switches:
        for ls_tag in A4A5_LEVEL_SWITCH_TAGS:
            if ls_tag in df_data.columns:
                val_counts = df_data[ls_tag].value_counts().to_dict()
                level_switch_conversions[ls_tag] = {str(k): int(v) for k, v in val_counts.items()}
                # Map to numeric float
                mapped = df_data[ls_tag].map(A4A5_LEVEL_SWITCH_BINARY_MAP)
                # Keep float type
                df_data[ls_tag] = pd.to_numeric(mapped, errors="coerce")

    # Convert all remaining columns to numeric float
    non_numeric_cols = []
    for col in df_data.columns:
        if not pd.api.types.is_numeric_dtype(df_data[col]):
            converted = pd.to_numeric(df_data[col], errors="coerce")
            if converted.isnull().all() and len(df_data) > 0:
                non_numeric_cols.append(col)
            else:
                df_data[col] = converted

    metadata: Dict[str, Any] = {
        "source_file": str(path.resolve()),
        "sheet_name": str(sheet_name),
        "total_rows_loaded": len(df_data),
        "total_columns": len(df_data.columns),
        "timestamp_start_utc": df_data.index[0].isoformat() if len(df_data) > 0 else None,
        "timestamp_end_utc": df_data.index[-1].isoformat() if len(df_data) > 0 else None,
        "duration_seconds": (df_data.index[-1] - df_data.index[0]).total_seconds() if len(df_data) > 0 else 0.0,
        "original_columns": header_info.original_columns,
        "column_renames": header_info.column_renames,
        "level_switch_conversions": level_switch_conversions,
        "non_numeric_columns": non_numeric_cols,
        "plc_state_columns": [c for c in A4A5_PLC_STATE_TAGS if c in df_data.columns],
        "header_stages": header_info.stage_row,
    }

    return df_data, metadata


# ==============================================================================
# 4. Data Quality and Cadence Analysis
# ==============================================================================

@dataclass
class A4A5DataQualityReport:
    """Detailed summary of data quality, sampling cadence, and gaps."""
    total_rows: int
    duration_seconds: float
    nominal_hz: float
    observed_mean_interval_s: float
    observed_median_interval_s: float
    min_interval_s: float
    max_interval_s: float
    gap_count_gt_3s: int
    gap_count_gt_10s: int
    gap_count_gt_30s: int
    gap_count_gt_600s: int
    max_gap_seconds: float
    missing_values_by_column: Dict[str, int]
    constant_columns: List[str]
    normal_period_row_count: int
    pre_start_row_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_swat_a4a5_telemetry(df: pd.DataFrame) -> A4A5DataQualityReport:
    """Analyze sampling continuity, gaps, missing values, and operational subsets.

    Parameters
    ----------
    df : Telemetry DataFrame indexed by UTC datetime.

    Returns
    -------
    A4A5DataQualityReport with comprehensive quality metrics.
    """
    if len(df) == 0:
        return A4A5DataQualityReport(
            total_rows=0, duration_seconds=0.0, nominal_hz=1.0,
            observed_mean_interval_s=0.0, observed_median_interval_s=0.0,
            min_interval_s=0.0, max_interval_s=0.0,
            gap_count_gt_3s=0, gap_count_gt_10s=0, gap_count_gt_30s=0,
            gap_count_gt_600s=0, max_gap_seconds=0.0,
            missing_values_by_column={}, constant_columns=[],
            normal_period_row_count=0, pre_start_row_count=0,
        )

    ts = df.index.to_series()
    deltas = ts.diff().dt.total_seconds().dropna()

    mean_s = float(deltas.mean()) if len(deltas) > 0 else 0.0
    med_s = float(deltas.median()) if len(deltas) > 0 else 0.0
    min_s = float(deltas.min()) if len(deltas) > 0 else 0.0
    max_s = float(deltas.max()) if len(deltas) > 0 else 0.0

    # Counts in various gap tiers
    g3 = int((deltas > 3.0).sum())
    g10 = int((deltas > 10.0).sum())
    g30 = int((deltas > 30.0).sum())
    g600 = int((deltas > 600.0).sum())

    missing = {col: int(df[col].isnull().sum()) for col in df.columns if df[col].isnull().sum() > 0}
    constant = [col for col in df.columns if df[col].nunique(dropna=False) <= 1]

    # Operational periods
    pre_start_mask = (df.index >= SWAT_A4A5_PRE_START_BUFFER_UTC[0]) & (df.index < SWAT_A4A5_PRE_START_BUFFER_UTC[1])
    normal_mask = (df.index >= SWAT_A4A5_PLANT_START_UTC) & (df.index <= SWAT_A4A5_NORMAL_END_UTC)

    return A4A5DataQualityReport(
        total_rows=len(df),
        duration_seconds=float((df.index[-1] - df.index[0]).total_seconds()),
        nominal_hz=1.0,
        observed_mean_interval_s=mean_s,
        observed_median_interval_s=med_s,
        min_interval_s=min_s,
        max_interval_s=max_s,
        gap_count_gt_3s=g3,
        gap_count_gt_10s=g10,
        gap_count_gt_30s=g30,
        gap_count_gt_600s=g600,
        max_gap_seconds=max_s,
        missing_values_by_column=missing,
        constant_columns=constant,
        normal_period_row_count=int(normal_mask.sum()),
        pre_start_row_count=int(pre_start_mask.sum()),
    )


# ==============================================================================
# 5. Attack Observability and Coverage Analysis
# ==============================================================================

class AttackObservability(Enum):
    OBSERVABLE = "OBSERVABLE"
    PARTIALLY_OBSERVABLE = "PARTIALLY_OBSERVABLE"
    UNOBSERVABLE = "UNOBSERVABLE"


@dataclass
class AttackCoverageInfo:
    """Summary of recorded telemetry coverage for a documented attack episode."""
    attack_id: str
    target_tags: List[str]
    start_utc: str
    end_utc: str
    duration_seconds: float
    observed_rows: int
    expected_rows_at_1hz: int
    coverage_fraction: float
    observability: AttackObservability
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["observability"] = self.observability.value
        return d


def compute_a4a5_attack_coverage(
    df: pd.DataFrame,
    schedule: Dict[str, A4A5Attack] = SWAT_A4A5_ATTACK_SCHEDULE,
) -> Dict[str, AttackCoverageInfo]:
    """Calculate recorded telemetry coverage for each official attack episode.

    Scientifically critical rule:
    Attacks A1, A2, and A4 have ZERO recorded telemetry rows in the workbook
    because they coincide with data acquisition gaps. They are classified as
    UNOBSERVABLE and must NEVER be counted as true negatives in evaluation.

    Parameters
    ----------
    df : Telemetry DataFrame indexed by UTC datetime.
    schedule : Attack schedule dictionary.

    Returns
    -------
    Dictionary mapping attack ID to AttackCoverageInfo.
    """
    coverage: Dict[str, AttackCoverageInfo] = {}

    for attack_id, attack in schedule.items():
        mask = (df.index >= attack.start_utc) & (df.index <= attack.end_utc)
        observed_rows = int(mask.sum())
        expected_rows = int(attack.duration_seconds)
        cov_frac = observed_rows / expected_rows if expected_rows > 0 else 0.0

        if observed_rows == 0:
            obs = AttackObservability.UNOBSERVABLE
            notes = (
                f"Attack {attack_id} falls entirely within an unobserved telemetry gap. "
                "ZERO rows recorded. Cannot be evaluated; must NOT be counted as True Negative."
            )
        elif observed_rows < expected_rows * 0.8:
            obs = AttackObservability.PARTIALLY_OBSERVABLE
            notes = (
                f"Attack {attack_id} observed with irregular cadence ({observed_rows}/{expected_rows} rows, "
                f"{cov_frac:.1%} coverage)."
            )
        else:
            obs = AttackObservability.OBSERVABLE
            notes = f"Attack {attack_id} fully observable ({observed_rows} rows)."

        coverage[attack_id] = AttackCoverageInfo(
            attack_id=attack_id,
            target_tags=list(attack.target_tags),
            start_utc=attack.start_utc.isoformat(),
            end_utc=attack.end_utc.isoformat(),
            duration_seconds=attack.duration_seconds,
            observed_rows=observed_rows,
            expected_rows_at_1hz=expected_rows,
            coverage_fraction=round(cov_frac, 4),
            observability=obs,
            notes=notes,
        )

    return coverage


# ==============================================================================
# 6. Gap-Aware Windowing and Manifest Generation
# ==============================================================================

@dataclass
class WindowAuditRecord:
    """Audit metadata for an individual sliding window."""
    window_id: str
    start_time: str
    end_time: str
    n_samples: int
    expected_samples_nominal: int
    observed_cadence_hz: float
    max_internal_gap_s: float
    coverage_frac: float
    is_eligible: bool
    ineligibility_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GapAwareWindowBuilder:
    """Sliding window builder that validates internal continuity and excludes gap-spanning windows.

    Windows must never silently span a large telemetry gap. A window containing
    observations separated by a 30-minute or 10-minute gap will produce distorted
    temporal features (e.g. duty cycle, trend) if treated as continuous.

    Parameters
    ----------
    window_seconds : Duration of each window in seconds (default 30.0).
    step_seconds : Step between successive window start times (default 30.0).
    min_samples : Minimum number of samples required to form a window (default 2).
    max_internal_gap_s : Maximum permissible gap between consecutive samples inside
                         a window. If exceeded, the window is marked ineligible.
                         Default: 15.0 s (half of a 30s window).
    """

    def __init__(
        self,
        window_seconds: float = 30.0,
        step_seconds: float = 30.0,
        min_samples: int = 2,
        max_internal_gap_s: Optional[float] = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be positive, got {window_seconds}")
        if step_seconds <= 0:
            raise ValueError(f"step_seconds must be positive, got {step_seconds}")
        if min_samples < 1:
            raise ValueError(f"min_samples must be >= 1, got {min_samples}")

        self.window_seconds = float(window_seconds)
        self.step_seconds = float(step_seconds)
        self.min_samples = int(min_samples)
        # Default to half the window length or at most 30s
        self.max_internal_gap_s = (
            float(max_internal_gap_s)
            if max_internal_gap_s is not None
            else min(30.0, self.window_seconds / 2.0)
        )

    def build_and_audit(
        self,
        df: pd.DataFrame,
        machine_id: str = "SWAT_A4A5",
        provenance: Provenance = Provenance.PUBLIC_DATASET,
    ) -> Tuple[List[WindowedData], pd.DataFrame]:
        """Build sliding windows and produce an exhaustive audit manifest.

        Parameters
        ----------
        df : Cleaned telemetry DataFrame indexed by UTC datetime.
        machine_id : Machine or subsystem identifier.
        provenance : Data provenance enum.

        Returns
        -------
        eligible_windows : List of WindowedData objects passing all eligibility checks.
        manifest_df : DataFrame recording metadata for ALL evaluated windows (both
                      eligible and ineligible) with reasons for any exclusions.
        """
        if len(df) == 0:
            return [], pd.DataFrame()

        min_ts = df.index.min()
        max_ts = df.index.max()

        window_delta = timedelta(seconds=self.window_seconds)
        step_delta = timedelta(seconds=self.step_seconds)

        eligible_windows: List[WindowedData] = []
        manifest_records: List[Dict[str, Any]] = []

        window_idx = 0
        current_start = min_ts

        while current_start + window_delta <= max_ts + step_delta:
            current_end = current_start + window_delta
            window_id = f"{machine_id}_w_{window_idx:06d}"

            # Slice window rows [start, end)
            mask = (df.index >= current_start) & (df.index < current_end)
            w_df = df.loc[mask]
            n_samples = len(w_df)

            expected_nominal = int(round(self.window_seconds * 1.0))
            obs_cadence = (n_samples / self.window_seconds) if self.window_seconds > 0 else 0.0

            # Compute internal gap and continuity
            max_gap = 0.0
            if n_samples >= 2:
                sample_deltas = w_df.index.to_series().diff().dt.total_seconds().dropna()
                max_gap = float(sample_deltas.max()) if len(sample_deltas) > 0 else 0.0
            elif n_samples == 1:
                max_gap = self.window_seconds

            coverage_frac = min(1.0, n_samples / expected_nominal) if expected_nominal > 0 else 0.0

            # Eligibility evaluation
            is_eligible = True
            reason = "ELIGIBLE"

            if n_samples < self.min_samples:
                is_eligible = False
                reason = f"INSUFFICIENT_SAMPLES ({n_samples} < {self.min_samples})"
            elif max_gap > self.max_internal_gap_s:
                is_eligible = False
                reason = f"EXCEEDS_GAP_THRESHOLD (max_gap={max_gap:.1f}s > {self.max_internal_gap_s:.1f}s)"

            manifest_records.append({
                "window_id": window_id,
                "start_time": current_start.isoformat(),
                "end_time": current_end.isoformat(),
                "n_samples": n_samples,
                "expected_samples_nominal": expected_nominal,
                "observed_cadence_hz": round(obs_cadence, 4),
                "max_internal_gap_s": round(max_gap, 2),
                "coverage_frac": round(coverage_frac, 4),
                "is_eligible": is_eligible,
                "ineligibility_reason": reason,
            })

            if is_eligible:
                w_obj = WindowedData(
                    machine_id=machine_id,
                    window_start=current_start.to_pydatetime(),
                    window_end=current_end.to_pydatetime(),
                    data=w_df.copy(),
                    provenance=provenance,
                    window_index=window_idx,
                )
                eligible_windows.append(w_obj)

            current_start += step_delta
            window_idx += 1

        manifest_df = pd.DataFrame(manifest_records)
        return eligible_windows, manifest_df


# ==============================================================================
# 7. Post-Prediction Attack Label Construction
# ==============================================================================

def construct_a4a5_window_labels(
    windows: List[WindowedData],
    schedule: Dict[str, A4A5Attack] = SWAT_A4A5_ATTACK_SCHEDULE,
    rule: str = "majority",
    exclude_unobservable: bool = True,
    unobservable_attack_ids: Optional[Set[str]] = None,
) -> pd.Series:
    """Construct binary ground-truth labels for windows strictly post-prediction.

    Scientifically critical rules:
    1. Labels are NEVER constructed or accessed during feature extraction, fitting,
       detector training, or anomaly scoring.
    2. Overlap is computed using calendar duration, not row count (because sampling
       is irregular).
       - 'majority': positive if >50% of the window duration overlaps an attack interval.
       - 'any': positive if any fraction of the window overlaps an attack interval.
    3. Unobservable attack periods:
       If `exclude_unobservable=True` and unobservable attacks are identified,
       windows overlapping unobservable attacks are assigned `np.nan` (excluded from
       evaluation), NEVER labeled 0 (normal). Labeling unobserved attack periods as
       normal would corrupt false-positive / true-negative metrics.

    Parameters
    ----------
    windows : List of WindowedData objects.
    schedule : Official attack schedule.
    rule : 'majority' or 'any'.
    exclude_unobservable : If True, returns np.nan for windows in unobservable attacks.
    unobservable_attack_ids : Optional set of attack IDs with 0 observed coverage.

    Returns
    -------
    pd.Series indexed by window_id with values 0.0, 1.0, or np.nan.
    """
    if rule not in ("majority", "any"):
        raise ValueError(f"Rule must be 'majority' or 'any', got '{rule}'.")

    unobs_ids = set(unobservable_attack_ids) if unobservable_attack_ids is not None else set()
    observable_ids = [aid for aid in schedule.keys() if aid not in unobs_ids]

    labels: Dict[str, float] = {}

    for i, w in enumerate(windows):
        ws = getattr(w, "window_start", getattr(w, "start_time", None))
        we = getattr(w, "window_end", getattr(w, "end_time", None))
        w_id = getattr(w, "window_id", f"{getattr(w, 'machine_id', 'w')}_w_{getattr(w, 'window_index', i):06d}")

        if ws is None or we is None:
            continue
        w_dur = (we - ws).total_seconds()
        if w_dur <= 0:
            labels[w_id] = 0.0
            continue

        # Check unobservable attacks first
        in_unobservable = False
        if exclude_unobservable and unobs_ids:
            for aid in unobs_ids:
                if aid in schedule:
                    atk = schedule[aid]
                    overlap_start = max(ws, atk.start_utc)
                    overlap_end = min(we, atk.end_utc)
                    if overlap_start < overlap_end:
                        in_unobservable = True
                        break

        if in_unobservable:
            labels[w_id] = np.nan
            continue

        # Evaluate observable attacks
        total_overlap_s = 0.0
        for aid in observable_ids:
            atk = schedule[aid]
            overlap_start = max(ws, atk.start_utc)
            overlap_end = min(we, atk.end_utc)
            if overlap_start < overlap_end:
                total_overlap_s += (overlap_end - overlap_start).total_seconds()

        if rule == "any":
            labels[w_id] = 1.0 if total_overlap_s > 0 else 0.0
        elif rule == "majority":
            labels[w_id] = 1.0 if (total_overlap_s / w_dur) > 0.5 else 0.0

    return pd.Series(labels, name="ground_truth_label")


# ==============================================================================
# 8. Post-Prediction Metrics and Evaluation
# ==============================================================================

@dataclass
class A4A5EvaluationMetrics:
    """Scientific evaluation metrics separating observable from unobservable episodes."""
    total_eligible_windows: int
    evaluated_windows: int
    excluded_windows_unobservable_attacks: int
    n_positive_windows: int
    n_negative_windows: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: Optional[float]
    recall: Optional[float]
    f1_score: Optional[float]
    accuracy: Optional[float]
    observable_attack_detection: Dict[str, Dict[str, Any]]
    unobservable_attacks_summary: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def evaluate_a4a5_predictions(
    predictions: pd.Series,
    labels: pd.Series,
    windows: List[WindowedData],
    schedule: Dict[str, A4A5Attack] = SWAT_A4A5_ATTACK_SCHEDULE,
    unobservable_attack_ids: Optional[Set[str]] = None,
) -> A4A5EvaluationMetrics:
    """Evaluate detector predictions against post-prediction labels.

    Handles:
    - Exclusion of NaN labels (unobservable periods).
    - Honest calculation of precision, recall, F1 (returns None when undefined).
    - Per-episode detection audit for observable attacks.
    - Explicit non-evaluation of unobservable attacks.

    Parameters
    ----------
    predictions : Binary 0/1 prediction series indexed by window_id.
    labels : Ground-truth label series indexed by window_id.
    windows : List of evaluated WindowedData objects.
    schedule : Attack schedule.
    unobservable_attack_ids : Optional set of attack IDs that had 0 rows.

    Returns
    -------
    A4A5EvaluationMetrics object.
    """
    unobs_ids = set(unobservable_attack_ids) if unobservable_attack_ids is not None else set()
    obs_ids = [aid for aid in schedule.keys() if aid not in unobs_ids]

    # Align on common window_ids
    common_idx = predictions.index.intersection(labels.index)
    preds = predictions.loc[common_idx]
    labs = labels.loc[common_idx]

    # Exclude unobservable attack periods (NaN)
    valid_mask = ~labs.isnull()
    eval_preds = preds.loc[valid_mask].astype(int)
    eval_labs = labs.loc[valid_mask].astype(int)

    n_excluded = int((~valid_mask).sum())
    n_total = len(common_idx)
    n_eval = len(eval_labs)

    n_pos = int((eval_labs == 1).sum())
    n_neg = int((eval_labs == 0).sum())

    tp = int(((eval_preds == 1) & (eval_labs == 1)).sum())
    fp = int(((eval_preds == 1) & (eval_labs == 0)).sum())
    tn = int(((eval_preds == 0) & (eval_labs == 0)).sum())
    fn = int(((eval_preds == 0) & (eval_labs == 1)).sum())

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall) / (precision + recall) if (precision and recall and (precision + recall) > 0) else None
    accuracy = (tp + tn) / n_eval if n_eval > 0 else None

    # Per-episode detection audit for observable attacks
    obs_detection: Dict[str, Dict[str, Any]] = {}

    for aid in obs_ids:
        atk = schedule[aid]
        atk_windows = []
        for i, w in enumerate(windows):
            w_id = getattr(w, "window_id", f"{getattr(w, 'machine_id', 'w')}_w_{getattr(w, 'window_index', i):06d}")
            ws = getattr(w, "window_start", getattr(w, "start_time", None))
            we = getattr(w, "window_end", getattr(w, "end_time", None))
            if ws and we and w_id in eval_preds.index and max(ws, atk.start_utc) < min(we, atk.end_utc):
                atk_windows.append((w_id, ws, we))

        detected = any(eval_preds.loc[wid] == 1 for wid, _, _ in atk_windows) if atk_windows else False
        first_alert_delay_s = None
        if detected:
            alert_times = [
                (ws - atk.start_utc).total_seconds()
                for wid, ws, _ in atk_windows
                if eval_preds.loc[wid] == 1
            ]
            first_alert_delay_s = max(0.0, float(min(alert_times)))

        obs_detection[aid] = {
            "target_tags": list(atk.target_tags),
            "target_stages": list(atk.target_stages),
            "overlapping_windows_count": len(atk_windows),
            "detected": detected,
            "detection_delay_seconds": first_alert_delay_s,
        }

    unobs_summary = {
        aid: "UNOBSERVABLE (0 rows recorded during gap; excluded from evaluation)."
        for aid in unobs_ids
    }

    return A4A5EvaluationMetrics(
        total_eligible_windows=n_total,
        evaluated_windows=n_eval,
        excluded_windows_unobservable_attacks=n_excluded,
        n_positive_windows=n_pos,
        n_negative_windows=n_neg,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=round(precision, 4) if precision is not None else None,
        recall=round(recall, 4) if recall is not None else None,
        f1_score=round(f1, 4) if f1 is not None else None,
        accuracy=round(accuracy, 4) if accuracy is not None else None,
        observable_attack_detection=obs_detection,
        unobservable_attacks_summary=unobs_summary,
    )


# ==============================================================================
# 10. Operational Clustered False-Alarm Incident Metrics
# ==============================================================================

def count_clustered_false_alarms(
    predictions: Union[pd.Series, np.ndarray, List[int]],
    ground_truth: Union[pd.Series, np.ndarray, List[float]],
) -> Tuple[int, int]:
    """Count false-positive windows and clustered false-alarm incidents.

    Requirements:
    - A false-positive window is predicted anomalous (1) whose ground-truth label is normal (0.0).
    - Consecutive false-positive windows form one operational false-alarm incident.
    - A positive or attack-labelled window (label == 1.0) breaks a false-alarm cluster.
    - Consecutive means adjacent windows in the sequence.

    Parameters
    ----------
    predictions  : Binary predictions (0=normal, 1=anomaly).
    ground_truth : Ground-truth labels (0.0=normal, 1.0=attack).

    Returns
    -------
    (fp_windows, clustered_incidents) : Tuple of integer counts.
    """
    preds = np.asarray(predictions, dtype=int)
    labels = np.asarray(ground_truth, dtype=float)

    if len(preds) != len(labels):
        raise ValueError(f"Length mismatch: {len(preds)} predictions vs {len(labels)} labels.")

    if len(preds) == 0:
        return 0, 0

    is_fp = (preds == 1) & (labels == 0.0)

    fp_windows = int(is_fp.sum())
    clustered_incidents = 0
    in_cluster = False

    for flag in is_fp:
        if flag:
            if not in_cluster:
                clustered_incidents += 1
                in_cluster = True
        else:
            in_cluster = False

    return fp_windows, clustered_incidents


def compute_clustered_false_alarm_metrics(
    predictions: Union[pd.Series, np.ndarray, List[int]],
    ground_truth: Union[pd.Series, np.ndarray, List[float]],
    duration_hours: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute detailed clustered false-alarm metrics.

    Parameters
    ----------
    predictions    : Binary predictions.
    ground_truth   : Ground-truth labels.
    duration_hours : Optional duration of evaluated partition in hours.

    Returns
    -------
    Dict containing fp_windows, clustered_incidents, and per-hour rates.
    """
    fp_windows, incidents = count_clustered_false_alarms(predictions, ground_truth)

    fp_windows_per_hour = None
    incidents_per_hour = None
    if duration_hours and duration_hours > 0:
        fp_windows_per_hour = round(fp_windows / duration_hours, 2)
        incidents_per_hour = round(incidents / duration_hours, 2)

    return {
        "false_positive_windows": fp_windows,
        "clustered_false_alarm_incidents": incidents,
        "false_positive_windows_per_hour": fp_windows_per_hour,
        "clustered_false_alarms_per_hour": incidents_per_hour,
    }

