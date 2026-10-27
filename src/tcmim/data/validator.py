"""
TCMIM — Data validation (S1, FR-DA-3).

Validates:
  1. Timestamp monotonicity
  2. Missing / NaN values
  3. Physical range violations
  4. Duplicate timestamps (warn only)

All validators return a ValidationReport rather than raising, so the
pipeline can choose to warn, filter, or halt based on severity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

import pandas as pd

from tcmim.schemas import SensorSample

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Summary of a validation pass over a list of SensorSamples.

    Attributes
    ----------
    total_checked         : Number of samples examined.
    nan_count             : Samples with NaN values (already excluded by loader).
    out_of_order_count    : Number of timestamp ordering violations.
    range_violation_count : Number of out-of-range values.
    duplicate_ts_count    : Number of duplicate timestamps (warn only).
    valid_count           : Samples that passed all checks.
    issues                : Human-readable list of issues found.
    passed                : True if no hard failures detected.
    """
    total_checked: int = 0
    nan_count: int = 0
    out_of_order_count: int = 0
    range_violation_count: int = 0
    duplicate_ts_count: int = 0
    valid_count: int = 0
    issues: List[str] = field(default_factory=list)
    passed: bool = True


def validate_samples(
    samples: List[SensorSample],
    physical_ranges: Optional[dict] = None,
) -> ValidationReport:
    """Validate a list of SensorSamples and return a report.

    Parameters
    ----------
    samples         : List of SensorSample objects to validate.
    physical_ranges : Optional dict mapping channel name → (min, max).
                      If None, range checks are skipped.

    Returns
    -------
    ValidationReport describing what was found.
    """
    report = ValidationReport(total_checked=len(samples))

    if not samples:
        report.issues.append("No samples to validate.")
        return report

    # ---- Sort by timestamp for ordering check ----------------------------
    sorted_ts = [s.timestamp for s in samples]

    # ---- Timestamp ordering ----------------------------------------------
    prev: Optional[datetime] = None
    for ts in sorted_ts:
        if prev is not None and ts < prev:
            report.out_of_order_count += 1
        prev = ts

    if report.out_of_order_count:
        msg = (
            f"Timestamp ordering: {report.out_of_order_count} "
            "out-of-order samples detected."
        )
        report.issues.append(msg)
        logger.warning(msg)

    # ---- Duplicate timestamps (warn only) --------------------------------
    ts_list = sorted_ts
    seen = set()
    for ts in ts_list:
        if ts in seen:
            report.duplicate_ts_count += 1
        seen.add(ts)
    if report.duplicate_ts_count:
        msg = f"Duplicate timestamps: {report.duplicate_ts_count} found (warning only)."
        report.issues.append(msg)
        logger.warning(msg)

    # ---- Physical range checks -------------------------------------------
    if physical_ranges:
        for s in samples:
            if s.channel in physical_ranges:
                lo, hi = physical_ranges[s.channel]
                if not (lo <= s.value <= hi):
                    report.range_violation_count += 1

        if report.range_violation_count:
            msg = (
                f"Range violations: {report.range_violation_count} "
                "samples outside physical bounds."
            )
            report.issues.append(msg)
            logger.warning(msg)

    # ---- Final summary ---------------------------------------------------
    hard_failures = report.out_of_order_count + report.range_violation_count
    report.valid_count = report.total_checked - hard_failures
    report.passed = hard_failures == 0

    return report


def validate_dataframe(
    df: pd.DataFrame,
    physical_ranges: Optional[dict] = None,
) -> ValidationReport:
    """Validate a pandas DataFrame directly (useful for MetroPT-3 DF interface).

    Checks timestamp index monotonicity, NaN presence, and optional ranges.

    Parameters
    ----------
    df              : DataFrame with DatetimeIndex.
    physical_ranges : Optional dict mapping column name → (min, max).

    Returns
    -------
    ValidationReport.
    """
    report = ValidationReport(total_checked=len(df))

    # ---- Monotonicity ----------------------------------------------------
    if not df.index.is_monotonic_increasing:
        violations = int((df.index.to_series().diff().dropna() < pd.Timedelta(0)).sum())
        report.out_of_order_count = violations
        msg = f"Timestamp monotonicity: {violations} out-of-order rows."
        report.issues.append(msg)
        logger.warning(msg)

    # ---- NaN values ------------------------------------------------------
    nan_total = int(df.isnull().sum().sum())
    report.nan_count = nan_total
    if nan_total:
        msg = f"NaN values: {nan_total} total across all columns."
        report.issues.append(msg)
        logger.warning(msg)

    # ---- Duplicate index -------------------------------------------------
    dup_count = int(df.index.duplicated().sum())
    report.duplicate_ts_count = dup_count
    if dup_count:
        msg = f"Duplicate timestamps: {dup_count} found (warning only)."
        report.issues.append(msg)
        logger.warning(msg)

    # ---- Physical ranges -------------------------------------------------
    if physical_ranges:
        for col, (lo, hi) in physical_ranges.items():
            if col not in df.columns:
                continue
            violations = int(((df[col] < lo) | (df[col] > hi)).sum())
            if violations:
                report.range_violation_count += violations
                msg = f"Range violation — {col}: {violations} rows outside [{lo}, {hi}]."
                report.issues.append(msg)
                logger.warning(msg)

    hard_failures = report.out_of_order_count + report.range_violation_count
    report.valid_count = report.total_checked - hard_failures
    report.passed = hard_failures == 0

    return report


def filter_range_violations(
    samples: List[SensorSample],
    physical_ranges: dict,
) -> Tuple[List[SensorSample], int]:
    """Remove samples outside physical ranges.

    Parameters
    ----------
    samples         : Input sample list.
    physical_ranges : Dict mapping channel name → (min, max).

    Returns
    -------
    (clean_samples, n_removed) where n_removed is the count dropped.
    """
    clean: List[SensorSample] = []
    removed = 0
    for s in samples:
        if s.channel in physical_ranges:
            lo, hi = physical_ranges[s.channel]
            if not (lo <= s.value <= hi):
                removed += 1
                continue
        clean.append(s)
    return clean, removed
