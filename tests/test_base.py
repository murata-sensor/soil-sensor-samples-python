"""Transport timing and timeout-contract tests."""

from __future__ import annotations

import pytest

from murata_soil_sensor.base import SerialTransport


class _StubSerial:
    def __init__(
        self,
        *,
        timeout=10.0,
        response=b"ok\r\n",
        fail_read=False,
        write_result=None,
    ):
        self.timeout = timeout
        self.response = response
        self.fail_read = fail_read
        self.write_result = write_result
        self.calls = []

    def write(self, data):
        self.calls.append(("write", bytes(data)))
        return len(data) if self.write_result is None else self.write_result

    def flush(self):
        self.calls.append(("flush", None))

    def read_until(self, expected):
        self.calls.append(("read_until", bytes(expected), self.timeout))
        if self.fail_read:
            raise RuntimeError("read failed")
        return self.response


def _transport(serial):
    transport = object.__new__(SerialTransport)
    transport._serial = serial
    return transport


def test_serial_transport_write_drains_output_before_returning():
    serial = _StubSerial()

    assert _transport(serial).write(b"abc") == 3
    assert serial.calls == [("write", b"abc"), ("flush", None)]


def test_serial_transport_drains_output_even_after_partial_write():
    serial = _StubSerial(write_result=1)

    assert _transport(serial).write(b"abc") == 1
    assert serial.calls == [("write", b"abc"), ("flush", None)]


@pytest.mark.parametrize(
    ("configured", "requested", "effective"),
    [(10.0, 5.0, 5.0), (2.0, 5.0, 2.0), (None, 5.0, 5.0)],
)
def test_read_until_uses_bounded_timeout_and_restores_configuration(
    configured, requested, effective
):
    serial = _StubSerial(timeout=configured)

    assert _transport(serial).read_until(b"\r\n", timeout=requested) == b"ok\r\n"
    assert serial.calls == [("read_until", b"\r\n", effective)]
    assert serial.timeout == configured


def test_read_until_restores_timeout_after_error():
    serial = _StubSerial(timeout=10.0, fail_read=True)

    with pytest.raises(RuntimeError, match="read failed"):
        _transport(serial).read_until(b"\r\n", timeout=1.0)

    assert serial.timeout == 10.0


def test_read_until_rejects_negative_per_call_timeout():
    with pytest.raises(ValueError, match="negative"):
        _transport(_StubSerial()).read_until(b"\r\n", timeout=-0.1)
