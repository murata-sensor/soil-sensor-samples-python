"""Factory tests: product resolution, aliases, and kwargs."""

import pytest

from murata_soil_sensor import create_sensor
from murata_soil_sensor.slt5006 import Slt5006
from murata_soil_sensor.slt5009 import Slt5009


def test_slt5005_uses_slt5006_handler_with_label():
    sensor = create_sensor("slt5005")
    assert isinstance(sensor, Slt5006)
    assert sensor.product == "SLT5005"


def test_kwargs_passed_through():
    sensor = create_sensor("SLT5009", slave=3)
    assert isinstance(sensor, Slt5009)
    assert sensor.slave == 3


def test_unknown_product_raises():
    with pytest.raises(ValueError):
        create_sensor("SLT9999")


def test_slt5008_baudrate_override():
    from murata_soil_sensor.slt5008 import Slt5008

    sensor = create_sensor("SLT5008", baudrate=9600)
    assert isinstance(sensor, Slt5008)
    assert sensor.serial_config.baudrate == 9600
    assert sensor.serial_config.bytesize == 8
    assert sensor.serial_config.parity == "N"
    assert sensor.serial_config.stopbits == 1
