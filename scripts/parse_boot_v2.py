#!/usr/bin/env python3
"""Parse Android boot header v0/v1/v2 (MTK style) and extract kernel / dtb."""
import struct, sys

def parse(p):
    d = open(p,'rb').read()
    print("== %s size=%d" % (p, len(d)))
    assert d[:8] == b'ANDROID!', d[:8]
    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr,
     tags_addr, page_size, header_version, os_version) = struct.unpack('<10I', d[8:48])
    name = d[0x30:0x40].split(b'\x00')[0].decode('latin-1','replace')
    cmdline = d[0x40:0x240].split(b'\x00')[0].decode('latin-1','replace')
    extra = d[0x260:0x660].split(b'\x00')[0].decode('latin-1','replace')
    print("  header_version=%d page_size=%d" % (header_version, page_size))
    print("  kernel size=%d addr=%#x" % (kernel_size, kernel_addr))
    print("  ramdisk size=%d addr=%#x" % (ramdisk_size, ramdisk_addr))
    print("  second size=%d addr=%#x tags=%#x" % (second_size, second_addr, tags_addr))
    print("  name=%r os_version=%#x" % (name, os_version))
    print("  cmdline=%r" % cmdline[:300])
    print("  extra=%r" % extra[:300])
    dtb_size = dtb_addr = 0
    rec_size = rec_off = hdr_size = 0
    if header_version >= 1:
        rec_size, rec_off, hdr_size = struct.unpack('<III', d[0x660:0x66c])
    if header_version >= 2:
        dtb_size, dtb_addr = struct.unpack('<II', d[0x66c:0x674])
        print("  dtb size=%d addr=%#x" % (dtb_size, dtb_addr))
    off = page_size
    k = d[off:off+kernel_size]; off += (kernel_size + page_size-1)//page_size*page_size
    r = d[off:off+ramdisk_size]; off += (ramdisk_size + page_size-1)//page_size*page_size
    print("  kernel head: %s" % k[:8].hex())
    print("  ramdisk head: %s" % r[:8].hex())
    open(p+'.kernel.gz','wb').write(k)
    if second_size:
        s = d[off:off+second_size]; off += (second_size+page_size-1)//page_size*page_size
        print("  second head: %s" % s[:8].hex())
    if dtb_size:
        dtb = d[off:off+dtb_size]; off += (dtb_size+page_size-1)//page_size*page_size
        print("  dtb head: %s" % dtb[:16].hex())
        open(p+'.dtb','wb').write(dtb)
        print("  wrote %s.dtb (%d bytes)" % (p, len(dtb)))
    print("  remaining bytes: %d" % (len(d)-off))

parse(sys.argv[1])
