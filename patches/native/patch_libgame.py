#!/usr/bin/env python3
"""Offline patches for Dino Pets 1.1.4 lib/armeabi/libgame.so (ARMv6, GNU ObjC/Cocotron).

Every patch verifies the original bytes before writing, so the script refuses to
touch any other build of the library.  Addresses are ELF virtual addresses of the
original library (image base 0); .text/.rodata are mapped at offset == vaddr and
.data at vaddr - 0x1000.

usage: patch_libgame.py <in libgame.so> <out libgame.so> [--debug-nslog] [--fix-dt-needed]

  --fix-dt-needed  rewrite the absolute DT_NEEDED paths
                   (/PortsTools/android/.../libc.so ...) to plain sonames, which
                   is required for targetSdkVersion >= 23 on Android 6.0+.
  --debug-nslog    route the game's (compiled-out) NSLog() to logcat with the
                   tag "DinoNSLog".  Debug builds only: slows the game down.
"""
import hashlib
import os
import struct
import subprocess
import sys
import tempfile

ORIG_SHA256 = "74dbc7c759f9378f985ea2ebce0fbfa4aaceb3e444d9f284bb25d8febed48874"
CROSS = os.environ.get("ARM_CROSS", "arm-linux-gnueabi-")


def u32(x):
    return struct.pack("<I", x & 0xFFFFFFFF)


def words(*ws):
    return b"".join(u32(w) for w in ws)


MOV_R0_0 = 0xE3A00000
MOV_R1_0 = 0xE3A01000
MOV_R2_0 = 0xE3A02000
BX_LR = 0xE12FFF1E
PUSH_FP_LR = 0xE92D4800
POP_FP_PC = 0xE8BD8800


def b(src, dst, link=False):
    off = (dst - (src + 8)) >> 2
    assert -(1 << 23) <= off < (1 << 23), "branch out of range"
    return (0xEB000000 if link else 0xEA000000) | (off & 0xFFFFFF)


def asm(addr, source, defsyms=None):
    """Assemble ARM source located at absolute address `addr`; returns bytes."""
    with tempfile.TemporaryDirectory() as td:
        s = os.path.join(td, "p.s")
        o = os.path.join(td, "p.o")
        e = os.path.join(td, "p.elf")
        bn = os.path.join(td, "p.bin")
        with open(s, "w") as f:
            f.write("\t.syntax unified\n\t.arm\n\t.text\n\t.global _start\n_start:\n" + source + "\n")
        subprocess.check_call([CROSS + "as", "-march=armv6", "-mfloat-abi=soft", "-o", o, s])
        cmd = [CROSS + "ld", "-Ttext=0x%x" % addr, "-e", "_start", "-o", e, o]
        for k, v in (defsyms or {}).items():
            cmd.append("--defsym=%s=0x%x" % (k, v))
        subprocess.check_call(cmd)
        subprocess.check_call([CROSS + "objcopy", "-O", "binary", "-j", ".text", e, bn])
        return open(bn, "rb").read()


def va2off(va):
    return va - 0x1000 if va >= 0x9A4550 else va


# ---------------------------------------------------------------------------
# Addresses (original libgame.so, Dino Pets 1.1.4 / versionCode 13)
# ---------------------------------------------------------------------------
NTP_CALLBACK = 0x5A535C              # void ntpCallback(double offset, int error)
GL_ntpAndroid = 0x5A53F8             # -[GameLayer ntpAndroid]
GL_loadingStepLoadSaveFile = 0x5AD868
GL_loadingStepSetupConfig = 0x5A4A70
GL_cfgDownload_badCfgCheck = 0x5A7624  # inside -[GameLayer loadingStepDownloadConfiguration]
GL_cfgDownload_upToDate = 0x5A7998     # "configuration up to date" block of the same method
GL_determineNTPFailure = 0x5A21F8
GL_updateMessagingRegistry = 0x60FA74
CloudStorage_startOperation = 0x4B38D0
CloudStorage_storeValue_forKey = 0x4B42AC
MCCPS_forceUpdateOnAllProperties = 0x64DE78
SocialUtils_checkNotifications_req = 0x4B6B8C  # 'beq skip_request' inside -[SocialUtils checkNotifications]
SocialUtils_checkNotifications_skip = 0x4B6C84

