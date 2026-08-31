"""List the available serial (COM) ports on this computer.

Useful for finding which port your USB-serial adapter / sensor is on.

Example:
    python examples/list_ports.py
"""

from __future__ import annotations


def main() -> int:
    try:
        from serial.tools import list_ports
    except ImportError:
        print("pyserial is required. Install it with: pip install -r requirements.txt")
        return 1

    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return 0

    for port in ports:
        description = ""
        if port.description and port.description != "n/a":
            description = f"  ({port.description})"
        print(f"{port.device}{description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
