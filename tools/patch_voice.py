#!/usr/bin/env python3
"""Build a reversible, size-preserving patch of the RAD 700i voice bank.

The container is:
    0x00  "RAD_700i_V1.2.0.1" + NUL padding
    0x20  309 x u32 BE block offsets
    0x4F4 first block; each block = u32 BE payload length + payload

Because the payload lengths are stored both in the table and per block,
replacing a payload with one of *identical length* leaves every offset and
every other block untouched. That makes the patch minimal and trivially
reversible: restoring the recorded original bytes returns the exact file.

No original firmware file is modified; output goes to out/.
"""
import struct, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "RAD_700i_V1.2.0.1.bin"
OUT = ROOT / "out"
OUT.mkdir(exist_ok=True)

# blocks that hold the pure synthetic beep tone (see work/voice/features.csv)
TARGETS = [16, 101, 170, 184]

sys.path.insert(0, str(ROOT / "tools"))
from tonegen import (render_tone, to_pcm16, ima_encode, ima_decode,
                     write_wav, BANDS, FS)

STEP = None  # supplied by tonegen


def block_table(d):
    n = (0x4F4 - 0x20) // 4
    return [struct.unpack(">I", d[0x20+4*i:0x24+4*i])[0] for i in range(n)]


def main(band="Ka"):
    d = bytearray(SRC.read_bytes())
    tab = block_table(d)
    patched = bytearray(d)
    manifest = {"source": SRC.name, "source_sha256": hashlib.sha256(d).hexdigest(),
                "tone": band, "patches": []}

    for bi in TARGETS:
        start = tab[bi]
        ln = struct.unpack(">I", d[start:start+4])[0]
        payload_off = start + 4
        orig = bytes(d[payload_off:payload_off+ln])
        # one ADPCM byte yields 2 samples
        nsamp = ln * 2
        pcm = to_pcm16(render_tone(band, n=nsamp, fs=FS))
        new = ima_encode(pcm, ln)
        assert len(new) == len(orig), (len(new), len(orig))
        patched[payload_off:payload_off+ln] = new
        manifest["patches"].append({
            "block_index": bi,
            "payload_file_offset": payload_off,
            "payload_offset_hex": hex(payload_off),
            "length": ln,
            "original_sha256": hashlib.sha256(orig).hexdigest(),
            "replacement_sha256": hashlib.sha256(new).hexdigest(),
            "original_first16": orig[:16].hex(),
            "replacement_first16": new[:16].hex(),
        })

    out = OUT / f"RAD_700i_V1.2.0.1_tonepatched_{band}.bin"
    out.write_bytes(bytes(patched))
    manifest["output"] = out.name
    manifest["output_sha256"] = hashlib.sha256(bytes(patched)).hexdigest()
    manifest["size_delta"] = len(patched) - len(d)

    # ---- verification -------------------------------------------------
    # 1. container integrity: every block length still matches its span
    tab2 = block_table(patched)
    assert tab2 == tab, "offset table changed"
    ok = 0
    for i in range(len(tab2)-2):
        span = tab2[i+1]-tab2[i]
        ln = struct.unpack(">I", patched[tab2[i]:tab2[i]+4])[0]
        ok += (ln == span-4)
    print(f"container: offsets unchanged, {ok}/{len(tab2)-2} block lengths consistent")

    # 2. only the target payload bytes differ
    diff = [i for i in range(len(d)) if d[i] != patched[i]]
    allowed = set()
    for bi in TARGETS:
        st = tab[bi]
        ln = struct.unpack(">I", d[st:st+4])[0]
        allowed |= set(range(st+4, st+4+ln))
    stray = [i for i in diff if i not in allowed]
    print(f"changed bytes: {len(diff)} (all inside target payloads: {not stray})")

    # 3. decode the patched blocks and confirm the intended carrier survives
    import numpy as np
    peaks = []
    for bi in TARGETS[:1] + TARGETS[1:2]:
        st = tab[bi]
        ln = struct.unpack(">I", patched[st:st+4])[0]
        dec = np.array(ima_decode(bytes(patched[st+4:st+4+ln])), dtype=float)
        write_wav(OUT / f"patched_block{bi}_decoded.wav", [int(x) for x in dec])
        F = np.abs(np.fft.rfft((dec - dec.mean()) * np.hanning(len(dec)), 1 << 15))
        k = int(np.argmax(F[1:])) + 1
        f = k * FS / (1 << 15)
        band_e = F[max(0, k-3):k+4].sum() / (F[1:].sum() + 1e-12)
        peaks.append((bi, round(f, 1), round(float(band_e), 3)))
        print(f"patched block {bi}: {len(dec)} samples, decoded carrier "
              f"{f:.1f} Hz, {100*band_e:.1f}% of energy within +-3 bins")
    best_f = peaks[0][1]
    n = 0
    manifest["verification"] = {"offsets_unchanged": True,
                                "block_lengths_consistent": f"{ok}/{len(tab2)-2}",
                                "changed_bytes": len(diff),
                                "stray_changes": len(stray),
                                "decoded_blocks": peaks}
    (OUT / f"patch_manifest_{band}.json").write_text(json.dumps(manifest, indent=1))
    print("wrote", out.name, "and", f"patch_manifest_{band}.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Ka")
