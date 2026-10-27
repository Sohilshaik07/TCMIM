"""
TCMIM — High-level event detector (S4, FR-ED-1, FR-ED-2).

Takes a chronological list of HealthSamples and applies CUSUM or
Page-Hinkley to the health degradation signal (1 − health_score) to
detect sustained-change onsets.  Returns a list of EventRecords.

Design
------
Input signal:  degradation_t = 1 − health_score_t
               (0 when healthy, 1 when maximally degraded)

The detector is applied to degradation rather than health_score so
that upward CUSUM tracks increasing degradation (consistent with the
PRD FR-ED-1 intent).

One EventRecord is created per alarm.  The onset_time is the
window_start of the alarming window — explicitly non-causal (FR-ED-2).

Usage
-----
>>> from tcmim.events.detector import EventDetector
>>> from tcmim.config import CUSUMConfig
>>> detector = EventDetector(cusum_config=CUSUMConfig(k=0.5, h=5.0))
>>> events = detector.detect(health_samples, modality=Modality.PRESSURE)
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

from tcmim.config import CUSUMConfig
from tcmim.events.cusum import CUSUMDetector, PageHinkleyDetector
from tcmim.schemas import EventRecord, HealthSample, Modality

logger = logging.getLogger(__name__)


class EventDetector:
    """Detect sustained-change onset events from health samples.

    Parameters
    ----------
    cusum_config  : CUSUM parameters (k and h).  Uses defaults if None.
    detector_type : 'cusum' (default) or 'page_hinkley'.
    """

    def __init__(
        self,
        cusum_config: Optional[CUSUMConfig] = None,
        detector_type: str = "cusum",
    ) -> None:
        cfg = cusum_config or CUSUMConfig()
        if detector_type == "cusum":
            self._detector = CUSUMDetector(k=cfg.k, h=cfg.h, reset=True)
            self._detector_name = "cusum"
        elif detector_type == "page_hinkley":
            self._detector = PageHinkleyDetector(reset=True)
            self._detector_name = "page_hinkley"
        else:
            raise ValueError(
                f"Unknown detector_type '{detector_type}'. "
                "Choose 'cusum' or 'page_hinkley'."
            )

    def detect(
        self,
        health_samples: List[HealthSample],
        modality: Modality = Modality.UNKNOWN,
    ) -> List[EventRecord]:
        """Detect events in a time-ordered list of HealthSamples.

        Parameters
        ----------
        health_samples : Chronological list of HealthSamples.
        modality       : Modality label for the resulting EventRecords.

        Returns
        -------
        List of EventRecords, one per alarm.

        Notes
        -----
        - onset_time = window_start of the alarming window (FR-ED-2).
        - Samples must be from a single machine; the machine_id of the
          first sample is used for all EventRecords.
        - NaN health scores are treated as degradation = 0 (no alarm).
        """
        if not health_samples:
            logger.warning("EventDetector.detect called with empty list.")
            return []

        machine_id = health_samples[0].machine_id
        provenance = health_samples[0].provenance

        # Build degradation signal: 1 − health_score
        degradation = np.array(
            [
                1.0 - s.health_score if not np.isnan(s.health_score) else 0.0
                for s in health_samples
            ],
            dtype=float,
        )

        alarms = self._detector.run(degradation)

        events: List[EventRecord] = []
        for alarm in alarms:
            alarming_sample = health_samples[alarm.index]
            event = EventRecord(
                machine_id=machine_id,
                modality=modality,
                onset_time=alarming_sample.window_start,
                detector=self._detector_name,
                score=alarm.score,
                provenance=provenance,
            )
            events.append(event)

        logger.info(
            "EventDetector (%s): %d events detected on '%s' "
            "from %d health samples.",
            self._detector_name,
            len(events),
            machine_id,
            len(health_samples),
        )
        return events

    def detect_with_scores(
        self,
        health_samples: List[HealthSample],
        modality: Modality = Modality.UNKNOWN,
    ) -> tuple:
        """Like detect(), but also returns the full CUSUM score trace.

        Returns
        -------
        (events, score_trace)  where score_trace is a 1-D numpy array
        with one entry per health sample.
        """
        if not health_samples:
            return [], np.array([])

        machine_id = health_samples[0].machine_id
        provenance = health_samples[0].provenance
        modality_label = modality

        degradation = np.array(
            [
                1.0 - s.health_score if not np.isnan(s.health_score) else 0.0
                for s in health_samples
            ],
            dtype=float,
        )

        scores, alarms = self._detector.run_with_scores(degradation)

        events: List[EventRecord] = []
        for alarm in alarms:
            alarming_sample = health_samples[alarm.index]
            event = EventRecord(
                machine_id=machine_id,
                modality=modality_label,
                onset_time=alarming_sample.window_start,
                detector=self._detector_name,
                score=alarm.score,
                provenance=provenance,
            )
            events.append(event)

        return events, scores
