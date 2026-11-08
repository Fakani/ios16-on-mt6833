import ctypes, struct, sys, os
lib = ctypes.CDLL('/usr/lib/libcompression.dylib')
lib.compression_decode_buffer.restype = ctypes.c_size_t
lib.compression_decode_buffer.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_int]
LZFSE=0x801

def unwrap(path):
    d=open(path,'rb').read(); i=d.find(b'IM4P'); p=i-2
    def ia5(p):
        l=d[p+1]; p+=2
        if l&0x80:
            n=l&0x7f; l=int.from_bytes(d[p:p+n],'big'); p+=n
        return d[p:p+l].decode(), p+l
    def octet(p):
        l=d[p+1]; p+=2
        if l&0x80:
            n=l&0x7f; l=int.from_bytes(d[p:p+n],'big'); p+=n
        return d[p:p+l], p+l
    m,p=ia5(p); t,p=ia5(p); de,p=ia5(p); pl,p=octet(p)
    return t,de,pl

def dec(payload, cap):
    out=ctypes.create_string_buffer(cap)
    n=lib.compression_decode_buffer(out,cap,payload,len(payload),None,LZFSE)
    return out.raw[:n] if n else None

os.makedirs('assets/decompressed', exist_ok=True)

# DeviceTree
t,de,pl = unwrap('assets/ipsw/Firmware/all_flash/DeviceTree.d22ap.im4p')
dt = dec(pl, 4<<20)
open('assets/decompressed/DeviceTree.d22ap.bin','wb').write(dt)
print('DeviceTree decompressed', len(dt), 'head:', dt[:64].hex())
print('  ascii:', ''.join(chr(c) if 32<=c<127 else '.' for c in dt[:96]))

# kernelcache
t,de,pl = unwrap('assets/ipsw/kernelcache.release.iphone10b')
kc = dec(pl, 512<<20)
print('kernelcache decompressed', len(kc) if kc else None)
if kc:
    open('assets/decompressed/kernelcache.release.iphone10b.bin','wb').write(kc)
    print('  head:', kc[:64].hex())
    magic, nfat = struct.unpack('>II', kc[:8])
    print('  magic=%#x nfat=%d' % (magic, nfat))
    off = 8
    for i in range(nfat):
        cputype, cpusub, offset, size, align = struct.unpack('>IIIII', kc[off:off+20]); off += 20
        print('   arch %d cputype=%#x cpusub=%#x off=%#x size=%#x align=%d' % (i, cputype, cpusub, offset, size, align))
        sub = kc[offset:offset+size]
        m = struct.unpack('<I', sub[:4])[0]
        print('    sub magic %#x' % m)
        if m == 0xFEEDFACF:
            cputype2, cpusub2, filetype, ncmds, sizeofcmds, flags = struct.unpack('<IIIIII', sub[4:28])
            print('    Mach-O filetype=%d ncmds=%d flags=%#x' % (filetype, ncmds, flags))
            o=32; names=[]
            for _ in range(ncmds):
                if o+8>len(sub): break
                cmd,sz = struct.unpack('<II', sub[o:o+8])
                if cmd == 0x35:
                    vmaddr, fileoff, entry_id_off = struct.unpack('<QQI', sub[o+8:o+28])
                    s = sub[o+32:o+sz].split(b'\x00')[0].decode('utf-8','replace')
                    names.append((s,fileoff,vmaddr))
                o+=sz
            print('    fileset entries:', len(names))
            open('assets/decompressed/kext_names.txt','w').write('\n'.join(n[0] for n in names))
            for n in names[:400]:
                print('      ', n[0])
