# Interrupt map (RXv3, INTB = 0xFFF57750)

Source: Ghidra 11.4.2 + Ghidra-Rare RX, project `work/ghidra/ghv3`, language RX:LE:32:RXv3.
256 relocated vectors collapse to 36 unique targets: default `0xFFFA9562` (221 vectors),
bare `RTE` stub `0xFFFA7F5A`, and 34 functional handlers. All 36 end in `RTE`.

| # | handler | vector idx | size | calls | peripherals | confidence |
|---|---|---|---|---|---|---|
| 1 | `0xFFFA1E6B` | [126] | 116 | FFFA1E59 | 0x0008281E | strong |
| 2 | `0xFFFA7498` | [29] | 86 | FFFB06A1 FFFB0976 | — | tentative |
| 3 | `0xFFFA7616` | [120] | 116 | FFFA768A | 0x0008201E | strong |
| 4 | `0xFFFA7AF9` | [39] | 102 | — | 0x000D0100 | strong |
| 5 | `0xFFFA7F5A` | [189] | 2 | — | — | tentative |
| 6 | `0xFFFA7FDA` | [146] | 68 | FFFA4028 | — | tentative |
| 7 | `0xFFFA8094` | [149] | 68 | FFFA4043 | — | tentative |
| 8 | `0xFFFA8156` | [152] | 104 | FFFA499D | — | tentative |
| 9 | `0xFFFA9562` | [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 18, 19, 20, 22, 24, 25, 28, 30, 31, 32, 33, 34, 35, 36, 37, 38, 40, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 116, 117, 118, 119, 122, 123, 124, 125, 127, 129, 130, 132, 133, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 147, 148, 150, 151, 153, 154, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 186, 187, 188, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255] | 75 | FFFA8BDA | — | tentative |
| 10 | `0xFFFA95AD` | [16] | 82 | FFFA8BDA | 0x00081300 | strong |
| 11 | `0xFFFA9FE3` | [27] | 67 | FFFA9E9C | — | tentative |
| 12 | `0xFFFAA026` | [26] | 67 | FFFA9E9C | — | tentative |
| 13 | `0xFFFAA718` | [110] | 923 | FFFA8BDA | 0x00087630 | strong |
| 14 | `0xFFFAAAB3` | [111] | 772 | FFFA8BDA | 0x00087634 | strong |
| 15 | `0xFFFAADB7` | [107] | 214 | FFFA8BDA | 0x00087638 | strong |
| 16 | `0xFFFAAE8D` | [112] | 585 | FFFA8BDA | 0x00087830 | strong |
| 17 | `0xFFFAB0D6` | [113] | 337 | FFFA8BDA | 0x00087834 | strong |
| 18 | `0xFFFAB227` | [17] | 131 | FFFA8BDA | 0x000875B0 | strong |
| 19 | `0xFFFAB2AA` | [106] | 215 | FFFA8BDA | 0x00087600, 0x00087680 | strong |
| 20 | `0xFFFB04EA` | [185] | 106 | FFFACA33 | — | tentative |
| 21 | `0xFFFB0554` | [90] | 89 | FFFB0266 | 0x0008705A | strong |
| 22 | `0xFFFB0AB2` | [121] | 116 | FFFB0B26 | 0x0008205E | strong |
| 23 | `0xFFFB0E07` | [109] | 102 | — | 0x000D0300 | strong |
| 24 | `0xFFFB0E6D` | [108] | 201 | FFFB0F98 | 0x000D0300 | strong |
| 25 | `0xFFFB1238` | [115] | 76 | — | 0x000D0062 | strong |
| 26 | `0xFFFB12A9` | [114] | 185 | FFFB1393 | 0x000D0062 | strong |
| 27 | `0xFFFB1918` | [41] | 102 | — | 0x000D0140 | strong |
| 28 | `0xFFFB2EF4` | [208] | 121 | FFFB2E56 | — | tentative |
| 29 | `0xFFFB5A72` | [155] | 68 | FFFA4A8A | — | tentative |
| 30 | `0xFFFB5CA2` | [85] | 76 | — | 0x0008A0A2 | strong |
| 31 | `0xFFFB5D13` | [84] | 185 | FFFB5DFD | 0x0008A0A2 | strong |
| 32 | `0xFFFC5BD6` | [131] | 66 | FFF8FF6A | — | tentative |
| 33 | `0xFFFC5C18` | [134] | 16 | — | — | tentative |
| 34 | `0xFFFC5C98` | [128] | 68 | FFFA4DBB | — | tentative |
| 35 | `0xFFFCF532` | [23] | 775 | FFFCF1A4 FFFD06B5 | — | tentative |
| 36 | `0xFFFCF839` | [21] | 194 | FFFD0780 FFFCF098 FFFD06B5 | 0x00087017 | strong |

## Confidence rule

`strong` = handler has resolved peripheral operands (identification still hypothesis).
`tentative` = no peripheral scalar resolved; may use computed pointers.

## Peripheral register totals

See `irq_registers.csv` (57 rows). Clusters: `0x87630-0x87838`, `0x875B0/0x87600/0x87680`,
`0x8281E/0x8201E/0x8205E`, `0x8A0A2`, `0x87017/0x8705A`, `0x81300`, `0x0D0062/0x0D0100/0x0D0140/0x0D0300`.

**No hardware name is assigned from address patterns alone** — pending Renesas register-map match.
