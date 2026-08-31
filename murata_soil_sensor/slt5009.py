"""SLT5009 — MODBUS RTU over RS-485.

Frame layout (multi-byte values are big-endian, per MODBUS)::

    Read  request : | SLAVE | 0x03 | ADDR(2) | COUNT(2) |                 CRC(le)
    Read  response: | SLAVE | 0x03 | BYTECNT | DATA[BYTECNT]            | CRC(le)
    Write request : | SLAVE | 0x10 | ADDR(2) | COUNT(2) | BYTECNT | DATA| CRC(le)
    Write response: | SLAVE | 0x10 | ADDR(2) | COUNT(2)                 | CRC(le)

* CRC is CRC-16/MODBUS, low byte first (see :func:`crc16.append_crc_le`).
* Register addresses follow the datasheet map. Each measured value occupies one
  16-bit register; the start address is the datasheet "upper byte" address and
  consecutive values are two apart (e.g. TEMP at ``0x0016``, EC_BULK at ``0x0018``).
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from .base import (
    ProtocolError,
    SensorDeviceError,
    SensorError,
    SensorTimeoutError,
    SerialConfig,
    SoilSensor,
    Transport,
    read_exact,
    signed_12bit,
)
from .crc16 import append_crc_le, check_crc_le
from .measurement import Measurement, SensorInfo, battery_voltage

__all__ = [
    "Slt5009",
    "start_broadcast_measurement",
    "read_broadcast_measurement",
]

_FC_READ = 0x03
_FC_WRITE = 0x10
_ERROR_FLAG = 0x80

# Register (datasheet upper-byte) addresses.
_REG_VERSION = 0x0000  # MAJOR, MINOR, REVISION (3 registers)
_REG_SERIAL = 0x0006  # 2 registers: hi<<16 | lo
_REG_SNSR_CTRL = 0x000A
_REG_SNSR_STATE = 0x000C
_REG_DDS = 0x000E
_REG_ADC_EC = 0x0010
_REG_MEAS_BLOCK = 0x0012  # PERMITTIVITY .. EC_PORE_COCO (10 registers)
_MEAS_COUNT = 10
_REG_SENSOR_NUMBER = 0x0026

_SNSR_CTRL_START = 0x0001
_SNSR_STATE_DONE = 0x0001

_INTER_FRAME_DELAY_S = 0.010

_ERROR_DESCRIPTIONS = {
    0x01: "illegal function code",
    0x02: "illegal start address",
    0x03: "illegal register count or value",
    0x04: "internal receive-buffer overflow",
    0x05: "CRC-16 error",
    0x06: "data read while measurement is in progress",
    0x10: "write failure to internal storage",
    0x20: "internal sensor communication error",
    0x40: "measurement timeout",
}


class Slt5009(SoilSensor):
    """Handler for SLT5009."""

    #: ec_pore_coco is available on SLT5009 firmware v1.2.1 and later.
    ec_pore_coco_min_version = "1.2.1"

    def __init__(
        self,
        slave: int = 1,
        *,
        product: str = "SLT5009",
        timeout: float = 1.0,
        poll_interval: float = 0.2,
        measurement_timeout: float = 10.0,
    ):
        if not 1 <= slave <= 31:
            raise ValueError("SLT5009 slave number must be 1..31")
        self.slave = slave
        if poll_interval < 0:
            raise ValueError("SLT5009 poll interval must not be negative")
        self.product = product
        self._timeout = timeout
        self._poll_interval = poll_interval
        self._measurement_timeout = measurement_timeout

    # -- serial ---------------------------------------------------------------
    @property
    def serial_config(self) -> SerialConfig:
        return SerialConfig(baudrate=9600, parity="N", stopbits=1, timeout=self._timeout)

    # -- frame builders (pure; unit-tested) -----------------------------------
    def build_read(self, address: int, count: int) -> bytes:
        """Build a Read Holding Registers (FC 0x03) request frame."""
        if not 0 <= address <= 0xFFFF:
            raise ValueError("MODBUS start address must be 0..65535")
        if not 1 <= count <= 20:
            raise ValueError("SLT5009 register count must be 1..20")
        if address + count * 2 - 1 > 0xFFFF:
            raise ValueError("MODBUS read range exceeds address space")
        frame = bytes(
            [
                self.slave & 0xFF,
                _FC_READ,
                (address >> 8) & 0xFF,
                address & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            ]
        )
        return append_crc_le(frame)

    def build_write(self, address: int, values: Sequence[int]) -> bytes:
        """Build a Write Multiple Registers (FC 0x10) request frame."""
        return self._build_write_frame(self.slave, address, values)

    @staticmethod
    def _build_write_frame(slave: int, address: int, values: Sequence[int]) -> bytes:
        if not 0 <= slave <= 31:
            raise ValueError("SLT5009 frame slave number must be 0..31")
        if not 0 <= address <= 0xFFFF:
            raise ValueError("MODBUS start address must be 0..65535")
        count = len(values)
        if not 1 <= count <= 20:
            raise ValueError("SLT5009 register count must be 1..20")
        if address + count * 2 - 1 > 0xFFFF:
            raise ValueError("MODBUS write range exceeds address space")
        if any(not 0 <= value <= 0xFFFF for value in values):
            raise ValueError("MODBUS register values must be 0..65535")
        payload = bytearray(
            [
                slave,
                _FC_WRITE,
                (address >> 8) & 0xFF,
                address & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
                count * 2,
            ]
        )
        for value in values:
            payload += bytes([(value >> 8) & 0xFF, value & 0xFF])
        return append_crc_le(bytes(payload))

    # -- transaction ----------------------------------------------------------
    def _transact(self, transport: Transport, frame: bytes) -> bytes:
        transport.reset_input()
        try:
            if transport.write(frame) != len(frame):
                raise SensorTimeoutError("incomplete MODBUS request write")
            header = read_exact(transport, 2, context="MODBUS response header")
            if header[1] & _ERROR_FLAG:
                response = header + read_exact(
                    transport, 3, context="MODBUS exception response"
                )
                if not check_crc_le(response):
                    raise ProtocolError("CRC mismatch in MODBUS exception response")
                if response[0] != frame[0]:
                    raise ProtocolError(
                        f"unexpected MODBUS exception slave {response[0]}"
                    )
                if response[1] != (frame[1] | _ERROR_FLAG):
                    raise ProtocolError(
                        f"unexpected MODBUS exception function 0x{response[1]:02X}"
                    )
                code = response[2]
                description = _ERROR_DESCRIPTIONS.get(code, "unknown sensor error")
                raise SensorDeviceError(code, description, operation="MODBUS request")

            if header[0] != frame[0]:
                raise ProtocolError(f"unexpected MODBUS response slave {header[0]}")
            if header[1] != frame[1]:
                operation = "read" if frame[1] == _FC_READ else "write"
                raise ProtocolError(
                    f"unexpected MODBUS {operation} function 0x{header[1]:02X}"
                )

            if frame[1] == _FC_READ:
                byte_count = read_exact(
                    transport, 1, context="MODBUS read byte count"
                )
                requested_count = (frame[4] << 8) | frame[5]
                if byte_count[0] != requested_count * 2:
                    raise ProtocolError(
                        f"unexpected MODBUS byte count {byte_count[0]}"
                    )
                return header + byte_count + read_exact(
                    transport,
                    byte_count[0] + 2,
                    context="MODBUS read response body",
                )
            if frame[1] == _FC_WRITE:
                return header + read_exact(
                    transport, 6, context="MODBUS write response body"
                )
            raise ProtocolError(f"unsupported request function 0x{frame[1]:02X}")
        finally:
            # Conservative half-duplex guard for adapter/device turn-around.
            time.sleep(_INTER_FRAME_DELAY_S)

    def _read_registers(self, transport: Transport, address: int, count: int) -> list:
        resp = self._transact(transport, self.build_read(address, count))
        expected = 3 + count * 2 + 2
        if len(resp) != expected:
            raise ProtocolError(f"unexpected MODBUS read length {len(resp)}")
        if not check_crc_le(resp):
            raise ProtocolError("CRC mismatch in read response")
        if resp[0] != self.slave:
            raise ProtocolError(f"unexpected MODBUS response slave {resp[0]}")
        if resp[1] != _FC_READ:
            raise ProtocolError(f"unexpected MODBUS read function 0x{resp[1]:02X}")
        if resp[2] != count * 2:
            raise ProtocolError(f"unexpected MODBUS byte count {resp[2]}")
        data = resp[3 : 3 + count * 2]
        return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]

    def _write_registers(
        self, transport: Transport, address: int, values: Sequence[int]
    ) -> None:
        resp = self._transact(transport, self.build_write(address, values))
        if len(resp) != 8:
            raise ProtocolError(f"unexpected MODBUS write length {len(resp)}")
        if not check_crc_le(resp):
            raise ProtocolError("CRC mismatch in write response")
        if resp[0] != self.slave:
            raise ProtocolError(f"unexpected MODBUS response slave {resp[0]}")
        if resp[1] != _FC_WRITE:
            raise ProtocolError(f"unexpected MODBUS write function 0x{resp[1]:02X}")
        echoed_address = (resp[2] << 8) | resp[3]
        echoed_count = (resp[4] << 8) | resp[5]
        if echoed_address != address or echoed_count != len(values):
            raise ProtocolError("MODBUS write acknowledgement does not echo the request")

    # -- high-level API -------------------------------------------------------
    def read_info(self, transport: Transport) -> SensorInfo:
        ver = self._read_registers(transport, _REG_VERSION, 3)
        firmware = f"{ver[0]}.{ver[1]}.{ver[2]}"
        ser = self._read_registers(transport, _REG_SERIAL, 2)
        serial_number = (ser[0] << 16) | ser[1]
        return SensorInfo(
            product=self.product, firmware_version=firmware, serial_number=serial_number
        )

    def read_measurement(self, transport: Transport) -> Measurement:
        self._write_registers(transport, _REG_SNSR_CTRL, [_SNSR_CTRL_START])
        self._wait_measurement(transport)
        return self.read_data(transport)

    def read_data(self, transport: Transport) -> Measurement:
        """Read the latest completed measurement without starting a new one."""
        return self._read_values(transport)

    def _wait_measurement(self, transport: Transport) -> None:
        deadline = time.monotonic() + self._measurement_timeout
        while time.monotonic() < deadline:
            state = self._read_registers(transport, _REG_SNSR_STATE, 1)
            if state[0] & _SNSR_STATE_DONE:
                return
            time.sleep(self._poll_interval)
        raise SensorTimeoutError("measurement did not complete in time")

    def _read_values(self, transport: Transport) -> Measurement:
        dds = self._read_registers(transport, _REG_DDS, 1)[0]
        adc_ec = self._read_registers(transport, _REG_ADC_EC, 1)[0]
        words = self._read_registers(transport, _REG_MEAS_BLOCK, _MEAS_COUNT)
        # words: perm, battery, temp, ec_bulk, vwc_rock, vwc, vwc_coco,
        #        reserved, ec_pore, ec_pore_coco
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

    def set_address(self, transport: Transport, new_address: int | str) -> None:
        """Write a new slave number (MODBUS address). Valid range: 1-31."""
        value = int(new_address)
        if not 1 <= value <= 31:
            raise ValueError("SLT5009 slave number must be 1..31")
        self._write_registers(transport, _REG_SENSOR_NUMBER, [value])
        self.slave = value
        if self.read_address(transport) != value:
            raise ProtocolError("SLT5009 address readback did not match the requested value")

    def read_address(self, transport: Transport) -> int:
        """Read the current MODBUS slave number from the public register."""
        value = self._read_registers(transport, _REG_SENSOR_NUMBER, 1)[0]
        if not 1 <= value <= 31:
            raise ProtocolError(f"invalid SLT5009 slave number {value}")
        return value


def _validate_broadcast_sensors(sensors: Sequence[Slt5009]) -> list[Slt5009]:
    result = list(sensors)
    if len(result) < 2:
        raise ValueError("broadcast measurement requires at least two SLT5009 sensors")
    if not all(isinstance(sensor, Slt5009) for sensor in result):
        raise TypeError("broadcast measurement supports only SLT5009 sensors")
    slaves = [sensor.slave for sensor in result]
    if len(set(slaves)) != len(slaves):
        raise ValueError("SLT5009 broadcast sensor addresses must be unique")
    return result


def start_broadcast_measurement(
    sensors: Sequence[Slt5009],
    transport: Transport,
    *,
    continue_on_error: bool = False,
) -> dict[int, SensorError] | None:
    """Start all SLT5009s on the bus together and wait for listed sensors.

    The FC10 broadcast is deliberately fixed to ``SNSR_CTRL=MEASRUN``. Every
    SLT5009 physically present on the bus starts, including sensors not listed
    in ``sensors``; MODBUS broadcast requests have no acknowledgement. With
    ``continue_on_error=True``, every listed sensor is polled and the return
    value maps failed slave numbers to their :class:`SensorError`; otherwise
    the first polling error is raised and the return value is ``None``.
    """
    checked = _validate_broadcast_sensors(sensors)
    frame = Slt5009._build_write_frame(0, _REG_SNSR_CTRL, [_SNSR_CTRL_START])
    transport.reset_input()
    try:
        if transport.write(frame) != len(frame):
            raise SensorTimeoutError("incomplete MODBUS broadcast write")
    finally:
        # Transport.write() drains the physical transmit queue. The silent
        # interval therefore starts after the final stop bit, even though a
        # MODBUS broadcast has no response to provide that synchronization.
        time.sleep(_INTER_FRAME_DELAY_S)
    time.sleep(max(sensor._poll_interval for sensor in checked))
    errors: dict[int, SensorError] = {}
    for sensor in checked:
        try:
            sensor._wait_measurement(transport)
        except SensorError as exc:
            if not continue_on_error:
                raise
            errors[sensor.slave] = exc
    return errors if continue_on_error else None


def read_broadcast_measurement(
    sensors: Sequence[Slt5009], transport: Transport
) -> list[Measurement]:
    """Start a measurement by broadcast and read every listed SLT5009."""
    checked = _validate_broadcast_sensors(sensors)
    start_broadcast_measurement(checked, transport)
    return [sensor.read_data(transport) for sensor in checked]
