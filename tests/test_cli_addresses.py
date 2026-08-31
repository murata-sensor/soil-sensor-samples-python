"""Tests for the CLI multi-sensor address helpers (examples/_cli.py)."""

import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
import _cli  # noqa: E402

from murata_soil_sensor import SensorTimeoutError, Slt5009  # noqa: E402


def _args(
    product,
    address=None,
    timeout=None,
    baud=None,
    sdi_crc=False,
    broadcast_start=False,
):
    return Namespace(
        product=product,
        port="COM3",
        address=address,
        timeout=timeout,
        baud=baud,
        sdi_crc=sdi_crc,
        broadcast_start=broadcast_start,
    )


def test_single_address_returns_one_sensor():
    sensors = _cli.build_sensors(_args("SLT5009", address="2"))
    assert len(sensors) == 1
    assert sensors[0].slave == 2


def test_comma_separated_addresses_return_multiple_sensors():
    sensors = _cli.build_sensors(_args("SLT5009", address="1,2,3"))
    assert [s.slave for s in sensors] == [1, 2, 3]


def test_multiple_addresses_rejected_for_single_sensor_product():
    with pytest.raises(ValueError):
        _cli.build_sensors(_args("SLT5006", address="1,2"))


def test_no_address_uses_product_default():
    sensors = _cli.build_sensors(_args("SLT5006"))
    assert len(sensors) == 1


def test_sensor_address_label():
    sensors = _cli.build_sensors(_args("SLT5007", address="0,1"))
    assert [_cli.sensor_address_label(s) for s in sensors] == ["0", "1"]


def test_duplicate_addresses_rejected():
    with pytest.raises(ValueError):
        _cli.build_sensors(_args("SLT5008", address="0,1,0"))


def test_numeric_duplicate_addresses_are_rejected_after_normalisation():
    with pytest.raises(ValueError, match="resolves to the same"):
        _cli.build_sensors(_args("SLT5009", address="1,01"))


@pytest.mark.parametrize("raw", [",,", "   ", " , "])
def test_empty_address_list_is_rejected(raw):
    with pytest.raises(ValueError, match="at least one address"):
        _cli.build_sensors(_args("SLT5009", address=raw))


def test_use_concurrent_only_for_multiple_sdi12_sensors():
    assert _cli.use_concurrent(_cli.build_sensors(_args("SLT5008", address="0,1")))
    assert not _cli.use_concurrent(_cli.build_sensors(_args("SLT5008", address="0")))
    assert not _cli.use_concurrent(_cli.build_sensors(_args("SLT5009", address="1,2")))


def test_sdi_crc_is_passed_only_to_slt5008():
    sensors = _cli.build_sensors(_args("SLT5008", address="0,1", sdi_crc=True))
    assert all(sensor.use_crc for sensor in sensors)
    with pytest.raises(ValueError, match="only supported for SLT5008"):
        _cli.build_sensors(_args("SLT5009", address="1", sdi_crc=True))


def test_slt5009_broadcast_requires_explicit_flag_and_two_addresses():
    sensors = _cli.build_sensors(
        _args("SLT5009", address="1,2", broadcast_start=True)
    )
    assert _cli.use_concurrent(sensors, broadcast_start=True)
    assert not _cli.use_concurrent(sensors, broadcast_start=False)
    with pytest.raises(ValueError, match="at least two"):
        _cli.build_sensors(_args("SLT5009", address="1", broadcast_start=True))
    with pytest.raises(ValueError, match="only supported for SLT5009"):
        _cli.build_sensors(_args("SLT5008", address="0,1", broadcast_start=True))


def test_tolerant_broadcast_errors_are_mapped_to_cli_address_labels(monkeypatch):
    sensors = [Slt5009(slave=1), Slt5009(slave=2)]
    error = SensorTimeoutError("sensor 1 did not finish")
    received = {}

    def start(selected, transport, *, continue_on_error):
        received.update(
            sensors=selected,
            transport=transport,
            continue_on_error=continue_on_error,
        )
        return {1: error}

    monkeypatch.setattr(_cli, "start_broadcast_measurement", start)
    transport = object()

    errors = _cli.start_concurrent_measurement(
        sensors, transport, continue_on_error=True
    )

    assert errors == {"1": error}
    assert received == {
        "sensors": sensors,
        "transport": transport,
        "continue_on_error": True,
    }


def test_measurement_flags_are_not_accepted_by_non_measurement_parser():
    parser = _cli.make_parser("test")
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--product", "SLT5008", "--port", "COM3", "--sdi-crc"]
        )


def test_measurement_parser_accepts_measurement_flags():
    parser = _cli.make_parser("test", measurement=True)
    args = parser.parse_args(
        ["--product", "SLT5008", "--port", "COM3", "--sdi-crc"]
    )
    assert args.sdi_crc
    assert not args.broadcast_start


@pytest.mark.parametrize(
    ("raw", "expected"), [("", None), (" 9600 ", 9600)]
)
def test_optional_positive_int(raw, expected):
    assert _cli.optional_positive_int(raw, "baud") == expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("", None), (" 0.25 ", 0.25)]
)
def test_optional_positive_float(raw, expected):
    assert _cli.optional_positive_float(raw, "timeout") == expected


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_optional_positive_values_reject_nonpositive_input(raw):
    with pytest.raises(ValueError, match="positive"):
        _cli.optional_positive_int(raw, "baud")
    with pytest.raises(ValueError, match="positive"):
        _cli.optional_positive_float(raw, "timeout")
