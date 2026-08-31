"""CRC-16 helpers shared by the Murata soil-sensor protocols.

SLT5005/5006/5007/5009 use the CRC-16/MODBUS parameters:

* initial value ``0xFFFF``
* polynomial ``0xA001`` (reflected form of ``0x8005``)

SLT5008 uses the SDI-12 CRC variant. It has the same reflected polynomial,
but starts at ``0x0000`` and encodes the 16-bit result as three printable ASCII
characters.

The **byte order on the wire differs per product**, so two append/verify
variants are provided:

* SLT5005 / SLT5006 / SLT5007 (Murata binary): CRC is sent **high byte first**
  (:func:`append_crc_be`).
* SLT5009 (MODBUS RTU): CRC is sent **low byte first**
  (:func:`append_crc_le`), as required by the MODBUS specification.
"""

from __future__ import annotations

__all__ = [
    "crc16_modbus",
    "append_crc_le",
    "append_crc_be",
    "check_crc_le",
    "check_crc_be",
    "crc16_sdi12",
    "encode_sdi12_crc",
    "check_sdi12_crc",
]


def crc16_modbus(data: bytes) -> int:
    """Return the CRC-16/MODBUS of ``data`` as a 16-bit integer."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def crc16_sdi12(data: bytes) -> int:
    """Return the SDI-12 CRC-16 of ``data`` (initial value ``0x0000``)."""
    crc = 0x0000
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def encode_sdi12_crc(data: str | bytes) -> str:
    """Return the SDI-12 three-character CRC for an address/data payload."""
    raw = data.encode("ascii") if isinstance(data, str) else bytes(data)
    crc = crc16_sdi12(raw)
    return "".join(
        chr(value)
        for value in (
            0x40 | (crc >> 12),
            0x40 | ((crc >> 6) & 0x3F),
            0x40 | (crc & 0x3F),
        )
    )


def check_sdi12_crc(response: str) -> bool:
    """Return True when ``response`` ends in a valid SDI-12 ASCII CRC."""
    if len(response) < 4:
        return False
    payload, received = response[:-3], response[-3:]
    if not 0x40 <= ord(received[0]) <= 0x4F:
        return False
    if any(not 0x40 <= ord(ch) <= 0x7F for ch in received[1:]):
        return False
    return encode_sdi12_crc(payload) == received


def append_crc_le(frame: bytes) -> bytes:
    """Append the CRC low byte first (MODBUS / SLT5009)."""
    crc = crc16_modbus(frame)
    return frame + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def append_crc_be(frame: bytes) -> bytes:
    """Append CRC high byte first (Murata binary / SLT5005 / SLT5006 / SLT5007)."""
    crc = crc16_modbus(frame)
    return frame + bytes([(crc >> 8) & 0xFF, crc & 0xFF])


def check_crc_le(frame: bytes) -> bool:
    """Return True if the trailing little-endian CRC of ``frame`` is valid."""
    if len(frame) < 3:
        return False
    received = frame[-2] | (frame[-1] << 8)
    return crc16_modbus(frame[:-2]) == received


def check_crc_be(frame: bytes) -> bool:
    """Return True if the trailing big-endian CRC of ``frame`` is valid."""
    if len(frame) < 3:
        return False
    received = (frame[-2] << 8) | frame[-1]
    return crc16_modbus(frame[:-2]) == received
