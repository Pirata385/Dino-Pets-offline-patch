#!/usr/bin/env python3
"""Dino Pets (Miniclip) plist crypto, reimplemented from libgame.so.

File format: 8-byte header holding the decimal plaintext length (NUL padded),
followed by the plaintext padded to a multiple of 8 and encrypted with a
Blowfish variant (ECB, 16 rounds) whose F() indexes S-box 0 with the *low*
byte of its input, and whose key schedule packs key bytes little-endian.
Data words are loaded little-endian.  Key: "W3LC0M3_T0_M1N1P3TZ".

usage: dpcrypt.py dec|enc <libgame.so> <in> <out>
"""
import struct
import sys

KEY = b"W3LC0M3_T0_M1N1P3TZ"
P_INIT_VA, S_INIT_VA = 0x956a20, 0x956a68  # tables copied by FUN_00570a1c


class DPBlowfish:
    def __init__(self, libpath, key=KEY):
        lib = open(libpath, 'rb').read()
        # .rodata is mapped at identical vaddr/offset in this ELF
        self.P = list(struct.unpack_from('<18I', lib, P_INIT_VA))
        s = struct.unpack_from('<1024I', lib, S_INIT_VA)
        self.S = [list(s[i * 256:(i + 1) * 256]) for i in range(4)]
        assert self.P[0] == 0x243F6A88, 'unexpected P table'
        n = len(key)
        for i in range(18):
            j = (i * 4)
            w = key[j % n] | key[(j + 1) % n] << 8 | key[(j + 2) % n] << 16 | key[(j + 3) % n] << 24
            self.P[i] ^= w
        l = r = 0
        for i in range(0, 18, 2):
            l, r = self.enc_block(l, r)
            self.P[i], self.P[i + 1] = l, r
        for b in range(4):
            for i in range(0, 256, 2):
                l, r = self.enc_block(l, r)
                self.S[b][i], self.S[b][i + 1] = l, r

    def F(self, x):
        S0, S1, S2, S3 = self.S
        return ((((S1[(x >> 8) & 0xff] + S0[x & 0xff]) & 0xffffffff) ^ S2[(x >> 16) & 0xff])
                + S3[x >> 24]) & 0xffffffff

    def enc_block(self, l, r):
        P, F = self.P, self.F
        for i in range(16):
            l ^= P[i]
            r ^= F(l)
            l, r = r, l
        l, r = r, l
        r ^= P[16]
        l ^= P[17]
        return l, r

    def dec_block(self, l, r):
        P, F = self.P, self.F
        for i in range(17, 1, -1):
            l ^= P[i]
            r ^= F(l)
            l, r = r, l
        l, r = r, l
        r ^= P[1]
        l ^= P[0]
        return l, r

    def _ecb(self, data, fn):
        out = bytearray(len(data))
        for o in range(0, len(data), 8):
            l, r = struct.unpack_from('<II', data, o)
            struct.pack_into('<II', out, o, *fn(l, r))
        return bytes(out)


def decrypt(bf, blob):
    n = int(blob[:8].split(b'\0')[0])
    body = blob[8:]
    body = body[:len(body) // 8 * 8]
    return bf._ecb(body, bf.dec_block)[:n]


def encrypt(bf, plain):
    n = len(plain)
    size = (n + 0x10) - (n + 8) % 8  # same formula as +[Utils encryptData:password:]
    buf = bytearray(size)
    hdr = str(n).encode() + b'\0'
    buf[:len(hdr)] = hdr
    buf[8:8 + n] = plain
    return bytes(buf[:8]) + bf._ecb(bytes(buf[8:]), bf.enc_block)


if __name__ == '__main__':
    mode, lib, src, dst = sys.argv[1:5]
    bf = DPBlowfish(lib)
    data = open(src, 'rb').read()
    open(dst, 'wb').write(decrypt(bf, data) if mode == 'dec' else encrypt(bf, data))
