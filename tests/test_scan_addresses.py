"""End-to-end tests for the address-scanning CLI."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import scan_addresses  # noqa: E402

from murata_soil_sensor import ProtocolError, SensorTimeoutError  # noqa: E402

from ._fake_transport import FakeTransport


class _Port:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class _ScanSensor:
    def __init__(self, outcomes):
        self.slave = 1
        self.outcomes = outcomes
        self.probes = []

    def open(self, port):
        assert port == "COM4"
        return _Port()

    def read_info(self, _transport):
        self.probes.append(self.slave)
        outcome = self.outcomes.get(
            self.slave,
            SensorTimeoutError(f"no response from address {self.slave}"),
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _info(serial):
    return SimpleNamespace(
        product="SLT5009",
        firmware_version="1.2.2",
        serial_number=serial,
    )


def _sdi12_info(serial):
    return SimpleNamespace(
        product="SLT5008",
        firmware_version="1.7.0",
        serial_number=serial,
    )


class _Sdi12ScanSensor:
    def __init__(self, query_outcome, probe_outcomes=None):
        self.address = "0"
        self.query_outcome = query_outcome
        self.probe_outcomes = probe_outcomes or {}
        self.probes = []

    def open(self, port):
        assert port == "COM4"
        return _Port()

    def query_address(self, _transport):
        if isinstance(self.query_outcome, Exception):
            raise self.query_outcome
        return self.query_outcome

    def _transaction(self, _transport, command, *, allow_empty=False):
        assert allow_empty is True
        candidate = command[0]
        self.probes.append((command, allow_empty))
        outcome = self.probe_outcomes.get(candidate, "")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def read_info(self, _transport):
        return _sdi12_info(22118001 + int(self.address))


def _run_sdi12_scan(monkeypatch, sensor):
    def make_sensor(*, timeout, **kwargs):
        assert timeout == 1.0
        assert kwargs == {}
        return sensor

    monkeypatch.setattr(scan_addresses, "Slt5008", make_sensor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan_addresses.py",
            "--product",
            "SLT5008",
            "--port",
            "COM4",
            "--timeout",
            "0.15",
        ],
    )
    return scan_addresses.main()


def _run_scan(monkeypatch, sensor):
    def create_sensor(product, *, timeout):
        assert product == "SLT5009"
        assert timeout == 0.15
        return sensor

    monkeypatch.setattr(scan_addresses, "create_sensor", create_sensor)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scan_addresses.py",
            "--product",
            "SLT5009",
            "--port",
            "COM4",
            "--timeout",
            "0.15",
        ],
    )
    return scan_addresses.main()


@pytest.mark.parametrize(
    "query_outcome",
    [
        None,
        None,
        ProtocolError("non-ASCII SDI-12 response"),
        SensorTimeoutError("incomplete SDI-12 response"),
        SensorTimeoutError("incomplete SDI-12 response (missing CR/LF)"),
    ],
    ids=["empty", "collision", "non-ascii", "partial", "missing-crlf"],
)
def test_slt5008_unusable_address_query_falls_back_to_all_numeric_probes(
    monkeypatch, capsys, query_outcome
):
    sensor = _Sdi12ScanSensor(query_outcome, {"3": "3"})

    result = _run_sdi12_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "3: SLT5008  firmware: 1.7.0  serial: 22118004\n"
    assert "probing each address with a! instead" in captured.err
    assert sensor.probes == [(f"{address}!", True) for address in "0123456789"]


def test_slt5008_valid_query_is_only_a_hint_and_full_probe_finds_second_dut(monkeypatch, capsys):
    sensor = _Sdi12ScanSensor("2", {"2": "2", "3": "3"})

    result = _run_sdi12_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == (
        "2: SLT5008  firmware: 1.7.0  serial: 22118003\n"
        "3: SLT5008  firmware: 1.7.0  serial: 22118004\n"
    )
    assert "?! reported 2" in captured.err
    assert "cannot prove that only one sensor is connected" in captured.err
    assert sensor.probes == [(f"{address}!", True) for address in "0123456789"]


def test_slt5008_probe_treats_only_empty_response_as_unused_and_reports_invalid(
    monkeypatch, capsys
):
    sensor = _Sdi12ScanSensor(
        None,
        {
            "1": "1",
            "2": "9",
            "3": ProtocolError("non-ASCII SDI-12 response"),
            "4": SensorTimeoutError("incomplete SDI-12 response (missing CR/LF)"),
        },
    )

    result = _run_sdi12_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == "1: SLT5008  firmware: 1.7.0  serial: 22118002\n"
    assert "0: protocol/device response error" not in captured.err
    assert "2: protocol/device response error: unexpected acknowledge-active" in captured.err
    assert "3: protocol/device response error: non-ASCII SDI-12 response" in captured.err
    assert "4: protocol/device response error: incomplete SDI-12 response" in captured.err
    assert "1 sensor(s) found: 1" in captured.err


@pytest.mark.parametrize("raw", [b"", b"No Response\r\n"])
def test_slt5008_probe_accepts_only_documented_no_response_outcomes(raw):
    assert (
        scan_addresses._probe_sdi12_address(
            scan_addresses.Slt5008(address="0"), FakeTransport([raw]), "0"
        )
        is False
    )


@pytest.mark.parametrize("raw", [b"\r\n", b"\x00\r\n", b"\x00\x00\r\n"])
def test_slt5008_probe_rejects_nonempty_frames_without_an_address(raw):
    with pytest.raises(ProtocolError, match="empty framed"):
        scan_addresses._probe_sdi12_address(
            scan_addresses.Slt5008(address="0"), FakeTransport([raw]), "0"
        )


@pytest.mark.parametrize(
    "raw",
    [
        b"No response\r\n",
        b"No Response \r\n",
        b"\x00No Response\x00\r\n",
        b"1\r\n",
    ],
)
def test_slt5008_probe_rejects_near_sentinel_and_wrong_address(raw):
    with pytest.raises(ProtocolError, match="unexpected acknowledge-active"):
        scan_addresses._probe_sdi12_address(
            scan_addresses.Slt5008(address="0"), FakeTransport([raw]), "0"
        )


def test_slt5008_probe_rejects_partial_sentinel_without_crlf():
    with pytest.raises(SensorTimeoutError, match="missing CR/LF"):
        scan_addresses._probe_sdi12_address(
            scan_addresses.Slt5008(address="0"),
            FakeTransport([b"No Response"]),
            "0",
        )


def test_scan_cli_reports_one_responder(monkeypatch, capsys):
    sensor = _ScanSensor({7: _info(24107928)})

    result = _run_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "7: SLT5009  firmware: 1.2.2  serial: 24107928\n"
    assert "1 sensor(s) found: 7" in captured.err
    assert sensor.probes == list(range(1, 32))


def test_scan_cli_keeps_two_responders_and_their_identity(monkeypatch, capsys):
    sensor = _ScanSensor(
        {
            1: _info(24107928),
            2: _info(23107013),
        }
    )

    result = _run_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.splitlines() == [
        "1: SLT5009  firmware: 1.2.2  serial: 24107928",
        "2: SLT5009  firmware: 1.2.2  serial: 23107013",
    ]
    assert "2 sensor(s) found: 1,2" in captured.err


def test_scan_cli_continues_after_unused_address_timeout(monkeypatch, capsys):
    sensor = _ScanSensor(
        {
            1: SensorTimeoutError("unused"),
            2: _info(24107928),
        }
    )

    result = _run_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith("2: SLT5009")
    assert "unused" not in captured.err
    assert sensor.probes[:3] == [1, 2, 3]


def test_scan_cli_reports_protocol_error_and_continues(monkeypatch, capsys):
    sensor = _ScanSensor(
        {
            1: ProtocolError("bad CRC"),
            2: _info(24107928),
        }
    )

    result = _run_scan(monkeypatch, sensor)

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out.startswith("2: SLT5009")
    assert "1: protocol/device response error: bad CRC" in captured.err
    assert "1 sensor(s) found: 2" in captured.err
    assert sensor.probes[:3] == [1, 2, 3]
