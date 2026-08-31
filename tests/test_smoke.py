"""Smoke test: the package imports and exposes a version string.

This keeps CI green during the scaffolding phase before the protocol handlers
are implemented.
"""

import murata_soil_sensor


def test_version_is_nonempty_string():
    assert isinstance(murata_soil_sensor.__version__, str)
    assert murata_soil_sensor.__version__
