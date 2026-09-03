# soil-sensor-samples-python

Sample Python code for communicating with **Murata soil sensors** from a PC
(Windows / Linux / macOS / Raspberry Pi).

> 日本語版は下部にあります。 / Japanese version is at the bottom.

---

## English

### Overview

This repository provides ready-to-use Python samples for communicating with
Murata soil sensors over a serial connection. You can use them to evaluate a
sensor and as a reference when integrating one into an application.

> **Safety:** These samples communicate with physical hardware and can change
> persistent settings such as sensor addresses. Turn off power before changing
> wiring, use only the rated power supply and interface, and follow the product
> datasheet and [wiring guide](docs/wiring/README.md). Validate the complete
> behavior in a safe evaluation environment before production use. The software
> is provided "as is"; see the [Disclaimer](#disclaimer) and [LICENSE](LICENSE).

It is organized in three layers:

- **Library** (`murata_soil_sensor/`) — reusable, UI-independent protocol handlers.
- **CLI examples** (`examples/`) — small command-line scripts for common tasks.
- **Simple GUI** — an optional real-time graph for continuous measurement.

This code has two intended uses:

1. **Operation check** — quickly verify that a sensor works on your PC.
2. **Integration reference** — a clean, well-documented reference implementation
   you can read, copy, and adapt when integrating a Murata soil sensor into your
   own system. The library is written to be portable in spirit, so the protocol
   logic can also be re-implemented in other languages (e.g. C / Arduino).

### Supported sensors

| Product | Interface | Protocol | Notes |
|---------|-----------|----------|-------|
| SLT5005 | RS-232C | Murata binary | Same firmware/protocol as SLT5006; RS-232C levels |
| SLT5006 | UART (TTL) | Murata binary | Single sensor |
| SLT5007 | RS-485 | Murata binary | Multi-sensor addressing |
| SLT5008 | SDI-12 (via USB converter) | SDI-12 (ASCII) | Full measurement API targets FW 1.7.0+; operation verified with TBS03 |
| SLT5009 | RS-485 | MODBUS RTU | Multi-sensor addressing |

See [docs/protocol/](docs/protocol/) for wire-protocol details,
[docs/wiring/](docs/wiring/) for wiring, and
[docs/integration/](docs/integration/) for embedding the library in your app.

SLT5008 can be used through a USB-SDI-12 converter that exposes a compatible
serial interface. Murata has verified operation with the Tekbox TBS03; other
general-purpose USB-SDI-12 converters are expected to work when they accept
CRLF-terminated SDI-12 ASCII commands and return CRLF-terminated responses, but
have not been verified by Murata. Follow the converter manual for its PC-side
serial settings and use `--baud` when needed. A converter with a proprietary
API or different framing may require an adapter-specific code change.

For the verified TBS03 configuration, the virtual COM port uses 19200 bps, 8
data bits, no parity, 1 stop bit, and no flow control. Configure the PC side
according to the converter rather than assuming the native SDI-12 line settings
of 1200 bps, 7E1.

### Features

- List available serial ports
- Read measurements (soil moisture / EC / temperature, etc.)
- Read sensor information (including SLT5008 SDI-12/vendor/model fields)
- Use CRC-protected SLT5008 measurement (`--sdi-crc`)
- Start multi-sensor measurements together (SDI-12 concurrent mode, or an
  explicit SLT5009 measurement-only broadcast)
- Change/read sensor addresses, scan a bus, and verify retention after a power cycle
- Continuous measurement with CSV logging
- Optional upload of each measurement to a Google Sheet (see below)
- Simple real-time GUI graph (optional; requires matplotlib)

### Requirements

- Python 3.9 or newer
- `pyserial` (core)
- `matplotlib` (only for the GUI graph; optional)
- On Linux/Raspberry Pi, Tk may be required for the GUI: `sudo apt install python3-tk`
- A USB-serial adapter appropriate for the sensor interface (see wiring guide)

### Installation

```bash
git clone https://github.com/murata-sensor/soil-sensor-samples-python.git
cd soil-sensor-samples-python
pip install -r requirements.txt        # core
pip install -r requirements-gui.txt    # optional: GUI graph
```

Or install directly as a package:

```bash
pip install git+https://github.com/murata-sensor/soil-sensor-samples-python.git
```

### Quick start

```bash
# List available serial ports (to find your sensor)
python examples/list_ports.py

# Read the latest measurement (add --all for advanced diagnostic DDS/ADC counts)
python examples/read_measurement.py --product SLT5009 --port COM3 --address 1

# Read sensor information
python examples/read_info.py --product SLT5006 --port /dev/ttyUSB0

# Log continuously to CSV
python examples/continuous_log.py --product SLT5007 --port COM3 --interval 10 --out data.csv

# Simple real-time graph (optional matplotlib)
python examples/gui_monitor.py --product SLT5009 --port COM3
```

### Sending the data to a dashboard (optional)

`continuous_log.py` can POST every measurement to a compatible Google Apps
Script web app that appends it to a Google Sheet. The receiver must implement
the JSON contract described in [examples/README.md](examples/README.md#uploading-measurements).

On Bash, enter the token without echoing it or placing it literally in the
command history:

```bash
read -rsp "SOIL_UPLOAD_TOKEN: " SOIL_UPLOAD_TOKEN; echo
export SOIL_UPLOAD_TOKEN
python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2 \
    --interval 300 --out data.csv \
    --upload-url https://script.google.com/macros/s/<deployment-id>/exec
unset SOIL_UPLOAD_TOKEN
```

- The upload happens once per measurement interval, in the same batch as the CSV row.
- The URL may also come from `SOIL_UPLOAD_URL`. The shared secret is accepted
  only through `SOIL_UPLOAD_TOKEN`, not as a command-line argument. Use a hidden
  prompt as above and remove the environment variable after use.
- An upload failure is reported and logging continues; the CSV stays complete.
- Sensors are identified by their serial number, so several sensors on one bus
  can share a single sheet.

Without `--upload-url` nothing is sent and no network access is used at all.

### Repository layout

```
murata_soil_sensor/   Reusable protocol library
examples/             CLI sample scripts + optional GUI
docs/protocol/        Wire-protocol specifications
docs/wiring/          Wiring guides per interface
docs/integration/     How to embed the library in your app
tests/                Unit tests
```

### License

BSD-3-Clause. See [LICENSE](LICENSE).

### Disclaimer

These samples are provided "as is", for evaluation and reference. Always validate
behavior against the relevant product datasheet before using in production.

---

## 日本語

### 概要

村田製作所の**土壌センサ**を PC（Windows / Linux / macOS / Raspberry Pi）から
シリアル通信で操作するための Python サンプルコード集です。センサの評価と、
アプリケーションへ組み込む際の参考実装として利用できます。

> **安全上の注意：** 本サンプルは実機と通信し、センサアドレスなどの不揮発設定を
> 変更できます。配線を変更する前に電源を切り、定格内の電源・インターフェースを
> 使用して、製品データシートと[配線ガイド](docs/wiring/README.md)に従ってください。
> 実運用前に安全な評価環境でシステム全体の動作を確認してください。本ソフトウェアは
> 「現状のまま」提供されます。[免責事項](#免責事項)および[LICENSE](LICENSE)も参照してください。

3 層構成です。

- **ライブラリ**（`murata_soil_sensor/`）— UI 非依存の再利用可能なプロトコル実装
- **CLI サンプル**（`examples/`）— よく使う操作の小さなコマンドラインスクリプト
- **簡易 GUI** — 連続測定のリアルタイムグラフ（任意）

本コードには 2 つの用途があります。

1. **動作確認** — PC でセンサが動くことを手軽に確認する。
2. **組み込み参考コード** — 土壌センサをアプリケーションに組み込む際に、読んで・
   コピーして・流用できるリファレンス実装。プロトコルロジックは他言語
   （例: C / Arduino）へも移植しやすい構造を志向します。

### 対応センサ

| 品番 | インターフェース | プロトコル | 備考 |
|------|------------------|------------|------|
| SLT5005 | RS-232C | ムラタ独自バイナリ | SLT5006 とファーム/プロトコル同一。RS-232C レベル |
| SLT5006 | UART (TTL) | ムラタ独自バイナリ | 単体センサ |
| SLT5007 | RS-485 | ムラタ独自バイナリ | マルチセンサ（アドレス指定） |
| SLT5008 | SDI-12（USB変換器経由） | SDI-12（ASCII） | 全測定APIはFW 1.7.0以降が対象。TBS03で動作確認済み |
| SLT5009 | RS-485 | MODBUS RTU | マルチセンサ（アドレス指定） |

プロトコル詳細は [docs/protocol/](docs/protocol/)、配線は [docs/wiring/](docs/wiring/)、アプリケーションへの組み込みは [docs/integration/](docs/integration/) を参照してください。

SLT5008 は、互換性のあるシリアルインターフェースを提供する一般的な
USB-SDI-12 変換器で利用できます。ムラタで動作確認済みの機種は Tekbox TBS03
です。その他の変換器も、CRLF終端のSDI-12 ASCIIコマンドを受け取り、CRLF終端の
応答を返す機種であれば動作が見込まれますが、ムラタでは未確認です。PC側の通信設定
は変換器の説明書に従い、必要に応じて `--baud` を指定してください。独自APIや異なる
フレーミングを使用する機種では、変換器に合わせたコード変更が必要な場合があります。

動作確認済みのTBS03では、仮想COMポートを19200 bps、8データビット、パリティなし、
1ストップビット、フロー制御なしに設定します。PC側にはSDI-12本来の1200 bps、
7E1を一律に設定せず、変換器の仕様に従ってください。

### 機能

- 利用可能なシリアルポートの一覧表示
- 測定値の読み出し（土壌水分 / EC / 温度 など）
- センサ情報の取得（SLT5008 の SDI-12 バージョン・ベンダ・モデルを含む）
- SLT5008 の CRC 付き測定（`--sdi-crc`）
- 複数センサの同時測定開始（SDI-12 同時計測、または明示指定した SLT5009
  測定開始専用ブロードキャスト）
- センサアドレスの変更・読出し・バス調査、および電源再投入後の保持確認
- 連続測定＋ CSV ログ保存
- 測定値の Google スプレッドシートへのアップロード（任意。下記参照）
- 簡易リアルタイムグラフ（任意。matplotlib が必要）

### 動作要件

- Python 3.9 以降
- `pyserial`（コア機能）
- `matplotlib`（GUI グラフ用。任意）
- Linux/Raspberry Pi で GUI を使う場合は Tk が必要な場合あり：`sudo apt install python3-tk`
- センサのインターフェースに適した USB シリアル変換器（配線ガイド参照）

### インストール

```bash
git clone https://github.com/murata-sensor/soil-sensor-samples-python.git
cd soil-sensor-samples-python
pip install -r requirements.txt        # コア
pip install -r requirements-gui.txt    # 任意：GUI グラフ
```

パッケージとして直接インストールも可能です。

```bash
pip install git+https://github.com/murata-sensor/soil-sensor-samples-python.git
```

### クイックスタート

```bash
# 利用可能なシリアルポートを一覧表示（センサのポートを探す）
python examples/list_ports.py

# 最新の測定値を読み出す（--all で高度な診断用 DDS/ADC カウント値も表示）
python examples/read_measurement.py --product SLT5009 --port COM3 --address 1

# センサ情報を読み出す
python examples/read_info.py --product SLT5006 --port /dev/ttyUSB0

# CSV へ連続ログ
python examples/continuous_log.py --product SLT5007 --port COM3 --interval 10 --out data.csv

# 簡易リアルタイムグラフ（任意の matplotlib）
python examples/gui_monitor.py --product SLT5009 --port COM3
```

### 取得データをダッシュボードへ送る（任意）

`continuous_log.py` は、測定するたびに互換性のある Google Apps Script の Web
アプリへ POST して Google スプレッドシートに追記できます。受信側は
[examples/README.md](examples/README.md#uploading-measurements) に記載した JSON 形式を実装する必要があります。

```powershell
$secureToken = Read-Host "SOIL_UPLOAD_TOKEN" -AsSecureString
$env:SOIL_UPLOAD_TOKEN = [System.Net.NetworkCredential]::new("", $secureToken).Password
python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2 `
    --interval 300 --out data.csv `
    --upload-url https://script.google.com/macros/s/<deployment-id>/exec
Remove-Item Env:SOIL_UPLOAD_TOKEN
```

- 送信は測定間隔ごとに 1 回、CSV への 1 行と同じタイミングで行われます。
- URL は `SOIL_UPLOAD_URL` でも指定できます。共有シークレットはコマンドライン
  引数ではなく `SOIL_UPLOAD_TOKEN` からのみ読みます。上記のように非表示入力し、
  使用後は環境変数を削除してください。
- 送信に失敗してもログは継続します（CSV は欠けません）。
- センサはシリアル番号で識別されるため、1 本のバス上の複数センサを 1 シートに
  まとめて記録できます。

`--upload-url` を指定しなければ何も送信されず、ネットワークにも一切アクセス
しません。

### ライセンス

BSD-3-Clause。[LICENSE](LICENSE) を参照してください。

### 免責事項

本サンプルは評価・参考用に「現状のまま」提供されます。実運用の前に、必ず該当
製品のデータシートで動作を確認してください。
