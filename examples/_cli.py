"""Shared command-line helpers for the example scripts.

Importing this module also makes the ``murata_soil_sensor`` package importable
when running an example directly from a source checkout (``python
examples/read_measurement.py``) without installing it first.
"""

from __future__ import annotations

import argparse
import copy
import sys
from dataclasses import replace
from pathlib import Path

# Allow running the examples straight from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from murata_soil_sensor import (  # noqa: E402
    SUPPORTED_PRODUCTS,
    Slt5008,
    Slt5009,
    create_sensor,
    read_broadcast_measurement,
    read_concurrent,
    start_broadcast_measurement,
    start_concurrent,
)

#: Products whose bus can carry more than one sensor at a given address.
MULTI_SENSOR_PRODUCTS = frozenset({"SLT5007", "SLT5008", "SLT5009"})


def optional_positive_int(value: str, label: str) -> int | None:
    """Parse an optional positive integer from a GUI/text field."""
    text = value.strip()
    if not text:
        return None
    result = int(text)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def optional_positive_float(value: str, label: str) -> float | None:
    """Parse an optional positive float from a GUI/text field."""
    text = value.strip()
    if not text:
        return None
    result = float(text)
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add the arguments shared by every example."""
    parser.add_argument(
        "--product",
        required=True,
        choices=SUPPORTED_PRODUCTS,
        help="Sensor product number.",
    )
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port, e.g. COM3 (Windows) or /dev/ttyUSB0 (Linux/macOS).",
    )
    parser.add_argument(
        "--address",
        help="Sensor address: MODBUS slave (SLT5009), sensor number (SLT5007), "
        "or SDI-12 address (SLT5008). Ignored for SLT5005/SLT5006. Comma-separated "
        "(e.g. 1,2,3) to read multiple sensors on one bus (SLT5007/5008/5009 only).",
    )
    parser.add_argument(
        "--baud",
        type=int,
        help="Override the baud rate (mainly for the SLT5008 converter).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="Serial read timeout in seconds.",
    )
    return parser


def add_measurement_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Add options that alter measurement commands rather than the connection."""
    parser.add_argument(
        "--sdi-crc",
        action="store_true",
        help="SLT5008 only: use aMC!/aCC! and verify CRC on every data response.",
    )
    parser.add_argument(
        "--broadcast-start",
        action="store_true",
        help="SLT5009 only: start two or more sensors together with a MODBUS broadcast.",
    )
    return parser


def make_parser(
    description: str | None, *, measurement: bool = False
) -> argparse.ArgumentParser:
    """Return an argument parser preloaded with the common arguments."""
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_args(parser)
    if measurement:
        add_measurement_args(parser)
    return parser


def build_sensor(args: argparse.Namespace):
    """Create a sensor handler from parsed common arguments."""
    product = args.product.upper()
    kwargs: dict = {}
    if args.timeout is not None:
        kwargs["timeout"] = args.timeout
    if product == "SLT5007":
        if args.address is not None:
            kwargs["sensor_number"] = int(args.address)
    elif product == "SLT5009":
        if args.address is not None:
            kwargs["slave"] = int(args.address)
    elif product == "SLT5008":
        if args.address is not None:
            kwargs["address"] = str(args.address)
        if args.baud is not None:
            kwargs["baudrate"] = args.baud
        kwargs["use_crc"] = bool(getattr(args, "sdi_crc", False))
    return create_sensor(product, **kwargs)


def _split_addresses(raw: str) -> list:
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_sensors(args: argparse.Namespace) -> list:
    """Create one sensor handler per address in ``--address``.

    A comma-separated ``--address`` (e.g. ``1,2,3``) creates one handler per
    address, for reading several sensors on one SLT5007/SLT5008/SLT5009 bus.
    """
    product = args.product.upper()
    if args.address is None:
        addresses = [None]
    else:
        addresses = _split_addresses(args.address)
        if not addresses:
            raise ValueError("--address must contain at least one address")
    if getattr(args, "sdi_crc", False) and product != "SLT5008":
        raise ValueError("--sdi-crc is only supported for SLT5008")
    if getattr(args, "broadcast_start", False):
        if product != "SLT5009":
            raise ValueError("--broadcast-start is only supported for SLT5009")
        if len(addresses) < 2:
            raise ValueError("--broadcast-start requires at least two SLT5009 addresses")
    if len(addresses) > 1 and product not in MULTI_SENSOR_PRODUCTS:
        raise ValueError(
            f"{product} is a single-sensor product; multiple addresses "
            "(--address a,b,c) are only supported on SLT5007/SLT5008/SLT5009"
        )
    if len(set(addresses)) != len(addresses):
        raise ValueError("--address lists the same address more than once")
    sensors = []
    for address in addresses:
        sub_args = copy.copy(args)
        sub_args.address = address
        sensors.append(build_sensor(sub_args))
    labels = [sensor_address_label(sensor) for sensor in sensors]
    if len(set(labels)) != len(labels):
        raise ValueError("--address resolves to the same address more than once")
    return sensors


def use_concurrent(sensors, *, broadcast_start: bool = False) -> bool:
    """Return whether the selected sensors should start one measurement together."""
    if len(sensors) < 2:
        return False
    if all(isinstance(sensor, Slt5008) for sensor in sensors):
        return True
    return broadcast_start and all(isinstance(sensor, Slt5009) for sensor in sensors)


def start_concurrent_measurement(
    sensors, transport, *, continue_on_error: bool = False
) -> dict[str, Exception]:
    """Dispatch a safe simultaneous start for a homogeneous sensor list."""
    if all(isinstance(sensor, Slt5008) for sensor in sensors):
        start_concurrent(sensors, transport)
        return {}
    if all(isinstance(sensor, Slt5009) for sensor in sensors):
        errors = start_broadcast_measurement(
            sensors, transport, continue_on_error=continue_on_error
        )
        return {str(address): error for address, error in (errors or {}).items()}
    raise ValueError("simultaneous measurement requires only SLT5008 or only SLT5009")


def read_concurrent_measurement(sensors, transport):
    """Start and read a homogeneous group using the product-specific mechanism."""
    if all(isinstance(sensor, Slt5008) for sensor in sensors):
        return read_concurrent(sensors, transport)
    if all(isinstance(sensor, Slt5009) for sensor in sensors):
        return read_broadcast_measurement(sensors, transport)
    raise ValueError("simultaneous measurement requires only SLT5008 or only SLT5009")


def sensor_address_label(sensor) -> str:
    """Return a short label identifying which address a handler targets."""
    for attr in ("slave", "sensor_number", "address"):
        if hasattr(sensor, attr):
            return str(getattr(sensor, attr))
    return sensor.product


def measurement_for_output(sensor, info, measurement):
    """Return a copy safe for user-visible output for the identified firmware.

    Older firmware can return a value in the register/block position later used
    for ``ec_pore_coco`` even though that field is not supported.  Keep reading
    the complete protocol response for compatibility, but never expose that
    position as a measurement unless identification proves the firmware supports
    it.  Identification failure therefore fails closed.
    """
    supported = info is not None and sensor.supports_ec_pore_coco(
        info.firmware_version
    )
    if supported or getattr(measurement, "ec_pore_coco", None) is None:
        return measurement
    return replace(measurement, ec_pore_coco=None)
