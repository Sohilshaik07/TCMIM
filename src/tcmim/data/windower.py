"""
TCMIM — Time-window builder (S1, FR-DA-4).

Slices a pandas DataFrame (DatetimeIndex) into overlapping or
non-overlapping windows, preserving provenance metadata.

Usage
-----
>>> from tcmim.data.windower import WindowBuilder, WindowedData
>>> wb = WindowBuilder(window_seconds=60, overlap_frac=0.5)
>>> windows = wb.build(df, machine_id="metropt3_compressor",
...                    provenance=Provenance.PUBLIC_DATASET)
>>> len(windows)
50232   # depends on data length
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import pandas as pd

from tcmim.schemas import Provenance

logger = logging.getLogger(__name__)


@dataclass
class WindowedData:
    """A single time window slice from a machine's data.

    Attributes
    ----------
    machine_id   : Logical machine identifier.
    window_start : Start of the window (inclusive).
    window_end   : End of the window (exclusive).
    data         : DataFrame slice for this window.
    provenance   : Provenance class inherited from the source.
    window_index : Sequential index of this window (0-based).
    """
    machine_id: str
    window_start: datetime
    window_end: datetime
    data: pd.DataFrame
    provenance: Provenance
    window_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, Provenance):
            self.provenance = Provenance(self.provenance)
        if self.window_end <= self.window_start:
            raise ValueError(
                f"window_end ({self.window_end}) must be after "
                f"window_start ({self.window_start})"
            )


class WindowBuilder:
    """Builds time windows from a DataFrame with a DatetimeIndex.

    Parameters
    ----------
    window_seconds : Length of each window in seconds.
    overlap_frac   : Fraction of overlap between consecutive windows [0, 1).
                     0.0 = non-overlapping, 0.5 = 50 % overlap, etc.
    min_samples    : Minimum number of rows required for a window to be
                     included; windows with fewer rows are discarded.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        overlap_frac: float = 0.5,
        min_samples: int = 2,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")
        if not (0.0 <= overlap_frac < 1.0):
            raise ValueError("overlap_frac must be in [0, 1).")
        if min_samples < 1:
            raise ValueError("min_samples must be >= 1.")

        self.window_seconds = window_seconds
        self.overlap_frac = overlap_frac
        self.min_samples = min_samples

        window_td = pd.Timedelta(seconds=window_seconds)
        step_td = pd.Timedelta(seconds=window_seconds * (1.0 - overlap_frac))
        self._window_td = window_td
        self._step_td = step_td

    def build(
        self,
        df: pd.DataFrame,
        machine_id: str,
        provenance: Provenance,
    ) -> List[WindowedData]:
        """Slice *df* into time windows.

        Parameters
        ----------
        df         : DataFrame with a monotonic DatetimeIndex.
        machine_id : Machine identifier to attach to each window.
        provenance : Provenance to propagate to each window.

        Returns
        -------
        List of WindowedData objects in chronological order.
        """
        if df.empty:
            logger.warning("WindowBuilder.build called with empty DataFrame.")
            return []

        start = df.index[0]
        end_global = df.index[-1]
        windows: List[WindowedData] = []
        idx = 0

        current_start = start
        while current_start <= end_global:
            current_end = current_start + self._window_td
            # Slice — include current_start, exclude current_end
            mask = (df.index >= current_start) & (df.index < current_end)
            slice_df = df.loc[mask]

            if len(slice_df) >= self.min_samples:
                # Ensure datetimes are timezone-aware
                ws = current_start
                we = current_end
                if hasattr(ws, "tzinfo") and ws.tzinfo is None:
                    ws = ws.replace(tzinfo=timezone.utc)
                if hasattr(we, "tzinfo") and we.tzinfo is None:
                    we = we.replace(tzinfo=timezone.utc)

                windows.append(
                    WindowedData(
                        machine_id=machine_id,
                        window_start=ws,
                        window_end=we,
                        data=slice_df.copy(),
                        provenance=provenance,
                        window_index=idx,
                    )
                )
                idx += 1

            current_start = current_start + self._step_td

        logger.debug(
            "WindowBuilder: %d windows built for '%s' "
            "(window=%.0fs, overlap=%.0f%%).",
            len(windows),
            machine_id,
            self.window_seconds,
            self.overlap_frac * 100,
        )
        return windows
