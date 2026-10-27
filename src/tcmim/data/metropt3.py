"""
TCMIM — MetroPT-3 dataset loader (S0, M1).

The MetroPT-3 dataset (UCI ML Repository) contains ~1.5 M rows of data
from a single air compressor sampled at ~10-second intervals.

Columns and their TCMIM modality mapping
-----------------------------------------
timestamp       — datetime index
TP2             — PRESSURE   (compressor output pressure, bar)
TP3             — PRESSURE   (pneumatic panel pressure, bar)
H1              — PRESSURE   (pressure sensor H1, bar)
DV_pressure     — PRESSURE   (pressure sensor DV, bar)
Reservoirs      — PRESSURE   (reservoirs pressure, bar)
Oil_temperature — TEMPERATURE (oil temperature, °C)
Motor_current   — CURRENT    (motor current, A)
COMP            — DIGITAL_STATE (compressor status, 0/1)
DV_eletric      — DIGITAL_STATE (DV electric status, 0/1)
Towers          — DIGITAL_STATE (towers status, 0/1)
MPG             — DIGITAL_STATE (MPG status, 0/1)
LPS             — DIGITAL_STATE (LPS status, 0/1)
Pressure_switch — DIGITAL_STATE (pressure switch, 0/1)
Oil_level       — DIGITAL_STATE (oil level indicator, 0/1)
Caudal_impulses — FLOW_PULSE  (flow pulse count, raw — NO physical
                               calibration factor applied; see FR-FE-4)

INTEGRITY NOTES
---------------
- MetroPT-3 is a single-machine dataset. It MUST NOT be used to make
  cross-machine propagation performance claims (PRD integrity rule 5).
- Caudal_impulses is a raw pulse count. No physical flow rate conversion
  is applied here because no calibration data exists (FR-FE-4 / rule 6).
- All samples carry provenance = PUBLIC_DATASET.
- Machine ID is fixed to 'metropt3_compressor' to distinguish from
  hardware nodes.

Usage
-----
>>> from tcmim.data.metropt3 import load_metropt3
>>> samples = load_metropt3("data/raw/MetroPT3(AirCompressor).csv")
>>> len(samples)
1516948   # approximate
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from tcmim.schemas import Modality, Provenance, SensorSample

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Column → Modality mapping for MetroPT-3
# --------------------------------------------------------------------------

METROPT3_MODALITY_MAP: Dict[str, Modality] = {
    "TP2":             Modality.PRESSURE,
    "TP3":             Modality.PRESSURE,
    "H1":              Modality.PRESSURE,
    "DV_pressure":     Modality.PRESSURE,
    "Reservoirs":      Modality.PRESSURE,
    "Oil_temperature": Modality.TEMPERATURE,
    "Motor_current":   Modality.CURRENT,
    "COMP":            Modality.DIGITAL_STATE,
    "DV_eletric":      Modality.DIGITAL_STATE,
    "Towers":          Modality.DIGITAL_STATE,
    "MPG":             Modality.DIGITAL_STATE,
    "LPS":             Modality.DIGITAL_STATE,
    "Pressure_switch": Modality.DIGITAL_STATE,
    "Oil_level":       Modality.DIGITAL_STATE,
    "Caudal_impulses": Modality.FLOW_PULSE,
}

# Columns to ingest (skip Unnamed index column and timestamp)
SENSOR_COLUMNS: List[str] = list(METROPT3_MODALITY_MAP.keys())

# Physical validity ranges (None means no bound on that side).
# These ranges are derived from the MetroPT-3 paper; they act as a
# coarse sanity check, NOT as calibrated limits.
PHYSICAL_RANGES: Dict[str, tuple] = {
    "TP2":             (-1.0, 15.0),   # bar — can briefly read ~−0.03
    "TP3":             (-1.0, 15.0),
    "H1":              (-1.0, 15.0),
    "DV_pressure":     (-1.0, 15.0),
    "Reservoirs":      (-1.0, 15.0),
    "Oil_temperature": (-10.0, 120.0), # °C
    "Motor_current":   (0.0, 50.0),    # A
    "COMP":            (0.0, 1.0),
    "DV_eletric":      (0.0, 1.0),
    "Towers":          (0.0, 1.0),
    "MPG":             (0.0, 1.0),
    "LPS":             (0.0, 1.0),
    "Pressure_switch": (0.0, 1.0),
    "Oil_level":       (0.0, 1.0),
    "Caudal_impulses": (0.0, 1e9),     # raw pulse count — unbounded above
}

MACHINE_ID = "metropt3_compressor"
SOURCE_ID  = "metropt3_uci"


def resolve_metropt3_path(explicit_path: Optional[str | Path] = None) -> Optional[Path]:
    """Resolve the MetroPT-3 CSV path from an explicit argument, environment, or repository standard locations.

    Priority order:
    1. explicit_path (if provided and exists)
    2. TCMIM_METROPT3_PATH environment variable (if set and exists)
    3. data/raw/MetroPT3(AirCompressor).csv (relative to current working directory)
    4. MetroPT3(AirCompressor).csv (repository root)
    """
    if explicit_path is not None:
        p = Path(explicit_path)
        return p if p.exists() else None

    env_path = os.environ.get("TCMIM_METROPT3_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    candidates = [
        Path("data/raw/MetroPT3(AirCompressor).csv"),
        Path("MetroPT3(AirCompressor).csv"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_metropt3(
    csv_path: str | Path,
    *,
    columns: Optional[List[str]] = None,
    max_rows: Optional[int] = None,
    validate: bool = True,
) -> List[SensorSample]:
    """Load MetroPT-3 CSV into a flat list of SensorSample objects.

    Parameters
    ----------
    csv_path : Path to the MetroPT-3 CSV file.
    columns  : Sensor columns to load (default: all SENSOR_COLUMNS).
    max_rows : If given, only the first *max_rows* rows are processed
               (useful for quick sanity checks / CI).
    validate : If True, apply range and monotonicity validation and log
               warnings for out-of-range values.

    Returns
    -------
    List of SensorSample — one per (row × column) combination.
    Rows with NaN values in a column are skipped for that column and
    a warning is logged.

    Notes
    -----
    This function does NOT raise on out-of-range values — it logs them
    as warnings and tags the corresponding sample with a note.  Callers
    that need strict filtering should post-process using
    ``tcmim.data.validator.filter_range_violations``.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"MetroPT-3 CSV not found at: {csv_path}")

    cols_to_load = columns if columns is not None else SENSOR_COLUMNS
    unknown = set(cols_to_load) - set(METROPT3_MODALITY_MAP)
    if unknown:
        raise ValueError(
            f"Unknown columns requested: {unknown}. "
            f"Valid options: {set(METROPT3_MODALITY_MAP)}"
        )

    logger.info("Loading MetroPT-3 from %s ...", csv_path)

    # Read only the columns we need + timestamp
    use_cols = ["timestamp"] + cols_to_load
    df = pd.read_csv(
        csv_path,
        usecols=use_cols,
        nrows=max_rows,
        parse_dates=["timestamp"],
    )

    # ---- Timestamp monotonicity check (FR-DA-3) --------------------------
    if validate:
        _validate_timestamps(df)

    # ---- Build SensorSample list -----------------------------------------
    samples: List[SensorSample] = []
    nan_counts: Dict[str, int] = {c: 0 for c in cols_to_load}
    range_violations: Dict[str, int] = {c: 0 for c in cols_to_load}

    for row in df.itertuples(index=False):
        ts: datetime = row.timestamp
        # Make timezone-aware (UTC) if naive
        if hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        for col in cols_to_load:
            val = getattr(row, col)

            # Skip NaN
            if pd.isna(val):
                nan_counts[col] += 1
                continue

            val = float(val)

            # Range check
            if validate:
                lo, hi = PHYSICAL_RANGES[col]
                if not (lo <= val <= hi):
                    range_violations[col] += 1
                    # Still include the sample — flag it via logging
                    logger.debug(
                        "Range violation %s=%s (expected [%s, %s]) at %s",
                        col, val, lo, hi, ts
                    )

            samples.append(
                SensorSample(
                    machine_id=MACHINE_ID,
                    channel=col,
                    modality=METROPT3_MODALITY_MAP[col],
                    timestamp=ts,
                    value=val,
                    provenance=Provenance.PUBLIC_DATASET,
                    source_id=SOURCE_ID,
                )
            )

    # ---- Summary logging --------------------------------------------------
    total_rows = len(df)
    total_samples = len(samples)
    logger.info(
        "MetroPT-3 loaded: %d rows × %d channels = %d samples",
        total_rows, len(cols_to_load), total_samples,
    )
    for col, cnt in nan_counts.items():
        if cnt:
            logger.warning("  NaN values skipped — %s: %d", col, cnt)
    for col, cnt in range_violations.items():
        if cnt:
            logger.warning(
                "  Range violations (included, flagged) — %s: %d", col, cnt
            )

    return samples


