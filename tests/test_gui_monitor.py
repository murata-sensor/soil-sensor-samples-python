"""GUI connection-option propagation without opening a display."""

from __future__ import annotations

import csv
import io
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("tkinter")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import gui_monitor  # noqa: E402

from murata_soil_sensor import Measurement, SensorInfo, create_sensor  # noqa: E402


class _Value:
    def __init__(self, value=""):
        self.value = value
        self.history = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        self.history.append(value)


class _Button:
    def __init__(self):
        self.options = {}

    def config(self, **options):
        self.options.update(options)


class _Canvas:
    def draw_idle(self):
        return None


class _Line:
    def __init__(self):
        self.data = None

    def set_data(self, xs, ys):
        self.data = (list(xs), list(ys))


class _Axes:
    def relim(self):
        return None

    def autoscale_view(self):
        return None


class _Sensor:
    def __init__(self, product="SLT5009", address=None):
        self.product = product
        if product == "SLT5008":
            self.address = str("0" if address is None else address)

    def supports_ec_pore_coco(self, firmware_version):
        return create_sensor(self.product).supports_ec_pore_coco(firmware_version)


class _BroadcastSensor(_Sensor):
    product = "SLT5009"

    def __init__(self, slave, responses):
        super().__init__(self.product)
        self.slave = slave
        self._responses = iter(responses)
        self.read_data_calls = 0

    def read_data(self, _transport):
        self.read_data_calls += 1
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _broadcast_failure_recovery_events(monkeypatch):
    sensor_1 = _BroadcastSensor(
        1,
        [
            Measurement(vwc=10.0),
            TimeoutError("read timeout"),
            Measurement(vwc=30.0),
        ],
    )
    sensor_2 = _BroadcastSensor(
        2,
        [Measurement(vwc=value) for value in (20.0, 21.0, 22.0, 23.0)],
    )
    sensors = [sensor_1, sensor_2]
    start_results = iter(
        [
            {},
            {"1": TimeoutError("start timeout")},
            {},
            {},
        ]
    )
    transport = object()
    tolerant_calls = []

    def start(selected, received_transport, *, continue_on_error):
        assert selected == sensors
        assert received_transport is transport
        tolerant_calls.append(continue_on_error)
        return next(start_results)

    monkeypatch.setattr(gui_monitor._cli, "start_concurrent_measurement", start)
    out_queue = queue.Queue()
    worker = gui_monitor._Worker(
        sensors,
        "COM3",
        1.0,
        out_queue,
        threading.Event(),
        broadcast_start=True,
    )

    for _ in range(4):
        worker._measure_concurrent(transport)

    events = []
    while not out_queue.empty():
        events.append(out_queue.get_nowait())
    assert tolerant_calls == [True, True, True, True]
    return sensors, events


@pytest.mark.parametrize(
    ("product", "address", "baud", "timeout", "sdi_crc", "broadcast_start"),
    [
        ("SLT5007", "1,2", "", "0.5", False, False),
        ("SLT5008", "0", "9600", "0.25", True, False),
        ("SLT5009", "1,2", "", "0.5", False, True),
    ],
)
def test_gui_passes_connection_and_measurement_options_to_sensor_and_worker(
    monkeypatch,
    product,
    address,
    baud,
    timeout,
    sdi_crc,
    broadcast_start,
):
    captured = {}
    sensors = [object(), object()] if "," in address else [object()]

    def build_sensors(args):
        captured["args"] = args
        return sensors

    class Worker:
        def __init__(
            self,
            selected,
            port,
            interval,
            out_queue,
            stop_event,
            *,
            broadcast_start=False,
        ):
            captured.update(
                selected=selected,
                port=port,
                interval=interval,
                out_queue=out_queue,
                stop_event=stop_event,
                worker_broadcast=broadcast_start,
            )
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(gui_monitor._cli, "build_sensors", build_sensors)
    monkeypatch.setattr(gui_monitor, "_Worker", Worker)

    app = object.__new__(gui_monitor.MonitorApp)
    app.product_var = _Value(product)
    app.port_var = _Value("COM3")
    app.address_var = _Value(address)
    app.interval_var = _Value("5")
    app.baud_var = _Value(baud)
    app.timeout_var = _Value(timeout)
    app.sdi_crc_var = _Value(sdi_crc)
    app.broadcast_start_var = _Value(broadcast_start)
    app.status_var = _Value()
    app.info_var = _Value()
    app.start_btn = _Button()
    app.stop_btn = _Button()
    app._queue = object()
    app._series = {}
    app._canvas = _Canvas()
    app._ec_pore_coco_ok = {}
    app._info_lines = {}
    app._infos = {}
    app._open_csv = lambda: None
    app._reset_axes = lambda: None

    app._on_start()

    args = captured["args"]
    assert args.product == product
    assert args.port == "COM3"
    assert args.address == address
    assert args.baud == (int(baud) if baud else None)
    assert args.timeout == float(timeout)
    assert args.sdi_crc is sdi_crc
    assert args.broadcast_start is broadcast_start
    assert captured["selected"] == sensors
    assert captured["worker_broadcast"] is broadcast_start
    assert app._worker.started


