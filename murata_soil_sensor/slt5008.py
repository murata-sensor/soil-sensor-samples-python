"""SLT5008 — SDI-12 protocol (via TBS03 or a TBS01A evaluation board).

SDI-12 commands are ASCII, addressed by a single digit (``0``-``9``), and
terminated with ``!``. Responses end with ``<CR><LF>``.

Note on serial settings: the PC talks to the **converter**, whose PC-side serial
settings differ from the native SDI-12 line (1200 bps, 7E1). The default here
(19200, 8N1) matches the TBS03 USB converter. TBS01A uses 8N1 with a selectable
baud rate; its evaluation board requires an external 9.6-16.0 V sensor supply
because its USB-derived 5 V output is outside the SLT5008 rating.

Measurement sequence::

    aI!    -> identification (firmware version, serial number)
    aM!/aMC! -> start measurement without/with CRC-protected data
    aC!/aCC! -> start concurrent measurement without/with CRC-protected data
                 and reply "atttnn"; per the SDI-12
              spec, *no* service request, so the bus stays free for other
              sensors to measure at the same time
    aD0!   -> a+DDS+ADC_EC+ADC_PERMITTIVITY+ADC_BATTERY+TEMP+EC_BULK
    aD1!   -> a+VWC+EC_PORE
    aD2!   -> a+VWC_ROCK+VWC_COCO+EC_PORE_COCO   (newer firmware)
    aAb!   -> change address from a to b
    ?!     -> report the address (single sensor on the bus only)
    a!     -> acknowledge active (used to probe whether address a answers)

The ``aM!`` reply can only report a single-digit value count, so it advertises 8
values (``aD0!`` + ``aD1!``); ``aD2!`` is still readable and ``aC!`` advertises
the full 11.

Data values are already in engineering units (scaled by the firmware). Use
:func:`read_concurrent` to read several sensors on one bus in parallel.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence

from .base import ProtocolError, SensorTimeoutError, SerialConfig, SoilSensor, Transport
from .crc16 import check_sdi12_crc
from .measurement import Measurement, SensorInfo, battery_voltage

__all__ = ["Slt5008", "read_concurrent", "start_concurrent"]

# Matches signed SDI-12 numeric values, e.g. "+123", "-4.5".
_VALUE_RE = re.compile(r"[+-]\d+(?:\.\d+)?")
_VALUE_SEQUENCE_RE = re.compile(r"(?:[+-]\d+(?:\.\d+)?)+")

# Slack added to the sensor-declared conversion time before reading concurrent data.
_CONCURRENT_MARGIN_S = 0.5

# SDI-12 permits the sensor to remain unresponsive for one second while the
# new address is committed to nonvolatile memory.
_ADDRESS_SETTLE_S = 1.0

# The raw DDS/ADC values correspond to unsigned 16-bit register values on the
# other product interfaces. Keep the ASCII representation within that lossless
# range instead of silently coercing malformed values.
_RAW_COUNT_MAX = 0xFFFF

# TBS03/TBS01A-family converters report a completed host-side read with this
# exact frame when no SDI-12 sensor replied.  Do not accept spelling, case,
# padding, or framing variants: they are malformed/unknown adapter data.
SDI12_NO_RESPONSE_SENTINEL = b"No Response\r\n"


def _raw_count(value: float, field: str) -> int:
    if not value.is_integer() or not 0 <= value <= _RAW_COUNT_MAX:
        raise ProtocolError(f"invalid {field} raw count: {value!r}")
    return int(value)


class Slt5008(SoilSensor):
    """Handler for SLT5008 (SDI-12)."""

    product = "SLT5008"

    #: ec_pore_coco is available on SLT5008 firmware v1.7.0 and later.
    ec_pore_coco_min_version = "1.7.0"

    battery_divider = 0.18

    def __init__(
        self,
        address: str = "0",
        *,
        baudrate: int = 19200,
        timeout: float = 2.0,
        measurement_timeout: float = 10.0,
        use_crc: bool = False,
    ):
        value = str(address)
        if len(value) != 1 or value not in "0123456789":
            raise ValueError("SLT5008 address must be a single digit 0-9")
        self.address = value
        self._baudrate = baudrate
        self._timeout = timeout
        self._measurement_timeout = measurement_timeout
        self.use_crc = bool(use_crc)

    # -- serial ---------------------------------------------------------------
    @property
    def serial_config(self) -> SerialConfig:
        return SerialConfig(
            baudrate=self._baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self._timeout,
        )

    # -- SDI-12 transaction ---------------------------------------------------
    def _transaction(
        self, transport: Transport, command: str, *, allow_empty: bool = False
    ) -> str:
        transport.reset_input()
        request = f"{command}\r\n".encode("ascii")
        if transport.write(request) != len(request):
            raise SensorTimeoutError("incomplete SDI-12 converter request write")
        line = transport.read_until(b"\r\n")
        if not line:
            if allow_empty:
                return ""
            raise SensorTimeoutError("no SDI-12 response")
        if line and not line.endswith(b"\r\n"):
            raise SensorTimeoutError("incomplete SDI-12 response (missing CR/LF)")
        if line == SDI12_NO_RESPONSE_SENTINEL:
            if allow_empty:
                return ""
            raise SensorTimeoutError("no SDI-12 response (converter sentinel)")
        try:
            response = line[:-2].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProtocolError("non-ASCII SDI-12 response") from exc
        # Some converter/driver combinations pad a complete response with NUL
        # bytes. Boundary padding is harmless, but deleting NULs from inside
        # the sensor payload could make corrupt data pass CRC validation.
        response = response.strip("\x00")
        if not response:
            # ``allow_empty`` applies only to a genuinely empty serial read.
            # A framed empty/NUL-only reply is adapter data and must remain an
            # invalid response rather than being mistaken for an unused address.
            raise ProtocolError("empty framed SDI-12 response")
        if "\x00" in response:
            raise ProtocolError("embedded NUL in SDI-12 response")
        if "\r" in response or "\n" in response:
            raise ProtocolError("embedded line ending in SDI-12 response")
        return response

    @staticmethod
    def parse_values(payload: str) -> list[float]:
        """Return the signed numeric values from an SDI-12 data payload."""
        if not payload or not payload[0].isdigit():
            raise ProtocolError(f"invalid SDI-12 data payload: {payload!r}")
        body = payload[1:]
        if body and _VALUE_SEQUENCE_RE.fullmatch(body) is None:
            raise ProtocolError(f"invalid SDI-12 data payload: {payload!r}")
        return [float(match) for match in _VALUE_RE.findall(body)]

    # -- high-level API -------------------------------------------------------
    def read_info(self, transport: Transport) -> SensorInfo:
        resp = self._transaction(transport, f"{self.address}I!")
        if not 21 <= len(resp) <= 28 or resp[0] != self.address:
            raise ProtocolError(f"unexpected identification response: {resp!r}")
        sdi_raw = resp[1:3]
        vendor = resp[3:11]
        model = resp[11:17]
        firmware_raw = resp[17:20]
        serial_raw = resp[20:]
        if (
            not sdi_raw.isascii()
            or not sdi_raw.isdigit()
            or vendor != "MurataCo"
            or model != "LT5008"
            or not firmware_raw.isascii()
            or not firmware_raw.isdigit()
            or not serial_raw.isascii()
            or not serial_raw.isdigit()
        ):
            raise ProtocolError(f"unexpected identification response: {resp!r}")
        sdi_version = f"{sdi_raw[0]}.{sdi_raw[1]}"
        firmware = ".".join(firmware_raw)
        serial_number = int(serial_raw)
        return SensorInfo(
            product=self.product,
            firmware_version=firmware,
            serial_number=serial_number,
            sdi_version=sdi_version,
            vendor=vendor,
            model=model,
        )

    def read_measurement(
        self, transport: Transport, *, use_crc: bool | None = None
    ) -> Measurement:
        crc = self.use_crc if use_crc is None else use_crc
        ttt = self._start_measurement(transport, "MC" if crc else "M")
        # ttt == 0 means the data are ready now and no service request is sent.
        if ttt > 0:
            self._wait_ready(transport, ttt)
        return self.read_data(transport, use_crc=crc)

    def read_data(
        self, transport: Transport, *, use_crc: bool | None = None
    ) -> Measurement:
        """Read out a measurement that has already been started with ``aM!``/``aC!``."""
        crc = self.use_crc if use_crc is None else use_crc
        d0 = self._read_data_values(transport, 0, crc)
        d1 = self._read_data_values(transport, 1, crc)
        # SLT5008 intentionally exposes D2 after both M/MC (n=8) and C/CC.
        d2 = self._read_data_values(transport, 2, crc)
        dds = _raw_count(d0[0], "DDS")
        adc_ec = _raw_count(d0[1], "ADC_EC")
        adc_permittivity = _raw_count(d0[2], "ADC_PERMITTIVITY")
        adc_battery = _raw_count(d0[3], "ADC_BATTERY")
        return Measurement(
            dds=dds,
            adc_ec=adc_ec,
            adc_permittivity=adc_permittivity,
            adc_battery=adc_battery,
            battery_v=battery_voltage(adc_battery, self.battery_divider),
            temperature_c=d0[4],
            ec_bulk=d0[5],
            vwc=d1[0],
            ec_pore=d1[1],
            vwc_rock=d2[0],
            vwc_coco=d2[1],
            ec_pore_coco=d2[2],
        )

    def _read_data_values(
        self, transport: Transport, index: int, use_crc: bool
    ) -> list[float]:
        resp = self._transaction(transport, f"{self.address}D{index}!")
        if use_crc:
            if not check_sdi12_crc(resp):
                raise ProtocolError(f"SDI-12 CRC mismatch in D{index} response")
            resp = resp[:-3]
        if not resp.startswith(self.address):
            raise ProtocolError(f"unexpected address in D{index} response: {resp!r}")
        values = self.parse_values(resp)
        allowed_counts = {0: {6}, 1: {2}, 2: {3}}
        if len(values) not in allowed_counts[index]:
            raise ProtocolError(
                f"unexpected value count in D{index} response: {len(values)}"
            )
        return values

    def _start_measurement(self, transport: Transport, command: str) -> float:
        """Send M/MC/C/CC and return ``ttt``, the seconds until data are ready."""
        resp = self._transaction(transport, f"{self.address}{command}!")
        concurrent = command in {"C", "CC"}
        expected_length = 6 if concurrent else 5
        if (
            len(resp) != expected_length
            or resp[0] != self.address
            or not resp[1:].isdigit()
            or int(resp[4:]) != (11 if concurrent else 8)
        ):
            raise ProtocolError(f"unexpected {command} response: {resp!r}")
        ttt = float(int(resp[1:4]))
        if ttt > self._measurement_timeout:
            raise SensorTimeoutError(
                f"sensor declared {ttt:.0f}s measurement time, exceeding "
                f"the {self._measurement_timeout:.0f}s limit"
            )
        return ttt

    def _wait_ready(self, transport: Transport, max_wait: float) -> None:
        # Proceed as soon as the service request (a<CR><LF>) arrives. Do not
        # clear the input buffer here: this is an unsolicited second response
        # and may already have reached a fast converter.
        # If no service request arrives, SDI-12 permits D0 after the declared
        # ttt has elapsed, so every read is bounded by the remaining ttt.
        deadline = time.monotonic() + max(max_wait, 0.0)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            line = transport.read_until(b"\r\n", timeout=remaining)
            if not line.endswith(b"\r\n"):
                continue
            try:
                response = line[:-2].decode("ascii")
            except UnicodeDecodeError:
                continue
            # The SDI-12 service request is exactly the sensor address.
            if response == self.address:
                return

    def set_address(self, transport: Transport, new_address: int | str) -> None:
        """Change the SDI-12 address.

        SDI-12 itself allows ``0``-``9``, ``a``-``z`` and ``A``-``Z``, but the
        SLT5008 firmware supports only the digits ``0``-``9``.
        """
        new = str(new_address)
        if len(new) != 1 or new not in "0123456789":
            raise ValueError(
                "SLT5008 supports only digit addresses 0-9 "
                "(SDI-12 also allows a-z / A-Z, but this sensor does not)"
            )
        old = self.address
        resp = self._transaction(transport, f"{old}A{new}!", allow_empty=True)
        if not resp:
            raise SensorTimeoutError("no address-change response from sensor")
        if resp != new:
            if resp == old:
                raise ProtocolError(f"sensor rejected address change to {new}")
            raise ProtocolError(f"unexpected address-change response: {resp!r}")
        self.address = new
        time.sleep(_ADDRESS_SETTLE_S)
        if not self.acknowledge(transport):
            raise SensorTimeoutError(f"sensor did not answer at new address {new}")

    def read_address(self, transport: Transport) -> str:
        """Verify and return the configured SDI-12 address."""
        if not self.acknowledge(transport):
            raise SensorTimeoutError(f"sensor did not answer at address {self.address}")
        return self.address

    def query_address(self, transport: Transport) -> str | None:
        """Return the address reported by the SDI-12 address query (``?!``).

        Every sensor answers ``?!`` at once, so this only works with a single
        sensor on the bus; ``None`` means the reply was not a single address
        character (no sensor, or several talking over each other).
        """
        resp = self._transaction(transport, "?!", allow_empty=True)
        return resp if len(resp) == 1 and resp in "0123456789" else None

    def acknowledge(self, transport: Transport) -> bool:
        """Return True when this address answers the acknowledge-active command (``a!``)."""
        response = self._transaction(transport, f"{self.address}!", allow_empty=True)
        if not response:
            return False
        if response != self.address:
            raise ProtocolError(
                f"unexpected acknowledge-active response for address {self.address}: "
                f"{response!r}"
            )
        return True


def read_concurrent(sensors: Sequence[Slt5008], transport: Transport) -> list[Measurement]:
    """Read several SLT5008 sensors on one SDI-12 bus at the same time.

    Convenience wrapper around :func:`start_concurrent` plus
    :meth:`Slt5008.read_data`. Returns one
    :class:`~murata_soil_sensor.measurement.Measurement` per sensor, in the
    same order as ``sensors``.
    """
    checked = _validate_concurrent_sensors(sensors)
    start_concurrent(checked, transport)
    return [sensor.read_data(transport) for sensor in checked]


def _validate_concurrent_sensors(
    sensors: Sequence[Slt5008],
) -> list[Slt5008]:
    checked = list(sensors)
    if len(checked) < 2:
        raise ValueError("concurrent measurement requires at least two SLT5008 sensors")
    if not all(isinstance(sensor, Slt5008) for sensor in checked):
        raise TypeError("concurrent measurement supports only SLT5008 sensors")
    addresses = [sensor.address for sensor in checked]
    if len(set(addresses)) != len(addresses):
        raise ValueError("concurrent SLT5008 addresses must be unique")
    return checked


def start_concurrent(sensors: Sequence[Slt5008], transport: Transport) -> None:
    """Start a concurrent measurement on every sensor and wait until data are ready.

    ``aC!`` — unlike ``aM!`` — leaves the bus free during conversion, so every
    sensor measures at the same time. Call :meth:`Slt5008.read_data` per sensor
    afterwards to keep one sensor's failure from discarding the others' data.
    """
    checked = _validate_concurrent_sensors(sensors)
    ready_at = 0.0
    for sensor in checked:
        ttt = sensor._start_measurement(transport, "CC" if sensor.use_crc else "C")
        ready_at = max(ready_at, time.monotonic() + ttt + _CONCURRENT_MARGIN_S)
    # aC! never sends a service request, and addressing a sensor before its
    # conversion finishes aborts the measurement, so wait out the longest ttt.
    remaining = ready_at - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
