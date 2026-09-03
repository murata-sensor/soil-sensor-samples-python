# Protocol specifications / プロトコル仕様

This directory documents the wire-protocol details needed to use these samples
with each supported Murata soil sensor. Refer to the current product datasheet
for the complete register map and electrical details.

各対応品番について、本サンプルの利用に必要な通信プロトコルをまとめます。完全な
レジスタマップや電気的仕様は、最新の製品データシートを参照してください。

| Product | Interface | Protocol | Baud (PC side) | Parity | Doc |
|---------|-----------|----------|----------------|--------|-----|
| SLT5005 | RS-232C | Murata binary | 9600 | None | [slt5006.md](slt5006.md) (same as SLT5006) |
| SLT5006 | UART (TTL) | Murata binary | 9600 | None | [slt5006.md](slt5006.md) |
| SLT5007 | RS-485 | Murata binary (multi-sensor) | 9600 | None | [slt5007.md](slt5007.md) |
| SLT5008 | SDI-12 via USB converter | SDI-12 (ASCII) | Converter-specific; TBS03: 19200 | Converter-specific; TBS03: 8N1 | [slt5008.md](slt5008.md) |
| SLT5009 | RS-485 | MODBUS RTU | 9600 | None | [slt5009.md](slt5009.md) |

The table shows the **PC side**. Murata has verified SLT5008 operation with
TBS03, which converts 19200/8N1 to the native SDI-12 line format. Other
general-purpose USB-SDI-12 converters are expected to work when their serial
command framing is compatible, but have not been verified by Murata; use the
PC-side settings specified by the converter. See [slt5008.md](slt5008.md).

表は **PC 側**の設定です。ムラタでは、19200/8N1をSDI-12へ変換するTBS03で
SLT5008の動作を確認しています。その他の一般的なUSB-SDI-12変換器も、シリアル
コマンドのフレーミングに互換性があれば動作が見込まれますが、ムラタでは未確認です。
PC側は各変換器の指定に従って設定してください。詳細は
[slt5008.md](slt5008.md)を参照してください。

## CRC-16 variants / CRC-16 の品種差

All products below use the reflected polynomial `0xA001`, but **SLT5008 has a
different initial value and wire encoding**. Do not use one hard-coded setting
for every product.

以下はすべて反転多項式 `0xA001` を使用しますが、**SLT5008 は初期値と伝送形式が
異なります**。全品種に同じ固定設定を使用しないでください。

| Product | Initial value | CRC input and wire representation |
|---------|---------------|-----------------------------------|
| SLT5005 / SLT5006 / SLT5007 | `0xFFFF` | Binary frame; see each product document for byte order |
| SLT5009 | `0xFFFF` | MODBUS RTU frame; low CRC byte first |
| SLT5008 | `0x0000` | For `aMC!` / `aCC!`, calculate over ASCII from the response address through the last data character, then append the CRC as three encoded ASCII characters before `<CR><LF>` |

```python
def crc16_a001(data: bytes, initial: int = 0xFFFF) -> int:
    crc = initial
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc
```

Use `initial=0x0000` for SLT5008 SDI-12 CRC responses and `0xFFFF` for the
other products. See [slt5008.md](slt5008.md) for the three-character encoding.
