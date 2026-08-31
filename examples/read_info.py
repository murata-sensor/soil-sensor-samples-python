"""Read a Murata soil sensor's information (firmware version, serial number).

Example:
    python examples/read_info.py --product SLT5006 --port COM3
    python examples/read_info.py --product SLT5009 --port COM4 --address 1,2
"""

from __future__ import annotations

import sys

import _cli


def main() -> int:
    parser = _cli.make_parser(__doc__)
    args = parser.parse_args()

    try:
        sensors = _cli.build_sensors(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    multi = len(sensors) > 1
    had_error = False

    with sensors[0].open(args.port) as transport:
        for index, sensor in enumerate(sensors):
            label = _cli.sensor_address_label(sensor)
            try:
                info = sensor.read_info(transport)
            except Exception as exc:  # one sensor failing must not hide the others
                print(f"error: {label}: {exc}", file=sys.stderr)
                had_error = True
                continue
            if multi:
                if index:
                    print()
                print(f"Address:  {label}")
            print(f"Product:  {info.product}")
            print(f"Firmware: {info.firmware_version}")
            print(f"Serial:   {info.serial_number}")
            if info.sdi_version is not None:
                print(f"SDI-12:   {info.sdi_version}")
            if info.vendor is not None:
                print(f"Vendor:   {info.vendor}")
            if info.model is not None:
                print(f"Model:    {info.model}")
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
