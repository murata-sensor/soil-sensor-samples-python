"""Tests for the optional GAS upload helper used by the examples."""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import _uploader  # noqa: E402

from murata_soil_sensor import Measurement, SensorInfo  # noqa: E402


def _args(**overrides):
    defaults = {"upload_url": None, "upload_timeout": 10.0}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_no_uploader_without_a_url(monkeypatch):
    monkeypatch.delenv(_uploader.URL_ENV, raising=False)
    assert _uploader.Uploader.from_args(_args()) is None


def test_url_may_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(_uploader.URL_ENV, "https://example.com/exec")
    monkeypatch.setenv(_uploader.TOKEN_ENV, "secret")
    assert _uploader.Uploader.from_args(_args()) is not None


def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.delenv(_uploader.TOKEN_ENV, raising=False)
    with pytest.raises(ValueError):
        _uploader.Uploader.from_args(_args(upload_url="https://example.com/exec"))


def test_plain_http_is_rejected(monkeypatch):
    # The shared secret travels in the body, so the transport must be encrypted.
    monkeypatch.setenv(_uploader.TOKEN_ENV, "secret")
    with pytest.raises(ValueError):
        _uploader.Uploader.from_args(_args(upload_url="http://example.com/exec"))


def test_row_payload_maps_and_skips_missing_values():
    info = SensorInfo(product="SLT5009", firmware_version="1.2.2", serial_number=24107928)
    measurement = Measurement(temperature_c=21.5, vwc=45.2, ec_bulk=0.51, battery_v=3.31)
    row = _uploader.row_payload("2026-07-31T14:30:00+09:00", info, measurement)
    assert row == {
        "ts": "2026-07-31T14:30:00+09:00",
        "serialNumber": "24107928",
        "battery_v": 3.31,
        "temperature_c": 21.5,
        "vwc_pct": 45.2,
        "ec_bulk_dsm": 0.51,
    }


def test_row_payload_without_identification():
    row = _uploader.row_payload("2026-07-31T14:30:00+09:00", None, Measurement(vwc=1.0))
    assert "serialNumber" not in row


def test_row_payload_omits_masked_ec_pore_coco_and_keeps_supported_value():
    timestamp = "2026-07-31T14:30:00+09:00"
    assert "ec_pore_coco_dsm" not in _uploader.row_payload(
        timestamp, None, Measurement(ec_pore_coco=None)
    )
    assert _uploader.row_payload(
        timestamp, None, Measurement(ec_pore_coco=1.23)
    )["ec_pore_coco_dsm"] == 1.23