NSLOG = 0x2FCA80                     # NSLog(): compiled to an empty stub in this build
NSLOGV = 0x2FC920                    # NSLogv(NSString *fmt, va_list)
NSLOG_SINK_PTR = 0x9E74E8            # sNSLogCString function pointer (R_ARM_RELATIVE)
ANDROID_LOG_PRINT_PLT = 0x2906B0
CODE_CAVE = 0x5A4010                 # -[GameLayer loadingStepSetupID]: dead code (no selector refs)


def patches(debug_nslog):
    p = []

    # 1. Startup step "load save file": never fetch the save from the (dead)
    #    cloud service.  The local save (Documents/save.plist) was already loaded
    #    in loading step 0; with no local save the game starts a new shelter,
    #    exactly as when the cloud returned no save.
    p.append(("loadingStepLoadSaveFile -> return 0 (skip cloud save download)",
              GL_loadingStepLoadSaveFile, words(0xE92D4FF0, 0xE28DB01C),
              words(MOV_R0_0, BX_LR)))

    # 2. Startup step "setup config": skip the MCConfigSetup HTTP request to
    #    services.miniclippt.com (it retried forever when unreachable on a
    #    fresh install).
    p.append(("loadingStepSetupConfig -> return 0 (skip remote config setup)",
              GL_loadingStepSetupConfig, words(0xE92D4FF0, 0xE28DB01C),
              words(MOV_R0_0, BX_LR)))

    # 3. Startup step "download configuration": after the method has loaded the
    #    local configuration (previously downloaded config if present, otherwise
    #    the bundled assets/config.plist) jump straight to the original
    #    "configuration is up to date" block instead of comparing against the
    #    server and downloading (mandatory on first launch -> endless retries).
    p.append(("loadingStepDownloadConfiguration -> treat local config as current",
              GL_cfgDownload_badCfgCheck, words(0xE5D9036D),
              words(b(GL_cfgDownload_badCfgCheck, GL_cfgDownload_upToDate))))

    # 4. Startup step "network time": -[GameLayer ntpAndroid] used to ask Java
    #    for an NTP offset (pool.ntp.org) and the game refused to start until it
    #    got one.  Report a successful lookup with a 0.0 s offset, i.e. the
    #    device clock is the time source (the game's own timers/anti-cheat logic
    #    is otherwise unchanged).
    ntp = words(PUSH_FP_LR, MOV_R0_0, MOV_R1_0, MOV_R2_0,
                b(GL_ntpAndroid + 16, NTP_CALLBACK, link=True), POP_FP_PC)
    p.append(("ntpAndroid -> ntpCallback(0.0, 0) (device clock as network time)",
              GL_ntpAndroid,
              words(0xE92D4800, 0xE59F0020, 0xE59F2020, 0xE1A0B00D, 0xE08F1000, 0xE0820001),
              ntp))

    # 5. Never probe www.google.com (only reached after an NTP failure; the
    #    original code also crashed on this path).
    p.append(("determineIfNTPFailureIsWithWorkingInternetConnection -> no-op",
              GL_determineNTPFailure, words(0xE92D4BF0), words(BX_LR)))

    # 6./7. Cloud save backup (shelter-services.miniclippt.com): the game keeps
    #    saving locally every few seconds; just drop the periodic upload.
    p.append(("CloudStorage startOperation -> no-op", CloudStorage_startOperation,
              words(0xE92D4FF0), words(BX_LR)))
    p.append(("CloudStorage storeValue:forKey: -> no-op", CloudStorage_storeValue_forKey,
              words(0xE92D4FF0), words(BX_LR)))

    # 8. Push/messaging registration with messenger.miniclippt.com.
    p.append(("GameLayer updateMessagingRegistry -> no-op", GL_updateMessagingRegistry,
              words(0xE92D4FF0), words(BX_LR)))

    # 9. Remote "cloud properties" refresh at launch (defaults are used).
    p.append(("MCCPS forceUpdateOnAllProperties -> no-op", MCCPS_forceUpdateOnAllProperties,
              words(0xE92D4870), words(BX_LR)))

    # 10. SocialUtils polls the social server every 5 s for "someone visited /
    #     rated you" notifications.  Keep the timer, skip the request.
    p.append(("SocialUtils checkNotifications -> skip server poll",
              SocialUtils_checkNotifications_req, words(0x0A00003C),
              words(b(SocialUtils_checkNotifications_req, SocialUtils_checkNotifications_skip))))

    if debug_nslog:
        tag_fmt = b"DinoNSLog\0%.*s\0"
        cave_src = """
nslog_thunk:
    sub     sp, sp, #16
    stmib   sp, {r1, r2, r3}
    str     lr, [sp]
    add     r1, sp, #4
    bl      NSLOGV
    ldr     lr, [sp]
    add     sp, sp, #16
    bx      lr
nslog_sink:                     @ (const char *s, int len, BOOL) -> logcat
    push    {r4, lr}
    sub     sp, sp, #8
    str     r0, [sp]
    mov     r3, r1
    adr     r1, tag
    adr     r2, fmt
    mov     r0, #4
    bl      ALOG
    add     sp, sp, #8
    pop     {r4, pc}
tag: .asciz "DinoNSLog"
fmt: .asciz "%.*s"
    .align 2
"""
        cave = asm(CODE_CAVE, cave_src, {"NSLOGV": NSLOGV, "ALOG": ANDROID_LOG_PRINT_PLT})
        sink_addr = CODE_CAVE + 8 * 4
        p.append(("debug: code cave (NSLog thunk + logcat sink)", CODE_CAVE, None, cave))
        p.append(("debug: NSLog -> thunk", NSLOG, words(0xE24DD010),
                  words(b(NSLOG, CODE_CAVE))))
        p.append(("debug: sNSLogCString -> logcat sink", NSLOG_SINK_PTR, words(0x2FCADC),
                  u32(sink_addr)))
    return p


