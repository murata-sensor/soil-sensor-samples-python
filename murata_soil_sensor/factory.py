"""Factory for creating a sensor handler from a product name."""

from __future__ import annotations

from .base import SoilSensor
from .slt5006 import Slt5006
from .slt5007 import Slt5007
from .slt5008 import Slt5008
from .slt5009 import Slt5009

__all__ = ["create_sensor", "SUPPORTED_PRODUCTS"]

# Products that share another product's protocol.
_ALIASES = {
    "SLT5005": "SLT5006",  # same firmware/protocol as SLT5006 (RS-232C interface)
}

_HANDLERS = {
    "SLT5006": Slt5006,
    "SLT5007": Slt5007,
    "SLT5008": Slt5008,
    "SLT5009": Slt5009,
}

SUPPORTED_PRODUCTS = ("SLT5005", "SLT5006", "SLT5007", "SLT5008", "SLT5009")


def create_sensor(product: str, **kwargs) -> SoilSensor:
    """Return a sensor handler for ``product`` (case-insensitive).

    Extra keyword arguments are passed to the handler constructor, e.g.
    ``create_sensor("SLT5009", slave=2)`` or ``create_sensor("SLT5007", sensor_number=1)``.
    ``SLT5005`` is handled by the SLT5006 handler, while keeping the requested
    product label.
    """
    requested = product.strip().upper()
    resolved = _ALIASES.get(requested, requested)
    handler_cls = _HANDLERS.get(resolved)
    if handler_cls is None:
        raise ValueError(
            f"unsupported product {product!r}; supported: {', '.join(SUPPORTED_PRODUCTS)}"
        )
    if requested in _ALIASES:
        kwargs.setdefault("product", requested)
    return handler_cls(**kwargs)
