"""End-to-end tests for address-change and retention CLI workflows."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import set_address  # noqa: E402
import verify_address  # noqa: E402

from murata_soil_sensor import ProtocolError, SensorTimeoutError  # noqa: E402


class _Port:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class _Sensor:
    def __init__(
        self,
        product,
        address,
        *,
        serial=123,
        probe_error=None,
        set_error=None,
    ):
        self.product = product
        self._address_attr = {
            "SLT5007": "sensor_number",
            "SLT5008": "address",
            "SLT5009": "slave",
        }[product]
        setattr(self, self._address_attr, address)
        self.serial = serial
        self.probe_error = probe_error
        self.set_error = set_error
        self.set_calls = []
        self.port = _Port()

    def open(self, _port):
        return self.port

    def read_address(self, _transport):
        if self.probe_error is not None:
            raise self.probe_error
        return getattr(self, self._address_attr)

    def read_info(self, _transport):
        if self.probe_error is not None:
            raise self.probe_error
        return SimpleNamespace(serial_number=self.serial)

    def set_address(self, _transport, value):
        self.set_calls.append(str(value))
        converted = str(value) if self.product == "SLT5008" else int(value)
        setattr(self, self._address_attr, converted)
        if self.set_error is not None:
            raise self.set_error

    @property
    def address_write_count(self):
        return len(self.set_calls)


def _address(product, value):
    return str(value) if product == "SLT5008" else int(value)


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_probe_treats_only_timeout_as_unused(product):
    sensor = _Sensor(product, "2" if product == "SLT5008" else 2, probe_error=SensorTimeoutError())
    set_address._require_unused(sensor, object())


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_probe_rejects_an_occupied_address(product):
    sensor = _Sensor(product, "2" if product == "SLT5008" else 2, serial=999)
    with pytest.raises(ProtocolError, match="already in use"):
        set_address._require_unused(sensor, object())


@pytest.mark.parametrize("product", ["SLT5007", "SLT5009"])
def test_probe_rejects_invalid_response_instead_of_treating_it_as_unused(product):
    sensor = _Sensor(product, 2, probe_error=ProtocolError("bad CRC"))
    with pytest.raises(ProtocolError, match="cannot confirm"):
        set_address._require_unused(sensor, object())


def test_slt5008_occupancy_probe_uses_identification_not_read_address():
    sensor = _Sensor("SLT5008", "2")
    calls = []

    def read_info(_transport):
        calls.append("read_info")
        raise SensorTimeoutError()

    def read_address(_transport):
        raise AssertionError("SLT5008 occupancy must not use read_address")

    sensor.read_info = read_info
    sensor.read_address = read_address

    set_address._require_unused(sensor, object())

    assert calls == ["read_info"]


def test_set_address_main_probes_then_changes_and_prints_safe_command(monkeypatch, capsys):
    current = _Sensor("SLT5009", 1)
    candidate = _Sensor("SLT5009", 2, probe_error=SensorTimeoutError())
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == "1" else candidate,
    )

    result = set_address.main(
        [
            "--product",
            "SLT5009",
            "--port",
            "COM3",
            "--address",
            "1",
            "--new-address",
            "2",
            "--baud",
            "9600",
            "--timeout",
            "0.5",
        ]
    )

    assert result == 0
    assert current.set_calls == ["2"]
    output = capsys.readouterr().out
    assert "without disconnecting energized wiring" in output
    assert "--baud 9600 --timeout 0.5" in output


@pytest.mark.parametrize(
    ("product", "old", "new"),
    [("SLT5007", 0, 1), ("SLT5008", "0", "1")],
)
def test_set_address_main_changes_other_addressable_products(product, old, new, monkeypatch):
    current = _Sensor(product, old)
    candidate = _Sensor(product, new, probe_error=SensorTimeoutError())
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == str(old) else candidate,
    )

    result = set_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            str(old),
            "--new-address",
            str(new),
        ]
    )

    assert result == 0
    assert current.set_calls == [str(new)]


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_set_address_main_refuses_occupied_address_before_write(monkeypatch, capsys, product):
    current = _Sensor(product, _address(product, 1))
    occupied = _Sensor(product, _address(product, 2), serial=999)
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == "1" else occupied,
    )

    result = set_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "1",
            "--new-address",
            "2",
        ]
    )

    assert result == 1
    assert current.set_calls == []
    assert current.address_write_count == 0
    assert "already in use" in capsys.readouterr().err


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_set_address_warns_that_post_write_failure_may_have_changed_address(
    monkeypatch, capsys, product
):
    current = _Sensor(
        product,
        _address(product, 1),
        set_error=SensorTimeoutError("write acknowledgement was lost"),
    )
    candidate = _Sensor(
        product, _address(product, 2), probe_error=SensorTimeoutError()
    )
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == "1" else candidate,
    )

    result = set_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "1",
            "--new-address",
            "2",
        ]
    )

    error = capsys.readouterr().err
    assert result == 1
    assert current.set_calls == ["2"]
    assert current.address_write_count == 1
    assert "may now use either 1 or 2" in error
    assert "Do not repeat the write yet" in error
    assert "Probe both addresses with all bus devices powered" in error


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_set_address_rejects_post_write_serial_mismatch(monkeypatch, capsys, product):
    current = _Sensor(product, _address(product, 1), serial=24107928)
    candidate = _Sensor(
        product, _address(product, 2), probe_error=SensorTimeoutError()
    )
    identities = iter(
        [
            SimpleNamespace(serial_number=24107928),
            SimpleNamespace(serial_number=23107013),
        ]
    )
    current.read_info = lambda _transport: next(identities)
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == "1" else candidate,
    )

    result = set_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "1",
            "--new-address",
            "2",
        ]
    )

    error = capsys.readouterr().err
    assert result == 1
    assert current.set_calls == ["2"]
    assert current.address_write_count == 1
    assert "serial number changed after address update" in error
    assert "Do not repeat the write yet" in error


@pytest.mark.parametrize(
    ("product", "new_address"),
    [("SLT5007", "01"), ("SLT5008", "1"), ("SLT5009", "01")],
)
def test_set_address_main_treats_same_normalized_address_as_noop(
    monkeypatch, capsys, product, new_address
):
    current = _Sensor(product, _address(product, 1))
    candidate = _Sensor(
        product,
        _address(product, 1),
        probe_error=AssertionError("must not probe"),
    )
    monkeypatch.setattr(
        set_address._cli,
        "build_sensor",
        lambda args: current if str(args.address) == "1" else candidate,
    )

    result = set_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "1",
            "--new-address",
            new_address,
        ]
    )

    assert result == 0
    assert current.set_calls == []
    assert current.address_write_count == 0
    assert "no nonvolatile write" in capsys.readouterr().out


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_verify_address_main_checks_address_and_serial(monkeypatch, capsys, product):
    sensor = _Sensor(product, _address(product, 2), serial=123)
    monkeypatch.setattr(verify_address._cli, "build_sensor", lambda _args: sensor)

    result = verify_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "2",
            "--expected-serial",
            "123",
        ]
    )

    assert result == 0
    assert "retained after power was restored" in capsys.readouterr().out


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_verify_address_main_rejects_serial_mismatch(monkeypatch, capsys, product):
    sensor = _Sensor(product, _address(product, 2), serial=999)
    monkeypatch.setattr(verify_address._cli, "build_sensor", lambda _args: sensor)

    result = verify_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "2",
            "--expected-serial",
            "123",
        ]
    )

    assert result == 1
    assert "serial is 999" in capsys.readouterr().err


@pytest.mark.parametrize("product", ["SLT5007", "SLT5008", "SLT5009"])
def test_verify_address_main_rejects_address_mismatch(monkeypatch, capsys, product):
    sensor = _Sensor(product, _address(product, 3), serial=123)
    monkeypatch.setattr(verify_address._cli, "build_sensor", lambda _args: sensor)

    result = verify_address.main(
        [
            "--product",
            product,
            "--port",
            "COM3",
            "--address",
            "2",
            "--expected-serial",
            "123",
        ]
    )

    assert result == 1
    assert "reports address 3; expected 2" in capsys.readouterr().err
