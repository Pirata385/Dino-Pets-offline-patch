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

# Facebook-exclusive dinosaur.  The "Login to Facebook" quest (q_fbLogin) rewarded
# 'other: d_Dimorphodon': -[GameLayer questRewardPopUpCallback:] un-hid that dino's
# shop entry and added its id to mUnlockedObjects, which is saved as key "1004" and
# re-applied by -[GameLayer unlockObjects:] on every load.  The offline edition does
# the same, without Facebook, once the tutorial is over.
FBDINO_CAVE = 0x5A4100               # rest of the dead -[GameLayer loadingStepSetupID]
FBDINO_CAVE_END = 0x5A47E8           # next method: -[GameLayer configSetupSuccessfulWithData:]
GL_onTutorialFinished_epilogue = 0x58F17C  # 'sub sp, fp, #28' before 'pop {r4-r9, sl, fp, pc}'
GL_showMainView = 0x5B8734           # 'push {r4-r9, sl, fp, lr}'; UI thread, each time the main map is entered
OBJC_GET_CLASS = 0x2920BC
OBJC_MSG_LOOKUP = 0x2951AC
# selector references (struct objc_selector) from GameLayer.mm's own selector table
FBDINO_SELREFS = {
    "SEL_getState": 0xB329F8,
    "SEL_containsObject": 0xB32D90,
    "SEL_getStructureConfigFromId": 0xB32B50,
    "SEL_setHidden": 0xB32D18,
    "SEL_addObject": 0xB32C80,
    "SEL_forceSave": 0xB30878,
    "SEL_stringWithUTF8String": 0xB319B8,
    "SEL_alloc": 0xB32850,
    "SEL_init": 0xB30268,
    "SEL_autorelease": 0xB30AE0,
    "SEL_sharedLocalizationUtils": 0xB30EF8,
    "SEL_getText": 0xB30EE0,
    "SEL_setTitle": 0xB32720,
    "SEL_addTextElement": 0xB30DB0,
    "SEL_addButton": 0xB31078,
    "SEL_showMessagePopUp": 0xB311B0,
    "SEL_performSelectorOnMainThread": 0xB308B0,  # ...:withObject:waitUntilDone:
}

