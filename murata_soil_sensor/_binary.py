"""Common implementation of the Murata binary protocol (SLT5006 / SLT5007).

Frame layout (all multi-byte measurement values are little-endian)::

    Read  request : | FC | ADDR | SIZE |                 CRC(be)
    Write request : | FC | ADDR | SIZE | DATA[SIZE]     | CRC(be)
    Response      : | FC | ADDR | SIZE | DATA[SIZE]     | CRC(be)

* ``FC`` = ``0x01`` (read) / ``0x02`` (write) for SLT5006. SLT5007 encodes the
  sensor number in ``FC`` (overridden in :mod:`~murata_soil_sensor.slt5007`).
* CRC is CRC-16/MODBUS sent high byte first (see :func:`crc16.append_crc_be`).

The measurement values live in a contiguous register block; see
:data:`_MEAS_START` / :data:`_MEAS_LEN` and :meth:`MurataBinarySensor.read_measurement`.
"""

from __future__ import annotations

import time

from .base import (
    ProtocolError,
    SensorDeviceError,
    SensorTimeoutError,
    SerialConfig,
    SoilSensor,
    Transport,
    read_exact,
    signed_12bit,
)
from .crc16 import append_crc_be, check_crc_be
from .measurement import Measurement, SensorInfo, battery_voltage

# Function codes (read/write) before any sensor-number encoding.
_FC_READ = 0x01
_FC_WRITE = 0x02

# Register (byte) addresses.
_REG_VERSION = 0x00  # MAJOR, MINOR, REVISION (3 bytes)
_REG_SERIAL = 0x03  # LL, LU, UL, UU (4 bytes)
_REG_SNSR_CTRL = 0x07
_REG_SNSR_STATE = 0x08
_REG_DDS = 0x09  # DDS (2 bytes) + ADC_EC (2 bytes)
_REG_MEAS_BLOCK = 0x0F  # PERMITTIVITY .. EC_PORE_COCO
_MEAS_LEN = 20  # bytes = 10 little-endian words

_SNSR_CTRL_START = 0x01
_SNSR_STATE_DONE = 0x01

# Give the sensor time to enter its measurement-time command handler after the
# start acknowledgement.  The legacy implementation provided this delay
# implicitly by reading into an oversized buffer until the serial timeout.
_MEASUREMENT_START_SETTLE = 0.3

_ERROR_DESCRIPTIONS = {
    0x01: "illegal function code",
    0x02: "illegal start address",
    0x03: "illegal byte size",
    0x04: "internal receive-buffer overflow",
    0x05: "CRC-16 error",
    0x06: "data read while measurement is in progress",
    0x10: "write failure to internal storage",
    0x20: "internal sensor communication error",
    0x40: "measurement timeout",
}


