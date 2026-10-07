#!/usr/bin/env python3
"""Parse GNU Objective-C ABI (module version 8) metadata out of libgame.so.

Emits JSON with:
  methods:   list of {cls, sel, kind ('-'/'+'), imp, types}
  selrefs:   list of {addr, sel, types}
  classes:   list of {name, addr, meta, super, ivars:[{name,type,offset}]}
Usage: objc_parse.py libgame.so out.json
"""
import json
import struct
import sys

lib, out = sys.argv[1], sys.argv[2]
d = open(lib, 'rb').read()

# --- ELF program headers -> vaddr->offset mapping (PT_LOAD) ---
e_phoff = struct.unpack_from('<I', d, 0x1c)[0]
e_phentsize, e_phnum = struct.unpack_from('<HH', d, 0x2a)
loads = []
for i in range(e_phnum):
    p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
        struct.unpack_from('<8I', d, e_phoff + i * e_phentsize)
    if p_type == 1:
        loads.append((p_vaddr, p_offset, p_filesz, p_memsz))


def off(va):
    for v, o, fs, ms in loads:
        if v <= va < v + fs:
            return o + (va - v)
    return None


def u32(va):
    o = off(va)
    return None if o is None else struct.unpack_from('<I', d, o)[0]


def u16(va):
    o = off(va)
    return struct.unpack_from('<H', d, o)[0]


def cstr(va):
    o = off(va)
    if o is None or va == 0:
        return None
    e = d.index(b'\0', o)
    return d[o:e].decode('latin1')


# --- init_array constructors -> module addresses ---
# find .init_array via section headers
e_shoff = struct.unpack_from('<I', d, 0x20)[0]
e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', d, 0x2e)
secs = {}
shstr_off = struct.unpack_from('<10I', d, e_shoff + e_shstrndx * e_shentsize)[4]
for i in range(e_shnum):
    sh = struct.unpack_from('<10I', d, e_shoff + i * e_shentsize)
    nm = d[shstr_off + sh[0]: d.index(b'\0', shstr_off + sh[0])].decode()
    secs[nm] = sh
GOT = 0x9baaf4  # DT_PLTGOT
ia = secs['.init_array']
ctors = struct.unpack_from('<%dI' % (ia[5] // 4), d, ia[4])
EXEC_CLASS = 0x29444c

modules = []
for c in ctors:
    c &= ~1
    # pattern: push; ldr r0,[pc,#a]; ldr r1,[pc,#b]; mov fp,sp; add r0,pc,r0; add r0,r1,r0; bl __objc_exec_class
    try:
        w = struct.unpack_from('<7I', d, off(c))
    except Exception:
        continue
    if w[1] & 0xfffff000 != 0xe59f0000 or w[2] & 0xfffff000 != 0xe59f1000:
        continue
    # check bl target
    bl = w[6]
    if bl >> 24 != 0xeb:
        continue
    imm = bl & 0xffffff
    if imm & 0x800000:
        imm -= 0x1000000
    tgt = c + 24 + 8 + imm * 4
    if tgt != EXEC_CLASS:
        continue
    lit0 = u32(c + 4 + 8 + (w[1] & 0xfff))
    lit1 = u32(c + 8 + 8 + (w[2] & 0xfff))
    pc_at_add = c + 16 + 8
    mod = (pc_at_add + lit0 + lit1) & 0xffffffff
    modules.append(mod)

methods, selrefs, classes, categories = [], [], [], []


def read_methods(mlist_va, clsname, kind, origin):
    while mlist_va:
        nxt = u32(mlist_va)
        cnt = u32(mlist_va + 4)
        for i in range(cnt):
            base = mlist_va + 8 + i * 12
            nm, ty, imp = u32(base), u32(base + 4), u32(base + 8)
            methods.append({'cls': clsname, 'sel': cstr(nm), 'kind': kind,
                            'imp': imp, 'types': cstr(ty), 'origin': origin})
        mlist_va = nxt


def read_ivars(iv_va):
    res = []
    if not iv_va:
        return res
    cnt = u32(iv_va)
    for i in range(cnt):
        b = iv_va + 4 + i * 12
        res.append({'name': cstr(u32(b)), 'type': cstr(u32(b + 4)), 'offset': u32(b + 8)})
    return res


for m in modules:
    ver, size, name, symtab = (u32(m + 4 * i) for i in range(4))
    if ver != 8:
        print('warn: module version', ver, hex(m), file=sys.stderr)
    selcnt, refs = u32(symtab), u32(symtab + 4)
    cc, catc = u16(symtab + 8), u16(symtab + 10)
    # selector refs: array of {name, types} until name==0 (GNU: sel_ref_cnt often 0; refs terminated)
    if refs and off(refs) is not None:
        a = refs
        while True:
            nm = u32(a)
            if not nm:
                break
            s = cstr(nm)
            if s is None:
                break
            selrefs.append({'addr': a, 'sel': s, 'types': cstr(u32(a + 4)) if u32(a + 4) else None,
                            'module': cstr(name)})
            a += 8
    for i in range(cc):
        cls = u32(symtab + 12 + 4 * i)
        meta, sup, cname = u32(cls), u32(cls + 4), u32(cls + 8)
        cn = cstr(cname)
        classes.append({'name': cn, 'addr': cls, 'meta': meta, 'super': cstr(sup) if sup else None,
                        'instance_size': u32(cls + 20), 'ivars': read_ivars(u32(cls + 24)),
                        'module': cstr(name)})
        read_methods(u32(cls + 28), cn, '-', 'class')
        read_methods(u32(meta + 28), cn, '+', 'class')
    for i in range(catc):
        cat = u32(symtab + 12 + 4 * (cc + i))
        catname, clsname = cstr(u32(cat)), cstr(u32(cat + 4))
        categories.append({'name': catname, 'cls': clsname, 'addr': cat})
        read_methods(u32(cat + 8), clsname, '-', 'cat:' + str(catname))
        read_methods(u32(cat + 12), clsname, '+', 'cat:' + str(catname))

json.dump({'modules': [hex(m) for m in modules], 'methods': methods, 'selrefs': selrefs,
           'classes': classes, 'categories': categories}, open(out, 'w'), indent=0)
print('modules', len(modules), 'classes', len(classes), 'categories', len(categories),
      'methods', len(methods), 'selrefs', len(selrefs))
