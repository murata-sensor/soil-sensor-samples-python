"""CRC-16 tests, including independently verified MODBUS/SDI-12 vectors."""

from murata_soil_sensor.crc16 import (
    append_crc_be,
    append_crc_le,
    check_crc_be,
    check_crc_le,
    check_sdi12_crc,
    crc16_modbus,
    crc16_sdi12,
    encode_sdi12_crc,
)


def test_known_modbus_vector():
    # CRC of "01 03 00 00 00 03" is 0xCB05 (verified independently).
    assert crc16_modbus(bytes.fromhex("010300000003")) == 0xCB05


def test_append_le_is_low_byte_first():
    assert append_crc_le(bytes.fromhex("010300000003")) == bytes.fromhex("01030000000305cb")


def test_append_be_is_high_byte_first():
    frame = bytes.fromhex("010300000003")
    crc = crc16_modbus(frame)
    assert append_crc_be(frame) == frame + bytes([crc >> 8, crc & 0xFF])


def test_check_roundtrip():
    assert check_crc_le(append_crc_le(b"\x01\x02\x03"))
    assert check_crc_be(append_crc_be(b"\x01\x02\x03"))
    assert not check_crc_le(append_crc_le(b"\x01\x02\x03")[:-1] + b"\x00")


def test_sdi12_crc_uses_zero_initial_value():
    assert crc16_sdi12(b"") == 0x0000
    assert crc16_modbus(b"") == 0xFFFF


def test_known_sdi12_d0_vector_from_datasheet():
    payload = "0+3085+2748+764+2632+29.6+0.03"
    assert crc16_sdi12(payload.encode("ascii")) == 0x69E4
    assert encode_sdi12_crc(payload) == "Fgd"
    assert check_sdi12_crc(payload + "Fgd")


def test_known_sdi12_d1_vector_from_datasheet():
    payload = "0+14.2+2.46"
    assert crc16_sdi12(payload.encode("ascii")) == 0x88C2
    assert encode_sdi12_crc(payload) == "HcB"
    assert check_sdi12_crc(payload + "HcB")


def test_sdi12_crc_rejects_corruption_and_malformed_suffixes():
    payload = "0+14.2+2.46"
    assert not check_sdi12_crc(payload + "HcC")
    assert not check_sdi12_crc(payload + "ABC")
    assert not check_sdi12_crc("@@@")  # no address/data payload
