"""
TCMIM — Stage 1 Unsupervised Anomaly Detection (ML-S1).

Implements Isolation Forest anomaly detection for single-machine multimodal
feature streams (e.g. MetroPT-3 compressor), strictly adhering to:
  1. Chronological splitting (no look-ahead bias, no window shuffling).
  2. Baseline fitting exclusively on a documented candidate baseline period
     (default: first 20% of chronological windows).
  3. Explicit feature sanitisation: zero-variance / constant channels and
     high-NaN channels are excluded from the model.
  4. Sparse missing values are imputed strictly using baseline-derived medians.
  5. Provenance integrity (FR-DA-2): synthetic fixtures must never be mixed
     into real evaluations.
  6. Scientific caution (FR-CRI-2, Section 2): an anomaly detection score
     is a statistical deviation from the baseline, NOT a confirmed failure.
  7. Deterministic baseline comparison: integration with MachineBaseline and
     CUSUMDetector on health degradation.

INTEGRITY NOTICE
----------------
The candidate baseline period (e.g. first 20%) is an unverified operational
baseline. No ground-truth certification exists proving that the compressor
was 100% defect-free during this interval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from tcmim.config import CUSUMConfig
from tcmim.events.cusum import CUSUMDetector
from tcmim.health.baseline import MachineBaseline
from tcmim.health.indicator import HealthIndicator
from tcmim.schemas import AnomalyRecord, MultimodalFeatureSample, Provenance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Baseline Split Metadata
# ---------------------------------------------------------------------------

@dataclass
class BaselineSplitInfo:
    """Documented configuration and interval for the candidate baseline period.

    Attributes
    ----------
    n_total          : Total number of chronological windows provided.
    n_baseline       : Number of windows allocated to the baseline split.
    baseline_frac    : Configured fraction of windows used for baseline.
    baseline_start   : Earliest window start in baseline period.
    baseline_end     : Latest window end in baseline period.
    eval_start       : Earliest window start in evaluation period (if any).
    eval_end         : Latest window end in evaluation period (if any).
    assumption_note  : Explicit documentation of baseline assumptions.
    """
    n_total: int
    n_baseline: int
    baseline_frac: float
    baseline_start: datetime
    baseline_end: datetime
    eval_start: Optional[datetime] = None
    eval_end: Optional[datetime] = None
    assumption_note: str = (
        "Candidate baseline assumes initial operational period reflects nominal "
        "dynamics. The audit verified no ground-truth label exists proving zero "
        "latent degradation during this interval."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_total": self.n_total,
            "n_baseline": self.n_baseline,
            "baseline_frac": self.baseline_frac,
            "baseline_start": self.baseline_start.isoformat(),
            "baseline_end": self.baseline_end.isoformat(),
            "eval_start": self.eval_start.isoformat() if self.eval_start else None,
            "eval_end": self.eval_end.isoformat() if self.eval_end else None,
            "assumption_note": self.assumption_note,
        }


# ---------------------------------------------------------------------------
# Feature extraction helper
# ---------------------------------------------------------------------------

def _flatten_features(sample: MultimodalFeatureSample) -> Dict[str, float]:
    """Flatten multimodal feature sample {modality: {feat: val}} -> {feat: val}."""
    flat: Dict[str, float] = {}
    for mod_feats in sample.features.values():
        flat.update(mod_feats)
    return flat


# ---------------------------------------------------------------------------
# Isolation Forest Anomaly Detector
# ---------------------------------------------------------------------------

class IsolationForestAnomalyDetector:
    """Unsupervised anomaly detector using scikit-learn Isolation Forest.

    Parameters
    ----------
    contamination : Contamination rate for IsolationForest (default: 0.05).
                    Pass 'auto' or a float in (0.0, 0.5].
    n_estimators  : Number of isolation trees (default: 100).
    max_samples   : Number of samples to draw per tree (default: 'auto').
    random_state  : Random seed for exact reproducibility (default: 42).
    baseline_frac : Fraction of chronological windows for fitting (default: 0.2).
    min_baseline_windows : Minimum windows required for baseline fit (default: 10).
    threshold     : Decision threshold on decision_function (default: 0.0).
                    Negative decision_function values indicate anomalies.
    max_nan_fraction : Max allowable NaN fraction per feature in baseline
                       before feature is excluded (default: 0.5).
    """

    def __init__(
        self,
        *,
        contamination: Union[float, str] = 0.05,
        n_estimators: int = 100,
        max_samples: Union[int, float, str] = "auto",
        random_state: int = 42,
        baseline_frac: float = 0.2,
        min_baseline_windows: int = 10,
        threshold: float = 0.0,
        max_nan_fraction: float = 0.5,
    ) -> None:
        if isinstance(contamination, float) and not (0.0 < contamination <= 0.5):
            raise ValueError(f"contamination must be in (0, 0.5], got {contamination}")
        if not (0.0 < baseline_frac < 1.0):
            raise ValueError(f"baseline_frac must be in (0, 1), got {baseline_frac}")
        if min_baseline_windows < 1:
            raise ValueError("min_baseline_windows must be at least 1")

        self.contamination = contamination
        self.n_estimators = n_estimators
        self.max_samples = max_samples
        self.random_state = random_state
        self.baseline_frac = baseline_frac
        self.min_baseline_windows = min_baseline_windows
        self.threshold = threshold
        self.max_nan_fraction = max_nan_fraction

        # Fitted attributes
        self.fitted_: bool = False
        self.machine_id_: Optional[str] = None
        self.provenance_: Optional[Provenance] = None
        self.split_info_: Optional[BaselineSplitInfo] = None
        self.feature_names_: List[str] = []
        self.excluded_features_: Dict[str, str] = {}
        self.feature_medians_: Dict[str, float] = {}
        self.model_: Optional[IsolationForest] = None

    def fit(
        self,
        samples: List[MultimodalFeatureSample],
        machine_id: Optional[str] = None,
    ) -> "IsolationForestAnomalyDetector":
        """Fit the Isolation Forest strictly on the candidate baseline windows.

        Parameters
        ----------
        samples    : List of MultimodalFeatureSamples in strict chronological order.
        machine_id : Optional machine ID override.

        Returns
        -------
        Self (fitted detector).

        Raises
        ------
        ValueError : If samples is empty, out of chronological order, contains
                     insufficient baseline windows, or has mixed provenance.
        """
        if not samples:
            raise ValueError("Cannot fit anomaly detector: empty sample list provided.")

        # 1. Enforce strict chronological ordering (temporal integrity)
        for i in range(len(samples) - 1):
            if samples[i].window_start > samples[i + 1].window_start:
                raise ValueError(
                    f"Temporal violation: sample[{i}].window_start ({samples[i].window_start}) "
                    f"> sample[{i+1}].window_start ({samples[i+1].window_start}). "
                    "Samples must be strictly chronological without shuffling to prevent leakage."
                )

        # 2. Provenance and machine ID integrity
        self.machine_id_ = machine_id or samples[0].machine_id
        self.provenance_ = samples[0].provenance
        for s in samples:
            if s.provenance != self.provenance_:
                raise ValueError(
                    f"Mixed provenance detected: initial {self.provenance_} vs {s.provenance}. "
                    "FR-DA-2 strictly prohibits mixing provenance in a single evaluation."
                )

        # 3. Chronological baseline split
        n_total = len(samples)
        n_baseline = max(1, int(n_total * self.baseline_frac))
        if n_baseline < self.min_baseline_windows:
            raise ValueError(
                f"Insufficient baseline windows ({n_baseline} < {self.min_baseline_windows}). "
                "Provide more windows or increase baseline_frac."
            )

        baseline_samples = samples[:n_baseline]
        eval_samples = samples[n_baseline:]

        self.split_info_ = BaselineSplitInfo(
            n_total=n_total,
            n_baseline=n_baseline,
            baseline_frac=self.baseline_frac,
            baseline_start=baseline_samples[0].window_start,
            baseline_end=baseline_samples[-1].window_end,
            eval_start=eval_samples[0].window_start if eval_samples else None,
            eval_end=eval_samples[-1].window_end if eval_samples else None,
        )

        # 4. Feature inspection & exclusion on baseline windows
        flat_baseline = [_flatten_features(s) for s in baseline_samples]
        candidate_features = sorted({f for row in flat_baseline for f in row.keys()})

        self.feature_names_ = []
        self.excluded_features_ = {}
        self.feature_medians_ = {}

        feature_matrix_cols: List[np.ndarray] = []

        for feat in candidate_features:
            vals = np.array([row.get(feat, np.nan) for row in flat_baseline], dtype=float)
            finite_mask = np.isfinite(vals)
            n_finite = int(np.sum(finite_mask))
            n_total_base = len(vals)
            nan_ratio = 1.0 - (n_finite / n_total_base)

            if nan_ratio > self.max_nan_fraction:
                self.excluded_features_[feat] = f"high_nan_ratio ({nan_ratio:.1%})"
                continue

            finite_vals = vals[finite_mask]
            if len(finite_vals) == 0:
                self.excluded_features_[feat] = "all_non_finite"
                continue

            std_val = float(np.std(finite_vals))
            if std_val < 1e-12:
                self.excluded_features_[feat] = f"constant_channel (std={std_val:.2e})"
                continue

            # Feature is valid
            median_val = float(np.nanmedian(vals))
            self.feature_medians_[feat] = median_val
            # Impute sparse missing values in baseline using baseline median
            imputed_vals = np.where(finite_mask, vals, median_val)
            feature_matrix_cols.append(imputed_vals)
            self.feature_names_.append(feat)

        if not self.feature_names_:
            raise ValueError(
                "No valid features remain after filtering constant and non-finite channels."
            )

        X_baseline = np.column_stack(feature_matrix_cols)

        # 5. Fit Isolation Forest
        self.model_ = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            max_samples=self.max_samples,
            random_state=self.random_state,
        )
        self.model_.fit(X_baseline)
        self.fitted_ = True

        logger.info(
            "Fitted IsolationForest on %d baseline windows across %d features. "
            "(Excluded %d constant/sparse features).",
            n_baseline,
            len(self.feature_names_),
            len(self.excluded_features_),
        )
        return self

    def predict_score(
        self,
        samples: List[MultimodalFeatureSample],
    ) -> List[AnomalyRecord]:
        """Score windows using the fitted Isolation Forest detector.

        Parameters
        ----------
        samples : List of MultimodalFeatureSample objects.

        Returns
        -------
        List of AnomalyRecord objects preserving chronological ordering.
        """
        if not self.fitted_ or self.model_ is None:
            raise RuntimeError("AnomalyDetector must be fitted before predict_score().")

        if not samples:
            return []

        # Chronological ordering check
        for i in range(len(samples) - 1):
            if samples[i].window_start > samples[i + 1].window_start:
                raise ValueError("Evaluation samples must be in chronological order.")

        # Build feature matrix using fitted feature names and baseline medians
        rows: List[List[float]] = []
        for s in samples:
            if s.provenance != self.provenance_:
                raise ValueError(
                    f"Provenance mismatch: detector trained on {self.provenance_}, "
                    f"received {s.provenance}."
                )
            flat = _flatten_features(s)
            row = []
            for feat in self.feature_names_:
                val = flat.get(feat, np.nan)
                if not np.isfinite(val):
                    val = self.feature_medians_[feat]
                row.append(val)
            rows.append(row)

        X_eval = np.array(rows, dtype=float)

        # In sklearn: decision_function returns anomaly score.
        # Lower = more abnormal. Score < threshold is flagged as anomaly.
        scores = self.model_.decision_function(X_eval)

        records: List[AnomalyRecord] = []
        for i, s in enumerate(samples):
            score_val = float(scores[i])
            is_anom = bool(score_val < self.threshold)
            records.append(
                AnomalyRecord(
                    timestamp=s.window_start,
                    machine_id=s.machine_id,
                    anomaly_score=score_val,
                    is_anomaly=is_anom,
                    detector="isolation_forest",
                    provenance=s.provenance,
                    window_end=s.window_end,
                )
            )

        return records

    def fit_and_score(
        self,
        samples: List[MultimodalFeatureSample],
        score_baseline: bool = True,
    ) -> Tuple[List[AnomalyRecord], Dict[str, Any]]:
        """Fit on baseline split, then score windows.

        Parameters
        ----------
        samples        : All chronological feature windows.
        score_baseline : If True, returns records for all windows (baseline + eval).
                         If False, returns records only for eval windows.

        Returns
        -------
        (records, summary_dict)
        """
        self.fit(samples)
        scored_samples = samples if score_baseline else samples[self.split_info_.n_baseline:]
        records = self.predict_score(scored_samples)

        anomaly_count = sum(1 for r in records if r.is_anomaly)
        total_count = len(records)
        rate = (anomaly_count / total_count) if total_count > 0 else 0.0

        summary = {
            "detector": "isolation_forest",
            "split_info": self.split_info_.to_dict(),
            "n_features_used": len(self.feature_names_),
            "features_used": list(self.feature_names_),
            "n_features_excluded": len(self.excluded_features_),
            "excluded_features": dict(self.excluded_features_),
            "model_params": {
                "contamination": self.contamination,
                "n_estimators": self.n_estimators,
                "random_state": self.random_state,
                "threshold": self.threshold,
            },
            "total_scored_windows": total_count,
            "anomaly_count": anomaly_count,
            "anomaly_rate": rate,
            "score_min": float(min(r.anomaly_score for r in records)) if records else np.nan,
            "score_mean": float(np.mean([r.anomaly_score for r in records])) if records else np.nan,
            "score_max": float(max(r.anomaly_score for r in records)) if records else np.nan,
        }
        return records, summary


# ---------------------------------------------------------------------------
# CUSUM Comparison Baseline
# ---------------------------------------------------------------------------

def run_cusum_comparison(
    samples: List[MultimodalFeatureSample],
    *,
    baseline_frac: float = 0.2,
    cusum_config: Optional[CUSUMConfig] = None,
) -> Tuple[List[AnomalyRecord], Dict[str, Any]]:
    """Run deterministic health-indicator + CUSUM detector as a comparison baseline.

    Parameters
    ----------
    samples       : Chronological list of feature windows.
    baseline_frac : Fraction used to fit MachineBaseline (default: 0.2).
    cusum_config  : CUSUMConfig parameters (k, h).

    Returns
    -------
    (records, summary_dict)
    """
    if not samples:
        raise ValueError("Cannot run CUSUM comparison on empty samples.")

    cfg = cusum_config or CUSUMConfig(k=0.5, h=5.0)

    # 1. Fit deterministic baseline on first baseline_frac
    baseline = MachineBaseline.fit(samples, baseline_frac=baseline_frac)
    indicator = HealthIndicator(baseline)
    health_samples = indicator.compute_all(samples)

    # 2. Degradation signal: 1 - health_score
    degradations = np.array([
        0.0 if np.isnan(hs.health_score) else (1.0 - hs.health_score)
        for hs in health_samples
    ])

    # 3. Run CUSUM
    detector = CUSUMDetector(k=cfg.k, h=cfg.h, reset=True)
    score_trace, alarms = detector.run_with_scores(degradations)

    alarm_indices = {a.index for a in alarms}

    records: List[AnomalyRecord] = []
    for t, s in enumerate(samples):
        records.append(
            AnomalyRecord(
                timestamp=s.window_start,
                machine_id=s.machine_id,
                anomaly_score=float(score_trace[t]),
                is_anomaly=(t in alarm_indices),
                detector="cusum_health",
                provenance=s.provenance,
                window_end=s.window_end,
            )
        )

    alarm_count = len(alarms)
    summary = {
        "detector": "cusum_health",
        "cusum_params": {"k": cfg.k, "h": cfg.h},
        "baseline_frac": baseline_frac,
        "n_baseline_windows": baseline.n_windows,
        "total_scored_windows": len(records),
        "alarm_count": alarm_count,
        "alarm_rate": (alarm_count / len(records)) if records else 0.0,
        "score_max": float(np.max(score_trace)) if len(score_trace) > 0 else 0.0,
    }
    return records, summary


# ---------------------------------------------------------------------------
# Aggregation & Analysis Helpers
# ---------------------------------------------------------------------------

def summarize_anomalies_by_day(records: List[AnomalyRecord]) -> pd.DataFrame:
    """Aggregate anomaly records by UTC calendar day, accounting for gaps.

    Parameters
    ----------
    records : List of AnomalyRecord objects.

    Returns
    -------
    pd.DataFrame with index = Date (YYYY-MM-DD), and columns:
      - window_count : Total observed windows on that day.
      - anomaly_count: Number of flagged anomaly windows.
      - anomaly_rate : anomaly_count / window_count.
      - score_min    : Minimum anomaly score for the day.
      - score_mean   : Mean anomaly score for the day.
    """
    if not records:
        return pd.DataFrame(
            columns=["window_count", "anomaly_count", "anomaly_rate", "score_min", "score_mean"]
        )

    rows = []
    for r in records:
        rows.append({
            "date": r.timestamp.date(),
            "is_anomaly": int(r.is_anomaly),
            "score": r.anomaly_score,
        })
    df = pd.DataFrame(rows)
    grouped = df.groupby("date").agg(
        window_count=("score", "count"),
        anomaly_count=("is_anomaly", "sum"),
        score_min=("score", "min"),
        score_mean=("score", "mean"),
    )
    grouped["anomaly_rate"] = grouped["anomaly_count"] / grouped["window_count"]
    grouped.index.name = "date"
    return grouped
