# Protocol specifications / プロトコル仕様

This directory documents the wire protocols used by each supported Murata soil
sensor. **Only customer-facing (public) information is included here.** Refer to
each product datasheet for the complete register map and electrical details.

各対応品番の通信プロトコルをまとめます。**顧客公開情報のみ**を記載します。完全な
レジスタマップや電気的仕様は各製品データシートを参照してください。

| Product | Interface | Protocol | Baud (PC side) | Parity | Doc |
|---------|-----------|----------|----------------|--------|-----|
| SLT5005 | RS-232C | Murata binary | 9600 | None | [slt5006.md](slt5006.md) (same as SLT5006) |
| SLT5006 | UART (TTL) | Murata binary | 9600 | None | [slt5006.md](slt5006.md) |
| SLT5007 | RS-485 | Murata binary (multi-sensor) | 9600 | None | [slt5007.md](slt5007.md) |
| SLT5008 | SDI-12 via TBS03 | SDI-12 (ASCII) | 19200 (TBS03) | None (8N1) | [slt5008.md](slt5008.md) |
| SLT5009 | RS-485 | MODBUS RTU | 9600 | None | [slt5009.md](slt5009.md) |

The table shows the **PC side**. On SLT5008, TBS03 converts 19200/8N1 to the
native SDI-12 line format, 1200/7E1. A TBS01A evaluation board instead uses its
jumper-selected baud rate and 8N1. Its USB-derived 5 V sensor output must not
power SLT5008; use an external 9.6-16.0 V sensor supply with common ground. See
[slt5008.md](slt5008.md).

表は **PC 側**の設定です。SLT5008 では TBS03 が 19200/8N1 を SDI-12 本来の
1200/7E1 に変換します。TBS01A 評価ボードではジャンパで選択したボーレートと
8N1 を使用します。ただし USB 由来の 5 V 出力は SLT5008 の電源に使用せず、GNDを
共通化した外部 9.6～16.0 V 電源を使用します。詳細は
[slt5008.md](slt5008.md) を参照してください。

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
