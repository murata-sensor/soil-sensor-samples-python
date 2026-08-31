"""SLT5006 (UART) and SLT5005 (RS-232C) — Murata binary protocol.

SLT5005 shares the SLT5006 firmware and protocol; only the electrical interface
differs (RS-232C vs UART). Use ``product="SLT5005"`` to label an SLT5005.

A single sensor is addressed; :meth:`set_address` is therefore not supported.
"""

from __future__ import annotations

from ._binary import MurataBinarySensor
from .base import SensorError, Transport

__all__ = ["Slt5006"]


class Slt5006(MurataBinarySensor):
    """Handler for SLT5006 (and SLT5005)."""

    #: ec_pore_coco is available on SLT5005/5006 firmware v1.7.5 and later.
    ec_pore_coco_min_version = "1.7.5"

    def __init__(self, product: str = "SLT5006", **kwargs):
        super().__init__(sensor_number=0, **kwargs)
        self.product = product

    def set_address(self, transport: Transport, new_address: int | str) -> None:
        raise SensorError(
            "SLT5006/SLT5005 is a single-sensor bus; address change is not supported"
        )
