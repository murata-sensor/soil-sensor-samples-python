"""SLT5009 MODBUS framing, validation, addressing, and broadcast tests."""

from collections import deque

import pytest

from murata_soil_sensor import slt5009 as slt5009_module
from murata_soil_sensor.base import (
    ProtocolError,
    SensorDeviceError,
    SensorTimeoutError,
    SerialTransport,
)
from murata_soil_sensor.crc16 import append_crc_le
from murata_soil_sensor.slt5006 import Slt5006
from murata_soil_sensor.slt5009 import (
    Slt5009,
    start_broadcast_measurement,
)

from .fakes import FakeTransport


@pytest.fixture(autouse=True)
def _avoid_real_protocol_delays(monkeypatch):
    monkeypatch.setattr(slt5009_module.time, "sleep", lambda _: None)


def _read_resp(slave: int, words: list[int], *, function: int = 0x03) -> bytes:
    payload = bytes([slave, function, len(words) * 2])
    for word in words:
        payload += bytes([(word >> 8) & 0xFF, word & 0xFF])
    return append_crc_le(payload)


def _write_resp(
    slave: int, addr: int, count: int, *, function: int = 0x10
) -> bytes:
    return append_crc_le(
        bytes(
            [
                slave,
                function,
                (addr >> 8) & 0xFF,
                addr & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            ]
        )
    )


def _exception_resp(slave: int, request_function: int, code: int) -> bytes:
    return append_crc_le(bytes([slave, request_function | 0x80, code]))


def _measurement_responses(slave: int) -> list[bytes]:
    return [
        _write_resp(slave, 0x000A, 1),
        _read_resp(slave, [0x0001]),
        _read_resp(slave, [16]),
        _read_resp(slave, [32]),
        _read_resp(
            slave,
            [100, 200, 16, 1000, 10, 20, 30, 0, 2000, 3000],
        ),
    ]


def test_build_read_vector():
    assert Slt5009(slave=1).build_read(0x0000, 3) == bytes.fromhex(
        "01030000000305cb"
    )


def test_build_write_vector():
    assert Slt5009(slave=1).build_write(0x000A, [1]) == bytes.fromhex(
        "0110000a0001020001673a"
    )


def test_build_write_multi_register_bytecount():
    frame = Slt5009(slave=1).build_write(0x0010, [0x1111, 0x2222])

    assert frame[4:7] == bytes([0x00, 0x02, 0x04])
    assert frame[7:11] == bytes([0x11, 0x11, 0x22, 0x22])


@pytest.mark.parametrize("bad", [0, 21])
def test_build_read_rejects_unsupported_register_count(bad):
    with pytest.raises(ValueError):
        Slt5009().build_read(0, bad)


@pytest.mark.parametrize("bad", [-1, 0x10000])
def test_build_write_rejects_out_of_range_values(bad):
    with pytest.raises(ValueError):
        Slt5009().build_write(0, [bad])


def test_read_uses_modbus_frame_byte_count():
    transport = FakeTransport([_read_resp(1, [0x1234])])

    assert Slt5009(slave=1)._read_registers(transport, 0x000E, 1) == [0x1234]
    assert transport.read_sizes == [2, 1, 4]


def test_fragmented_modbus_read_is_reassembled():
    transport = FakeTransport(
        [_read_resp(1, [1, 2, 3])], max_chunk_size=1
    )

    assert Slt5009(slave=1)._read_registers(transport, 0x0000, 3) == [1, 2, 3]
    assert len(transport.read_sizes) > 3


def test_partial_modbus_frame_times_out():
    response = _read_resp(1, [0x1234])[:-1]

    with pytest.raises(SensorTimeoutError, match="MODBUS read response body"):
        Slt5009(slave=1)._read_registers(
            FakeTransport([response], max_chunk_size=1), 0x000E, 1
        )


def test_crc_valid_modbus_exception_is_decoded():
    with pytest.raises(SensorDeviceError) as caught:
        Slt5009(slave=1)._read_registers(
            FakeTransport([_exception_resp(1, 0x03, 0x02)]), 0x0000, 1
        )

    assert caught.value.code == 0x02
    assert "illegal start address" in str(caught.value)


def test_modbus_request_crc_exception_has_product_specific_description():
    with pytest.raises(SensorDeviceError) as caught:
        Slt5009(slave=1)._read_registers(
            FakeTransport([_exception_resp(1, 0x03, 0x05)]), 0x0000, 1
        )

    assert caught.value.code == 0x05
    assert "CRC-16 error" in str(caught.value)


