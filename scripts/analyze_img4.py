#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal Apple IMG4 / IM4P parser + Mach-O / kernelcache / Apple DeviceTree probe.
Written for the iOS16.5-on-MT6833 feasibility study. Pure stdlib."""
import sys, os, struct, hashlib

def der_tlv(buf, off=0):
    tag = buf[off]; off += 1
    l = buf[off]; off += 1
    if l & 0x80:
        n = l & 0x7f
        l = int.from_bytes(buf[off:off+n], 'big'); off += n
    return tag, l, off

def parse_im4p(data):
    out = {"raw_len": len(data)}
    if data[:4] != b'IM4P':
        out["error"] = "not IM4P: %r" % data[:8]
        return out
    off = 0
    tag, l, off = der_tlv(data, off)          # SEQUENCE
    out["seq_len"] = l
    fields = []
    while off < len(data):
        tag, l, hdr = der_tlv(data, off)
        body = data[hdr:hdr+l]
        fields.append((tag, l, body))
        off = hdr + l
        if off >= len(data): break
    i = 0
    for tag, l, body in fields:
        if i == 0 and tag == 0x16:      # IA5String magic
            out["magic"] = body.decode('ascii', 'replace')
        elif i == 1 and tag == 0x16:
            out["type"] = body.decode('ascii', 'replace')
        elif i == 2 and tag == 0x16:
            out["desc"] = body.decode('ascii', 'replace')
        elif tag == 0x04:
            if "data" not in out:
                out["data"] = body
                out["data_off"] = hdr
            else:
                out.setdefault("extra_octets", []).append((l, body[:16].hex()))
        elif tag == 0x16:
            out.setdefault("strings", []).append(body.decode('ascii', 'replace'))
        i += 1
    d = out.get("data")
    if d:
        out["payload_magic"] = d[:16].hex()
        out["payload_magic_ascii"] = ''.join(chr(c) if 32 <= c < 127 else '.' for c in d[:16])
        out["payload_sha256"] = hashlib.sha256(d).hexdigest()
    return out

def macho_probe(d):
    m = d[:4]
    info = {"first4": m.hex(), "first4_ascii": ''.join(chr(c) if 32<=c<127 else '.' for c in m)}
    if m in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
        is64 = m[3] == 0xfe and m[0] == 0xcf
        info["kind"] = "Mach-O 64" if is64 else "Mach-O 32"
        cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack('<iiIIII', d[4:28])
        info.update(cputype=hex(cputype), cpusubtype=hex(cpusub & 0xffffffff),
                    filetype=filetype, ncmds=ncmds, sizeofcmds=sizeofcmds, flags=hex(flags))
        off = 32 if is64 else 28
        cmds = []
        for _ in range(min(ncmds, 4000)):
            if off + 8 > len(d): break
            cmd, sz = struct.unpack('<II', d[off:off+8])
            cmds.append(cmd)
            off += sz
        info["lc_histogram"] = {hex(c): cmds.count(c) for c in sorted(set(cmds))}
        # LC_BUILD_VERSION / LC_VERSION_MIN
        names = {0x32:'LC_BUILD_VERSION',0x24:'LC_VERSION_MIN_MACOSX',0x25:'LC_VERSION_MIN_IPHONEOS',
                 0x2f:'LC_VERSION_MIN_TVOS',0x30:'LC_VERSION_MIN_WATCHOS'}
        vers = []
        off = 32 if is64 else 28
        for _ in range(min(ncmds, 4000)):
            if off + 8 > len(d): break
            cmd, sz = struct.unpack('<II', d[off:off+8])
            if cmd == 0x32 and sz >= 24:
                platform, minos, sdk, ntools = struct.unpack('<IIII', d[off+8:off+24])
                vers.append({"platform": platform, "minos": "%d.%d.%d" % (minos>>16,(minos>>8)&0xff,minos&0xff),
                             "sdk": "%d.%d.%d" % (sdk>>16,(sdk>>8)&0xff,sdk&0xff)})
            elif cmd in names:
                v, s = struct.unpack('<II', d[off+8:off+16])
                vers.append({names[cmd]: "%d.%d.%d" % (v>>16,(v>>8)&0xff,v&0xff)})
            off += sz
        info["versions"] = vers[:6]
        return info
    if m[:4] == b'comp' or m[:8] == b'complzss':
        info["kind"] = "LZSS (complzss) compressed"
        return info
    if m[:4] == b'\x1f\x8b\x08\x00' or m[:2] == b'\x1f\x8b':
        info["kind"] = "gzip"
        return info
    info["kind"] = "unknown"
    return info

def apple_dt_probe(d):
    info = {}
    if len(d) < 32: return {"error": "too short"}
    magic = struct.unpack('>I', d[0:4])[0]
    info["magic"] = hex(magic)
    if magic == 0xD00DFEED:
        info["kind"] = "Flattened DeviceTree (FDT-like)"
        totalsize, off_struct, off_strings, off_rsv = struct.unpack('>IIII', d[4:20])
        version, last_comp, boot_cpuid, size_strings, size_struct = struct.unpack('>IIIII', d[20:40])
        info.update(total= totalsize, version=version, last_comp=last_comp,
                    size_strings=size_strings, size_struct=size_struct)
        # scan strings block for model/compatible
        sb = d[off_strings:off_strings+size_strings]
        txt = sb.decode('latin-1')
        keys = [k for k in txt.split('\x00') if k]
        info["interesting"] = [k for k in keys if any(t in k.lower() for t in
            ('arm-io','aic','pmu','dcp','sep','aop','gpu','disph0','i2c','spi','uart','wdt','pmgr','dart','lcd','clcd','backlight','touch','multitouch'))][:80]
        info["n_keys"] = len(keys)
    else:
        info["kind"] = "unknown"
    return info

def walk(path):
    data = open(path,'rb').read()
    print("="*78)
    print("FILE:", path, "size=%d" % len(data))
    im = parse_im4p(data)
    for k in ("magic","type","desc","raw_len","seq_len","payload_magic","payload_magic_ascii","extra_octets","strings"):
        if k in im: print("  %-20s %s" % (k, im[k]))
    d = im.get("data")
    if d:
        print("  %-20s %s" % ("payload_len", len(d)))
        if im.get("type") == "dtre" or path.endswith("DeviceTree.d22ap.im4p"):
            print("  DT:", apple_dt_probe(d))
        else:
            print("  MACHO:", macho_probe(d))
    print()

for p in sys.argv[1:]:
    if os.path.isdir(p):
        for root,_,files in os.walk(p):
            for f in sorted(files):
                walk(os.path.join(root,f))
    else:
        walk(p)
