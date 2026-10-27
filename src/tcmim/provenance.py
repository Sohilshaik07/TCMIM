"""
TCMIM — Provenance guard utilities.

These functions are the software enforcement of TCMIM integrity rules
(Section 2 of the PRD).  Any module that produces or consumes real-result
reports MUST call `assert_not_synthetic` before writing output.

Usage
-----
>>> from tcmim.provenance import assert_not_synthetic, filter_real
>>> assert_not_synthetic(sample)          # raises if SYNTHETIC
>>> real_only = filter_real(sample_list)  # removes SYNTHETIC rows
"""

from __future__ import annotations

from typing import Any, Iterable, List, TypeVar

from tcmim.schemas import Provenance

T = TypeVar("T")


def is_real(obj: Any) -> bool:
    """Return True if *obj* has a non-SYNTHETIC provenance attribute."""
    prov = getattr(obj, "provenance", None)
    if prov is None:
        raise AttributeError(
            f"Object of type {type(obj).__name__!r} has no 'provenance' "
            "attribute — cannot enforce provenance guard."
        )
    return Provenance(prov) != Provenance.SYNTHETIC


def assert_not_synthetic(obj: Any, context: str = "") -> None:
    """Raise if *obj* carries SYNTHETIC provenance.

    Parameters
    ----------
    obj     : Any TCMIM dataclass with a ``provenance`` field.
    context : Optional description of where this check is called from,
              included in the error message for easier debugging.

    Raises
    ------
    ProvenanceViolation
        Always raised when provenance is SYNTHETIC.
    """
    prov = getattr(obj, "provenance", None)
    if prov is None:
        raise AttributeError(
            f"Object of type {type(obj).__name__!r} has no 'provenance' "
            "attribute — cannot enforce provenance guard."
        )
    if Provenance(prov) == Provenance.SYNTHETIC:
        msg = (
            "INTEGRITY VIOLATION: SYNTHETIC data cannot appear in real-result "
            f"reports (FR-DA-5 / Section 2 rule 2). Object: {obj!r}"
        )
        if context:
            msg += f"\nContext: {context}"
        raise ProvenanceViolation(msg)


def filter_real(items: Iterable[T]) -> List[T]:
    """Return only items whose provenance is not SYNTHETIC.

    Parameters
    ----------
    items : Iterable of TCMIM dataclass instances with a provenance field.

    Returns
    -------
    List of items with HARDWARE or PUBLIC_DATASET provenance.
    """
    return [item for item in items if is_real(item)]


def provenance_banner(provenance: Provenance) -> str:
    """Return a human-readable status/provenance banner for reports.

    The banner is prepended to every exported CSV/JSON (FR-UI-4).
    """
    labels = {
        Provenance.HARDWARE: "DATA SOURCE: HARDWARE (real sensor data)",
        Provenance.PUBLIC_DATASET: "DATA SOURCE: PUBLIC DATASET (real, single-machine only)",
        Provenance.SYNTHETIC: (
            "DATA SOURCE: SYNTHETIC FIXTURE — "
            "NOT FOR USE IN REAL-WORLD PERFORMANCE REPORTS"
        ),
    }
    return f"[TCMIM PROVENANCE BANNER] {labels[Provenance(provenance)]}"


class ProvenanceViolation(RuntimeError):
    """Raised when SYNTHETIC data is used in a real-result context."""
