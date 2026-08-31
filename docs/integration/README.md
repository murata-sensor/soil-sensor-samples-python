# Integration guide / 統合ガイド

How to use `murata_soil_sensor` inside your own application, and what to keep in
mind when porting the protocol to another platform or language.

自社アプリケーションへ `murata_soil_sensor` を組み込む際の使い方と、他プラット
フォーム／他言語へ移植する際の要点をまとめます。

## 1. Basic usage

```python
from murata_soil_sensor import create_sensor

sensor = create_sensor("SLT5009", slave=1)   # SLT5006/5007/5008 also supported
with sensor.open("COM3") as transport:        # /dev/ttyUSB0 on Linux/macOS
    info = sensor.read_info(transport)
    data = sensor.read_measurement(transport)

print(info.firmware_version, info.serial_number)
print(data.temperature_c, data.vwc, data.ec_bulk)
```

`open()` returns a `SerialTransport` (a context manager). If you already have a
byte stream, you can implement the small `Transport` protocol yourself and pass
it to `read_info` / `read_measurement` directly — this is what the unit tests do.
Custom transports must implement `read_until(expected, *, timeout=None)` and
honor the optional per-call upper bound; SLT5008 uses it to avoid waiting past
the sensor-declared `ttt` measurement time.

### Firmware-dependent `ec_pore_coco`

This table records the production-firmware boundary for the
`ec_pore_coco` field only. It does not, by itself, declare every other
high-level API operation supported on every listed version.

| Product | Production firmware without `ec_pore_coco` | Production firmware with `ec_pore_coco` |
|---------|--------------------------------------------|-----------------------------------------|
| SLT5005 / SLT5006 | 1.6.3 | 1.7.5, 1.7.6 |
| SLT5007 | 1.0.0, 1.0.1 | 1.1.1, 1.1.2 |
| SLT5008 | 1.4.0 | 1.7.0 |
| SLT5009 | 1.0.2, 1.1.0 | 1.2.1, 1.2.2 |

For SLT5005/5006/5007/5009, the protocol handlers keep reading the complete
response for compatibility. The example applications call
`sensor.supports_ec_pore_coco(info.firmware_version)`
before user-visible output: unsupported or unidentified firmware gets an empty
CSV field, no GUI value/plot, and no `ec_pore_coco_dsm` upload property. Direct
library integrations should make the same capability check before using
`Measurement.ec_pore_coco`.

For SLT5008 this table describes only the `ec_pore_coco` feature boundary. The
full high-level D0/D1/D2 measurement API still targets firmware 1.7.0 or later;
the table does not extend that API to firmware 1.4.0.

## 2. Error handling

All errors derive from `SensorError`:

```python
from murata_soil_sensor import (
    ProtocolError,
    SensorDeviceError,
    SensorError,
    SensorTimeoutError,
)

try:
    data = sensor.read_measurement(transport)
except SensorTimeoutError:
    ...  # no (complete) response within the timeout
except SensorDeviceError as exc:
    print(exc.code, exc.description)  # CRC-valid error/exception from the sensor
except ProtocolError:
    ...  # CRC/function/address/length mismatch or unparseable response
except SensorError:
    ...  # anything else from the library
```

## 3. Timeouts and retries

Set the serial read timeout when creating the sensor:

```python
sensor = create_sensor("SLT5009", slave=1, timeout=1.0)
```

A minimal retry wrapper:

```python
import time
from murata_soil_sensor import SensorError

def read_with_retry(sensor, transport, attempts=3, delay=0.5):
    for attempt in range(attempts):
        try:
            return sensor.read_measurement(transport)
        except SensorError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
```

## 4. Multi-sensor buses

RS-485 (SLT5007/SLT5009) and SDI-12 (SLT5008) allow several sensors on one line,
each with its own address. Create one handler per address and share the transport:

```python
transport = create_sensor("SLT5009").open("COM3")
for slave in (1, 2, 3):
    sensor = create_sensor("SLT5009", slave=slave)
    print(slave, sensor.read_measurement(transport).vwc)
```

Address parameter per product:

| Product | Parameter | Range |
|---------|-----------|-------|
| SLT5007 | `sensor_number` | 0–31 |
| SLT5008 | `address` | `0`-`9` |
| SLT5009 | `slave` | 1–31 |

Use `set_address()` to change a sensor's address (not supported on SLT5005/5006).
`read_address()` verifies the configured address on SLT5007/5008/5009. The
`set_address.py` example first probes the requested address, checks a live
readback and serial identity, then prints a `verify_address.py` command. Perform
the probe with all bus devices powered, or with only the target connected. To
test retention, turn the sensor power source off without connecting or
disconnecting energized wiring, wait a few seconds, restore power, and run the
printed command.