def test_modbus_exception_crc_is_checked_before_device_error():
    response = bytearray(_exception_resp(1, 0x03, 0x02))
    response[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch") as caught:
        Slt5009(slave=1)._read_registers(
            FakeTransport([bytes(response)]), 0x0000, 1
        )

    assert not isinstance(caught.value, SensorDeviceError)


def test_modbus_exception_slave_is_validated():
    with pytest.raises(ProtocolError, match="exception slave"):
        Slt5009(slave=1)._read_registers(
            FakeTransport([_exception_resp(2, 0x03, 0x02)]), 0x0000, 1
        )


def test_modbus_exception_function_is_validated():
    with pytest.raises(ProtocolError, match="exception function"):
        Slt5009(slave=1)._read_registers(
            FakeTransport([_exception_resp(1, 0x10, 0x02)]), 0x0000, 1
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_read_resp(2, [1]), "response slave"),
        (_read_resp(1, [1], function=0x04), "read function"),
        (_read_resp(1, [1, 2]), "byte count"),
    ],
)
def test_modbus_read_header_fields_are_validated(response, message):
    with pytest.raises(ProtocolError, match=message):
        Slt5009(slave=1)._read_registers(
            FakeTransport([response]), 0x000E, 1
        )


def test_modbus_read_crc_is_validated():
    response = bytearray(_read_resp(1, [1]))
    response[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch"):
        Slt5009(slave=1)._read_registers(
            FakeTransport([bytes(response)]), 0x000E, 1
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_write_resp(2, 0x000A, 1), "response slave"),
        (_write_resp(1, 0x000A, 1, function=0x11), "write function"),
        (_write_resp(1, 0x000C, 1), "does not echo"),
        (_write_resp(1, 0x000A, 2), "does not echo"),
    ],
)
def test_modbus_write_acknowledgement_is_validated(response, message):
    with pytest.raises(ProtocolError, match=message):
        Slt5009(slave=1)._write_registers(
            FakeTransport([response]), 0x000A, [1]
        )


def test_modbus_write_acknowledgement_crc_is_validated():
    response = bytearray(_write_resp(1, 0x000A, 1))
    response[-1] ^= 0x01

    with pytest.raises(ProtocolError, match="CRC mismatch"):
        Slt5009(slave=1)._write_registers(
            FakeTransport([bytes(response)]), 0x000A, [1]
        )


def test_modbus_inter_frame_delay_is_applied(monkeypatch):
    delays = []
    monkeypatch.setattr(slt5009_module.time, "sleep", delays.append)

    Slt5009(slave=1)._read_registers(
        FakeTransport([_read_resp(1, [1])]), 0x000E, 1
    )

    assert delays == [pytest.approx(0.010)]


def test_read_measurement_with_fragmented_frames():
    measurement = Slt5009(slave=1).read_measurement(
        FakeTransport(_measurement_responses(1), max_chunk_size=2)
    )

    assert measurement.dds == 16
    assert measurement.adc_ec == 32
    assert measurement.adc_permittivity == 100
    assert measurement.adc_battery == 200
    assert measurement.temperature_c == pytest.approx(1.0)
    assert measurement.ec_bulk == pytest.approx(1.0)
    assert measurement.vwc == pytest.approx(2.0)
    assert measurement.ec_pore == pytest.approx(2.0)
    assert measurement.ec_pore_coco == pytest.approx(3.0)


def test_read_address():
    assert Slt5009(slave=5).read_address(
        FakeTransport([_read_resp(5, [5])])
    ) == 5


def test_read_address_rejects_invalid_register_value():
    with pytest.raises(ProtocolError, match="invalid SLT5009 slave number"):
        Slt5009(slave=5).read_address(
            FakeTransport([_read_resp(5, [0])])
        )


def test_set_address_acks_on_old_slave_then_reads_back_on_new_slave():
    sensor = Slt5009(slave=1)
    transport = FakeTransport(
        [
            _write_resp(1, 0x0026, 1),
            _read_resp(5, [5]),
        ],
        max_chunk_size=1,
    )

    sensor.set_address(transport, "5")

    assert sensor.slave == 5
    assert transport.writes[0] == bytes.fromhex("0110002600010200056155")
    assert transport.writes[1][0:2] == bytes([5, 0x03])


def test_set_address_validates_ack_before_updating_local_slave():
    sensor = Slt5009(slave=1)

    with pytest.raises(ProtocolError, match="does not echo"):
        sensor.set_address(
            FakeTransport([_write_resp(1, 0x0028, 1)]), 5
        )

    assert sensor.slave == 1


def test_set_address_validates_immediate_readback():
    sensor = Slt5009(slave=1)
    transport = FakeTransport(
        [
            _write_resp(1, 0x0026, 1),
            _read_resp(5, [4]),
        ]
    )

    with pytest.raises(ProtocolError, match="readback"):
        sensor.set_address(transport, 5)

    assert sensor.slave == 5