def load_metropt3_dataframe(
    csv_path: str | Path,
    *,
    columns: Optional[List[str]] = None,
    max_rows: Optional[int] = None,
) -> pd.DataFrame:
    """Load MetroPT-3 and return a clean pandas DataFrame.

    This is a lighter-weight alternative to ``load_metropt3`` when you
    need the raw tabular form for exploration or batch feature extraction.

    Parameters
    ----------
    csv_path : Path to the MetroPT-3 CSV file.
    columns  : Sensor columns to load (default: all SENSOR_COLUMNS).
    max_rows : If given, only the first *max_rows* rows are processed.

    Returns
    -------
    DataFrame with a DatetimeIndex (UTC) and selected sensor columns.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"MetroPT-3 CSV not found at: {csv_path}")

    cols_to_load = columns if columns is not None else SENSOR_COLUMNS
    use_cols = ["timestamp"] + cols_to_load

    df = pd.read_csv(
        csv_path,
        usecols=use_cols,
        nrows=max_rows,
        parse_dates=["timestamp"],
    )
    df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC")
    return df


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _validate_timestamps(df: pd.DataFrame) -> None:
    """Check that timestamps are monotonically non-decreasing (FR-DA-3)."""
    ts_series = pd.to_datetime(df["timestamp"])
    violations = (ts_series.diff().dropna() < pd.Timedelta(0)).sum()
    if violations:
        logger.warning(
            "MetroPT-3 timestamp monotonicity: %d out-of-order rows detected.",
            violations,
        )
    else:
        logger.debug("MetroPT-3 timestamps: monotonicity OK.")
