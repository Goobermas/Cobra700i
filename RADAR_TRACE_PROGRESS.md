# Radar path — bounded evidence and next investigation

The known alert-record consumer compares a 32-bit record field with these
codes, according to `BAND_MAP.md` and `ALERT_PATH.md`:

| Code | Reported alert class |
|---|---|
| `0x10` | X |
| `0x20` | K |
| `0x30` or `0x05` | Ka |
| `0x80` | MRCD/MRCT |

This confirms *classification/logging* behavior, **not** the upstream radar
detector signal path. The producer for `0x397A8` (working table) and any
acquisition/DSP transform must be traced from actual stores, computed-pointer
writes included. The downstream history ring at `0x3BF88` cannot by itself
identify the live detection source.

## Suggested next verified edge

1. Enumerate *memory-writing instructions*, not just immediate literals, in
   routines that can reach the working record array at `0x397A8`.
2. For each candidate store, record `source function`, `instruction address`,
   `destination effective-address expression`, `width`, and `source value`.
3. Trace the producer's upstream inputs to an interrupt handler, peripheral
   buffer, or DSP routine only where the dataflow can be demonstrated.
4. If a link crosses one of the 90 `jsr Rn` sites, record the site and unresolved
   register dependency; no callback edge is justified without the actual target.

No verified acquisition→alert producer edge has been established in the
publicly reproducible dataset yet. No patched firmware is part of this work.
