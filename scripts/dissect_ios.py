#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iOS 16.5 (iPhone10,3 / d22ap) boot-artifact dissection:
   IM4P unwrap -> LZFSE decode (via macOS libcompression) -> Mach-O fileset / Apple FDT probe."""
import sys, os, struct, ctypes, plistlib, collections

# ---------- libcompression binding ----------
_lib = ctypes.CDLL('/usr/lib/libcompression.dylib')
_lib.compression_decode_buffer.restype = ctypes.c_size_t
_lib.compression_decode_buffer.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                           ctypes.c_void_p, ctypes.c_size_t,
                                           ctypes.c_void_p, ctypes.c_int]
ALGOS = {'lz4':0x100, 'zlib':0x200, 'lzma':0x400, 'lzfse':0x800, 'lzvn':0x900, 'lz4raw':0x101}

def lzfse_decode(src: bytes, guess=64*1024*1024):
    out = ctypes.create_string_buffer(guess)
    n = _lib.compression_decode_buffer(out, guess, src, len(src), None, ALGOS['lzfse'])
    if n == 0:
        for k in ('lzvn','lz4','lzma','zlib'):
            n = _lib.compression_decode_buffer(out, guess, src, len(src), None, ALGOS[k])
            if n: return out.raw[:n], k
        return None, None
    return out.raw[:n], 'lzfse'

# ---------- IM4P ----------
def im4p_unwrap(data: bytes):
    i = data.find(b'IM4P')
    if i < 0: return None
    p = i - 2  # back up to the IA5String tag/length of the magic
    def ia5(p):
        assert data[p] == 0x16, hex(data[p])
        l = data[p+1]; p += 2
        if l & 0x80:
            n = l & 0x7f; l = int.from_bytes(data[p:p+n],'big'); p += n
        return data[p:p+l].decode('ascii','replace'), p+l
    def octet(p):
        assert data[p] == 0x04, hex(data[p])
        l = data[p+1]; p += 2
        if l & 0x80:
            n = l & 0x7f; l = int.from_bytes(data[p:p+n],'big'); p += n
        return data[p:p+l], p+l
    magic, p = ia5(p)
    typ, p = ia5(p)
    desc, p = ia5(p)
    payload, p = octet(p)
    info = {'magic':magic,'type':typ,'desc':desc,'payload_len':len(payload)}
    try:
        kb, p2 = octet(p); info['keybag'] = kb.hex()
    except Exception:
        info['keybag'] = None
    return info, payload

# ---------- Mach-O ----------
LC_FILESET_ENTRY = 0x35
def macho_fileset(d):
    magic = struct.unpack('<I', d[:4])[0]
    if magic != 0xFEEDFACF: return None
    cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack('<IIIIII', d[4:28])
    res = {'cputype':hex(cputype),'cpusubtype':hex(cpusub&0xffffffff),'filetype':filetype,
           'filetype_name':{0xc:'MH_FILESET',0xb:'MH_KEXT_BUNDLE',0x2:'MH_EXECUTE',0x6:'MH_DYLIB'}.get(filetype,'?'),
           'ncmds':ncmds,'flags':hex(flags)}
    off = 32; entries = []; plat = []
    for _ in range(ncmds):
        if off+8 > len(d): break
        cmd, sz = struct.unpack('<II', d[off:off+8])
        if cmd == LC_FILESET_ENTRY and sz >= 32:
            vmaddr, fileoff, entry_id_off = struct.unpack('<QQI', d[off+8:off+28])
            # entry_id is a string at the end of the lc
            s = d[off+32:off+sz].split(b'\x00')[0].decode('utf-8','replace')
            entries.append((s, fileoff, vmaddr))
        elif cmd == 0x32:  # LC_BUILD_VERSION
            platform, minos, sdk, ntools = struct.unpack('<IIII', d[off+8:off+24])
            plat.append((platform, "%d.%d.%d"%(minos>>16,(minos>>8)&0xff,minos&0xff)))
        off += sz
    res['platform'] = plat[:2]
    res['fileset_entries'] = entries
    return res

def macho_kext_bundle(d):
    if struct.unpack('<I', d[:4])[0] != 0xFEEDFACF: return None
    cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack('<IIIIII', d[4:28])
    out = {'filetype':filetype,'ncmds':ncmds}
    off = 32; sym = None; bundle = None
    for _ in range(ncmds):
        if off+8 > len(d): break
        cmd, sz = struct.unpack('<II', d[off:off+8])
        if cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack('<IIII', d[off+8:off+24])
            out['nsyms'] = nsyms
            st = d[stroff:stroff+strsize].decode('latin-1','replace').split('\x00')
            out['symbol_sample'] = [x for x in st if x][:12]
        if cmd == 0x1b:  # LC_UUID
            out['uuid'] = d[off+8:off+24].hex()
        off += sz
    return out

# ---------- Apple FDT ----------
FDT_MAGIC = 0xD00DFEED
def fdt_strings(d):
    magic, totalsize, off_struct, off_strings, off_rsv = struct.unpack('>IIIII', d[:20])
    ver, lastcomp, bootcpu, size_strings, size_struct = struct.unpack('>IIIII', d[20:40])
    sb = d[off_struct:off_struct+size_struct]
    strs = d[off_strings:off_strings+size_strings]
    names = strs.decode('latin-1').split('\x00')
    # walk structure block: FDT_BEGIN_NODE=1, END_NODE=2, PROP=3, NOP=4, END=9
    p = 0; path = []; nodes = []; props = []
    def cstr(b, i):
        j = b.index(b'\x00', i); return b[i:j].decode('latin-1'), j+1
    while p < len(sb):
        tok = struct.unpack('>I', sb[p:p+4])[0]; p += 4
        if tok == 1:
            nm, p = cstr(sb, p); p = (p + 3) & ~3
            path.append(nm); nodes.append('/'.join(x for x in path if x))
        elif tok == 2:
            if path: path.pop()
        elif tok == 3:
            ln, nameoff = struct.unpack('>II', sb[p:p+8]); p += 8
            val = sb[p:p+ln]; p = (p + ln + 3) & ~3
            pname = strs[nameoff:strs.index(b'\x00', nameoff)].decode('latin-1')
            props.append(('/'.join(x for x in path if x), pname, val))
        elif tok == 9:
            break
        else:
            break
    return {'total':totalsize,'version':ver,'n_nodes':len(nodes),'n_props':len(props)}, nodes, props

def main(paths):
    for path in paths:
        print('='*80); print('FILE', path, os.path.getsize(path))
        data = open(path,'rb').read()
        info, payload = im4p_unwrap(data)
        print('  IM4P type=%-6s desc=%-40s payload=%d keybag=%s' % (
            info['type'], info['desc'][:40], info['payload_len'],
            'YES' if info['keybag'] else 'no'))
        print('  payload[0:8] =', payload[:8].hex(), repr(payload[:8]))
        blob = payload; comp = None
        if payload[:4] == b'bvx2' or payload[:4] == b'bvx1':
            blob, comp = lzfse_decode(payload)
            print('  decompressed ->', comp, len(blob) if blob else 'FAIL')
            if blob is None: continue
            print('  decompressed[0:8] =', blob[:8].hex(), repr(blob[:8]))
        if blob[:4] == b'\xcf\xfa\xed\xfe':
            fs = macho_fileset(blob)
            if fs:
                print('  MACHO fileset: filetype=%s ncmds=%d platform=%s' % (fs['filetype_name'], fs['ncmds'], fs['platform']))
                ents = fs['fileset_entries']
                print('  fileset entries: %d' % len(ents))
                names = [e[0] for e in ents]
                for n in names[:200]: print('    -', n)
            else:
                print('  MACHO:', macho_kext_bundle(blob))
        elif struct.unpack('>I', blob[:4])[0] == FDT_MAGIC:
            hdr, nodes, props = fdt_strings(blob)
            print('  APPLE FDT:', hdr)
            interesting = [ (n,p) for (n,p,v) in props if p in ('compatible','device_type','model','name','interrupt-parent','reg') ]
            print('  --- compatible strings (first 120) ---')
            seen=set()
            for n,p,v in props:
                if p == 'compatible':
                    s = v.rstrip(b'\x00').decode('latin-1')
                    if s and s not in seen:
                        seen.add(s)
                        print('    %-46s @ %s' % (s[:46], n[:70]))
                        if len(seen) > 130: break

if __name__ == '__main__':
    main(sys.argv[1:])
