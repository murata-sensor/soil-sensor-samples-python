"""Regression tests for per-sensor fault isolation in continuous logging."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import continuous_log  # noqa: E402

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
    def __init__(
        self,
        address: int | str,
        *,
        product: str = "SLT5009",
        measurement: Measurement | None = None,
        read_results: list[Measurement | Exception] | None = None,
        firmware_version: str = "1.2.3",
    ):
        self.product = product
        self._address = str(address) if product == "SLT5008" else int(address)
        if product == "SLT5007":
            self.sensor_number = int(address)
        elif product == "SLT5008":
            self.address = str(address)
        elif product == "SLT5009":
            self.slave = int(address)
        else:
            raise ValueError(f"unsupported test product: {product}")
        self.measurement = measurement
        self.read_results = list(read_results) if read_results is not None else None
        self.firmware_version = firmware_version
        self.read_data_calls = 0
        self.transport = _Transport()

    def open(self, _port):
        return self.transport

    def read_info(self, _transport):
        return SensorInfo(
            product=self.product,
            firmware_version=self.firmware_version,
            serial_number=100 + int(self._address),
        )

    def supports_ec_pore_coco(self, firmware_version: str) -> bool:
        return create_sensor(self.product).supports_ec_pore_coco(firmware_version)

    def read_data(self, _transport):
        self.read_data_calls += 1
        if self.read_results is not None:
            if not self.read_results:
                raise AssertionError("sensor received more reads than configured")
            result = self.read_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        if self.measurement is None:
            raise AssertionError("failed sensor must not be read")
        return self.measurement

    def read_measurement(self, transport):
        return self.read_data(transport)


def test_logger_keeps_other_sensor_when_broadcast_poll_fails(monkeypatch, capsys):
    failed = _Sensor(1)
    responsive = _Sensor(2, measurement=Measurement(vwc=42.0))
    sensors = [failed, responsive]
    timeout = SensorTimeoutError("measurement did not complete")

    monkeypatch.setattr(continuous_log._cli, "build_sensors", lambda _args: sensors)
    monkeypatch.setattr(
        continuous_log._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: broadcast_start,
    )

    def start(_sensors, _transport, *, continue_on_error):
        assert continue_on_error
        return {"1": timeout}

    monkeypatch.setattr(continuous_log._cli, "start_concurrent_measurement", start)
    monkeypatch.setattr(
        continuous_log._uploader.Uploader,
        "from_args",
        classmethod(lambda _cls, _args: None),
    )

    result = continuous_log.main(
        [
            "--product",
            "SLT5009",
            "--port",
            "COM3",
            "--address",
            "1,2",
            "--broadcast-start",
            "--count",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert failed.read_data_calls == 0
    assert responsive.read_data_calls == 1
    assert "error: 1: measurement did not complete" in captured.err
    assert ",2,1.2.3,102," in captured.out


def test_logger_drops_failed_samples_and_records_recovery_across_cycles(
    monkeypatch, capsys, tmp_path
):
    healthy = _Sensor(
        1,
        read_results=[
            Measurement(vwc=11.0),
            Measurement(vwc=12.0),
            Measurement(vwc=13.0),
            Measurement(vwc=14.0),
        ],
    )
    flaky = _Sensor(
        2,
        read_results=[
            Measurement(vwc=21.0),
            SensorTimeoutError("data response timed out"),
            Measurement(vwc=24.0),
        ],
    )
    sensors = [healthy, flaky]
    poll_timeout = SensorTimeoutError("measurement poll timed out")
    start_results = iter([{}, {"2": poll_timeout}, {}, {}])
    start_calls = 0

    monkeypatch.setattr(continuous_log._cli, "build_sensors", lambda _args: sensors)
    monkeypatch.setattr(
        continuous_log._cli,
        "use_concurrent",
        lambda _sensors, *, broadcast_start: broadcast_start,
    )

    def start(_sensors, _transport, *, continue_on_error):
        nonlocal start_calls
        start_calls += 1
        assert continue_on_error
        return next(start_results)

    monkeypatch.setattr(continuous_log._cli, "start_concurrent_measurement", start)
    monkeypatch.setattr(
        continuous_log._uploader.Uploader,
        "from_args",
        classmethod(lambda _cls, _args: None),
    )
    monkeypatch.setattr(continuous_log.time, "sleep", lambda _delay: None)

    output = tmp_path / "recovery.csv"
    result = continuous_log.main(
        [
            "--product",
            "SLT5009",
            "--port",
            "COM4",
            "--address",
            "1,2",
            "--broadcast-start",
            "--interval",
            "0",
            "--count",
            "4",
            "--out",
            str(output),
        ]
    )

    assert result == 0
    assert start_calls == 4
    assert healthy.read_data_calls == 4
    assert flaky.read_data_calls == 3

    with output.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    values_by_address = {
        address: [row["vwc"] for row in rows if row["address"] == address] for address in ("1", "2")
    }
    assert values_by_address == {
        "1": ["11.0", "12.0", "13.0", "14.0"],
        "2": ["21.0", "24.0"],
    }
    assert len(rows) == 6

    captured = capsys.readouterr()
    assert "error: 2: measurement poll timed out" in captured.err
    assert "error: 2: data response timed out" in captured.err


@pytest.mark.parametrize(
    (
        "product",
        "old_firmware",
        "current_firmware",
        "broadcast_option",
        "simultaneous",
    ),
    [
        pytest.param("SLT5007", "1.0.1", "1.1.2", False, False, id="slt5007"),
        pytest.param("SLT5008", "1.4.0", "1.7.0", False, True, id="slt5008"),
        pytest.param("SLT5009", "1.1.0", "1.2.2", True, True, id="slt5009"),
    ],
)
def test_logger_masks_ec_pore_coco_per_sensor_in_csv_and_upload(
    monkeypatch,
    tmp_path,
    product,
    old_firmware,
    current_firmware,
    broadcast_option,
    simultaneous,
):
    """Check output masking only; fake SLT5008 FW1.4 data is not read/HIL qualification."""
    old_address, current_address = ("0", "1") if product == "SLT5008" else (1, 2)
    old = _Sensor(
        old_address,
        product=product,
        firmware_version=old_firmware,
        measurement=Measurement(vwc=10.0, ec_pore_coco=91.0),
    )
    current = _Sensor(
        current_address,
        product=product,
        firmware_version=current_firmware,
        measurement=Measurement(vwc=20.0, ec_pore_coco=2.2),
    )
    sensors = [old, current]

    monkeypatch.setattr(continuous_log._cli, "build_sensors", lambda _args: sensors)

    def use_concurrent(selected, *, broadcast_start):
        assert selected is sensors
        assert broadcast_start is broadcast_option
        if product == "SLT5008":
            assert [sensor.address for sensor in selected] == ["0", "1"]
            assert all(isinstance(sensor.address, str) for sensor in selected)
        return simultaneous

    monkeypatch.setattr(continuous_log._cli, "use_concurrent", use_concurrent)
    concurrent_starts = []

    def start_concurrent(selected, _transport, *, continue_on_error):
        assert selected is sensors
        assert continue_on_error is broadcast_option
        concurrent_starts.append(selected)
        return {}

    monkeypatch.setattr(
        continuous_log._cli,
        "start_concurrent_measurement",
        start_concurrent,
    )

    class CaptureUploader:
        rows = None

        def send(self, rows):
            self.rows = rows
            return True

    uploader = CaptureUploader()
    monkeypatch.setattr(
        continuous_log._uploader.Uploader,
        "from_args",
        classmethod(lambda _cls, _args: uploader),
    )

    output = tmp_path / "mixed-firmware.csv"
    argv = [
        "--product",
        product,
        "--port",
        "COM3",
        "--address",
        f"{old_address},{current_address}",
        "--count",
        "1",
        "--out",
        str(output),
    ]
    if broadcast_option:
        argv.append("--broadcast-start")
    result = continuous_log.main(argv)

    assert result == 0
    assert len(concurrent_starts) == (1 if simultaneous else 0)
    with output.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["firmware"] == old_firmware
    assert rows[0]["ec_pore_coco"] == ""
    assert rows[1]["firmware"] == current_firmware
    assert rows[1]["ec_pore_coco"] == "2.2"
    assert "ec_pore_coco_dsm" not in uploader.rows[0]
    assert uploader.rows[1]["ec_pore_coco_dsm"] == 2.2


def test_output_mask_fails_closed_without_identification():
    sensor = _Sensor(1, measurement=Measurement(ec_pore_coco=91.0))
    raw = sensor.measurement

    filtered = continuous_log._cli.measurement_for_output(sensor, None, raw)

    assert filtered.ec_pore_coco is None
    assert raw.ec_pore_coco == 91.0
