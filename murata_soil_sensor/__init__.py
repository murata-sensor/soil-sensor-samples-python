"""Murata soil sensor communication library (samples).

Supports SLT5005 / SLT5006 / SLT5007 / SLT5008 / SLT5009.

Quick start::

    from murata_soil_sensor import create_sensor

    sensor = create_sensor("SLT5009", slave=1)
    with sensor.open("COM3") as transport:
        info = sensor.read_info(transport)
        data = sensor.read_measurement(transport)
        print(info, data)

See ``docs/protocol/`` for the wire-protocol specifications.
"""

from __future__ import annotations

from .base import (
    ProtocolError,
    SensorDeviceError,
    SensorError,
    SensorTimeoutError,
    SerialConfig,
    SerialTransport,
    SoilSensor,
    Transport,
)
from .crc16 import check_sdi12_crc, crc16_modbus, crc16_sdi12, encode_sdi12_crc
from .factory import SUPPORTED_PRODUCTS, create_sensor
from .measurement import ADVANCED_FIELDS, FIELD_UNITS, Measurement, SensorInfo
from .slt5006 import Slt5006
from .slt5007 import Slt5007
from .slt5008 import Slt5008, read_concurrent, start_concurrent
from .slt5009 import Slt5009, read_broadcast_measurement, start_broadcast_measurement

__version__ = "0.1.1"

__all__ = [
    "__version__",
    "create_sensor",
    "SUPPORTED_PRODUCTS",
    "Slt5006",
    "Slt5007",
    "Slt5008",
    "read_concurrent",
    "start_concurrent",
    "Slt5009",
    "read_broadcast_measurement",
    "start_broadcast_measurement",
    "SoilSensor",
    "SerialConfig",
    "SerialTransport",
    "Transport",
    "Measurement",
    "SensorInfo",
    "FIELD_UNITS",
    "ADVANCED_FIELDS",
    "SensorError",
    "SensorTimeoutError",
    "ProtocolError",
    "SensorDeviceError",
    "crc16_modbus",
    "crc16_sdi12",
    "encode_sdi12_crc",
    "check_sdi12_crc",
]
