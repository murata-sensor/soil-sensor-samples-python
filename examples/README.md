# Examples / サンプル

Command-line examples and an optional GUI. These scripts are implemented on top
of the `murata_soil_sensor` library.

以下のスクリプトは `murata_soil_sensor` ライブラリを用いた CLI／GUI サンプルです。

| Script | Purpose |
|--------|---------|
| `list_ports.py` | List available serial (COM) ports |
| `read_measurement.py` | Read measurements (add `--all` for advanced diagnostic DDS/ADC counts) |
| `read_info.py` | Read firmware version / serial number |
| `set_address.py` | Change the sensor address |
| `verify_address.py` | Verify address retention and serial identity after a power cycle |
| `scan_addresses.py` | Find which addresses are in use (SLT5007/5008/5009) |
| `continuous_log.py` | Continuous measurement with CSV logging |
| `gui_monitor.py` | Simple real-time graph (optional matplotlib) |

Connection arguments shared by the sensor examples:

```
--product   SLT5005 | SLT5006 | SLT5007 | SLT5008 | SLT5009
--port      Serial port (e.g. COM3, /dev/ttyUSB0)
--address   Sensor address / slave number (SLT5007: 0-31, SLT5009: 1-31, SLT5008: 0-9)
--baud      Override the default baud rate (mainly the SLT5008 converter)
--timeout   Serial read timeout in seconds
```

Measurement commands (`read_measurement.py` and `continuous_log.py`) also
accept:

```
--sdi-crc   SLT5008: use MC/CC and verify every D-response CRC
--broadcast-start  SLT5009: start 2+ sensors together by MODBUS broadcast
```

`read_measurement.py` also accepts `--all` to include the advanced diagnostic
DDS/ADC counts.
`gui_monitor.py` accepts `--sdi-crc` and `--broadcast-start` as command-line
preselections and provides the same choices as GUI checkboxes. The GUI also
provides baud-override and timeout fields for matching the host-side settings
specified by the USB-SDI-12 converter.

### Multiple sensors on one bus

SLT5007, SLT5008, and SLT5009 support several sensors on a single RS-485/SDI-12
bus. Pass a comma-separated `--address` to `read_measurement.py`,
`continuous_log.py`, or `gui_monitor.py` to read them all in one run, e.g.:

```
python examples/read_measurement.py --product SLT5009 --port COM3 --address 1,2,3
```

`continuous_log.py` and `gui_monitor.py` add an `address` column to the CSV
output when more than one address is given; `gui_monitor.py` plots one line per
sensor.

Both also record `firmware` and `serial` columns so a log identifies the sensor
it came from. `continuous_log.py` prints the identification to stderr, keeping
stdout a valid CSV stream.

`ec_pore_coco` is firmware-dependent. On firmware that does not support it (or
when identification fails), `continuous_log.py` and the GUI keep the fixed CSV
column but leave that row's value empty; the GUI does not plot it, and upload
payloads omit it. See the complete production-firmware table in the
[integration guide](../docs/integration/README.md#firmware-dependent-ec_pore_coco).

Two or more SLT5008s use SDI-12 concurrent measurement automatically. Add
`--sdi-crc` to select `aCC!` (or `aMC!` for one sensor) and validate `aD0!`,
`aD1!`, and `aD2!` with the SLT5008 CRC initial value `0x0000`.
The full SLT5008 measurement layout requires firmware 1.7.0 or later.

SLT5009 measurements remain sequential by default. Add `--broadcast-start` to
start two or more with the fixed MODBUS broadcast `SNSR_CTRL=MEASRUN`, then
read each addressed sensor. A broadcast has no acknowledgement and starts
**every** SLT5009 physically present on the bus, including sensors not listed
in `--address`; first confirm that the supply can handle their simultaneous
measurement-current peak. During continuous logging and GUI monitoring, a
listed sensor that fails its completion poll is skipped for that cycle while
the remaining sensors are still read.

### Finding the addresses on a bus

`scan_addresses.py` reports which addresses answer:

```
python examples/scan_addresses.py --product SLT5009 --port COM3
```

SLT5008 is asked directly with the SDI-12 address query (`?!`). That command is
answered by every sensor at once, so when several are connected the script falls
back to probing addresses `0`-`9` with `a!`. SLT5007 and SLT5009 have no address
query, so their whole range (0-31 and 1-31) is probed.

SLT5007 can also reset its sensor number to 0:

```
python examples/scan_addresses.py --product SLT5007 --port COM3 --clear-address
```

Every SLT5007 on the bus acts on that command and none of them acknowledges it,
so connect a single sensor before running it.

SLT5007 のセンサ番号が不明になった場合は `--clear-address` で 0 に戻せます。
バス上の全 SLT5007 が反応するため、必ず 1 台のみ接続して実行してください。

### Changing and retaining an address

Before changing an address, keep all devices on the bus powered so the new
address can be checked, or connect only the target sensor. `set_address.py`
probes the new address before writing: an answering or malformed device causes
the operation to stop, and only a timeout is treated as unused. It also verifies
the live register/acknowledgement and reads the serial number before and after
the change. It prints a follow-up command such as:

```text
python examples/verify_address.py --product SLT5009 --port COM3 \
    --address 2 --expected-serial 24107928
```

After `set_address.py` succeeds, turn the sensor power source off without
connecting or disconnecting energized wiring. Wait a few seconds, restore
power, and run that exact command. Passing requires both the configured address
and the physical sensor's serial number to match. This procedure works for
SLT5007, SLT5008, and SLT5009.

アドレス変更前は、バス上の全機器を通電して新アドレスの応答を確認するか、対象
センサ1台だけを接続してください。変更後は通電中の配線を抜き差しせず、電源供給元
をOFFにします。数秒待って電源を再投入し、表示された確認コマンドを実行します。

### Uploading measurements

`continuous_log.py` can also POST each measurement to a Google Apps Script web
app that appends it to a Google Sheet or another data store.

```
--upload-url      Web app URL (default: $SOIL_UPLOAD_URL)
--upload-timeout  Seconds to wait for the web app (default: 10)
```

The shared secret is read from `$SOIL_UPLOAD_TOKEN` only, never from the command
line. Set it with the hidden-input steps in the top-level README and remove the
environment variable after use. Uploading happens once per `--interval`, so
pick an interval of a few minutes rather than seconds. Failures are printed to
stderr and logging continues, so the CSV remains the complete record.

The request is an HTTPS `POST` with `Content-Type: application/json` and this
shape (fields whose measurements are unavailable are omitted):

```json
{
  "token": "shared secret",
  "rows": [
    {
      "ts": "2026-09-03T12:34:56+09:00",
      "serialNumber": "24107928",
      "battery_v": 12.1,
      "temperature_c": 24.5,
      "vwc_pct": 31.2,
      "vwc_coco_pct": 30.8,
      "vwc_rock_pct": 18.4,
      "ec_bulk_dsm": 0.42,
      "ec_pore_dsm": 1.11,
      "ec_pore_coco_dsm": 1.08
    }
  ]
}
```

The receiver must return a JSON object containing `{"ok": true}`. Treat the
token and sensor serial numbers as sensitive data, restrict access to the
receiver and sheet, and do not log the token.

CSV output refuses to replace an existing file by default. Pass `--overwrite`
only when replacing that file is intentional. The GUI likewise reports an
error when its CSV path already exists; choose a new path before starting.
