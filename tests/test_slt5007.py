"""SLT5007 function-code, error, and address-management tests."""

import pytest

from murata_soil_sensor import slt5007 as slt5007_module
from murata_soil_sensor.base import (
    ProtocolError,
    SensorDeviceError,
    SensorError,
    SensorTimeoutError,
)
from murata_soil_sensor.crc16 import append_crc_be, check_crc_be
from murata_soil_sensor.slt5006 import Slt5006
from murata_soil_sensor.slt5007 import Slt5007

from .fakes import FakeTransport


def _read_resp(sensor_number: int, addr: int, data: bytes) -> bytes:
    fc = (sensor_number << 2) | 0x01
    return append_crc_be(bytes([fc, addr, len(data)]) + data)


def _write_resp(sensor_number: int, addr: int, data: int) -> bytes:
    fc = (sensor_number << 2) | 0x02
    return append_crc_be(bytes([fc, addr, 0x01, data]))


def _error_resp(request_fc: int, code: int) -> bytes:
    return append_crc_be(bytes([request_fc | 0x80, code]))


def test_read_frame_encodes_sensor_number():
    assert Slt5007(sensor_number=2).build_read(0x00, 3) == bytes.fromhex(
        "08000303b0"
    )


def test_write_frame_encodes_sensor_number():
    frame = Slt5007(sensor_number=2).build_write(0x23, 0x05)

    assert frame[0] == 0x0A
    assert frame[1] == 0x23
    assert check_crc_be(frame)


def test_read_response_uses_read_response_function_bit():
    sensor = Slt5007(sensor_number=2)
    transport = FakeTransport([_read_resp(2, 0x23, bytes([2]))])

    assert sensor.read_address(transport) == 2
    assert transport.read_sizes == [1, 2, 3]


def test_fragmented_read_address_is_reassembled():
    sensor = Slt5007(sensor_number=7)
    transport = FakeTransport(
        [_read_resp(7, 0x23, bytes([7]))], max_chunk_size=1
    )

    assert sensor.read_address(transport) == 7


def test_read_address_rejects_out_of_range_register_value():
    sensor = Slt5007(sensor_number=2)

    with pytest.raises(ProtocolError, match="invalid SLT5007 sensor number"):
        sensor.read_address(
            FakeTransport([_read_resp(2, 0x23, bytes([0x20]))])
        )


def test_binary_error_response_preserves_request_function_code():
    sensor = Slt5007(sensor_number=2)
    request_fc = (2 << 2) | 0x00

    with pytest.raises(SensorDeviceError) as caught:
        sensor.read_address(FakeTransport([_error_resp(request_fc, 0x06)]))

    assert caught.value.code == 0x06


def test_read_response_with_request_function_code_is_rejected():
    sensor = Slt5007(sensor_number=2)
    wrong = append_crc_be(bytes([0x08, 0x23, 0x01, 0x02]))

    with pytest.raises(ProtocolError, match="read function code"):
        sensor.read_address(FakeTransport([wrong]))


def test_set_address_acknowledges_with_new_function_code_and_reads_back():
    sensor = Slt5007(sensor_number=0)
    transport = FakeTransport(
        [
            _write_resp(1, 0x23, 1),
            _read_resp(1, 0x23, bytes([1])),
        ],
        max_chunk_size=1,
    )

    sensor.set_address(transport, 1)

    assert sensor.sensor_number == 1
    assert transport.writes[0][0] == 0x02
    assert transport.writes[1][0] == 0x04
    assert transport.writes[0][1] == transport.writes[1][1] == 0x23


def test_set_address_rejects_old_function_code_in_ack():
    sensor = Slt5007(sensor_number=0)
    old_fc_ack = _write_resp(0, 0x23, 1)

    with pytest.raises(ProtocolError, match="write function code"):
        sensor.set_address(FakeTransport([old_fc_ack]), 1)

    assert sensor.sensor_number == 0


def test_set_address_validates_ack_echo_before_updating_local_address():
    sensor = Slt5007(sensor_number=0)
    wrong_echo = _write_resp(1, 0x23, 2)

    with pytest.raises(ProtocolError, match="does not echo"):
        sensor.set_address(FakeTransport([wrong_echo]), 1)

    assert sensor.sensor_number == 0


def test_set_address_validates_immediate_readback():
    sensor = Slt5007(sensor_number=0)
    transport = FakeTransport(
        [
            _write_resp(1, 0x23, 1),
            _read_resp(1, 0x23, bytes([2])),
        ]
    )

    with pytest.raises(ProtocolError, match="readback"):
        sensor.set_address(transport, 1)

    assert sensor.sensor_number == 1


@pytest.mark.parametrize("bad", [-1, 32, 99])
def test_set_address_range_validation(bad):
    with pytest.raises(ValueError):
        Slt5007().set_address(FakeTransport(), bad)


def test_clear_address_broadcasts_and_expects_no_reply(monkeypatch):
    monkeypatch.setattr(slt5007_module.time, "sleep", lambda _: None)
    sensor = Slt5007(sensor_number=7)
    transport = FakeTransport()

    sensor.clear_address(transport)

    assert sensor.sensor_number == 0
    assert transport.writes[0][1] == 0x24
    assert transport.writes[0][3] == 0x01
    assert check_crc_be(transport.writes[0])
    assert transport.read_sizes == []


def test_clear_address_rejects_a_short_write(monkeypatch):
    monkeypatch.setattr(slt5007_module.time, "sleep", lambda _: None)
    sensor = Slt5007(sensor_number=7)

    with pytest.raises(SensorTimeoutError, match="clear-address"):
        sensor.clear_address(FakeTransport(write_result=1))

    assert sensor.sensor_number == 7


@pytest.mark.parametrize("bad", [-1, 32, 99])
def test_constructor_range_validation(bad):
    with pytest.raises(ValueError):
        Slt5007(sensor_number=bad)


def test_slt5006_style_scaling_is_shared():
    assert isinstance(Slt5007(), Slt5006.__bases__[0])


def test_slt5006_address_operations_are_unsupported():
    with pytest.raises(SensorError):
        Slt5006().read_address(FakeTransport())
    with pytest.raises(SensorError):
        Slt5006().set_address(FakeTransport(), 1)