FBDINO_SRC = r"""
    .equ OFF_TUTORIAL,    0x314     @ GameLayer.mTutorial, nil once the tutorial is finished
    .equ OFF_POPUPMGR,    0xc8c     @ GameLayer message pop-up manager (-showMessagePopUp:)
    .equ OFF_UNLOCKED_HI, 0x1000    @ GameLayer.mUnlockedObjects at +0x1138:
    .equ OFF_UNLOCKED_LO, 0x138     @   NSMutableSet, saved as key "1004"
    .equ CFG_ID,          0x8       @ BaseConfig: structure id (NSString)
    .equ CFG_SHOPENTRY,   0x1c      @ BaseConfig: shop entry object (-setHidden:)
    .equ ST_VISITING,     4         @ -[GameLayer getState] values
    .equ ST_FEEDMG,       0x28
    .equ ST_LOADVISIT,    0x2c

    @ ptab offsets (PC-relative pointers, see the table at the end)
    .equ T_getState, 0
    .equ T_containsObject, 4
    .equ T_getStructureConfigFromId, 8
    .equ T_setHidden, 12
    .equ T_addObject, 16
    .equ T_forceSave, 20
    .equ T_stringWithUTF8String, 24
    .equ T_alloc, 28
    .equ T_init, 32
    .equ T_autorelease, 36
    .equ T_sharedLocalizationUtils, 40
    .equ T_getText, 44
    .equ T_setTitle, 48
    .equ T_addTextElement, 52
    .equ T_addButton, 56
    .equ T_showMessagePopUp, 60
    .equ T_performOnMain, 64
    .equ P_NSString, 68
    .equ P_dino, 72
    .equ P_MessagePopUpParams, 76
    .equ P_LocalizationUtils, 80
    .equ P_CNGTL, 84
    .equ P_OK, 88
    .equ P_text, 92

hook_tutorial_finished:                 @ +0: replaces the epilogue's 'sub sp, fp, #28'
    mov     r0, r8                      @ r8 = self throughout -[GameLayer onTutorialFinished]
    bl      fbdino_grant
    sub     sp, fp, #28
    pop     {r4, r5, r6, r7, r8, r9, sl, fp, pc}

hook_show_main_view:                    @ +16: replaces the prologue's 'push {r4-r9, sl, fp, lr}'
    push    {r0, r1, r2, r3, ip, lr}
    bl      fbdino_grant
    pop     {r0, r1, r2, r3, ip, lr}
    push    {r4, r5, r6, r7, r8, r9, sl, fp, lr}
    b       SHOW_MAIN_VIEW_BODY

@ void fbdino_grant(GameLayer *self)
@   once the tutorial is finished and d_Dimorphodon is not unlocked yet:
@   [[self getStructureConfigFromId:@"d_Dimorphodon"]->shopEntry setHidden:NO];
@   [self->mUnlockedObjects addObject:cfg->id]; [self forceSave];
@   then a "Congratulations!" pop-up, queued with performSelectorOnMainThread so it
@   opens after the current state change has finished.
fbdino_grant:
    push    {r4, r5, r6, r7, r8, lr}
    ldr     r7, 8f
7:  add     r7, pc, r7                  @ r7 = ptab
    movs    r4, r0
    beq     9f
    ldr     r0, [r4, #OFF_TUTORIAL]
    cmp     r0, #0
    bne     9f                          @ tutorial still running
    add     r0, r4, #OFF_UNLOCKED_HI
    ldr     r5, [r0, #OFF_UNLOCKED_LO]
    cmp     r5, #0
    beq     9f
    mov     r0, r4
    mov     r1, #T_getState
    bl      send
    cmp     r0, #ST_VISITING
    cmpne   r0, #ST_LOADVISIT
    beq     9f                          @ never while visiting another shelter
    mov     r8, r0
    ldr     r0, [r7, #P_dino]
    add     r0, r0, r7
    bl      nsstring
    movs    r6, r0
    beq     9f
    mov     r0, r5
    mov     r1, #T_containsObject
    mov     r2, r6
    bl      send
    tst     r0, #0xff
    bne     9f                          @ already unlocked: no second grant
    mov     r0, r4
    mov     r1, #T_getStructureConfigFromId
    mov     r2, r6
    bl      send
    movs    r6, r0                      @ r6 = BaseConfig *
    beq     9f
    ldr     r0, [r6, #CFG_SHOPENTRY]
    mov     r1, #T_setHidden
    mov     r2, #0
    bl      send
    mov     r0, r5
    mov     r1, #T_addObject
    ldr     r2, [r6, #CFG_ID]
    bl      send
    mov     r0, r4
    mov     r1, #T_forceSave
    bl      send
    cmp     r8, #ST_FEEDMG
    beq     9f                          @ no pop-ups during the feeding mini-game
    ldr     r0, [r7, #P_MessagePopUpParams]
    add     r0, r0, r7
    bl      OBJC_GET_CLASS
    mov     r1, #T_alloc
    bl      send
    mov     r1, #T_init
    bl      send
    mov     r1, #T_autorelease
    bl      send
    movs    r6, r0                      @ r6 = MessagePopUpParams
    beq     9f
    ldr     r0, [r7, #P_LocalizationUtils]
    add     r0, r0, r7
    bl      OBJC_GET_CLASS
    mov     r1, #T_sharedLocalizationUtils
    bl      send
    mov     r5, r0                      @ r5 = [LocalizationUtils sharedLocalizationUtils]
    ldr     r0, [r7, #P_CNGTL]
    add     r0, r0, r7
    bl      nsstring
    mov     r2, r0
    mov     r0, r5
    mov     r1, #T_getText
    bl      send                        @ "Congratulations!"
    mov     r2, r0
    mov     r0, r6
    mov     r1, #T_setTitle
    bl      send
    ldr     r0, [r7, #P_text]
    add     r0, r0, r7
    bl      nsstring
    mov     r2, r0
    mov     r0, r6
    mov     r1, #T_addTextElement
    bl      send
    ldr     r0, [r7, #P_OK]
    add     r0, r0, r7
    bl      nsstring
    mov     r2, r0
    mov     r0, r5
    mov     r1, #T_getText
    bl      send                        @ "OK"
    mov     r2, r0
    mov     r0, r6
    mov     r1, #T_addButton
    bl      send
    ldr     r5, [r4, #OFF_POPUPMGR]
    cmp     r5, #0
    beq     9f
    ldr     r8, [r7, #T_performOnMain]
    add     r8, r8, r7
    mov     r0, r5
    mov     r1, r8
    bl      OBJC_MSG_LOOKUP
    mov     ip, r0
    ldr     r2, [r7, #T_showMessagePopUp]
    add     r2, r2, r7                  @ performSelectorOnMainThread:@selector(showMessagePopUp:)
    mov     r3, r6                      @   withObject:params
    sub     sp, sp, #8
    mov     r0, #0
    str     r0, [sp]                    @   waitUntilDone:NO
    mov     r0, r5
    mov     r1, r8
    blx     ip
    add     sp, sp, #8
9:  pop     {r4, r5, r6, r7, r8, pc}
8:  .word   ptab - (7b + 8)

send:                                   @ r0 = receiver, r1 = ptab offset of a SEL, r2 = argument
    push    {r4, r5, r6, lr}
    mov     r4, r0
    ldr     r5, [r7, r1]
    add     r5, r5, r7
    mov     r6, r2
    mov     r1, r5
    bl      OBJC_MSG_LOOKUP             @ nil receivers get the runtime's nil method
    mov     r3, r0
    mov     r0, r4
    mov     r1, r5
    mov     r2, r6
    blx     r3
    pop     {r4, r5, r6, pc}

nsstring:                               @ r0 = C string -> [NSString stringWithUTF8String:]
    push    {r4, lr}
    mov     r4, r0
    ldr     r0, [r7, #P_NSString]
    add     r0, r0, r7
    bl      OBJC_GET_CLASS
    mov     r1, #T_stringWithUTF8String
    mov     r2, r4
    bl      send
    pop     {r4, pc}

    .align 2
ptab:
    .word   SEL_getState - ptab
    .word   SEL_containsObject - ptab
    .word   SEL_getStructureConfigFromId - ptab
    .word   SEL_setHidden - ptab
    .word   SEL_addObject - ptab
    .word   SEL_forceSave - ptab
    .word   SEL_stringWithUTF8String - ptab
    .word   SEL_alloc - ptab
    .word   SEL_init - ptab
    .word   SEL_autorelease - ptab
    .word   SEL_sharedLocalizationUtils - ptab
    .word   SEL_getText - ptab
    .word   SEL_setTitle - ptab
    .word   SEL_addTextElement - ptab
    .word   SEL_addButton - ptab
    .word   SEL_showMessagePopUp - ptab
    .word   SEL_performSelectorOnMainThread - ptab
    .word   s_NSString - ptab
    .word   s_dino - ptab
    .word   s_MessagePopUpParams - ptab
    .word   s_LocalizationUtils - ptab
    .word   s_CNGTL - ptab
    .word   s_OK - ptab
    .word   s_text - ptab
s_NSString:           .asciz "NSString"
s_dino:               .asciz "d_Dimorphodon"
s_MessagePopUpParams: .asciz "MessagePopUpParams"
s_LocalizationUtils:  .asciz "LocalizationUtils"
s_CNGTL:              .asciz "CNGTL"
s_OK:                 .asciz "OK"
s_text:               .asciz "You unlocked the exclusive Facebook dino!\nDimorphodon is now free in the Dinos shop."
    .align 2
"""
FBDINO_HOOK_TUTORIAL = FBDINO_CAVE + 0
FBDINO_HOOK_MAINVIEW = FBDINO_CAVE + 16


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

    # 11. Facebook-exclusive dinosaur: unlock d_Dimorphodon (the q_fbLogin quest's
    #     reward) once the tutorial is finished - right when it finishes, and when
    #     the main map opens for saves that finished it before this patch.
    #     mUnlockedObjects is a set, so it is granted at most once per save.
    defs = dict(FBDINO_SELREFS, OBJC_GET_CLASS=OBJC_GET_CLASS, OBJC_MSG_LOOKUP=OBJC_MSG_LOOKUP,
                SHOW_MAIN_VIEW_BODY=GL_showMainView + 4)
    cave = asm(FBDINO_CAVE, FBDINO_SRC, defs)
    assert FBDINO_CAVE + len(cave) <= FBDINO_CAVE_END, "FB dino code does not fit"
    p.append(("FB dino: unlock code in dead loadingStepSetupID (%d bytes)" % len(cave),
              FBDINO_CAVE, None, cave))
    p.append(("onTutorialFinished -> unlock FB dino", GL_onTutorialFinished_epilogue,
              words(0xE24BD01C), words(b(GL_onTutorialFinished_epilogue, FBDINO_HOOK_TUTORIAL))))
    p.append(("showMainView -> unlock FB dino (saves that finished the tutorial earlier)",
              GL_showMainView, words(0xE92D4FF0), words(b(GL_showMainView, FBDINO_HOOK_MAINVIEW))))

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