def test_gui_exclusive_csv_mode_refuses_to_overwrite_existing_evidence(tmp_path):
    path = tmp_path / "measurement.csv"
    path.write_text("original\n", encoding="utf-8")
    app = object.__new__(gui_monitor.MonitorApp)
    app.csv_var = _Value(str(path))
    app._multi = True
    app._csv_file = None
    app._csv_writer = None
    app._csv_open_mode = "x"

    with pytest.raises(FileExistsError):
        app._open_csv()

    assert path.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize(
    ("product", "old_firmware", "current_firmware"),
    [
        pytest.param("SLT5007", "1.0.1", "1.1.2", id="slt5007"),
        pytest.param("SLT5008", "1.4.0", "1.7.0", id="slt5008"),
        pytest.param("SLT5009", "1.1.0", "1.2.2", id="slt5009"),
    ],
)
def test_gui_masks_ec_pore_coco_per_sensor_in_csv_and_plot(
    product, old_firmware, current_firmware
):
    app = object.__new__(gui_monitor.MonitorApp)
    app._multi = True
    app._ec_pore_coco_ok = {}
    app._info_lines = {}
    app._infos = {}
    app._start_time = datetime(2026, 8, 7, 12, 0, 0)
    app.info_var = _Value()
    app.status_var = _Value()
    app.parameter_var = _Value("ec_pore_coco")
    app._csv_file = io.StringIO()
    app._csv_writer = csv.writer(app._csv_file)
    app._ax = _Axes()
    app._canvas = _Canvas()

    plotted = []

    def line_for(label):
        plotted.append(label)
        return {"xs": [], "ys": [], "line": _Line()}

    app._line_for = line_for
    old_label, current_label = ("0", "1") if product == "SLT5008" else ("1", "2")
    old_sensor = _Sensor(product, old_label)
    current_sensor = _Sensor(product, current_label)
    if product == "SLT5008":
        assert old_sensor.address == "0"
        assert current_sensor.address == "1"
        assert isinstance(old_sensor.address, str)
        assert isinstance(current_sensor.address, str)
    old_info = SensorInfo(product, old_firmware, 101)
    current_info = SensorInfo(product, current_firmware, 102)
    app._handle_info(old_label, old_sensor, old_info)
    app._handle_info(current_label, current_sensor, current_info)
    timestamp = datetime(2026, 8, 7, 12, 0, 1)

    app._handle_measurement(
        old_label, old_sensor, timestamp, Measurement(ec_pore_coco=91.0)
    )
    assert plotted == []
    assert app.status_var.get() == (f"{old_label}: ec_pore_coco not supported on this firmware")
    assert f"{old_label}: firmware: {old_firmware}" in app.info_var.get()
    assert "(ec_pore_coco not supported)" in app.info_var.get()

    app._handle_measurement(
        current_label, current_sensor, timestamp, Measurement(ec_pore_coco=2.2)
    )
    assert plotted == [current_label]
    assert app.status_var.get() == f"{current_label}: ec_pore_coco: 2.2 dS/m"

    app._csv_file.seek(0)
    rows = list(csv.reader(app._csv_file))
    ec_index = 4 + Measurement.field_names().index("ec_pore_coco")
    assert rows[0][1:4] == [old_label, old_firmware, "101"]
    assert rows[0][ec_index] == ""
    assert rows[1][1:4] == [current_label, current_firmware, "102"]
    assert rows[1][ec_index] == "2.2"