The CLI examples support this directly: pass a comma-separated `--address`
(e.g. `--address 1,2,3`) to `read_measurement.py`, `continuous_log.py`, or
`gui_monitor.py` to read every sensor on the bus in one run.

For SLT5008, `read_measurement()` reads sensors one after
another (each `aM!` holds the bus). To measure several SLT5008 sensors at the
same time instead, use `read_concurrent()`:

```python
from murata_soil_sensor import read_concurrent
from murata_soil_sensor.slt5008 import Slt5008

sensors = [Slt5008(address=a) for a in "012"]
with sensors[0].open("COM3") as transport:
    for sensor, measurement in zip(sensors, read_concurrent(sensors, transport)):
        print(sensor.address, measurement.vwc)
```

`read_measurement.py`, `continuous_log.py` and `gui_monitor.py` all use
`read_concurrent()` automatically when given 2+ SLT5008 addresses. Note that
`aC!` sends no service request, so `read_concurrent()` waits out the conversion
time reported by the sensors (5 s on current SLT5008 firmware) before reading
the data. This is why measuring several SLT5008 sensors takes about as long as
measuring one.

SLT5008 CRC measurement is opt-in so existing applications keep their prior
non-CRC command flow by default:

```python
sensors = [Slt5008(address=a, use_crc=True) for a in "012"]
```

This selects `aMC!`/`aCC!` and verifies the three-character CRC independently
on `aD0!`, `aD1!`, and `aD2!`. The SLT5008 CRC initial value is `0x0000`.
The full D0/D1/D2 measurement API targets SLT5008 firmware 1.7.0 or later.

To keep one sensor's failure from discarding the others' data, split the two
phases and read each sensor in its own `try`:

```python
from murata_soil_sensor import start_concurrent

start_concurrent(sensors, transport)
for sensor in sensors:
    try:
        print(sensor.address, sensor.read_data(transport).vwc)
    except Exception as exc:
        print(f"{sensor.address}: {exc}")
```

SLT5009 can likewise start two or more devices together with a fixed MODBUS
broadcast and then read each addressed result:

```python
from murata_soil_sensor import read_broadcast_measurement

sensors = [create_sensor("SLT5009", slave=n) for n in (1, 2)]
measurements = read_broadcast_measurement(sensors, transport)
```

That convenience call is fail-fast. For continuous acquisition, poll every
listed sensor and preserve the responsive sensors' data:

```python
from murata_soil_sensor import start_broadcast_measurement

errors = start_broadcast_measurement(
    sensors, transport, continue_on_error=True
)
for sensor in sensors:
    if sensor.slave in errors:
        print(sensor.slave, errors[sensor.slave])
        continue
    try:
        print(sensor.slave, sensor.read_data(transport).vwc)
    except Exception as exc:
        print(sensor.slave, exc)
```

Broadcast has no acknowledgement and starts **every** SLT5009 on the physical
bus, even one omitted from the list. Check the supply's simultaneous current
capacity. The command-line examples require the explicit `--broadcast-start`
flag and do not expose generic broadcast register writes.

## 5. Threading

A `SerialTransport` is **not** safe to use from multiple threads at once. For a
responsive UI, run all reads in one background thread and hand results to the UI
thread via a queue (see [`examples/gui_monitor.py`](../../examples/gui_monitor.py)).
Do not call the same transport from both threads concurrently.

## 6. Porting to another language

The protocol logic is simple and portable. Key facts (full details in
[`docs/protocol/`](../protocol/)):

- SLT5005/5006/5007/5009 use CRC-16/MODBUS, init `0xFFFF`, polynomial `0xA001`.
- CRC byte order: **SLT5005/5006/5007 = high byte first**, **SLT5009 = low byte first**.
- SLT5008 CRC mode uses the same reflected polynomial with init `0x0000`, then
  encodes the result into three SDI-12 ASCII characters.
- Measurement data endianness: **SLT5006/5007 = little-endian**, **SLT5009 = big-endian**.
- Scalings: temperature = signed 12-bit × 0.0625 °C; EC × 0.001; VWC × 0.1.
- SLT5008 (SDI-12) values are ASCII and already scaled by the firmware.

SLT5008 identification also publishes `SensorInfo.sdi_version`, `.vendor`, and
`.model` in addition to the common firmware and serial fields.

The `murata_soil_sensor/crc16.py` and per-product modules are intentionally small
so they can be used as a reference when implementing the same protocol in C,
Arduino, or another environment.

## 7. Measurement units

| Field | Unit |
|-------|------|
| `temperature_c` | °C |
| `ec_bulk`, `ec_pore`, `ec_pore_coco` | dS/m |
| `vwc`, `vwc_rock`, `vwc_coco` | % volumetric water content |
| `dds`, `adc_ec`, `adc_permittivity`, `adc_battery` | raw counts |
