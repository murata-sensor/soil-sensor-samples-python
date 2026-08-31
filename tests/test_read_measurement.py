"""Firmware-gated output tests for the one-shot measurement CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import read_measurement  # noqa: E402

from murata_soil_sensor import (  # noqa: E402
    Measurement,
    SensorInfo,
    SensorTimeoutError,
    create_sensor,
)


class _Transport:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class _Sensor:
    product = "SLT5006"
    ec_pore_coco_min_version = "1.7.5"

    def __init__(self, firmware_version):
        self.firmware_version = firmware_version

    def open(self, _port):
        return _Transport()

    def read_info(self, _transport):
        return SensorInfo(self.product, self.firmware_version, 23126040)

    def read_measurement(self, _transport):
        return Measurement(vwc=20.0, ec_pore_coco=91.0)

    def supports_ec_pore_coco(self, firmware_version):
        return tuple(map(int, firmware_version.split("."))) >= (1, 7, 5)


class _Slt5007Sensor(_Sensor):
    product = "SLT5007"
    ec_pore_coco_min_version = "1.1.1"

    def supports_ec_pore_coco(self, firmware_version):
        return create_sensor(self.product).supports_ec_pore_coco(firmware_version)


class _Slt5008Sensor(_Sensor):
    product = "SLT5008"
    ec_pore_coco_min_version = "1.7.0"

    def __init__(self, firmware_version, address="0"):
        super().__init__(firmware_version)
        self.address = str(address)

    def supports_ec_pore_coco(self, firmware_version):
        return create_sensor(self.product).supports_ec_pore_coco(firmware_version)


class _BroadcastSensor:
    product = "SLT5009"
    ec_pore_coco_min_version = "1.2.1"

    def __init__(self, slave, serial_number, measurement, *, firmware_version="1.2.2"):
        self.slave = slave
        self.serial_number = serial_number
        self.measurement = measurement
        self.firmware_version = firmware_version
        self.transport = _Transport()
        self.opened_port = None
        self.individual_read_calls = 0

    def open(self, port):
        self.opened_port = port
        return self.transport

    def read_info(self, _transport):
        return SensorInfo(self.product, self.firmware_version, self.serial_number)

    def read_measurement(self, _transport):
        self.individual_read_calls += 1
        return self.measurement

    def supports_ec_pore_coco(self, firmware_version):
        return tuple(map(int, firmware_version.split("."))) >= (1, 2, 1)


@pytest.mark.parametrize(("firmware", "supported"), [("1.6.3", False), ("1.7.6", True)])
def test_cli_only_prints_ec_pore_coco_for_supported_firmware(
    monkeypatch, capsys, firmware, supported
):
    sensor = _Sensor(firmware)
    monkeypatch.setattr(read_measurement._cli, "build_sensors", lambda _args: [sensor])
    monkeypatch.setattr(
        read_measurement._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["read_measurement.py", "--product", "SLT5006", "--port", "COM13"],
    )

    assert read_measurement.main() == 0
    output = capsys.readouterr().out
    if supported:
        assert "ec_pore_coco: 91.0 dS/m" in output
        assert "not supported" not in output
    else:
        assert "ec_pore_coco: not supported on this firmware" in output
        assert "ec_pore_coco: 91.0 dS/m" not in output


@pytest.mark.parametrize(
    ("firmware", "supported"),
    [("1.0.1", False), ("1.1.2", True)],
)
def test_slt5007_cli_masks_ec_pore_coco_by_firmware(monkeypatch, capsys, firmware, supported):
    sensor = _Slt5007Sensor(firmware)
    monkeypatch.setattr(read_measurement._cli, "build_sensors", lambda _args: [sensor])
    monkeypatch.setattr(
        read_measurement._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "read_measurement.py",
            "--product",
            "SLT5007",
            "--port",
            "COM4",
            "--address",
            "1",
        ],
    )

    assert read_measurement.main() == 0
    output = capsys.readouterr().out
    if supported:
        assert "ec_pore_coco: 91.0 dS/m" in output
        assert "not supported" not in output
    else:
        assert "ec_pore_coco: not supported on this firmware" in output
        assert "ec_pore_coco: 91.0 dS/m" not in output


@pytest.mark.parametrize(("firmware", "supported"), [("1.4.0", False), ("1.7.0", True)])
def test_slt5008_cli_output_masking_substitute_does_not_qualify_fw_140_reads(
    monkeypatch, capsys, firmware, supported
):
    """Exercise formatting with a fake measurement, not FW1.4 D0/D1/D2 support."""
    sensor = _Slt5008Sensor(firmware)
    monkeypatch.setattr(read_measurement._cli, "build_sensors", lambda _args: [sensor])

    def use_concurrent(sensors, *, broadcast_start):
        assert sensors == [sensor]
        assert sensor.address == "0"
        assert isinstance(sensor.address, str)
        assert broadcast_start is False
        return False

    monkeypatch.setattr(read_measurement._cli, "use_concurrent", use_concurrent)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "read_measurement.py",
            "--product",
            "SLT5008",
            "--port",
            "COM4",
            "--address",
            "0",
        ],
    )

    assert read_measurement.main() == 0
    output = capsys.readouterr().out
    if supported:
        assert "ec_pore_coco: 91.0 dS/m" in output
        assert "not supported" not in output
    else:
        assert "ec_pore_coco: not supported on this firmware" in output
        assert "ec_pore_coco: 91.0 dS/m" not in output


@pytest.mark.parametrize(("firmware", "supported"), [("1.1.0", False), ("1.2.2", True)])
def test_slt5009_cli_masks_ec_pore_coco_by_firmware(monkeypatch, capsys, firmware, supported):
    sensor = _BroadcastSensor(
        1,
        24107928,
        Measurement(vwc=20.0, ec_pore_coco=91.0),
        firmware_version=firmware,
    )
    monkeypatch.setattr(read_measurement._cli, "build_sensors", lambda _args: [sensor])
    monkeypatch.setattr(
        read_measurement._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: False,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "read_measurement.py",
            "--product",
            "SLT5009",
            "--port",
            "COM4",
            "--address",
            "1",
        ],
    )

    assert read_measurement.main() == 0
    output = capsys.readouterr().out
    if supported:
        assert "ec_pore_coco: 91.0 dS/m" in output
        assert "not supported" not in output
    else:
        assert "ec_pore_coco: not supported on this firmware" in output
        assert "ec_pore_coco: 91.0 dS/m" not in output


def test_slt5009_broadcast_one_shot_prints_both_sensors(monkeypatch, capsys):
    sensors = [
        _BroadcastSensor(1, 24107928, Measurement(vwc=11.0, ec_pore_coco=1.1)),
        _BroadcastSensor(2, 23107013, Measurement(vwc=22.0, ec_pore_coco=2.2)),
    ]
    concurrent_call = {}

    def build(args):
        assert args.product == "SLT5009"
        assert args.address == "1,2"
        assert args.broadcast_start
        return sensors

    def use_concurrent(selected, *, broadcast_start):
        assert selected is sensors
        assert broadcast_start
        return True

    def read_concurrent(selected, transport):
        concurrent_call.update(sensors=selected, transport=transport)
        return [sensor.measurement for sensor in selected]

    monkeypatch.setattr(read_measurement._cli, "build_sensors", build)
    monkeypatch.setattr(read_measurement._cli, "use_concurrent", use_concurrent)
    monkeypatch.setattr(
        read_measurement._cli,
        "read_concurrent_measurement",
        read_concurrent,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "read_measurement.py",
            "--product",
            "SLT5009",
            "--port",
            "COM4",
            "--address",
            "1,2",
            "--broadcast-start",
        ],
    )

    assert read_measurement.main() == 0

    output = capsys.readouterr().out
    assert concurrent_call == {"sensors": sensors, "transport": sensors[0].transport}
    assert sensors[0].opened_port == "COM4"
    assert [sensor.individual_read_calls for sensor in sensors] == [0, 0]
    assert "=== address 1 ===" in output
    assert "serial: 24107928" in output
    assert "vwc: 11.0 %" in output
    assert "=== address 2 ===" in output
    assert "serial: 23107013" in output
    assert "vwc: 22.0 %" in output
    assert output.index("=== address 1 ===") < output.index("=== address 2 ===")


def test_slt5009_broadcast_one_shot_does_not_print_partial_results(monkeypatch, capsys):
    sensors = [
        _BroadcastSensor(1, 24107928, Measurement(vwc=11.0)),
        _BroadcastSensor(2, 23107013, Measurement(vwc=22.0)),
    ]

    monkeypatch.setattr(read_measurement._cli, "build_sensors", lambda _args: sensors)
    monkeypatch.setattr(
        read_measurement._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: broadcast_start,
    )

    read_attempts = []

    def fail_on_second_sensor(selected, _transport):
        measurements = []
        for sensor in selected:
            read_attempts.append(sensor.slave)
            if sensor.slave == 2:
                raise SensorTimeoutError("address 2 data response timed out")
            measurements.append(sensor.measurement)
        return measurements

    monkeypatch.setattr(
        read_measurement._cli,
        "read_concurrent_measurement",
        fail_on_second_sensor,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "read_measurement.py",
            "--product",
            "SLT5009",
            "--port",
            "COM4",
            "--address",
            "1,2",
            "--broadcast-start",
        ],
    )

    with pytest.raises(SensorTimeoutError, match="address 2 data response timed out"):
        read_measurement.main()

    assert read_attempts == [1, 2]
    assert capsys.readouterr().out == ""
