"""Change a sensor's address / slave number.

Examples:
    python examples/set_address.py --product SLT5009 --port COM3 --address 1 --new-address 2
    python examples/set_address.py --product SLT5007 --port COM3 --address 0 --new-address 1
    python examples/set_address.py --product SLT5008 --port COM3 --address 0 --new-address 1

Note: SLT5005/SLT5006 are single-sensor buses and do not support this.
"""

from __future__ import annotations

import copy
import sys

import _cli

from murata_soil_sensor import (  # noqa: E402
    ProtocolError,
    SensorError,
    SensorTimeoutError,
    Slt5008,
)


def _build_sensor_at(args, address):
    candidate_args = copy.copy(args)
    candidate_args.address = str(address)
    return _cli.build_sensor(candidate_args)


def _require_unused(sensor, transport) -> None:
    """Refuse an address write unless the requested address is silent."""
    label = _cli.sensor_address_label(sensor)
    try:
        if isinstance(sensor, Slt5008) or sensor.product == "SLT5008":
            info = sensor.read_info(transport)
            detail = f"serial {info.serial_number} answered"
        else:
            reported = sensor.read_address(transport)
            detail = f"sensor reported address {reported}"
    except SensorTimeoutError:
        return
    except SensorError as exc:
        raise ProtocolError(
            f"cannot confirm address {label} is unused; it returned an invalid response: {exc}"
        ) from exc
    raise ProtocolError(f"address {label} is already in use ({detail})")


def main(argv=None) -> int:
    parser = _cli.make_parser(__doc__)
    parser.add_argument(
        "--new-address",
        required=True,
        help="New address (SLT5007: 0-31, SLT5009: 1-31, SLT5008: single digit 0-9).",
    )
    args = parser.parse_args(argv)
    write_attempted = False

    try:
        sensor = _cli.build_sensor(args)
        candidate = _build_sensor_at(args, args.new_address)
        requested = _cli.sensor_address_label(candidate)
        with sensor.open(args.port) as transport:
            old_address = sensor.read_address(transport)
            before = sensor.read_info(transport)
            if str(old_address) == requested:
                changed = False
                confirmed = old_address
                after = before
            else:
                _require_unused(candidate, transport)
                # From this point on, a missing acknowledgement/readback does
                # not prove that the nonvolatile write failed.
                write_attempted = True
                sensor.set_address(transport, requested)
                confirmed = sensor.read_address(transport)
                after = sensor.read_info(transport)
                changed = True
            if str(confirmed) != requested:
                raise ProtocolError(
                    f"address readback is {confirmed}, expected {requested}"
                )
            if str(after.serial_number) != str(before.serial_number):
                raise ProtocolError(
                    "serial number changed after address update; another sensor may have replied"
                )
    except (ValueError, SensorError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if write_attempted:
            print(
                "warning: an address write was attempted, so the sensor may now "
                f"use either {old_address} or {requested}. Do not repeat the write yet. "
                "Probe both addresses with all bus devices powered. If identity remains "
                "ambiguous, turn power off before isolating the target sensor, restore "
                "power, then scan and verify its serial number.",
                file=sys.stderr,
            )
        return 1

    if changed:
        print(
            f"Address changed from {old_address} to {confirmed}; live readback and serial "
            f"identity ({after.serial_number}) verified."
        )
    else:
        print(
            f"Address is already {confirmed}; no nonvolatile write was performed. "
            f"Serial identity ({after.serial_number}) verified."
        )
    print(
        "Turn the sensor power source OFF without disconnecting energized wiring. "
        "Wait a few seconds, restore power, then verify retention with:"
    )
    baud_option = f" --baud {args.baud}" if args.baud is not None else ""
    timeout_option = f" --timeout {args.timeout}" if args.timeout is not None else ""
    print(
        f"python examples/verify_address.py --product {args.product.upper()} "
        f"--port {args.port} --address {confirmed} "
        f"--expected-serial {after.serial_number}{baud_option}{timeout_option}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
