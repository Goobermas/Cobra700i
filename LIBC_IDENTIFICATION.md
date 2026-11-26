# C runtime identification — evidence ledger

Status: **provisional**. The raw firmware and Ghidra exports are private and are
not contained in this repository. Identifications below are from reported RXv3
instruction traces; the full file strings and independent library comparison
still need to be checked in the private workspace.

| Function | Candidate | Confidence | Evidence to reproduce privately |
|---|---|---|---|
| `0xFFFC8B56` | `fopen`-like | probable | Reported mode parser compares the first character with `r` (`0x72`), `w` (`0x77`), `a` (`0x61`), accepts `b`/`+`, sets `EINVAL` (`0x16`), and calls a device-open helper. |
| `0xFFFC6D31` | `freopen`-like | probable | Reported cleanup of an existing stream followed by a call to `0xFFFC8B56` using the original filename/mode arguments. |
| `0xFFFC6D60` | stream teardown | probable | Reported flag test, optional release of the field at object offset `+4`, and clearing of that field; **no indirect call**. Exact `fclose` vs cleanup-only semantics not proven. |
| `0xFFFA8422` | stdio initialization | probable | Three objects at `0x7E744`, `0x7E78C`, `0x7E7D4`, with 0x48-byte spacing, are reportedly initialized by the same wrapper using ROM strings. |
| `0xFFFA850A` | stdio cleanup/service | probable | One direct call from reset; iterates the pointer table at `0x6AA14` and invokes `0xFFFC6D60` when low flag bits are set. No evidence of recurring scheduler invocation. |

The 0x48-byte template reportedly begins at `0xFFF574B4` and runs through
`0xFFF574FB` inclusive (18 little-endian dwords). The adjacent word at
`0xFFF574B0` is reported as a stream/object count, not independently decoded.
The names *stdin*, *stdout* and *stderr* require decoding the actual strings
and stream assignments rather than reasoning from the number three.

## Required private verification

1. Decode NUL-terminated bytes at `0xFFF74C29`, `0xFFF74C32`, `0xFFF74C34`,
   `0xFFF74C3E`, and `0xFFF74C40`. Record both exact bytes and interpreted strings
   **in the private workspace**, not in this public repository.
2. Check argument liveness through `0xFFFC8B56`: the source reportedly saves
   incoming R1 into R15 at `0xFFFC8B5D`, then overwrites R1 at `0xFFFC8B66`.
   `pushm R7-R9` does **not** save R15; do not infer the calling convention from
   that push instruction.
3. Confirm the complete stream template copy and later field initialization;
   `0x48` is a reported span, not a substitute for enumerating stores.
4. Compare standard function signatures and return/error behavior before
   promoting any of these five labels to `VERIFIED`.

## Reproducible classification

`tools/analysis/classify.py` consumes the private function inventory, exported
assembly, and the corrected direct-call graph. It writes complete CSVs under
ignored `out/ghidra/`, including a libc-candidate view and a baseline count.

`tools/analysis/classification_seeds.csv` is **reviewable evidence input**, not
an automated signature database. Runtime guesses are marked `PROBABLE`, while
unmatched functions remain `UNKNOWN`. Do not turn all code reachable from a
libc candidate into libc by transitive closure.