@pytest.mark.parametrize("product", ["SLT5007", "SLT5009"])
def test_gui_masks_ec_pore_coco_when_identification_is_missing(product):
    app = object.__new__(gui_monitor.MonitorApp)
    app._multi = False
    app._ec_pore_coco_ok = {}
    app._infos = {}
    app._start_time = None
    app.status_var = _Value()
    app.parameter_var = _Value("ec_pore_coco")
    app._csv_file = io.StringIO()
    app._csv_writer = csv.writer(app._csv_file)

    app._handle_measurement(
        product,
        _Sensor(product),
        datetime(2026, 8, 7, 12, 0, 1),
        Measurement(ec_pore_coco=91.0),
    )

    app._csv_file.seek(0)
    row = next(csv.reader(app._csv_file))
    ec_index = 3 + Measurement.field_names().index("ec_pore_coco")
    assert row[ec_index] == ""
    assert app.status_var.get() == "ec_pore_coco not supported on this firmware"


def test_worker_broadcast_failure_keeps_healthy_sensor_and_recovers(monkeypatch):
    sensors, events = _broadcast_failure_recovery_events(monkeypatch)

    assert all(
        event[3].tzinfo is not None and event[3].utcoffset() is not None
        for event in events
        if event[0] == "data"
    )

    normalized = []
    for event in events:
        if event[0] == "data":
            normalized.append(("data", event[1], event[4].vwc))
        else:
            normalized.append(("error", event[1]))

    assert normalized == [
        ("data", "1", 10.0),
        ("data", "2", 20.0),
        ("error", "1: start timeout"),
        ("data", "2", 21.0),
        ("error", "1: read timeout"),
        ("data", "2", 22.0),
        ("data", "1", 30.0),
        ("data", "2", 23.0),
    ]
    assert sensors[0].read_data_calls == 3
    assert sensors[1].read_data_calls == 4
    assert [event[4].vwc for event in events if event[:2] == ("data", "1")] == [
        10.0,
        30.0,
    ]


def test_gui_queue_does_not_log_or_plot_failed_broadcast_samples(monkeypatch):
    sensors, events = _broadcast_failure_recovery_events(monkeypatch)
    app = object.__new__(gui_monitor.MonitorApp)
    app._queue = queue.Queue()
    for event in events:
        app._queue.put(event)
    app._multi = True
    app._ec_pore_coco_ok = {"1": True, "2": True}
    app._infos = {
        "1": SensorInfo("SLT5009", "1.2.2", 101),
        "2": SensorInfo("SLT5009", "1.2.2", 102),
    }
    app._start_time = next(event[3] for event in events if event[0] == "data")
    app.status_var = _Value()
    app.parameter_var = _Value("vwc")
    app._csv_file = io.StringIO()
    app._csv_writer = csv.writer(app._csv_file)
    app._series = {}
    app._ax = _Axes()
    app._canvas = _Canvas()

    def line_for(label):
        return app._series.setdefault(
            label,
            {"xs": [], "ys": [], "line": _Line()},
        )

    scheduled = []
    app._line_for = line_for
    app.after = lambda delay, callback: scheduled.append((delay, callback))

    app._poll_queue()

    assert app._queue.empty()
    assert len(scheduled) == 1
    assert scheduled[0][0] == 200
    assert app.status_var.history == [
        "1: vwc: 10.0 %",
        "2: vwc: 20.0 %",
        "Error: 1: start timeout",
        "2: vwc: 21.0 %",
        "Error: 1: read timeout",
        "2: vwc: 22.0 %",
        "1: vwc: 30.0 %",
        "2: vwc: 23.0 %",
    ]
    assert app._series["1"]["ys"] == [10.0, 30.0]
    assert app._series["2"]["ys"] == [20.0, 21.0, 22.0, 23.0]

    app._csv_file.seek(0)
    rows = list(csv.reader(app._csv_file))
    vwc_index = 4 + Measurement.field_names().index("vwc")
    assert [row[1] for row in rows] == ["1", "2", "2", "2", "1", "2"]
    assert [float(row[vwc_index]) for row in rows] == [
        10.0,
        20.0,
        21.0,
        22.0,
        30.0,
        23.0,
    ]
    assert sensors[0].read_data_calls == 3
