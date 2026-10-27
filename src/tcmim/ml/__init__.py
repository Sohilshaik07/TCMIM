"""
TCMIM — Machine Learning Package (M8 / Stage 1).

Exposes Stage 1 unsupervised anomaly detection components, schema, and baseline comparisons.
"""

from tcmim.ml.anomaly_detector import (
    BaselineSplitInfo,
    IsolationForestAnomalyDetector,
    run_cusum_comparison,
    summarize_anomalies_by_day,
)
from tcmim.schemas import AnomalyRecord

__all__ = [
    "AnomalyRecord",
    "BaselineSplitInfo",
    "IsolationForestAnomalyDetector",
    "run_cusum_comparison",
    "summarize_anomalies_by_day",
]