class MurataBinarySensor(SoilSensor):
    """Shared logic for the SLT5006/SLT5007 binary protocol."""

    def __init__(
        self,
        sensor_number: int = 0,
        *,
        timeout: float = 0.3,
        poll_interval: float = 0.2,
        measurement_timeout: float = 30.0,
    ):
        self.sensor_number = sensor_number
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._measurement_timeout = measurement_timeout

    # -- serial ---------------------------------------------------------------
    @property
    def serial_config(self) -> SerialConfig:
        return SerialConfig(baudrate=9600, parity="N", stopbits=1, timeout=self._timeout)

    # -- function-code encoding (overridden by SLT5007) -----------------------
    def _fc_read(self) -> int:
        return _FC_READ

    def _fc_write(self) -> int:
        return _FC_WRITE

    def _fc_read_response(self) -> int:
        return self._fc_read()

    def _fc_write_response(self, address: int, data: int) -> int:
        return self._fc_write()

    # -- frame builders (pure; unit-tested) -----------------------------------
    def build_read(self, address: int, size: int) -> bytes:
        """Build a read-request frame for ``size`` bytes at ``address``."""
        if not 0 <= address <= 0xFF:
            raise ValueError("binary register address must be 0..255")
        if not 1 <= size <= 26:
            raise ValueError("binary read size must be 1..26")
        if address + size - 1 > 0xFF:
            raise ValueError("binary read range exceeds address space")
        return append_crc_be(bytes([self._fc_read(), address, size]))

    def build_write(self, address: int, data: int) -> bytes:
        """Build a single-byte write-request frame."""
        if not 0 <= address <= 0xFF:
            raise ValueError("binary register address must be 0..255")
        if not 0 <= data <= 0xFF:
            raise ValueError("binary register value must be 0..255")
        return append_crc_be(bytes([self._fc_write(), address, 0x01, data]))

    # -- transaction ----------------------------------------------------------
    def _transact(self, transport: Transport, frame: bytes) -> bytes:
        transport.reset_input()
        if transport.write(frame) != len(frame):
            raise SensorTimeoutError("incomplete binary request write")
        first = read_exact(transport, 1, context="binary response")
        if first[0] & 0x80:
            error_frame = first + read_exact(
                transport, 3, context="binary error response"
            )
            if not check_crc_be(error_frame):
                raise ProtocolError("CRC mismatch in binary error response")
            expected_fc = frame[0] | 0x80
            if error_frame[0] != expected_fc:
                raise ProtocolError(
                    f"unexpected error function code 0x{error_frame[0]:02X}"
                )
            code = error_frame[1]
            description = _ERROR_DESCRIPTIONS.get(code, "unknown sensor error")
            raise SensorDeviceError(code, description, operation="binary request")

        header = first + read_exact(transport, 2, context="binary response header")
        if header[2] > 26:
            raise ProtocolError(f"invalid binary response size {header[2]}")
        return header + read_exact(
            transport, header[2] + 2, context="binary response body"
        )

    def _read_registers(self, transport: Transport, address: int, size: int) -> bytes:
        resp = self._transact(transport, self.build_read(address, size))
        if not check_crc_be(resp):
            raise ProtocolError("CRC mismatch in read response")
        if resp[0] != self._fc_read_response():
            raise ProtocolError(f"unexpected read function code 0x{resp[0]:02X}")
        if resp[1] != address:
            raise ProtocolError(f"unexpected read address 0x{resp[1]:02X}")
        if resp[2] != size:
            raise ProtocolError(f"unexpected size field 0x{resp[2]:02X}")
        return resp[3 : 3 + size]

    def _write_register(self, transport: Transport, address: int, data: int) -> None:
        resp = self._transact(transport, self.build_write(address, data))
        if not check_crc_be(resp):
            raise ProtocolError("CRC mismatch in write response")
        expected_fc = self._fc_write_response(address, data)
        if resp[0] != expected_fc:
            raise ProtocolError(f"unexpected write function code 0x{resp[0]:02X}")
        if resp[1:4] != bytes([address, 0x01, data]):
            raise ProtocolError("write acknowledgement does not echo the request")

    # -- high-level API -------------------------------------------------------
    def read_info(self, transport: Transport) -> SensorInfo:
        ver = self._read_registers(transport, _REG_VERSION, 3)
        firmware = f"{ver[0]}.{ver[1]}.{ver[2]}"
        ser = self._read_registers(transport, _REG_SERIAL, 4)
        serial_number = ser[0] | (ser[1] << 8) | (ser[2] << 16) | (ser[3] << 24)
        return SensorInfo(
            product=self.product, firmware_version=firmware, serial_number=serial_number
        )

    def read_measurement(self, transport: Transport) -> Measurement:
        self._start_measurement(transport)
        self._wait_measurement(transport)
        return self._read_values(transport)

    def _start_measurement(self, transport: Transport) -> None:
        self._write_register(transport, _REG_SNSR_CTRL, _SNSR_CTRL_START)

    def _wait_measurement(self, transport: Transport) -> None:
        deadline = time.monotonic() + self._measurement_timeout
        time.sleep(_MEASUREMENT_START_SETTLE)
        while time.monotonic() < deadline:
            state = self._read_registers(transport, _REG_SNSR_STATE, 1)
            if state[0] & _SNSR_STATE_DONE:
                return
            time.sleep(self._poll_interval)
        raise SensorTimeoutError("measurement did not complete in time")

    def _read_values(self, transport: Transport) -> Measurement:
        # DDS + ADC_EC (2 little-endian words).
        head = self._read_registers(transport, _REG_DDS, 4)
        dds = head[0] | (head[1] << 8)
        adc_ec = head[2] | (head[3] << 8)

        block = self._read_registers(transport, _REG_MEAS_BLOCK, _MEAS_LEN)
        words = [block[i] | (block[i + 1] << 8) for i in range(0, _MEAS_LEN, 2)]
        # words: perm, battery, temp, ec_bulk, vwc_rock, vwc, vwc_coco,
        #        ec_pore_s1 (unused), ec_pore, ec_pore_coco
        return Measurement(
            dds=dds,
            adc_ec=adc_ec,
            adc_permittivity=words[0],
            adc_battery=words[1],
            battery_v=battery_voltage(words[1], self.battery_divider),
            temperature_c=round(signed_12bit(words[2]) * 0.0625, 4),
            ec_bulk=round(words[3] * 0.001, 3),
            vwc_rock=round(words[4] * 0.1, 1),
            vwc=round(words[5] * 0.1, 1),
            vwc_coco=round(words[6] * 0.1, 1),
            ec_pore=round(words[8] * 0.001, 3),
            ec_pore_coco=round(words[9] * 0.001, 3),
        )
