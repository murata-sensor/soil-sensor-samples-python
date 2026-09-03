"""Optional upload of measurements to a Google Apps Script (GAS) web app.

The receiver is expected to append the uploaded rows to a Google Sheet or other
data store. See ``examples/README.md`` for the JSON request contract.

Only the standard library is used, so no extra dependency is needed.

The web app URL may be given with ``--upload-url`` or the ``SOIL_UPLOAD_URL``
environment variable. The shared secret is read from ``SOIL_UPLOAD_TOKEN``
only and is never accepted as a command-line argument. Set it with the hidden
prompt described in the top-level README rather than typing it literally into
a shell command.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL_ENV = "SOIL_UPLOAD_URL"
TOKEN_ENV = "SOIL_UPLOAD_TOKEN"

#: Measurement attribute -> field name expected by the web app.
_FIELD_MAP = {
    "battery_v": "battery_v",
    "temperature_c": "temperature_c",
    "vwc": "vwc_pct",
    "vwc_coco": "vwc_coco_pct",
    "vwc_rock": "vwc_rock_pct",
    "ec_bulk": "ec_bulk_dsm",
    "ec_pore": "ec_pore_dsm",
    "ec_pore_coco": "ec_pore_coco_dsm",
}


def add_arguments(parser) -> None:
    """Add the upload options to an example's argument parser."""
    parser.add_argument(
        "--upload-url",
        help=f"Google Apps Script web app URL to POST each measurement to "
        f"(default: ${URL_ENV}). The shared secret is read from ${TOKEN_ENV}.",
    )
    parser.add_argument(
        "--upload-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the web app to answer.",
    )


def row_payload(timestamp: str, info, measurement) -> dict:
    """Build the JSON object for one measurement of one sensor."""
    row: dict = {"ts": timestamp}
    if info is not None:
        row["serialNumber"] = str(info.serial_number)
    for attribute, field in _FIELD_MAP.items():
        value = getattr(measurement, attribute, None)
        if value is not None:
            row[field] = value
    return row


class Uploader:
    """POSTs measurement rows to the GAS web app; failures are non-fatal."""

    def __init__(self, url: str, token: str, timeout: float = 10.0):
        if not url.lower().startswith("https://"):
            raise ValueError("--upload-url must be an https:// URL")
        self._url = url
        self._token = token
        self._timeout = timeout

    @classmethod
    def from_args(cls, args) -> Uploader | None:
        """Return an uploader when uploading was requested, otherwise ``None``."""
        url = getattr(args, "upload_url", None) or os.environ.get(URL_ENV)
        if not url:
            return None
        token = os.environ.get(TOKEN_ENV)
        if not token:
            raise ValueError(f"uploading needs the shared secret in ${TOKEN_ENV}")
        return cls(url, token, getattr(args, "upload_timeout", 10.0))

    def send(self, rows: list) -> bool:
        """Upload one batch of rows. Returns False (and warns) on failure."""
        if not rows:
            return True
        body = json.dumps({"token": self._token, "rows": rows}).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            print(f"error: upload: {exc}", file=sys.stderr)
            return False
        if not result.get("ok"):
            print(f"error: upload rejected: {result.get('error')}", file=sys.stderr)
            return False
        return True
