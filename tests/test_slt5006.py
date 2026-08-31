"""SLT5006 frame, response-validation, and measurement tests."""

import pytest

from murata_soil_sensor import _binary as binary_module
from murata_soil_sensor.base import (
    ProtocolError,
    SensorDeviceError,
    SensorTimeoutError,
)
from murata_soil_sensor.crc16 import append_crc_be
from murata_soil_sensor.slt5006 import Slt5006

from .fakes import FakeTransport


def _resp(fc: int, addr: int, data: bytes) -> bytes:
    return append_crc_be(bytes([fc, addr, len(data)]) + data)


def _error_resp(fc: int, code: int) -> bytes:
    return append_crc_be(bytes([fc | 0x80, code]))


def _measurement_responses() -> list[bytes]:
    block = bytes.fromhex(
        "64 00 c8 00 10 00 e8 03 0a 00 14 00 1e 00 "
        "00 00 d0 07 b8 0b"
    )
    return [
        _resp(0x02, 0x07, bytes([0x01])),
        _resp(0x01, 0x08, bytes([0x01])),
        _resp(0x01, 0x09, bytes([0x10, 0x00, 0x20, 0x00])),
        _resp(0x01, 0x0F, block),
    ]


def test_build_read_vector():
    assert Slt5006().build_read(0x00, 3) == bytes.fromhex("0100030160")


@pytest.mark.parametrize("address,size", [(-1, 1), (0, 0), (0, 27), (250, 7)])
def test_build_read_rejects_invalid_or_wrapping_range(address, size):
    with pytest.raises(ValueError):
        Slt5006().build_read(address, size)


def test_build_write_vector():
    assert Slt5006().build_write(0x07, 0x01) == bytes.fromhex("020701010d70")


def test_read_uses_frame_length_instead_of_fixed_buffer():
    transport = FakeTransport([_resp(0x01, 0x00, bytes([1, 7, 6]))])

    assert Slt5006()._read_registers(transport, 0x00, 3) == bytes([1, 7, 6])
    assert transport.read_sizes == [1, 2, 5]


def test_fragmented_read_response_is_reassembled():
    transport = FakeTransport(
        [
            _resp(0x01, 0x00, bytes([1, 7, 6])),
            _resp(0x01, 0x03, bytes([0x39, 0x30, 0x00, 0x00])),
        ],
        max_chunk_size=1,
    )

    info = Slt5006().read_info(transport)

    assert info.firmware_version == "1.7.6"
    assert info.serial_number == 12345
    assert len(transport.read_sizes) > 6


def test_partial_binary_frame_times_out():
    truncated = _resp(0x01, 0x00, bytes([1, 7, 6]))[:-1]

    with pytest.raises(SensorTimeoutError, match="binary response body"):
        Slt5006().read_info(FakeTransport([truncated], max_chunk_size=1))


def test_crc_valid_binary_error_is_decoded():
    with pytest.raises(SensorDeviceError) as caught:
        Slt5006().read_info(FakeTransport([_error_resp(0x01, 0x02)]))

    assert caught.value.code == 0x02
    assert "illegal start address" in str(caught.value)


def test_measurement_busy_version_read_is_decoded_after_start():
    transport = FakeTransport(
        [
            _resp(0x02, 0x07, bytes([0x01])),
            _error_resp(0x01, 0x06),
        ]
    )
    sensor = Slt5006()

    sensor._start_measurement(transport)
    with pytest.raises(SensorDeviceError) as caught:
        sensor.read_info(transport)

    assert caught.value.code == 0x06
    assert caught.value.description == "data read while measurement is in progress"
    assert transport.writes == [
        bytes.fromhex("02 07 01 01 0D 70"),
        bytes.fromhex("01 00 03 01 60"),
    ]


def test_binary_error_crc_is_checked_before_raising_device_error():
    response = bytearray(_error_resp(0x01, 0x05))
    response[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch") as caught:
        Slt5006().read_info(FakeTransport([bytes(response)]))

    assert not isinstance(caught.value, SensorDeviceError)


def test_binary_error_function_code_is_validated():
    with pytest.raises(ProtocolError, match="unexpected error function"):
        Slt5006().read_info(FakeTransport([_error_resp(0x02, 0x02)]))


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_resp(0x02, 0x00, bytes([1, 7, 6])), "function code"),
        (_resp(0x01, 0x01, bytes([1, 7, 6])), "read address"),
        (_resp(0x01, 0x00, bytes([1, 7])), "size field"),
    ],
)
def test_read_response_header_fields_are_validated(response, message):
    with pytest.raises(ProtocolError, match=message):
        Slt5006().read_info(FakeTransport([response]))


def test_read_response_crc_is_validated():
    response = bytearray(_resp(0x01, 0x00, bytes([1, 7, 6])))
    response[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch"):
        Slt5006().read_info(FakeTransport([bytes(response)]))


@pytest.mark.parametrize(
    "ack",
    [
        _resp(0x01, 0x07, bytes([0x01])),
        _resp(0x02, 0x08, bytes([0x01])),
        _resp(0x02, 0x07, bytes([0x00])),
    ],
)
def test_write_acknowledgement_must_echo_request(ack):
    with pytest.raises(ProtocolError):
        Slt5006()._write_register(FakeTransport([ack]), 0x07, 0x01)


def test_write_acknowledgement_crc_is_validated():
    ack = bytearray(_resp(0x02, 0x07, bytes([0x01])))
    ack[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch"):
        Slt5006()._write_register(FakeTransport([bytes(ack)]), 0x07, 0x01)


def test_read_measurement_with_fragmented_frames():
    transport = FakeTransport(_measurement_responses(), max_chunk_size=2)

    measurement = Slt5006().read_measurement(transport)

    assert measurement.dds == 16
    assert measurement.adc_ec == 32
    assert measurement.adc_permittivity == 100
    assert measurement.adc_battery == 200
    assert measurement.temperature_c == pytest.approx(1.0)
    assert measurement.ec_bulk == pytest.approx(1.0)
    assert measurement.vwc_rock == pytest.approx(1.0)
    assert measurement.vwc == pytest.approx(2.0)
    assert measurement.vwc_coco == pytest.approx(3.0)
    assert measurement.ec_pore == pytest.approx(2.0)
    assert measurement.ec_pore_coco == pytest.approx(3.0)


def test_measurement_waits_before_first_state_poll(monkeypatch):
    delays = []
    monkeypatch.setattr(binary_module.time, "sleep", delays.append)

    Slt5006().read_measurement(FakeTransport(_measurement_responses()))

    assert delays == [pytest.approx(0.3)]


def test_measurement_values_are_rounded():
    block = bytes.fromhex(
        "00 00 00 00 00 00 00 00 38 00 00 00 00 00 "
        "00 00 00 00 00 00"
    )
    responses = _measurement_responses()
    responses[-1] = _resp(0x01, 0x0F, block)

    measurement = Slt5006().read_measurement(FakeTransport(responses))

    assert measurement.vwc_rock == 5.6
    assert repr(measurement.vwc_rock) == "5.6"


def test_negative_temperature():
    block = bytes.fromhex(
        "00 00 00 00 f0 0f 00 00 00 00 00 00 00 00 "
        "00 00 00 00 00 00"
    )
    responses = _measurement_responses()
    responses[-1] = _resp(0x01, 0x0F, block)

    measurement = Slt5006().read_measurement(FakeTransport(responses))

    assert measurement.temperature_c == pytest.approx(-1.0)
