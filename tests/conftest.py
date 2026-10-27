"""
TCMIM — pytest conftest.py

Shared fixtures available to all tests.

Fixtures
--------
metropt3_csv_path : Path to the MetroPT-3 CSV (skips if not found).
metropt3_df_small : First 500 rows of MetroPT-3 as a DataFrame.
synthetic_window  : A WindowedData object built from synthetic data.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tcmim.data.windower import WindowedData
from tcmim.schemas import Provenance

# ---- MetroPT-3 CSV discovery ----------------------------------------

_ENV_METROPT3_PATH = os.environ.get("TCMIM_METROPT3_PATH")
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CSV_CANDIDATES = [
    Path(_ENV_METROPT3_PATH) if _ENV_METROPT3_PATH else None,
    Path("data/raw/MetroPT3(AirCompressor).csv"),
    _PROJECT_ROOT / "data" / "raw" / "MetroPT3(AirCompressor).csv",
    Path("MetroPT3(AirCompressor).csv"),
    _PROJECT_ROOT / "MetroPT3(AirCompressor).csv",
]


def _find_metropt3_csv() -> Path | None:
    for p in _CSV_CANDIDATES:
        if p is not None and p.exists():
            return p
    return None


@pytest.fixture(scope="session")
def metropt3_csv_path():
    """Return the MetroPT-3 CSV path, or skip the test if not found."""
    path = _find_metropt3_csv()
    if path is None:
        pytest.skip(
            "MetroPT-3 CSV not found in data/raw/ or configured path — skipping real-data test. "
            "To enable, place MetroPT3(AirCompressor).csv in data/raw/ or set TCMIM_METROPT3_PATH."
        )
    return path


@pytest.fixture(scope="session")
def metropt3_df_small(metropt3_csv_path):
    """Return first 500 rows of MetroPT-3 as a timezone-aware DataFrame."""
    from tcmim.data.metropt3 import load_metropt3_dataframe
    return load_metropt3_dataframe(metropt3_csv_path, max_rows=500)


@pytest.fixture
def synthetic_window():
    """Return a simple synthetic WindowedData with 60 rows of Gaussian data."""
    import pandas as pd
    from datetime import datetime, timezone

    np.random.seed(42)
    n = 60
    idx = pd.date_range("2020-01-01", periods=n, freq="10s", tz="UTC")
    df = pd.DataFrame({
        "TP2": np.random.normal(5.0, 0.5, n),
        "Motor_current": np.random.normal(10.0, 1.0, n),
    }, index=idx)

    return WindowedData(
        machine_id="synthetic_machine",
        window_start=idx[0].to_pydatetime(),
        window_end=idx[-1].to_pydatetime(),
        data=df,
        provenance=Provenance.SYNTHETIC,
        window_index=0,
    )