@pytest.mark.parametrize("bad", [0, 32, 300])
def test_set_address_range_validation(bad):
    with pytest.raises(ValueError):
        Slt5009(slave=1).set_address(FakeTransport(), bad)


@pytest.mark.parametrize("bad", [0, 32])
def test_constructor_rejects_non_unicast_slave(bad):
    with pytest.raises(ValueError):
        Slt5009(slave=bad)


def test_broadcast_start_uses_fixed_measurement_vector_and_no_ack_read():
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]
    transport = FakeTransport(
        [
            _read_resp(1, [1]),
            _read_resp(2, [1]),
        ]
    )

    start_broadcast_measurement(sensors, transport)

    assert transport.writes[0] == bytes.fromhex(
        "0010000a00010200016aaa"
    )
    assert transport.writes[1][0:2] == bytes([1, 0x03])
    assert transport.writes[2][0:2] == bytes([2, 0x03])
    assert transport.read_sizes == [2, 1, 4, 2, 1, 4]


def test_serial_flush_precedes_broadcast_gap_and_first_poll(monkeypatch):
    events = []
    responses = deque([_read_resp(1, [1]), _read_resp(2, [1])])

    class StubSerial:
        timeout = 1.0

        def __init__(self):
            self.active = bytearray()

        def reset_input_buffer(self):
            events.append(("reset",))
            self.active.clear()

        def write(self, frame):
            events.append(("write", frame[0]))
            if frame[0] != 0:
                self.active = bytearray(responses.popleft())
            return len(frame)

        def flush(self):
            events.append(("flush",))

        def read(self, size):
            result = bytes(self.active[:size])
            del self.active[:size]
            return result

    transport = object.__new__(SerialTransport)
    transport._serial = StubSerial()
    monkeypatch.setattr(
        slt5009_module.time,
        "sleep",
        lambda delay: events.append(("sleep", delay)),
    )

    start_broadcast_measurement(
        [Slt5009(slave=1, poll_interval=0), Slt5009(slave=2, poll_interval=0)],
        transport,
    )

    assert events[:8] == [
        ("reset",),
        ("write", 0),
        ("flush",),
        ("sleep", pytest.approx(0.010)),
        ("sleep", 0),
        ("reset",),
        ("write", 1),
        ("flush",),
    ]


def test_broadcast_short_write_fails_without_reading():
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]
    transport = FakeTransport(write_result=0)

    with pytest.raises(SensorTimeoutError, match="broadcast write"):
        start_broadcast_measurement(sensors, transport)

    assert transport.read_sizes == []


def test_broadcast_short_write_still_applies_silent_interval(monkeypatch):
    waits = []
    monkeypatch.setattr(slt5009_module.time, "sleep", waits.append)
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]

    with pytest.raises(SensorTimeoutError, match="broadcast write"):
        start_broadcast_measurement(sensors, FakeTransport(write_result=1))

    assert waits == [pytest.approx(0.010)]


def test_normal_short_write_still_applies_silent_interval(monkeypatch):
    waits = []
    monkeypatch.setattr(slt5009_module.time, "sleep", waits.append)

    with pytest.raises(SensorTimeoutError, match="request write"):
        Slt5009(slave=1).read_address(FakeTransport(write_result=1))

    assert waits == [pytest.approx(0.010)]


def test_broadcast_can_continue_waiting_after_one_sensor_fails():
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]
    transport = FakeTransport([b"", _read_resp(2, [1])])

    errors = start_broadcast_measurement(
        sensors, transport, continue_on_error=True
    )

    assert list(errors) == [1]
    assert isinstance(errors[1], SensorTimeoutError)
    assert transport.writes[1][0:2] == bytes([1, 0x03])
    assert transport.writes[2][0:2] == bytes([2, 0x03])


def test_broadcast_remains_fail_fast_by_default():
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]
    transport = FakeTransport([b"", _read_resp(2, [1])])

    with pytest.raises(SensorTimeoutError):
        start_broadcast_measurement(sensors, transport)

    assert len(transport.writes) == 2


def test_broadcast_requires_two_unique_slt5009_sensors():
    with pytest.raises(ValueError, match="at least two"):
        start_broadcast_measurement([Slt5009(slave=1)], FakeTransport())
    with pytest.raises(ValueError, match="unique"):
        start_broadcast_measurement(
            [Slt5009(slave=1), Slt5009(slave=1)], FakeTransport()
        )
    with pytest.raises(TypeError, match="only SLT5009"):
        start_broadcast_measurement(
            [Slt5009(slave=1), Slt5006()], FakeTransport()
        )


def test_constructor_rejects_negative_poll_interval():
    with pytest.raises(ValueError, match="poll interval"):
        Slt5009(poll_interval=-0.1)
