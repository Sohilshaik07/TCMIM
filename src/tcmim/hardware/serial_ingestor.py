"""
TCMIM — Serial Ingestor for Hardware Provenance (M4, M9).

Reads JSON lines from an active Serial port (connected to an ESP32),
parses the acceleration data, and emits TCMIM SensorSample objects with
HARDWARE provenance.

Usage
-----
>>> from tcmim.hardware.serial_ingestor import SerialIngestor
>>> ingestor = SerialIngestor(port="COM3", baudrate=115200)
>>> for sample in ingestor.read_stream():
...     print(sample)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

try:
    import serial
except ImportError:
    serial = None  # Graceful fallback if pyserial is not installed

from tcmim.schemas import Modality, Provenance, SensorSample

logger = logging.getLogger(__name__)


class SerialIngestor:
    """Reads hardware sensor data from a serial port."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        if serial is None:
            raise ImportError(
                "The 'pyserial' package is required for hardware ingestion. "
                "Install it via: pip install pyserial"
            )
        
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None

    def open(self) -> None:
        """Open the serial connection."""
        try:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            logger.info("Opened serial port %s at %d baud.", self.port, self.baudrate)
        except serial.SerialException as e:
            logger.error("Failed to open serial port %s: %s", self.port, e)
            raise

    def close(self) -> None:
        """Close the serial connection."""
        if self._ser and self._ser.is_open:
            self._ser.close()
            logger.info("Closed serial port %s.", self.port)

    def read_stream(self) -> Iterator[SensorSample]:
        """Yields parsed SensorSample objects continuously from the serial stream."""
        if not self._ser or not self._ser.is_open:
            self.open()

        logger.info("Listening for HARDWARE telemetry on %s...", self.port)
        
        try:
            while True:
                line = self._ser.readline().decode('utf-8', errors='replace').strip()
                if not line:
                    continue
                
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipped malformed serial line: %s", line)
                    continue
                
                # Expecting format:
                # {"machine_id": "esp...", "timestamp_ms": 1234, "data": {"accel_x": 0.1, ...}}
                if "machine_id" not in payload or "data" not in payload:
                    continue
                    
                machine_id = payload["machine_id"]
                data = payload["data"]
                
                # The top-level timestamp represents the packet timestamp.
                packet_time = datetime.now(tz=timezone.utc)

                # 1. Vibration
                if all(k in data for k in ("accel_x", "accel_y", "accel_z")):
                    x, y, z = data["accel_x"], data["accel_y"], data["accel_z"]
                    magnitude = (x**2 + y**2 + z**2) ** 0.5
                    yield SensorSample(
                        timestamp=packet_time,
                        machine_id=machine_id,
                        modality=Modality.VIBRATION,
                        value=magnitude,
                        provenance=Provenance.HARDWARE,
                        channel="adxl345_mag",
                        source_id="serial_ingestor"
                    )

                # 2. Temperature
                if "temperature" in data:
                    yield SensorSample(
                        timestamp=packet_time,
                        machine_id=machine_id,
                        modality=Modality.TEMPERATURE,
                        value=float(data["temperature"]),
                        provenance=Provenance.HARDWARE,
                        channel="ds18b20_temp",
                        source_id="serial_ingestor"
                    )

                # 3. Current
                if "current" in data:
                    yield SensorSample(
                        timestamp=packet_time,
                        machine_id=machine_id,
                        modality=Modality.CURRENT,
                        value=float(data["current"]),
                        provenance=Provenance.HARDWARE,
                        channel="ina219_current",
                        source_id="serial_ingestor"
                    )

                # 4. RPM (Rotation)
                if "rpm" in data:
                    yield SensorSample(
                        timestamp=packet_time,
                        machine_id=machine_id,
                        modality=Modality.ROTATION,
                        value=float(data["rpm"]),
                        provenance=Provenance.HARDWARE,
                        channel="tachometer_rpm",
                        source_id="serial_ingestor"
                    )
                    
        except KeyboardInterrupt:
            logger.info("Serial stream interrupted by user.")
        finally:
            self.close()
