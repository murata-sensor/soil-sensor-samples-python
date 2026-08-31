"""Verify an address and sensor identity after safely cycling sensor power.

Run ``set_address.py`` first. Turn the power source OFF without disconnecting
energized sensor wiring, wait a few seconds, restore power, and run the command
printed by that script.

Example:
    python examples/verify_address.py --product SLT5009 --port COM3 \
        --address 2 --expected-serial 24107928
"""

from __future__ import annotations

import sys

import _cli

from murata_soil_sensor import SensorError  # noqa: E402


def main(argv=None) -> int:
    parser = _cli.make_parser(__doc__)
    parser.add_argument(
        "--expected-serial",
        required=True,
        help="Serial number printed before sensor power was turned off.",
    )
    args = parser.parse_args(argv)

    if not args.address or "," in args.address:
        parser.error("--address must specify exactly one address to verify")

    try:
        sensor = _cli.build_sensor(args)
        with sensor.open(args.port) as transport:
            address = sensor.read_address(transport)
            info = sensor.read_info(transport)
    except (ValueError, SensorError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    expected_address = int(args.address) if isinstance(address, int) else args.address
    if address != expected_address:
        print(
            f"error: sensor reports address {address}; expected {expected_address}",
            file=sys.stderr,
        )
        return 1
    try:
        expected_serial = int(args.expected_serial)
    except ValueError:
        expected_serial = args.expected_serial
    if info.serial_number != expected_serial:
        print(
            f"error: serial is {info.serial_number}; expected {expected_serial}",
            file=sys.stderr,
        )
        return 1

    print(
        f"PASS: address {address} retained after power was restored; "
        f"serial {info.serial_number} matches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
