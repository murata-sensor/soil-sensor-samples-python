"""Simple real-time GUI monitor (Tkinter + matplotlib).

Reads measurements continuously in a background thread and plots one selected
value over time. Optionally logs every measurement to a CSV file.

A comma-separated address (e.g. ``1,2,3``) reads and plots several sensors on
one bus (SLT5007/SLT5008/SLT5009 only), each as its own line.

Requirements:
    pip install -r requirements-gui.txt     # adds matplotlib
    # On Linux/Raspberry Pi you may also need Tk: sudo apt install python3-tk

Run:
    python examples/gui_monitor.py
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk
from typing import Any, TextIO, cast

import _cli

from murata_soil_sensor import (  # noqa: E402
    ADVANCED_FIELDS,
    FIELD_UNITS,
    SUPPORTED_PRODUCTS,
    Measurement,
)

FigureCanvasTkAgg: Any
Figure: Any
try:
    from matplotlib import figure as _matplotlib_figure
    from matplotlib.backends import backend_tkagg as _backend_tkagg
except ImportError:  # matplotlib is an optional dependency (requirements-gui.txt)
    FigureCanvasTkAgg = None
    Figure = None
else:
    FigureCanvasTkAgg = _backend_tkagg.FigureCanvasTkAgg
    Figure = _matplotlib_figure.Figure

# Numeric fields worth plotting.
PLOTTABLE = [
    "temperature_c",
    "vwc",
    "vwc_rock",
    "vwc_coco",
    "ec_bulk",
    "ec_pore",
    "ec_pore_coco",
    "adc_permittivity",
    "adc_battery",
    "dds",
    "adc_ec",
]


def _available_ports() -> list:
    """Return the device names of the serial ports currently available."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [port.device for port in list_ports.comports()]


class _Worker(threading.Thread):
    """Background thread that reads one or more sensors at a fixed interval."""

    def __init__(self, sensors, port, interval, out_queue, stop_event, *, broadcast_start=False):
        super().__init__(daemon=True)
        self._sensors = sensors
        self._port = port
        self._interval = interval
        self._queue = out_queue
        self._stop = stop_event
        self._broadcast_start = broadcast_start

    def run(self) -> None:
        try:
            with self._sensors[0].open(self._port) as transport:
                self._read_infos(transport)
                simultaneous = _cli.use_concurrent(
                    self._sensors, broadcast_start=self._broadcast_start
                )
                while not self._stop.is_set():
                    started = time.monotonic()
                    if simultaneous:
                        self._measure_concurrent(transport)
                    else:
                        self._measure_sequential(transport)
                    # The interval is a period, so subtract the time the readout took.
                    self._stop.wait(max(0.0, self._interval - (time.monotonic() - started)))
        except Exception as exc:
            self._queue.put(("error", f"could not open {self._port}: {exc}"))

    def _read_infos(self, transport) -> None:
        for sensor in self._sensors:
            label = _cli.sensor_address_label(sensor)
            try:
                info = sensor.read_info(transport)
                self._queue.put(("info", label, sensor, info))
            except Exception as exc:  # keep going even if info fails
                self._queue.put(("error", f"{label}: read_info: {exc}"))

    def _measure_concurrent(self, transport) -> None:
        try:
            start_errors = _cli.start_concurrent_measurement(
                self._sensors,
                transport,
                continue_on_error=self._broadcast_start,
            )
        except Exception as exc:
            self._queue.put(("error", str(exc)))
            return
        timestamp = datetime.now().astimezone()
        for sensor in self._sensors:
            label = _cli.sensor_address_label(sensor)
            if label in start_errors:
                self._queue.put(("error", f"{label}: {start_errors[label]}"))
                continue
            try:
                self._queue.put(("data", label, sensor, timestamp, sensor.read_data(transport)))
            except Exception as exc:  # one sensor failing must not drop the others
                self._queue.put(("error", f"{label}: {exc}"))

    def _measure_sequential(self, transport) -> None:
        for sensor in self._sensors:
            label = _cli.sensor_address_label(sensor)
            try:
                measurement = sensor.read_measurement(transport)
                self._queue.put(
                    (
                        "data",
                        label,
                        sensor,
                        datetime.now().astimezone(),
                        measurement,
                    )
                )
            except Exception as exc:  # keep the GUI responsive on errors
                self._queue.put(("error", f"{label}: {exc}"))
            if self._stop.is_set():
                break


