# Wiring guide / 配線ガイド

Choose a USB-serial adapter that matches the sensor's electrical interface.
Verify the product number and supply voltage before applying power: SLT5008 uses
a different voltage range from the other products.

センサのインターフェースに合った USB シリアル変換器を選んでください。ピン配置・
電源範囲は各製品データシートを参照し、通電前に品番と電源電圧を確認してください。
SLT5008 とその他の品番では電源電圧が異なります。

> **Power must be off before connecting or disconnecting the sensor. Hot
> plugging is prohibited. / センサの接続・取り外しは必ず電源を切ってから行って
> ください。活線挿抜は禁止です。**

## Cable colors and unused wires / 線色と未使用線

| Color | SLT5005 / 5006 / 5007 / 5009 | SLT5008 |
|-------|---------------------------------|---------|
| RED | Supply, 3.0-6.0 V / 電源 3.0～6.0 V | Supply, 9.6-16.0 V / 電源 9.6～16.0 V |
| BLACK | Ground / GND | Ground / GND |
| WHITE | Active-high enable; low selects standby / Highで動作、Lowでスタンバイ | Not connected; leave floating / 未接続、フローティング |
| BLUE | SLT5005/6: sensor TX; SLT5007/9: Data- (inverting) | SDI-12 DATA |
| YELLOW | SLT5005/6: sensor RX; SLT5007/9: Data+ (non-inverting) | Not connected; leave floating / 未接続、フローティング |
| GREEN | Internal use; leave floating / 内部用、フローティング | Internal use; leave floating / 内部用、フローティング |
| ORANGE | Internal use; leave floating / 内部用、フローティング | Internal use; leave floating / 内部用、フローティング |
| GRAY / shield | Connect to GND (VSS) for stable communication / 安定通信のためGND接続推奨 | Connect to GND for stable communication / 安定通信のためGND接続推奨 |

Leave every unused wire electrically floating and insulate it so it cannot
short to another conductor. On SLT5005/5006/5007/5009, if the enable function
is not controlled by the host, connect **WHITE to RED**. Do not make that
connection on SLT5008.

未使用線はそれぞれ電気的にフローティングとし、他の線と短絡しないよう個別に絶縁
してください。SLT5005/5006/5007/5009 でイネーブルを制御しない場合に限り、
**WHITE と RED を接続**します。SLT5008 では接続しないでください。

## SLT5006 — UART (TTL)

- Use a USB-UART adapter at the sensor's logic level (see datasheet).
- Connect BLUE (sensor TX) to adapter RX, YELLOW (sensor RX) to adapter TX,
  BLACK to GND, and RED to a 3.0-6.0 V supply.
- Connect WHITE to RED unless the host actively controls enable/standby.
- 9600 bps, 8N1.

## SLT5005 — RS-232C

- Same protocol as SLT5006 but with RS-232C signal levels.
- Use a USB-RS232C adapter, not a TTL UART adapter.
- Connect BLUE (sensor TX) to adapter RX, YELLOW (sensor RX) to adapter TX,
  BLACK to ground, RED to a 3.0-6.0 V supply, and WHITE to RED unless enable is
  controlled separately.
- 9600 bps, 8N1.

## SLT5007 / SLT5009 — RS-485

- Use a half-duplex USB-RS485 adapter. Connect BLUE to Data- (inverting) and
  YELLOW to Data+ (non-inverting). If the adapter uses A/B labels, follow its
  documentation to map those labels to the stated polarity.
- Connect BLACK to supply ground, RED to a 3.0-6.0 V supply, and WHITE to RED
  unless enable is controlled separately.
- The sensors have no internal termination. Fit 120 ohm termination at the bus
  ends when required by the cable topology; do not place it at every sensor.
- Multiple sensors can share the bus; each has its own address.
- 9600 bps, 8N1.

## SLT5008 — SDI-12 via TBS03

Recommended TBS03 connection:

| SLT5008 wire | TBS03 terminal |
|--------------|----------------|
| RED | SDI-12 POWER (12 V from TBS03, within the sensor's 9.6-16.0 V range) |
| BLACK | GND |
| BLUE | SDI-12 DATA |
| GRAY / shield | SHIELD/GND (recommended) |

Leave WHITE, YELLOW, GREEN, and ORANGE floating and individually insulated.

- TBS03 virtual COM port: **19200 bps, 8 data bits, no parity, 1 stop bit, no
  flow control**.
- Native SDI-12 is 1200 bps, 7E1. TBS03 generates this line format together
  with break, mark, and bidirectional timing; do not configure the PC for 7E1.
- A TBS01A evaluation board can also handle the data conversion. Match
  `--baud` to its jumper selection (factory default 9600); its host side is
  always 8N1. **Do not power SLT5008 from the board's USB-derived 5 V sensor
  output.** Use an external 9.6-16.0 V supply (normally 12 V) for the sensor and
  connect the supply, sensor, and board grounds together.
- When powered only from USB, the TBS03 12 V sensor output is limited to
  120 mA total. With a suitable 10.5-16 V external input connected as specified
  in the TBS03 manual, the sensor output is limited to 250 mA total. Include
  every connected sensor's active and inrush current; if the applicable limit
  can be exceeded, use a separately rated sensor supply.

TBS03 推奨配線は RED→SDI-12 POWER、BLACK→GND、BLUE→SDI-12 DATA、
GRAY/シールド→SHIELD/GNDです。WHITE、YELLOW、GREEN、ORANGE は個別に
絶縁してフローティングにします。PC 側は 19200 bps、8N1、フロー制御なしです。
SDI-12 側の 1200 bps、7E1、break/mark、送受信方向は TBS03 が処理します。
TBS01A 評価ボード使用時は、USB 由来の 5 V 出力をセンサ電源に使用せず、外部
9.6～16.0 V（通常 12 V）をセンサへ供給して GND を共通化してください。
TBS03 を USB のみで給電する場合、12 V センサ出力は合計 120 mA までです。
TBS03 の取扱説明書に従って 10.5～16 V の外部入力を使用する場合、センサ出力は
合計 250 mA までです。接続する全センサの動作電流と突入電流を合算し、該当する
上限を超える可能性がある場合は、容量を満たす別電源を使用してください。

## Simultaneous measurement and power / 同時測定時の電源

SDI-12 concurrent measurement (`aC!` / `aCC!`) and an SLT5009 broadcast
measurement start can cause several sensors to become active at nearly the
same time. Size the power supply, wiring, and converter for the **sum** of the
active and inrush currents, with adequate margin. Broadcast must not be used to
change addresses because every connected SLT5009 would receive the write.

SDI-12同時計測（`aC!` / `aCC!`）やSLT5009のブロードキャスト測定開始では、
複数台がほぼ同時に動作状態になります。電源・配線・変換器は、全台分の動作電流と
突入電流の合計に余裕を持たせて選定してください。アドレス変更にはブロードキャスト
を使用しないでください。接続中の全SLT5009が書き込みを受けるためです。

## References / 参照資料

- The applicable Murata soil-sensor datasheet (power, cable, and interface ratings)
- [Tekbox TBS03 SDI-12/USB converter manual](https://www.tekbox.com/product/TBS03_SDI-12_USBConverterManual.pdf)
- [Tekbox TBS01A evaluation-board manual](https://www.tekbox.com/product/TBS01A_EVB_Manual.pdf)
