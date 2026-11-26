# RAD 700i boot sequence (RXv3, Ghidra 11.4.2 + Ghidra-Rare RX)

Reset vector `0xFFFFFFFC -> 0xFFFA8708`, 119 bytes. Language `RX:LE:32:RXv3`.

## Confirmed register writes (from reset_handler assembly)

| instr | meaning |
|---|---|
| `mvtc #0x9000,USP` / `mvtc #0x9600,ISP` | stacks set via control registers (no `mov #imm,R0`) |
| `mvtc #0xFFF57750,INTB` | relocated 256-entry vector table |
| `mvtc #0xFFFFFF80,EXTB` | exception table |
| `FPSW=0x100`, `DPSW=0x100` | FPU/DSP status reset |
| `0x81400=7`, `0x81401=7` | system/clock control bytes |
| `PSW=0x00030000` | **I=1 (interrupts enabled), U=1 (USP selected), IPL=0** |

R0 is the stack pointer (`rx.cspec: <stackpointer register="R0" space="ram" growth="negative"/>`);
USP/ISP are selected by PSW.U, so no immediate SP load exists.

## Initialization calls, in order

Before `PSW` write (interrupts masked): `FFFAA2A4` (thunk), `FFFC71B1`, `FFFA8AA2`
(RAM clear 0x84 dwords @0x6AA64), `FFFA8422`, `FFFA8B07`, `FFFA8A80` (clear 4 words @0x391EE),
`FFFA8318`, then `PSW=0x30000`, then `FFFA8BDA(0xb,1,0x10000000)`, `FFF93A4C` (387 B, 16 calls),
`FFFA850A`, then `bra.b .` idle spin.

`FFFA850A` walks a device table at `0x6AA14`, count `0xFFF574B0`, calling `FFFC6D60` for entries
whose flags&7 != 0. **Proven: table-driven dispatcher. Not proven: periodic/polled.**

## Vector tables

Fixed `0xFFFFFFD0..0xFFFFFFFC`: 12 entries, all valid; `FFFA9562` is the default handler,
`FFFFFFFC` is reset. Relocated `0xFFF57750` (INTB): 256 entries, all point into ROM,
36 unique targets, default `FFFA9562`.
