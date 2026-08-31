"""SLT5007 — Murata binary protocol over RS-485 (multi-sensor bus).

SLT5007 uses the same frame as SLT5006, but the function-code byte encodes the
sensor number so several sensors can share one RS-485 bus::

    FC = (sensor_number << 2) | rw     # rw = 0 read, 2 write

The sensor number can be changed by writing the ``SENSOR_NUMBER`` register.
"""

from __future__ import annotations

import time

from ._binary import MurataBinarySensor
from .base import ProtocolError, SensorTimeoutError, Transport

__all__ = ["Slt5007"]

_REG_SENSOR_NUMBER = 0x23
_REG_CLEAR_NUMBER = 0x24

# The sensor stores the cleared number in EEPROM before it listens again.
_CLEAR_SETTLE_S = 0.2


class Slt5007(MurataBinarySensor):
    """Handler for SLT5007."""

    product = "SLT5007"

    #: ec_pore_coco is available on SLT5007 firmware v1.1.1 and later.
    ec_pore_coco_min_version = "1.1.1"

    def __init__(self, sensor_number: int = 0, **kwargs):
        if not 0 <= sensor_number <= 31:
            raise ValueError("SLT5007 sensor number must be 0..31")
        super().__init__(sensor_number=sensor_number, **kwargs)

    def _fc_read(self) -> int:
        return (self.sensor_number << 2) | 0x00

    def _fc_write(self) -> int:
        return (self.sensor_number << 2) | 0x02

    def _fc_read_response(self) -> int:
        return (self.sensor_number << 2) | 0x01

    def _fc_write_response(self, address: int, data: int) -> int:
        # SENSOR_NUMBER is committed before the firmware builds its ACK.
        sensor_number = data if address == _REG_SENSOR_NUMBER else self.sensor_number
        return (sensor_number << 2) | 0x02

    def read_address(self, transport: Transport) -> int:
        """Read the current sensor number from the public register."""
        value = self._read_registers(transport, _REG_SENSOR_NUMBER, 1)[0]
        if not 0 <= value <= 31:
            raise ProtocolError(f"invalid SLT5007 sensor number {value}")
        return value

    def set_address(self, transport: Transport, new_address: int | str) -> None:
        """Write a new sensor number (0-31; takes effect for subsequent commands)."""
        value = int(new_address)
        if not 0 <= value <= 31:
            raise ValueError("SLT5007 sensor number must be 0..31")
        self._write_register(transport, _REG_SENSOR_NUMBER, value)
        self.sensor_number = value
        if self.read_address(transport) != value:
            raise ProtocolError("SLT5007 address readback did not match the requested value")

    def clear_address(self, transport: Transport) -> None:
        """Reset the sensor number to 0.

        Every sensor on the bus acts on this regardless of its current number,
        and none of them answers it, so run it with one sensor connected.
        """
        transport.reset_input()
        frame = self.build_write(_REG_CLEAR_NUMBER, 0x01)
        if transport.write(frame) != len(frame):
            raise SensorTimeoutError("incomplete SLT5007 clear-address write")
        time.sleep(_CLEAR_SETTLE_S)
        self.sensor_number = 0