def fix_dt_needed(data):
    """Point DT_NEEDED entries that hold absolute build-machine paths at the
    basename that already ends those strings in .dynstr."""
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x2E)
    secs = []
    for i in range(e_shnum):
        secs.append(struct.unpack_from("<10I", data, e_shoff + i * e_shentsize))
    shstr = secs[e_shstrndx][4]

    def name(sh):
        o = shstr + sh[0]
        return data[o:data.index(b"\0", o)].decode()

    dyn = next(s for s in secs if name(s) == ".dynamic")
    dynstr = next(s for s in secs if name(s) == ".dynstr")
    out = bytearray(data)
    changed = []
    for o in range(dyn[4], dyn[4] + dyn[5], 8):
        tag, val = struct.unpack_from("<iI", data, o)
        if tag == 0:
            break
        if tag != 1:  # DT_NEEDED
            continue
        so = dynstr[4] + val
        s = data[so:data.index(b"\0", so)].decode()
        if "/" in s:
            base = s.rsplit("/", 1)[1]
            newval = val + len(s) - len(base)
            struct.pack_into("<iI", out, o, tag, newval)
            changed.append((s, base))
    return bytes(out), changed


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    src, dst = args
    data = bytearray(open(src, "rb").read())
    digest = hashlib.sha256(data).hexdigest()
    print("input sha256:", digest)
    if digest != ORIG_SHA256:
        sys.exit("ABORT: this is not the Dino Pets 1.1.4 libgame.so these patches were made for")
    for desc, va, orig, new in patches("--debug-nslog" in flags):
        off = va2off(va)
        if orig is not None:
            cur = bytes(data[off:off + len(orig)])
            if cur != orig:
                sys.exit("ABORT: unexpected bytes at 0x%x for '%s': %s" % (va, desc, cur.hex()))
        data[off:off + len(new)] = new
        print("  [ok] 0x%06x %-70s (%d bytes)" % (va, desc, len(new)))
    out = bytes(data)
    if "--fix-dt-needed" in flags:
        out, changed = fix_dt_needed(out)
        for a, bb in changed:
            print("  [ok] DT_NEEDED %s -> %s" % (a, bb))
    open(dst, "wb").write(out)
    print("output sha256:", hashlib.sha256(out).hexdigest())


if __name__ == "__main__":
    main()
