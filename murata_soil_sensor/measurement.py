"""Data structures for sensor information and measurements.

These are plain dataclasses with no I/O dependencies, so they are easy to read,
serialize (e.g. to CSV/JSON), and reuse when integrating a sensor into your own
application.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

__all__ = [
    "SensorInfo",
    "Measurement",
    "FIELD_UNITS",
    "ADVANCED_FIELDS",
    "battery_voltage",
]

# Engineering unit for each measurement field ("" = dimensionless / raw counts).
FIELD_UNITS = {
    "dds": "counts",
    "adc_ec": "counts",
    "adc_permittivity": "counts",
    "adc_battery": "counts",
    "battery_v": "V",
    "temperature_c": "degC",
    "ec_bulk": "dS/m",
    "vwc": "%",
    "vwc_rock": "%",
    "vwc_coco": "%",
    "ec_pore": "dS/m",
    "ec_pore_coco": "dS/m",
}

# Advanced diagnostic counts. The examples show them only when requested.
ADVANCED_FIELDS = frozenset({"dds", "adc_ec", "adc_permittivity", "adc_battery"})

# The battery ADC is 12 bit against a 3.3 V reference.
_ADC_REFERENCE_V = 3.3
_ADC_FULL_SCALE = 4096


def battery_voltage(adc_battery: int | None, divider: float) -> float | None:
    """Convert a raw battery ADC count to the supply voltage in volts.

    ``divider`` is the product's resistive divider ratio; see
    :attr:`~murata_soil_sensor.base.SoilSensor.battery_divider`.
    """
    if adc_battery is None:
        return None
    return round(adc_battery * _ADC_REFERENCE_V / _ADC_FULL_SCALE / divider, 3)


@dataclass
class SensorInfo:
    """Identification read from a sensor."""

    product: str
    firmware_version: str
    serial_number: int
    sdi_version: str | None = None
    vendor: str | None = None
    model: str | None = None


@dataclass
class Measurement:
    """A single set of measured values.

    Fields are ``None`` when a given product does not report that value. Units:

    * ``temperature_c``: degrees Celsius
    * ``ec_bulk`` / ``ec_pore`` / ``ec_pore_coco``: dS/m (bulk/pore EC)
    * ``vwc`` / ``vwc_rock`` / ``vwc_coco``: % volumetric water content
    * ``battery_v``: supply voltage in V, derived from ``adc_battery``
    * ``adc_*`` / ``dds``: raw ADC / oscillator counts (unscaled)
    """

    dds: int | None = None
    adc_ec: int | None = None
    adc_permittivity: int | None = None
    adc_battery: int | None = None
    battery_v: float | None = None
    temperature_c: float | None = None
    ec_bulk: float | None = None
    vwc: float | None = None
    vwc_rock: float | None = None
    vwc_coco: float | None = None
    ec_pore: float | None = None
    ec_pore_coco: float | None = None

    def as_dict(self) -> dict:
        """Return the measurement as an ordinary dictionary."""
        return asdict(self)

    @classmethod
    def field_names(cls) -> list:
        """Return the ordered field names (useful for CSV headers)."""
        return [f.name for f in fields(cls)]

    def csv_row(self) -> list:
        """Return values in :meth:`field_names` order (``None`` -> empty)."""
        return ["" if v is None else v for v in self.as_dict().values()]
