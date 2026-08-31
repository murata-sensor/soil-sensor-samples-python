"""Tests for measurement dataclasses and the signed-12-bit helper."""

import pytest

from murata_soil_sensor import create_sensor
from murata_soil_sensor.base import signed_12bit
from murata_soil_sensor.measurement import Measurement, SensorInfo, battery_voltage


def test_field_names_and_csv_row():
    names = Measurement.field_names()
    assert "temperature_c" in names
    assert len(names) == 12

    m = Measurement(temperature_c=1.5, vwc=20.0)
    row = m.csv_row()
    # None fields become empty strings; provided values are kept.
    assert row[names.index("temperature_c")] == 1.5
    assert row[names.index("vwc")] == 20.0
    assert row[names.index("ec_pore")] == ""


def test_battery_voltage_uses_the_product_divider():
    # SLT5008 divides by 0.18, the other products by 0.5.
    assert battery_voltage(2048, 0.18) == pytest.approx(9.167, abs=0.001)
    assert battery_voltage(2048, 0.5) == pytest.approx(3.3, abs=0.001)
    assert battery_voltage(None, 0.5) is None


def test_as_dict_roundtrip():
    m = Measurement(dds=10, adc_ec=20)
    assert m.as_dict()["dds"] == 10
    assert m.as_dict()["adc_ec"] == 20


def test_sensor_info():
    info = SensorInfo(product="SLT5009", firmware_version="1.2.3", serial_number=42)
    assert info.product == "SLT5009"
    assert info.serial_number == 42


def test_signed_12bit():
    assert signed_12bit(0x0000) == 0
    assert signed_12bit(0x07FF) == 2047
    assert signed_12bit(0x0800) == -2048
    assert signed_12bit(0x0FFF) == -1
    # Upper bits above bit 11 are ignored.
    assert signed_12bit(0xF010) == 0x010


@pytest.mark.parametrize(
    ("product", "firmware", "supported"),
    [
        ("SLT5005", "1.6.3", False),
        ("SLT5005", "1.7.5", True),
        ("SLT5005", "1.7.6", True),
        ("SLT5006", "1.6.3", False),
        ("SLT5006", "1.7.5", True),
        ("SLT5006", "1.7.6", True),
        ("SLT5007", "1.0.0", False),
        ("SLT5007", "1.0.1", False),
        ("SLT5007", "1.1.1", True),
        ("SLT5007", "1.1.2", True),
        ("SLT5008", "1.4.0", False),
        ("SLT5008", "1.7.0", True),
        ("SLT5009", "1.0.2", False),
        ("SLT5009", "1.1.0", False),
        ("SLT5009", "1.2.1", True),
        ("SLT5009", "1.2.2", True),
    ],
)
def test_ec_pore_coco_support_for_every_market_firmware(
    product, firmware, supported
):
    assert create_sensor(product).supports_ec_pore_coco(firmware) is supported
