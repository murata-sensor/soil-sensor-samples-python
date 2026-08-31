"""Continuously measure and log to a CSV file (and the console).

Examples:
    python examples/continuous_log.py --product SLT5009 --port COM3 --address 1 \
        --interval 10 --out data.csv
    python examples/continuous_log.py --product SLT5006 --port COM3 --count 5
    python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2,3 \
        --interval 10 --out data.csv

Each measurement can also be uploaded to a Google Sheet, which is how the
soil-sensor-data-monitoring dashboard gets its data:

    $env:SOIL_UPLOAD_TOKEN = "..."
    python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2 \
        --interval 300 --out data.csv --upload-url https://script.google.com/...

Press Ctrl+C to stop.
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime

import _cli
import _uploader

from murata_soil_sensor import Measurement  # noqa: E402


def _read_infos(sensors, transport) -> dict:
    """Identify every sensor once; the values are repeated in each logged row."""
    infos = {}
    for sensor in sensors:
        label = _cli.sensor_address_label(sensor)
        try:
            info = sensor.read_info(transport)
        except Exception as exc:  # keep logging even if identification fails
            print(f"error: {label}: read_info: {exc}", file=sys.stderr)
            infos[label] = None
        else:
            print(
                f"{label}: {info.product}  firmware: {info.firmware_version}  "
                f"serial: {info.serial_number}",
                file=sys.stderr,
            )
            infos[label] = info
    return infos


def main(argv=None) -> int:
    parser = _cli.make_parser(__doc__, measurement=True)
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds from the start of one measurement to the start of the next.",
    )
    parser.add_argument(
        "--count", type=int, default=0, help="Number of measurements (0 = run until Ctrl+C)."
    )
    parser.add_argument("--out", help="CSV output file (default: stdout only).")
    _uploader.add_arguments(parser)
    args = parser.parse_args(argv)

    try:
        sensors = _cli.build_sensors(args)
        uploader = _uploader.Uploader.from_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    multi = len(sensors) > 1

    header = [
        "timestamp",
        *(["address"] if multi else []),
        "firmware",
        "serial",
        *Measurement.field_names(),
    ]

    out_file = open(args.out, "w", newline="", encoding="utf-8") if args.out else None
    writer = csv.writer(out_file) if out_file else None

    taken = 0
    try:
        with sensors[0].open(args.port) as transport:
            # Identification goes to stderr so stdout stays a valid CSV stream.
            infos = _read_infos(sensors, transport)
            if writer:
                writer.writerow(header)
            print(",".join(header))
            simultaneous = _cli.use_concurrent(
                sensors, broadcast_start=args.broadcast_start
            )
            while args.count == 0 or taken < args.count:
                started = time.monotonic()
                # The offset makes the timestamp unambiguous for the upload target.
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                start_errors = {}
                if simultaneous:
                    try:
                        start_errors = _cli.start_concurrent_measurement(
                            sensors,
                            transport,
                            continue_on_error=bool(args.broadcast_start),
                        )
                    except Exception as exc:
                        print(f"error: simultaneous measurement start: {exc}", file=sys.stderr)
                        start_errors = {
                            _cli.sensor_address_label(sensor): exc for sensor in sensors
                        }
                upload_rows = []
                for sensor in sensors:
                    label = _cli.sensor_address_label(sensor)
                    if label in start_errors:
                        print(f"error: {label}: {start_errors[label]}", file=sys.stderr)
                        continue
                    try:
                        measurement = (
                            sensor.read_data(transport)
                            if simultaneous
                            else sensor.read_measurement(transport)
                        )
                    except Exception as exc:  # one sensor failing must not stop the log
                        print(f"error: {label}: {exc}", file=sys.stderr)
                        continue
                    info = infos.get(label)
                    measurement = _cli.measurement_for_output(
                        sensor, info, measurement
                    )
                    row = [
                        timestamp,
                        *([label] if multi else []),
                        info.firmware_version if info else "",
                        info.serial_number if info else "",
                        *measurement.csv_row(),
                    ]
                    print(",".join(str(v) for v in row))
                    if writer:
                        writer.writerow(row)
                        out_file.flush()
                    if uploader:
                        upload_rows.append(_uploader.row_payload(timestamp, info, measurement))
                if uploader:
                    # A failed upload only costs this sample; the CSV still has it.
                    uploader.send(upload_rows)
                taken += 1
                if args.count == 0 or taken < args.count:
                    # The interval is a period, so subtract the time the readout took.
                    time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    finally:
        if out_file:
            out_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
