"""Find out which addresses are in use on a sensor bus.

SLT5008 has an SDI-12 address query (``?!``) and is asked directly. SLT5007 and
SLT5009 have no such command, so every address in their range is probed in turn
and the ones that answer are reported.

SLT5007 can also reset its sensor number to 0 (``--clear-address``). Every
SLT5007 on the bus acts on that command, so connect a single sensor first.

Examples:
    python examples/scan_addresses.py --product SLT5008 --port COM3
    python examples/scan_addresses.py --product SLT5009 --port COM3
    python examples/scan_addresses.py --product SLT5007 --port COM3 --clear-address
"""

from __future__ import annotations

import argparse
import sys

import _cli

from murata_soil_sensor import (  # noqa: E402
    ProtocolError,
    SensorError,
    SensorTimeoutError,
    Slt5007,
    Slt5008,
    create_sensor,
)

# Addresses that answer nothing must not cost a full read timeout each.
DEFAULT_SCAN_TIMEOUT = 0.3

#: Address range to probe, per product.
SCAN_RANGES = {"SLT5007": range(0, 32), "SLT5009": range(1, 32)}

SDI12_ADDRESSES = "0123456789"


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--product",
        required=True,
        choices=sorted(_cli.MULTI_SENSOR_PRODUCTS),
        help="Sensor product number (only multi-sensor buses have addresses).",
    )
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port, e.g. COM3 (Windows) or /dev/ttyUSB0 (Linux/macOS).",
    )
    parser.add_argument(
        "--baud",
        type=int,
        help="Override the baud rate (mainly for the SLT5008 converter).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_SCAN_TIMEOUT,
        help="Serial read timeout per probe in seconds.",
    )
    parser.add_argument(
        "--clear-address",
        action="store_true",
        help="SLT5007 only: reset the connected sensor's number to 0.",
    )
    return parser


def _describe(label, sensor, transport) -> None:
    try:
        info = sensor.read_info(transport)
    except Exception as exc:  # the sensor answered, so still report it
        print(f"{label}: found (read_info failed: {exc})")
        return
    print(
        f"{label}: {info.product}  firmware: {info.firmware_version}  serial: {info.serial_number}"
    )


def _summarise(found) -> int:
    if not found:
        print("no sensors found", file=sys.stderr)
        return 1
    print(f"{len(found)} sensor(s) found: {','.join(str(f) for f in found)}", file=sys.stderr)
    return 0


def _probe_sdi12_address(sensor, transport, candidate: str) -> bool:
    """Return whether ``candidate`` gives its exact acknowledge-active reply.

    A truly empty read or the converter's exact documented no-response sentinel
    means the address is unused. Keeping ``allow_empty=True`` distinguishes
    those cases from incomplete or malformed responses.
    """
    response = sensor._transaction(  # noqa: SLF001 - exact a! reply is required here
        transport, f"{candidate}!", allow_empty=True
    )
    if not response:
        return False
    if response != candidate:
        raise ProtocolError(
            f"unexpected acknowledge-active response for address {candidate}: {response!r}"
        )
    return True


def _scan_sdi12(args) -> int:
    # ?! gets a normal response, so do not cut it short with the probe timeout.
    kwargs = {"timeout": max(args.timeout, 1.0)}
    if args.baud is not None:
        kwargs["baudrate"] = args.baud
    sensor = Slt5008(**kwargs)

    with sensor.open(args.port) as transport:
        try:
            address = sensor.query_address(transport)
        except SensorError as exc:
            # With multiple sensors, simultaneous ?! responses may be non-ASCII,
            # truncated, or otherwise malformed. Those outcomes make ?! unusable,
            # but they must not prevent the safe addressed fallback below.
            print(f"?! response error: {exc}", file=sys.stderr)
            address = None
        if address is not None:
            print(
                f"?! reported {address}; confirming the complete bus with addressed a! probes "
                "because ?! cannot prove that only one sensor is connected",
                file=sys.stderr,
            )
        else:
            print(
                "?! gave no usable reply; probing each address with a! instead "
                "(?! only works with a single sensor on the bus)",
                file=sys.stderr,
            )
        found = []
        probe_error_seen = False
        for candidate in SDI12_ADDRESSES:
            sensor.address = candidate
            try:
                present = _probe_sdi12_address(sensor, transport, candidate)
            except SensorError as exc:
                probe_error_seen = True
                print(
                    f"{candidate}: protocol/device response error: {exc}",
                    file=sys.stderr,
                )
                continue
            if not present:
                continue
            found.append(candidate)
            _describe(candidate, sensor, transport)
    result = _summarise(found)
    return 1 if probe_error_seen else result


def _probe_address(sensor, value) -> None:
    if hasattr(sensor, "slave"):
        sensor.slave = value
    else:
        sensor.sensor_number = value


def _scan_by_probing(args, product) -> int:
    candidates = SCAN_RANGES[product]
    print(
        f"probing {product} addresses {candidates.start}-{candidates.stop - 1} on {args.port} ...",
        file=sys.stderr,
    )
    sensor = create_sensor(product, timeout=args.timeout)
    found = []
    with sensor.open(args.port) as transport:
        for candidate in candidates:
            _probe_address(sensor, candidate)
            try:
                info = sensor.read_info(transport)
            except SensorTimeoutError:  # an unused address simply does not answer
                continue
            except SensorError as exc:
                print(
                    f"{candidate}: protocol/device response error: {exc}",
                    file=sys.stderr,
                )
                continue
            found.append(candidate)
            print(
                f"{candidate}: {info.product}  firmware: {info.firmware_version}  "
                f"serial: {info.serial_number}"
            )
    return _summarise(found)


def _clear_address(args) -> int:
    print(
        "warning: every SLT5007 on the bus will reset its sensor number to 0",
        file=sys.stderr,
    )
    sensor = Slt5007(timeout=args.timeout)
    with sensor.open(args.port) as transport:
        sensor.clear_address(transport)
        # The command is not acknowledged, so confirm by reading address 0 back.
        try:
            info = sensor.read_info(transport)
        except Exception as exc:
            print(f"error: no answer at sensor number 0 after clearing: {exc}", file=sys.stderr)
            return 1
    print(f"0: {info.product}  firmware: {info.firmware_version}  serial: {info.serial_number}")
    print("sensor number cleared to 0", file=sys.stderr)
    return 0


def main() -> int:
    args = _make_parser().parse_args()
    product = args.product.upper()

    if args.clear_address:
        if product != "SLT5007":
            print("error: --clear-address is only supported on SLT5007", file=sys.stderr)
            return 1
        return _clear_address(args)

    try:
        if product == "SLT5008":
            return _scan_sdi12(args)
        return _scan_by_probing(args, product)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
