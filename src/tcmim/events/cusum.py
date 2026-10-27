"""
TCMIM — CUSUM and Page-Hinkley detectors (S4, FR-ED-1).

Both detectors operate on a time-ordered sequence of scalar values
(typically a health score or a single z-score) and return the index
at which an event onset is declared.

CUSUM (Cumulative Sum)
----------------------
Formula from PRD FR-ED-1:

    S_t = max(0, S_{t-1} + x_t − k)
    Alarm when S_t > h

Where:
    x_t : input value at time t  (z-score or degraded health signal)
    k   : allowance / slack (PRD: configurable, default 0.5)
    h   : decision threshold   (PRD: configurable, default 5.0)
    S_0 = 0

The detector is one-sided (detects upward shifts from normal).
For symmetric detection, run two instances with +x and −x.

Page-Hinkley
------------
A variant of CUSUM with a running mean estimate:

    m_t = m_{t-1} + (x_t − m_{t-1}) / t   (running mean)
    T_t = T_{t-1} + (x_t − m_t − δ)
    PH_t = T_t − min(T_0, ..., T_t)
    Alarm when PH_t > λ

Where δ (delta) is a minimal drift and λ (lambda) is the threshold.

Integrity note (FR-ED-2)
------------------------
Detection timestamps mark when a sustained change was DETECTED, not
when it originated.  Callers must not interpret the onset_time as the
physical cause time.

Usage
-----
>>> from tcmim.events.cusum import CUSUMDetector, PageHinkleyDetector
>>> det = CUSUMDetector(k=0.5, h=5.0)
>>> alarms = det.run(z_scores)       # returns list of alarm indices
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Alarm dataclass
# --------------------------------------------------------------------------

@dataclass
class DetectorAlarm:
    """One alarm event from a detector.

    Attributes
    ----------
    index       : Index in the input sequence where the alarm fired.
    score       : Detector score at the alarm point.
    detector    : Name of the detector that fired.
    reset_index : Index where the detector score was reset to 0 after alarm.
                  None if the detector was not reset.
    """
    index: int
    score: float
    detector: str
    reset_index: Optional[int] = None


# --------------------------------------------------------------------------
# CUSUM detector
# --------------------------------------------------------------------------

class CUSUMDetector:
    """One-sided CUSUM detector (FR-ED-1).

    S_t = max(0, S_{t-1} + x_t − k),  alarm when S_t > h.

    Parameters
    ----------
    k        : Allowance / slack parameter (default 0.5).
    h        : Decision threshold (default 5.0).
    reset    : If True, reset S to 0 after each alarm (allows multiple
               alarms on the same sequence).  If False, stop at the
               first alarm.
    """

    NAME = "cusum"

    def __init__(
        self,
        k: float = 0.5,
        h: float = 5.0,
        reset: bool = True,
    ) -> None:
        if k < 0:
            raise ValueError("CUSUM k must be non-negative.")
        if h <= 0:
            raise ValueError("CUSUM h must be positive.")
        self.k = k
        self.h = h
        self.reset = reset

    def run(
        self,
        x: np.ndarray,
    ) -> List[DetectorAlarm]:
        """Run CUSUM over the sequence *x*.

        Parameters
        ----------
        x : 1-D array of input values (z-scores or health degradation).

        Returns
        -------
        List of DetectorAlarm objects (one per alarm event).
        """
        x = np.asarray(x, dtype=float)
        alarms: List[DetectorAlarm] = []
        S = 0.0
        last_reset = 0

        for t, val in enumerate(x):
            if np.isnan(val):
                continue
            S = max(0.0, S + val - self.k)
            if S > self.h:
                alarm = DetectorAlarm(
                    index=t,
                    score=S,
                    detector=self.NAME,
                    reset_index=t if self.reset else None,
                )
                alarms.append(alarm)
                if self.reset:
                    S = 0.0

        return alarms

    def run_with_scores(
        self,
        x: np.ndarray,
    ) -> Tuple[np.ndarray, List[DetectorAlarm]]:
        """Run CUSUM and also return the full score trace.

        Returns
        -------
        (score_trace, alarms)  where score_trace is a 1-D array of S_t values.
        """
        x = np.asarray(x, dtype=float)
        scores = np.zeros(len(x))
        alarms: List[DetectorAlarm] = []
        S = 0.0

        for t, val in enumerate(x):
            if np.isnan(val):
                scores[t] = S
                continue
            S = max(0.0, S + val - self.k)
            scores[t] = S
            if S > self.h:
                alarm = DetectorAlarm(
                    index=t,
                    score=S,
                    detector=self.NAME,
                    reset_index=t if self.reset else None,
                )
                alarms.append(alarm)
                if self.reset:
                    S = 0.0

        return scores, alarms


# --------------------------------------------------------------------------
# Page-Hinkley detector
# --------------------------------------------------------------------------

class PageHinkleyDetector:
    """Page-Hinkley detector — a running-mean variant of CUSUM.

    Parameters
    ----------
    delta  : Minimum drift magnitude to detect (default 0.05).
    lambda_: Alarm threshold (default 50.0).
    reset  : If True, reset after each alarm.
    """

    NAME = "page_hinkley"

    def __init__(
        self,
        delta: float = 0.05,
        lambda_: float = 50.0,
        reset: bool = True,
    ) -> None:
        if delta < 0:
            raise ValueError("PageHinkley delta must be non-negative.")
        if lambda_ <= 0:
            raise ValueError("PageHinkley lambda must be positive.")
        self.delta = delta
        self.lambda_ = lambda_
        self.reset = reset

    def run(
        self,
        x: np.ndarray,
    ) -> List[DetectorAlarm]:
        """Run Page-Hinkley over sequence *x*.

        Parameters
        ----------
        x : 1-D array of input values.

        Returns
        -------
        List of DetectorAlarm objects.
        """
        x = np.asarray(x, dtype=float)
        alarms: List[DetectorAlarm] = []

        x_mean = 0.0
        T = 0.0
        T_min = 0.0
        n = 0

        for t, val in enumerate(x):
            if np.isnan(val):
                continue
            n += 1
            x_mean = x_mean + (val - x_mean) / n     # online mean
            T = T + val - x_mean - self.delta
            T_min = min(T_min, T)
            ph = T - T_min

            if ph > self.lambda_:
                alarm = DetectorAlarm(
                    index=t,
                    score=ph,
                    detector=self.NAME,
                    reset_index=t if self.reset else None,
                )
                alarms.append(alarm)
                if self.reset:
                    T = 0.0
                    T_min = 0.0
                    x_mean = 0.0
                    n = 0

        return alarms

    def run_with_scores(
        self,
        x: np.ndarray,
    ) -> Tuple[np.ndarray, List[DetectorAlarm]]:
        """Run Page-Hinkley and return full score trace."""
        x = np.asarray(x, dtype=float)
        scores = np.zeros(len(x))
        alarms: List[DetectorAlarm] = []

        x_mean = 0.0
        T = 0.0
        T_min = 0.0
        n = 0

        for t, val in enumerate(x):
            if np.isnan(val):
                continue
            n += 1
            x_mean = x_mean + (val - x_mean) / n
            T = T + val - x_mean - self.delta
            T_min = min(T_min, T)
            ph = T - T_min
            scores[t] = ph

            if ph > self.lambda_:
                alarm = DetectorAlarm(
                    index=t,
                    score=ph,
                    detector=self.NAME,
                    reset_index=t if self.reset else None,
                )
                alarms.append(alarm)
                if self.reset:
                    T = 0.0
                    T_min = 0.0
                    x_mean = 0.0
                    n = 0

        return scores, alarms