class MonitorApp(tk.Tk):
    """Tkinter application: connection controls plus a live plot."""

    def __init__(
        self,
        show_advanced: bool = False,
        product=None,
        port=None,
        address=None,
        *,
        sdi_crc: bool = False,
        broadcast_start: bool = False,
        baud: int | None = None,
        timeout: float | None = None,
        csv_exclusive: bool = True,
    ):
        super().__init__()
        self.title("Murata soil sensor monitor")
        self.geometry("820x560")

        self._show_advanced = show_advanced
        self._parameters = (
            list(PLOTTABLE) if show_advanced else [m for m in PLOTTABLE if m not in ADVANCED_FIELDS]
        )
        self._prefill = (
            product,
            port,
            address,
            sdi_crc,
            broadcast_start,
            baud,
            timeout,
        )

        self._queue: queue.Queue = queue.Queue()
        self._worker: _Worker | None = None
        self._stop_event: threading.Event | None = None
        self._sensors: list = []
        self._multi = False
        self._ec_pore_coco_ok: dict = {}
        self._info_lines: dict = {}
        self._infos: dict = {}
        self._start_time: datetime | None = None
        self._series: dict = {}  # label -> {"xs": [...], "ys": [...], "line": Line2D}
        self._csv_file: TextIO | None = None
        self._csv_writer: Any | None = None
        self._csv_open_mode = "x" if csv_exclusive else "w"

        self._build_controls()
        self._build_plot()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_queue)

    # -- UI construction ------------------------------------------------------
    def _build_controls(self) -> None:
        frame = ttk.Frame(self, padding=8)
        frame.pack(side=tk.TOP, fill=tk.X)

        self.product_var = tk.StringVar(value=self._prefill[0] or "SLT5009")
        self.port_var = tk.StringVar(value=self._prefill[1] or "")
        self.address_var = tk.StringVar(value=self._prefill[2] or "1")
        self.interval_var = tk.StringVar(value="5")
        self.parameter_var = tk.StringVar(value="vwc")
        self.csv_var = tk.StringVar(value="")
        self.sdi_crc_var = tk.BooleanVar(value=self._prefill[3])
        self.broadcast_start_var = tk.BooleanVar(value=self._prefill[4])
        self.baud_var = tk.StringVar(
            value="" if self._prefill[5] is None else str(self._prefill[5])
        )
        self.timeout_var = tk.StringVar(
            value="" if self._prefill[6] is None else str(self._prefill[6])
        )

        def add(label, widget, col):
            ttk.Label(frame, text=label).grid(row=0, column=col, sticky=tk.W, padx=2)
            widget.grid(row=1, column=col, padx=2)

        add(
            "Product",
            ttk.Combobox(
                frame,
                textvariable=self.product_var,
                values=list(SUPPORTED_PRODUCTS),
                width=9,
                state="readonly",
            ),
            0,
        )
        self.port_combo = ttk.Combobox(
            frame,
            textvariable=self.port_var,
            width=14,
            state="readonly",
            values=_available_ports(),
            postcommand=self._refresh_ports,
        )
        add("Port", self.port_combo, 1)
        add("Address", ttk.Entry(frame, textvariable=self.address_var, width=6), 2)
        add("Interval [s]", ttk.Entry(frame, textvariable=self.interval_var, width=6), 3)
        add(
            "Parameter",
            ttk.Combobox(
                frame,
                textvariable=self.parameter_var,
                values=self._parameters,
                width=16,
                state="readonly",
            ),
            4,
        )
        add("CSV (optional)", ttk.Entry(frame, textvariable=self.csv_var, width=18), 5)

        self.parameter_var.trace_add("write", self._on_parameter_change)

        self.start_btn = ttk.Button(frame, text="Start", command=self._on_start)
        self.start_btn.grid(row=1, column=6, padx=6)
        self.stop_btn = ttk.Button(frame, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.grid(row=1, column=7, padx=2)
        ttk.Label(frame, text="Baud override").grid(
            row=2, column=0, sticky=tk.W, padx=2, pady=(4, 0)
        )
        ttk.Entry(frame, textvariable=self.baud_var, width=9).grid(
            row=2, column=1, sticky=tk.W, padx=2, pady=(4, 0)
        )
        ttk.Label(frame, text="Timeout [s]").grid(row=2, column=2, sticky=tk.W, padx=2, pady=(4, 0))
        ttk.Entry(frame, textvariable=self.timeout_var, width=7).grid(
            row=2, column=3, sticky=tk.W, padx=2, pady=(4, 0)
        )
        ttk.Checkbutton(frame, text="SLT5008 CRC", variable=self.sdi_crc_var).grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=(4, 0)
        )
        ttk.Checkbutton(
            frame,
            text="SLT5009 broadcast start (all bus sensors)",
            variable=self.broadcast_start_var,
        ).grid(row=3, column=2, columnspan=4, sticky=tk.W, pady=(4, 0))

        self.info_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.info_var, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)
        self.status_var = tk.StringVar(value="Idle")
        ttk.Label(self, textvariable=self.status_var, anchor=tk.W).pack(side=tk.BOTTOM, fill=tk.X)

    def _refresh_ports(self) -> None:
        """Refresh the port dropdown with the currently available ports."""
        self.port_combo["values"] = _available_ports()

    def _on_parameter_change(self, *_args) -> None:
        """Clear the plotted series and reset the axis for the new parameter."""
        self._series.clear()
        self._reset_axes()
        self._canvas.draw_idle()

    def _reset_axes(self) -> None:
        self._ax.cla()
        self._ax.set_xlabel("elapsed [s]")
        self._ax.set_ylabel(self.parameter_var.get())
        self._ax.grid(True)

    def _line_for(self, label: str):
        """Return the plotted series for ``label``, creating it if needed."""
        series = self._series.get(label)
        if series is None:
            (line,) = self._ax.plot([], [], marker=".", label=label if self._multi else None)
            series = {"xs": [], "ys": [], "line": line}
            self._series[label] = series
            if self._multi:
                self._ax.legend(loc="upper right", fontsize="small")
        return series

    def _build_plot(self) -> None:
        self._figure = Figure(figsize=(8, 4), dpi=100)
        self._ax = self._figure.add_subplot(111)
        self._reset_axes()
        self._canvas = FigureCanvasTkAgg(self._figure, master=self)
        self._canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # -- start/stop -----------------------------------------------------------
    def _on_start(self) -> None:
        try:
            interval = float(self.interval_var.get())
            if interval <= 0:
                raise ValueError("interval must be positive")
            baud = _cli.optional_positive_int(self.baud_var.get(), "baud")
            timeout = _cli.optional_positive_float(self.timeout_var.get(), "timeout")
            args = argparse.Namespace(
                product=self.product_var.get(),
                port=self.port_var.get(),
                address=self.address_var.get() or None,
                baud=baud,
                timeout=timeout,
                sdi_crc=self.sdi_crc_var.get(),
                broadcast_start=self.broadcast_start_var.get(),
            )
            sensors = _cli.build_sensors(args)
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            return

        self._sensors = sensors
        self._multi = len(sensors) > 1
        try:
            self._open_csv()
        except OSError as exc:
            self.status_var.set(f"Error: cannot open CSV output: {exc}")
            return
        self._series.clear()
        self._reset_axes()
        self._canvas.draw_idle()
        self._start_time = datetime.now().astimezone()
        self._ec_pore_coco_ok.clear()
        self._info_lines.clear()
        self._infos.clear()
        self.info_var.set("")

        self._stop_event = threading.Event()
        self._worker = _Worker(
            sensors,
            args.port,
            interval,
            self._queue,
            self._stop_event,
            broadcast_start=args.broadcast_start,
        )
        self._worker.start()

        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        label = f"{args.product} x{len(sensors)}" if self._multi else args.product
        self.status_var.set(f"Running ({label} on {args.port})")

    def _on_stop(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self._close_csv()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Stopped")

    # -- CSV ------------------------------------------------------------------
    def _open_csv(self) -> None:
        import csv

        path = self.csv_var.get().strip()
        if not path:
            return
        csv_file = cast(
            TextIO,
            open(path, self._csv_open_mode, newline="", encoding="utf-8"),
        )
        csv_writer = csv.writer(csv_file)
        self._csv_file = csv_file
        self._csv_writer = csv_writer
        header = [
            "timestamp",
            *(["address"] if self._multi else []),
            "firmware",
            "serial",
            *Measurement.field_names(),
        ]
        csv_writer.writerow(header)

    def _close_csv(self) -> None:
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None

    # -- queue draining / plotting -------------------------------------------
    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                if item[0] == "error":
                    self.status_var.set(f"Error: {item[1]}")
                elif item[0] == "info":
                    _, label, sensor, info = item
                    self._handle_info(label, sensor, info)
                else:
                    _, label, sensor, timestamp, measurement = item
                    self._handle_measurement(label, sensor, timestamp, measurement)
        except queue.Empty:
            pass
        self.after(200, self._poll_queue)

    def _handle_info(self, label: str, sensor, info) -> None:
        ok = sensor.supports_ec_pore_coco(info.firmware_version)
        self._ec_pore_coco_ok[label] = ok
        self._infos[label] = info
        prefix = f"{label}: " if self._multi else ""
        self._info_lines[label] = (
            f"{prefix}firmware: {info.firmware_version}  serial: {info.serial_number}"
            + ("" if ok else "  (ec_pore_coco not supported)")
        )
        self.info_var.set("   ".join(self._info_lines[lbl] for lbl in self._info_lines))

    def _handle_measurement(
        self, label: str, sensor, timestamp: datetime, measurement: Measurement
    ) -> None:
        info = self._infos.get(label)
        measurement = _cli.measurement_for_output(sensor, info, measurement)
        csv_writer = self._csv_writer
        csv_file = self._csv_file
        if csv_writer is not None and csv_file is not None:
            row = [
                timestamp.isoformat(timespec="seconds"),
                *([label] if self._multi else []),
                info.firmware_version if info else "",
                info.serial_number if info else "",
                *measurement.csv_row(),
            ]
            csv_writer.writerow(row)
            csv_file.flush()

        parameter = self.parameter_var.get()
        prefix = f"{label}: " if self._multi else ""
        if parameter == "ec_pore_coco" and not self._ec_pore_coco_ok.get(label, False):
            self.status_var.set(f"{prefix}ec_pore_coco not supported on this firmware")
            return
        value = measurement.as_dict().get(parameter)
        if value is None:
            self.status_var.set(f"{prefix}{parameter} not reported by this product")
            return
        elapsed = (timestamp - self._start_time).total_seconds() if self._start_time else 0.0
        series = self._line_for(label)
        series["xs"].append(elapsed)
        series["ys"].append(value)
        series["line"].set_data(series["xs"], series["ys"])
        self._ax.relim()
        self._ax.autoscale_view()
        self._canvas.draw_idle()
        unit = FIELD_UNITS.get(parameter, "")
        self.status_var.set(f"{prefix}{parameter}: {value} {unit}".rstrip())

    def _on_close(self) -> None:
        self._on_stop()
        self.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include advanced/raw parameters (DDS, ADC) in the parameter list.",
    )
    parser.add_argument("--product", choices=SUPPORTED_PRODUCTS, help="Preselect the product.")
    parser.add_argument("--port", help="Preselect the serial port.")
    parser.add_argument("--address", help="Preselect the address.")
    parser.add_argument("--baud", type=int, help="Preselect the converter baud override.")
    parser.add_argument("--timeout", type=float, help="Preselect the serial timeout in seconds.")
    parser.add_argument("--sdi-crc", action="store_true", help="Preselect SLT5008 CRC measurement.")
    parser.add_argument(
        "--broadcast-start",
        action="store_true",
        help="Preselect SLT5009 MODBUS broadcast measurement start.",
    )
    args = parser.parse_args()

    if Figure is None:
        print(
            "matplotlib is required for the GUI. Install it with:\n"
            "    pip install -r requirements-gui.txt",
            file=sys.stderr,
        )
        return 1
    MonitorApp(
        show_advanced=args.all,
        product=args.product,
        port=args.port,
        address=args.address,
        sdi_crc=args.sdi_crc,
        broadcast_start=args.broadcast_start,
        baud=args.baud,
        timeout=args.timeout,
    ).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
