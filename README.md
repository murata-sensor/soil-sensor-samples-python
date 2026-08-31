# soil-sensor-samples-python

Sample Python code for communicating with **Murata soil sensors** from a PC
(Windows / Linux / macOS / Raspberry Pi).

> 日本語版は下部にあります。 / Japanese version is at the bottom.

---

## English

### Overview

This repository provides ready-to-use Python samples that let you talk to Murata
soil sensors over a serial connection. The goal is to reduce customer support
effort and make it easy to evaluate Murata soil sensors in your own system.

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
| SLT5008 | SDI-12 (via TBS03) | SDI-12 (ASCII) | Full measurement API targets FW 1.7.0+; TBS03 PC side: 19200 bps, 8N1 |
| SLT5009 | RS-485 | MODBUS RTU | Multi-sensor addressing |

See [docs/protocol/](docs/protocol/) for wire-protocol details,
[docs/wiring/](docs/wiring/) for wiring, and
[docs/integration/](docs/integration/) for embedding the library in your app.

The recommended PC adapter for SLT5008 is the Tekbox TBS03. Its virtual COM
port uses 19200 bps, 8 data bits, no parity, 1 stop bit, and no flow control.
A TBS01A evaluation board can also be used for data conversion at its
jumper-selected baud rate; its host-side format is likewise 8N1. Its
USB-derived 5 V sensor supply is outside the SLT5008 rating, so power the sensor
from an external 9.6-16.0 V supply (normally 12 V) and share ground. Do not
configure the PC port for native SDI-12 (1200 bps, 7E1), because the converter
generates that side.

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

# Read the latest measurement (add --all for raw DDS/ADC values)
python examples/read_measurement.py --product SLT5009 --port COM3 --address 1

# Read sensor information
python examples/read_info.py --product SLT5006 --port /dev/ttyUSB0

# Log continuously to CSV
python examples/continuous_log.py --product SLT5007 --port COM3 --interval 10 --out data.csv

# Simple real-time graph (optional matplotlib)
python examples/gui_monitor.py --product SLT5009 --port COM3
```

### Sending the data to a dashboard (optional)

`continuous_log.py` can POST every measurement to a Google Apps Script web app,
which appends it to a Google Sheet. This is the data path used by
**soil-sensor-data-monitoring**, a companion project that visualizes the sheet
in a browser.

```bash
export SOIL_UPLOAD_TOKEN="<shared secret>"   # PowerShell: $env:SOIL_UPLOAD_TOKEN = "..."
python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2 \
    --interval 300 --out data.csv \
    --upload-url https://script.google.com/macros/s/<deployment-id>/exec
```

- The upload happens once per measurement interval, in the same batch as the CSV row.
- The URL may also come from `SOIL_UPLOAD_URL`. The shared secret is read from
  `SOIL_UPLOAD_TOKEN` only, so it never appears in the shell history.
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
シリアル通信で操作するための Python サンプルコード集です。顧客サポート負荷の
低減と、ムラタ土壌センサの評価容易化を目的としています。

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
2. **組み込み参考コード** — 顧客が自社システムに土壌センサを組み込む際に、読んで・
   コピーして・流用できる、きれいで十分に文書化されたリファレンス実装。プロトコル
   ロジックは他言語（例: C / Arduino）へも移植しやすい構造を志向します。

### 対応センサ

| 品番 | インターフェース | プロトコル | 備考 |
|------|------------------|------------|------|
| SLT5005 | RS-232C | ムラタ独自バイナリ | SLT5006 とファーム/プロトコル同一。RS-232C レベル |
| SLT5006 | UART (TTL) | ムラタ独自バイナリ | 単体センサ |
| SLT5007 | RS-485 | ムラタ独自バイナリ | マルチセンサ（アドレス指定） |
| SLT5008 | SDI-12（TBS03 経由） | SDI-12（ASCII） | 全測定APIはFW 1.7.0以降が対象。TBS03のPC側は19200 bps、8N1 |
| SLT5009 | RS-485 | MODBUS RTU | マルチセンサ（アドレス指定） |

プロトコル詳細は [docs/protocol/](docs/protocol/)、配線は [docs/wiring/](docs/wiring/)、自社アプリへの組み込みは [docs/integration/](docs/integration/) を参照してください。

SLT5008 の推奨 PC 変換器は Tekbox TBS03 です。仮想 COM ポートは
19200 bps、8 データビット、パリティなし、1 ストップビット、フロー制御なしです。
TBS01A 評価ボードもジャンパで選択したボーレート（データ形式は同じく 8N1）で
データ変換に使用できます。ただし USB 由来のセンサ電源は 5 V で SLT5008 の定格外
です。センサには外部 9.6～16.0 V（通常 12 V）を供給し、GND を共通化してください。
SDI-12 本来の 1200 bps、7E1 は変換器側が生成するため、PC 側には設定しません。

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

# 最新の測定値を読み出す（--all で生の DDS/ADC 値も表示）
python examples/read_measurement.py --product SLT5009 --port COM3 --address 1

# センサ情報を読み出す
python examples/read_info.py --product SLT5006 --port /dev/ttyUSB0

# CSV へ連続ログ
python examples/continuous_log.py --product SLT5007 --port COM3 --interval 10 --out data.csv

# 簡易リアルタイムグラフ（任意の matplotlib）
python examples/gui_monitor.py --product SLT5009 --port COM3
```

### 取得データをダッシュボードへ送る（任意）

`continuous_log.py` は、測定するたびに Google Apps Script の Web アプリへ POST
して Google スプレッドシートに追記できます。これは、シートをブラウザで可視化する
関連プロジェクト **soil-sensor-data-monitoring** のデータ経路です。

```powershell
$env:SOIL_UPLOAD_TOKEN = "<共有シークレット>"
python examples/continuous_log.py --product SLT5009 --port COM3 --address 1,2 `
    --interval 300 --out data.csv `
    --upload-url https://script.google.com/macros/s/<deployment-id>/exec
```

- 送信は測定間隔ごとに 1 回、CSV への 1 行と同じタイミングで行われます。
- URL は `SOIL_UPLOAD_URL` でも指定できます。共有シークレットは
  `SOIL_UPLOAD_TOKEN` からのみ読むので、コマンド履歴に残りません。
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
