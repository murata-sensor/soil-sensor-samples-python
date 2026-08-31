"""Exit-status and fault-isolation tests for the information CLI."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import read_info  # noqa: E402

from murata_soil_sensor import SensorInfo, SensorTimeoutError  # noqa: E402


class _Transport:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class _Sensor:
    product = "SLT5009"

    def __init__(self, slave: int, result: SensorInfo | Exception):
        self.slave = slave
        self._result = result

    def open(self, _port):
        return _Transport()

    def read_info(self, _transport):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _run(monkeypatch, sensors) -> int:
    monkeypatch.setattr(read_info._cli, "build_sensors", lambda _args: sensors)
    monkeypatch.setattr(
        sys,
        "argv",
        ["read_info.py", "--product", "SLT5009", "--port", "COM4"],
    )
    return read_info.main()


def _info(serial: int) -> SensorInfo:
    return SensorInfo("SLT5009", "1.2.2", serial)


def test_read_info_returns_zero_when_all_sensors_succeed(monkeypatch, capsys):
    result = _run(
        monkeypatch,
        [_Sensor(1, _info(24107928)), _Sensor(2, _info(23107013))],
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "Address:  1" in captured.out
    assert "Serial:   24107928" in captured.out
    assert "Address:  2" in captured.out
    assert "Serial:   23107013" in captured.out
    assert captured.err == ""


def test_read_info_returns_one_when_the_only_sensor_fails(monkeypatch, capsys):
    result = _run(
        monkeypatch,
        [_Sensor(1, SensorTimeoutError("no response"))],
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "error: 1: no response" in captured.err


def test_read_info_reports_partial_failure_and_keeps_other_sensor(monkeypatch, capsys):
    result = _run(
        monkeypatch,
        [
            _Sensor(1, SensorTimeoutError("no response")),
            _Sensor(2, _info(23107013)),
        ],
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "Address:  2" in captured.out
    assert "Serial:   23107013" in captured.out
    assert "error: 1: no response" in captured.err
