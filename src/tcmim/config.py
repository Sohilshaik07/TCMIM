"""
TCMIM — Pipeline configuration.

All algorithm parameters that are open decisions (Section 16 of the PRD)
are centralised here.  Parameters are intentionally over-documented
because Section 16 requires them to be fixed and documented at M3.

Usage
-----
>>> from tcmim.config import TCMIMConfig
>>> cfg = TCMIMConfig()            # sensible defaults
>>> cfg.cusum_k = 0.5              # tune before M3 design review
>>> cfg.validate()                 # raises if values are inconsistent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class WindowConfig:
    """Time-window parameters per modality (Open Decision 1).

    window_seconds : Length of one analysis window in seconds.
    overlap_frac   : Fraction of overlap between consecutive windows [0, 1).
    """
    window_seconds: float = 60.0     # to be finalised at M3
    overlap_frac: float = 0.5        # to be finalised at M3

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive.")
        if not (0.0 <= self.overlap_frac < 1.0):
            raise ValueError("overlap_frac must be in [0, 1).")


@dataclass
class CUSUMConfig:
    """CUSUM / Page-Hinkley event detector parameters (Open Decision 2).

    Formula (FR-ED-1):
        S_t = max(0, S_{t-1} + z_t − k)
        Event when S_t > h

    k : Allowance / slack parameter.
    h : Decision threshold (alarm level).
    """
    k: float = 0.5    # to be finalised at M3
    h: float = 5.0    # to be finalised at M3

    def __post_init__(self) -> None:
        if self.k < 0:
            raise ValueError("CUSUM k must be non-negative.")
        if self.h <= 0:
            raise ValueError("CUSUM h must be positive.")


@dataclass
class EdgeLifecycleConfig:
    """Thresholds for the 8-state edge lifecycle (Open Decision 3 / FR-EL-1).

    All thresholds are counts of accepted PropagationObservations unless
    noted otherwise.  Finalised at M6 design review.
    """
    candidate_threshold: int = 1       # obs needed to enter CANDIDATE
    provisional_threshold: int = 3     # obs needed to enter PROVISIONAL
    confirmed_threshold: int = 6       # obs needed to enter CONFIRMED
    strengthening_threshold: int = 10  # obs needed to enter STRENGTHENING
    stable_threshold: int = 15         # obs needed to enter STABLE
    weakening_threshold: int = 3       # consecutive non-observations to WEAKENING
    expired_threshold: int = 7         # consecutive non-observations to EXPIRED
    min_direction_consistency: float = 0.7  # gate for CONFIRMED and above


@dataclass
class MatchingConfig:
    """Event-matching parameters (FR-EM-1)."""
    max_delay_s: float = 600.0    # Maximum plausible propagation delay (10 min)
    min_delay_s: float = 0.0      # Minimum plausible delay (can be 0)


@dataclass
class TCMIMConfig:
    """Master configuration for the TCMIM pipeline.

    All parameters with 'to be finalised at M_x' comments are open
    decisions from PRD Section 16.  They should be locked down in
    code via a separate committed config file at the relevant milestone.
    """
    # Window parameters per modality; default applies to all unless overridden
    default_window: WindowConfig = field(default_factory=WindowConfig)
    modality_windows: Dict[str, WindowConfig] = field(default_factory=dict)

    # CUSUM parameters (Open Decision 2)
    cusum: CUSUMConfig = field(default_factory=CUSUMConfig)

    # Edge lifecycle (Open Decision 3)
    edge_lifecycle: EdgeLifecycleConfig = field(default_factory=EdgeLifecycleConfig)

    # Event matching (FR-EM-1)
    matching: MatchingConfig = field(default_factory=MatchingConfig)

    # Random seed for reproducibility (NFR)
    random_seed: int = 42

    def validate(self) -> None:
        """Check cross-parameter consistency. Raises ValueError on failure."""
        if self.matching.min_delay_s >= self.matching.max_delay_s:
            raise ValueError(
                "matching.min_delay_s must be less than matching.max_delay_s"
            )
        # Lifecycle ordering
        lc = self.edge_lifecycle
        thresholds = [
            lc.candidate_threshold,
            lc.provisional_threshold,
            lc.confirmed_threshold,
            lc.strengthening_threshold,
            lc.stable_threshold,
        ]
        for i in range(len(thresholds) - 1):
            if thresholds[i] >= thresholds[i + 1]:
                raise ValueError(
                    "EdgeLifecycleConfig: thresholds must be strictly increasing "
                    f"(candidate < provisional < confirmed < strengthening < stable). "
                    f"Got: {thresholds}"
                )

    def get_window(self, modality: str) -> WindowConfig:
        """Return the WindowConfig for a modality, falling back to default."""
        return self.modality_windows.get(modality, self.default_window)
