#!/usr/bin/env python3
"""A deliberately tiny RX interpreter for the instruction forms in this patch.

Only encodings attested in the vendor image are decoded, and each decoder is
checked by the tests. Notation follows the disassembly in work/main_full.dis.

Decoded forms
  e5 q s d    mov.l  s*4[Rs], d*4[Rd]      mem -> mem, q = Rs<<4 | Rd
  e4 q d      mov.l  [Rs],   d*4[Rd]      mem -> mem, zero source displacement
  e1 q s      mov.l  s*4[Rs], [Rd]        mem -> mem, zero destination
  e3 q        mov.l  Rs, [Rd]             q = Rd<<4 | Rs
  ec q        mov.l  [Rs], Rd             q = Rs<<4 | Rd
  c3 q        mov.b  Rs, [Rd]             q = Rd<<4 | Rs
  c5 q s d    mov.b  s[Rs], d[Rd]         mem -> mem, byte displacements
  fb 12 imm32 mov.l  #imm32, r1           imm32 little-endian
  fb e2 imm32 mov.l  #imm32, r14
  05 disp24   bsr.a  target               disp24 little-endian, from pc+4
  02          rts
  67 nn       rtsd   #nn

Flags: none of the decoded forms touch PSW on RX (MOV/BSR/RTS/RTSD are not
flag-writing instructions), so `psw` is left alone by `step()`. The tests rely
on that: any flag change would be a bug in the design, not the interpreter.
"""
BIG = 0xFFFFFFFF


class CPU:
    def __init__(self, mem=None, flash=None):
        self.r = [0] * 16          # r0..r14 general, r15 = SP
        self.psw = {"C": 0, "Z": 1, "S": 0, "O": 0, "I": 1}
        self.mem = mem if mem is not None else {}
        self.flash = flash if flash is not None else {}
        self.pc = 0
        self.trace = []

    # ---- memory (big-endian, byte addressed) ----
    def rb(self, a):
        return self.mem.get(a & BIG, 0)

    def wb(self, a, v):
        self.mem[a & BIG] = v & 0xFF

    def rl(self, a):
        return (self.rb(a) << 24) | (self.rb(a + 1) << 16) | (self.rb(a + 2) << 8) | self.rb(a + 3)

    def wl(self, a, v):
        for i in range(4):
            self.wb(a + i, (v >> (24 - 8 * i)) & 0xFF)

    # ---- fetch ----
    def fetch(self, n):
        out = [self.flash.get((self.pc + i) & BIG, 0xFF) for i in range(n)]
        self.pc = (self.pc + n) & BIG
        return out

    def step(self):
        here = self.pc
        op = self.fetch(1)[0]
        if op == 0x05:                                   # bsr.a
            b = self.fetch(3)
            d = b[0] | (b[1] << 8) | (b[2] << 16)
            if d & 0x800000:
                d -= 0x1000000
            target = (self.pc + d) & BIG                 # pc already past the insn
            self.r[15] = (self.r[15] - 4) & BIG
            self.wl(self.r[15], self.pc)                 # RX pushes the PC
            self.pc = target
        elif op == 0x02:                                 # rts
            self.pc = self.rl(self.r[15])
            self.r[15] = (self.r[15] + 4) & BIG
        elif op == 0x67:                                 # rtsd #imm
            n = self.fetch(1)[0]
            self.pc = self.rl(self.r[15])
            self.r[15] = (self.r[15] + 4 + n) & BIG
        elif op == 0xfb:
            sub = self.fetch(1)[0]
            imm = self.fetch(4)
            v = imm[0] | (imm[1] << 8) | (imm[2] << 16) | (imm[3] << 24)
            if sub == 0x12:
                self.r[1] = v
            elif sub == 0xe2:
                self.r[14] = v
            else:
                raise NotImplementedError(f"fb {sub:02x} at 0x{here:08X}")
        elif op == 0xe5:
            q, s, d = self.fetch(3)
            v = self.rl((self.r[q >> 4] + s * 4) & BIG)
            self.wl((self.r[q & 0xF] + d * 4) & BIG, v)
        elif op == 0xe4:
            q, d = self.fetch(2)
            v = self.rl(self.r[q >> 4])
            self.wl((self.r[q & 0xF] + d * 4) & BIG, v)
        elif op == 0xe1:
            q, s = self.fetch(2)
            v = self.rl((self.r[q >> 4] + s * 4) & BIG)
            self.wl(self.r[q & 0xF], v)
        elif op == 0xe3:
            q = self.fetch(1)[0]
            self.wl(self.r[q >> 4], self.r[q & 0xF])
        elif op == 0xec:
            q = self.fetch(1)[0]
            self.r[q & 0xF] = self.rl(self.r[q >> 4])
        elif op == 0xc3:
            q = self.fetch(1)[0]
            self.wb(self.r[q >> 4], self.r[q & 0xF])
        elif op == 0xc5:
            q, s, d = self.fetch(3)
            self.wb((self.r[q & 0xF] + d) & BIG, self.rb((self.r[q >> 4] + s) & BIG))
        else:
            raise NotImplementedError(f"opcode {op:02x} at 0x{here:08X}")
        self.trace.append((here, op))
        return op

    def run(self, stop_pcs=(), limit=64):
        stops = set(stop_pcs)
        for _ in range(limit):
            if self.pc in stops:
                return "stop"
            self.step()
        raise RuntimeError("step limit reached (control flow did not terminate)")


def assemble_bsr_a(site, target):
    """bsr.a encoding: 05 disp24, disp = target - (site + 4), little-endian."""
    d = (target - (site + 4)) & 0xFFFFFF
    return bytes([0x05, d & 0xFF, (d >> 8) & 0xFF, (d >> 16) & 0xFF])
