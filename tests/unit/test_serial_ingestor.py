"""
TCMIM — Unit tests for hardware serial ingestor (M4).
"""

import json
import pytest
from unittest.mock import MagicMock

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from tcmim.hardware.serial_ingestor import SerialIngestor
from tcmim.schemas import Modality, Provenance


@pytest.mark.skipif(not HAS_SERIAL, reason="pyserial not installed")
class TestSerialIngestor:
    def _mock_ingestor(self, monkeypatch, json_lines):
        """Helper to yield a specific set of JSON lines before KeyboardInterrupt."""
        mock_serial_cls = MagicMock()
        mock_instance = MagicMock()
        mock_serial_cls.return_value = mock_instance
        
        def mock_readline():
            if not hasattr(mock_readline, "idx"):
                mock_readline.idx = 0
            if mock_readline.idx < len(json_lines):
                line = json_lines[mock_readline.idx]
                mock_readline.idx += 1
                return line
            raise KeyboardInterrupt()

        mock_instance.readline.side_effect = mock_readline
        mock_instance.is_open = True
        
        monkeypatch.setattr("tcmim.hardware.serial_ingestor.serial.Serial", mock_serial_cls)
        return SerialIngestor(port="COM_MOCK")

    def test_parses_vibration_only_packet(self, monkeypatch):
        lines = [
            b'{"machine_id": "espA", "timestamp_ms": 100, "data": {"accel_x": 0.0, "accel_y": 3.0, "accel_z": 4.0}}\n',
            b'junk data\n'
        ]
        ingestor = self._mock_ingestor(monkeypatch, lines)
        samples = list(ingestor.read_stream())
        
        assert len(samples) == 1
        s = samples[0]
        assert s.machine_id == "espA"
        assert s.modality == Modality.VIBRATION
        assert s.provenance == Provenance.HARDWARE
        assert s.value == 5.0  # sqrt(9+16)

    def test_parses_vibration_and_current(self, monkeypatch):
        lines = [
            b'{"machine_id": "espB", "timestamp_ms": 200, "data": {"accel_x": 1.0, "accel_y": 0.0, "accel_z": 0.0, "current": 2.5}}\n'
        ]
        ingestor = self._mock_ingestor(monkeypatch, lines)
        samples = list(ingestor.read_stream())
        
        assert len(samples) == 2
        assert {s.modality for s in samples} == {Modality.VIBRATION, Modality.CURRENT}
        assert all(s.machine_id == "espB" for s in samples)
        current_sample = next(s for s in samples if s.modality == Modality.CURRENT)
        assert current_sample.value == 2.5

    def test_parses_vibration_current_rpm(self, monkeypatch):
        lines = [
            b'{"machine_id": "esp1", "timestamp_ms": 300, "data": {"accel_x": 0.0, "accel_y": 0.0, "accel_z": 1.0, "current": 1.1, "rpm": 1200.0}}\n'
        ]
        ingestor = self._mock_ingestor(monkeypatch, lines)
        samples = list(ingestor.read_stream())
        
        assert len(samples) == 3
        mods = {s.modality for s in samples}
        assert mods == {Modality.VIBRATION, Modality.CURRENT, Modality.ROTATION}
        rpm_sample = next(s for s in samples if s.modality == Modality.ROTATION)
        assert rpm_sample.value == 1200.0

    def test_parses_full_multimodal_packet(self, monkeypatch):
        lines = [
            b'{"machine_id": "M_TEST", "timestamp_ms": 400, "data": {"accel_x": 0.0, "accel_y": 0.0, "accel_z": 1.0, "temperature": 45.2, "current": 1.5, "rpm": 1100}}\n'
        ]
        ingestor = self._mock_ingestor(monkeypatch, lines)
        samples = list(ingestor.read_stream())
        
        assert len(samples) == 4
        mods = {s.modality for s in samples}
        assert mods == {Modality.VIBRATION, Modality.TEMPERATURE, Modality.CURRENT, Modality.ROTATION}
        
        # All samples must have the same exact timestamp (the packet time)
        timestamps = {s.timestamp for s in samples}
        assert len(timestamps) == 1
        
        temp_sample = next(s for s in samples if s.modality == Modality.TEMPERATURE)
        assert temp_sample.value == 45.2

    def test_malformed_optional_fields_ignored(self, monkeypatch):
        # Missing 'accel_y', so VIBRATION shouldn't be yielded. Has 'temperature' but no 'current'.
        lines = [
            b'{"machine_id": "espC", "timestamp_ms": 500, "data": {"accel_x": 1.0, "accel_z": 1.0, "temperature": 25.0}}\n'
        ]
        ingestor = self._mock_ingestor(monkeypatch, lines)
        samples = list(ingestor.read_stream())
        
        assert len(samples) == 1
        assert samples[0].modality == Modality.TEMPERATURE
