"""
TCMIM — Unit tests for provenance guard (M0).

Tests cover:
- is_real() returns True for HARDWARE and PUBLIC_DATASET
- is_real() returns False for SYNTHETIC
- assert_not_synthetic() raises ProvenanceViolation for SYNTHETIC
- assert_not_synthetic() is silent for real provenance
- filter_real() removes SYNTHETIC items
- provenance_banner() returns correct string labels
"""

import pytest

from tcmim.provenance import (
    ProvenanceViolation,
    assert_not_synthetic,
    filter_real,
    is_real,
    provenance_banner,
)
from tcmim.schemas import Provenance, SensorSample, Modality
from datetime import datetime, timezone

NOW = datetime(2020, 2, 1, tzinfo=timezone.utc)


def _sample(prov: Provenance) -> SensorSample:
    return SensorSample(
        machine_id="m1",
        channel="TP2",
        modality=Modality.PRESSURE,
        timestamp=NOW,
        value=5.0,
        provenance=prov,
        source_id="src",
    )


class TestIsReal:
    def test_hardware_is_real(self):
        assert is_real(_sample(Provenance.HARDWARE)) is True

    def test_public_dataset_is_real(self):
        assert is_real(_sample(Provenance.PUBLIC_DATASET)) is True

    def test_synthetic_is_not_real(self):
        assert is_real(_sample(Provenance.SYNTHETIC)) is False

    def test_no_provenance_raises(self):
        class NoProvenance:
            pass
        with pytest.raises(AttributeError, match="provenance"):
            is_real(NoProvenance())


class TestAssertNotSynthetic:
    def test_hardware_passes(self):
        assert_not_synthetic(_sample(Provenance.HARDWARE))  # no raise

    def test_public_dataset_passes(self):
        assert_not_synthetic(_sample(Provenance.PUBLIC_DATASET))  # no raise

    def test_synthetic_raises(self):
        with pytest.raises(ProvenanceViolation, match="SYNTHETIC"):
            assert_not_synthetic(_sample(Provenance.SYNTHETIC))

    def test_context_in_message(self):
        with pytest.raises(ProvenanceViolation, match="my_context"):
            assert_not_synthetic(
                _sample(Provenance.SYNTHETIC), context="my_context"
            )


class TestFilterReal:
    def test_removes_synthetic(self):
        items = [
            _sample(Provenance.HARDWARE),
            _sample(Provenance.SYNTHETIC),
            _sample(Provenance.PUBLIC_DATASET),
        ]
        real = filter_real(items)
        assert len(real) == 2
        for item in real:
            assert item.provenance != Provenance.SYNTHETIC

    def test_empty_list(self):
        assert filter_real([]) == []

    def test_all_synthetic(self):
        items = [_sample(Provenance.SYNTHETIC)] * 5
        assert filter_real(items) == []

    def test_none_synthetic(self):
        items = [_sample(Provenance.HARDWARE), _sample(Provenance.PUBLIC_DATASET)]
        assert len(filter_real(items)) == 2


class TestProvenanceBanner:
    def test_hardware_banner(self):
        banner = provenance_banner(Provenance.HARDWARE)
        assert "HARDWARE" in banner

    def test_public_dataset_banner(self):
        banner = provenance_banner(Provenance.PUBLIC_DATASET)
        assert "PUBLIC DATASET" in banner

    def test_synthetic_banner_warns(self):
        banner = provenance_banner(Provenance.SYNTHETIC)
        assert "SYNTHETIC" in banner
        assert "NOT FOR USE" in banner
