"""Transport, serial configuration, and the common sensor interface.

The design deliberately separates three concerns so the code is easy to read,
test, and port:

* :class:`SerialConfig` — the serial-line settings for a product.
* :class:`Transport` — a minimal byte-stream interface. :class:`SerialTransport`
  implements it with pyserial; tests can supply a fake instead.
* :class:`SoilSensor` — the high-level, product-independent API
  (:meth:`read_info`, :meth:`read_measurement`, :meth:`set_address`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .measurement import Measurement, SensorInfo

__all__ = [
    "SensorError",
    "SensorTimeoutError",
    "ProtocolError",
    "SensorDeviceError",
    "SerialConfig",
    "Transport",
    "SerialTransport",
    "SoilSensor",
    "read_exact",
    "signed_12bit",
    "parse_version",
]


class SensorError(Exception):
    """Base class for all sensor communication errors."""


class SensorTimeoutError(SensorError):
    """No (complete) response was received within the timeout."""


class ProtocolError(SensorError):
    """The sensor returned an error frame or an unparseable response."""


class SensorDeviceError(ProtocolError):
    """A CRC-valid error response returned by the sensor."""

    def __init__(self, code: int, description: str, *, operation: str = "request"):
        self.code = code
        self.description = description
        self.operation = operation
        super().__init__(f"{operation} failed with 0x{code:02X}: {description}")


def signed_12bit(raw: int) -> int:
    """Interpret the low 12 bits of ``raw`` as a signed (two's complement) value."""
    value = raw & 0x0FFF
    if value & 0x0800:
        value -= 0x1000
    return value


def parse_version(version: str) -> tuple:
    """Parse a ``"major.minor.revision"`` string into a comparable tuple."""
    parts = []
    for piece in str(version).split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


@dataclass(frozen=True)
class SerialConfig:
    """Serial-line settings. ``parity`` is one of ``'N'``, ``'E'``, ``'O'``."""

    baudrate: int
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 1.0

    def open(self, port: str):
        """Open and return a configured ``serial.Serial`` (requires pyserial)."""
        import serial

        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }
        bytesize_map = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS,
        }
        stopbits_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}
        return serial.Serial(
            port=port,
            baudrate=self.baudrate,
            bytesize=bytesize_map[self.bytesize],
            parity=parity_map[self.parity],
            stopbits=stopbits_map[self.stopbits],
            timeout=self.timeout,
        )


@runtime_checkable
class Transport(Protocol):
    """Minimal byte-stream interface used by the protocol handlers."""

    def write(self, data: bytes) -> int:
        """Write ``data``, drain queued output, and return the byte count."""

    def read(self, size: int) -> bytes:
        """Read up to ``size`` bytes (may return fewer on timeout)."""

    def read_until(
        self, expected: bytes, *, timeout: float | None = None
    ) -> bytes:
        """Read through ``expected`` with an optional per-call timeout."""

    def reset_input(self) -> None:
        """Discard any buffered input."""


def read_exact(transport: Transport, size: int, *, context: str = "response") -> bytes:
    """Read exactly ``size`` bytes, accepting a response split across reads."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = transport.read(size - len(chunks))
        if not chunk:
            raise SensorTimeoutError(
                f"short {context} ({len(chunks)} bytes, expected {size})"
            )
        if len(chunk) > size - len(chunks):
            raise ProtocolError(f"transport returned too many bytes for {context}")
        chunks.extend(chunk)
    return bytes(chunks)


class SerialTransport:
    """A :class:`Transport` backed by a pyserial ``Serial`` port."""

    def __init__(self, port: str, config: SerialConfig):
        self._serial = config.open(port)

    def write(self, data: bytes) -> int:
        written = self._serial.write(data)
        # ``serial.write`` may return after queuing bytes in the OS/USB driver.
        # Waiting here makes Transport.write's completion contract suitable for
        # half-duplex protocols whose silent interval begins after the last bit.
        self._serial.flush()
        return written

    def read(self, size: int) -> bytes:
        return self._serial.read(size)

    def read_until(
        self, expected: bytes, *, timeout: float | None = None
    ) -> bytes:
        if timeout is None:
            return self._serial.read_until(expected)
        if timeout < 0:
            raise ValueError("read timeout must not be negative")
        previous = self._serial.timeout
        effective = timeout if previous is None else min(previous, timeout)
        self._serial.timeout = effective
        try:
            return self._serial.read_until(expected)
        finally:
            self._serial.timeout = previous

    def reset_input(self) -> None:
        self._serial.reset_input_buffer()

    def close(self) -> None:
        self._serial.close()

    def __enter__(self) -> SerialTransport:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class SoilSensor(ABC):
    """Product-independent high-level API for a Murata soil sensor."""

    #: Human-readable product identifier (e.g. ``"SLT5006"``).
    product: str = "unknown"

    #: Minimum firmware version that reports ``ec_pore_coco`` (None = always).
    ec_pore_coco_min_version: str | None = None

    #: Resistive divider in front of the battery ADC, used to derive ``battery_v``.
    battery_divider: float = 0.5

    def supports_ec_pore_coco(self, firmware_version: str) -> bool:
        """Return True if this firmware version reports ``ec_pore_coco``."""
        if self.ec_pore_coco_min_version is None:
            return True
        return parse_version(firmware_version) >= parse_version(self.ec_pore_coco_min_version)

    @property
    @abstractmethod
    def serial_config(self) -> SerialConfig:
        """The serial settings to use for this product."""

    @abstractmethod
    def read_info(self, transport: Transport) -> SensorInfo:
        """Read firmware version and serial number."""

    @abstractmethod
    def read_measurement(self, transport: Transport) -> Measurement:
        """Trigger a measurement (if needed) and return the values."""

    @abstractmethod
    def set_address(self, transport: Transport, new_address: int | str) -> None:
        """Change the sensor's address / slave number."""

    def read_address(self, transport: Transport) -> int | str:
        """Read or verify the configured address when the product supports it."""
        raise SensorError(f"{self.product} does not support an address")

    def open(self, port: str) -> SerialTransport:
        """Open a :class:`SerialTransport` for this product on ``port``."""
        return SerialTransport(port, self.serial_config)
