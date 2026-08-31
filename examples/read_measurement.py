"""Read the latest measurement from a Murata soil sensor.

By default only the customer-facing values are shown. Use --all to also print
the raw/internal parameters (DDS and ADC counts).

Example:
    python examples/read_measurement.py --product SLT5009 --port COM3 --address 1
    python examples/read_measurement.py --product SLT5006 --port COM13 --all
    python examples/read_measurement.py --product SLT5009 --port COM3 --address 1,2,3
"""

from __future__ import annotations

import sys

import _cli

from murata_soil_sensor import ADVANCED_FIELDS, FIELD_UNITS  # noqa: E402


def main() -> int:
    parser = _cli.make_parser(__doc__, measurement=True)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Also show raw/internal parameters (DDS, ADC counts).",
    )
    args = parser.parse_args()

    try:
        sensors = _cli.build_sensors(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    multi = len(sensors) > 1
    simultaneous = _cli.use_concurrent(
        sensors, broadcast_start=args.broadcast_start
    )

    with sensors[0].open(args.port) as transport:
        infos = [sensor.read_info(transport) for sensor in sensors]
        if simultaneous:
            measurements = _cli.read_concurrent_measurement(sensors, transport)
        else:
            measurements = [sensor.read_measurement(transport) for sensor in sensors]

    for index, (sensor, info, measurement) in enumerate(zip(sensors, infos, measurements)):
        if multi:
            if index > 0:
                print()
            print(f"=== address {_cli.sensor_address_label(sensor)} ===")

        print(f"product: {info.product}")
        print(f"firmware: {info.firmware_version}")
        print(f"serial: {info.serial_number}")
        print("-" * 32)

        ec_pore_coco_ok = sensor.supports_ec_pore_coco(info.firmware_version)
        for name, value in measurement.as_dict().items():
            if value is None:
                continue
            if name in ADVANCED_FIELDS and not args.all:
                continue
            if name == "ec_pore_coco" and not ec_pore_coco_ok:
                print(
                    f"{name}: not supported on this firmware "
                    f"(requires >= {sensor.ec_pore_coco_min_version})"
                )
                continue
            unit = FIELD_UNITS.get(name, "")
            print(f"{name}: {value} {unit}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
