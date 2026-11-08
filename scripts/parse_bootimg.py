#!/usr/bin/env python3
"""Parse Android boot.img / vendor_boot.img / dtbo.img from the OPPO PGCM10 backup."""
import struct, sys, os

def parse_boot(p):
    d = open(p,'rb').read()
    magic = d[:8]
    print("== %s size=%d magic=%r" % (p, len(d), magic))
    if magic == b'ANDROID!':
        kernel_size, ramdisk_size, os_version, header_size = struct.unpack('<IIII', d[8:24])
        reserved = struct.unpack('<IIII', d[24:40])
        header_version, = struct.unpack('<I', d[40:44])
        cmdline = d[44:44+1536].split(b'\x00')[0].decode('latin-1','replace')
        print("   boot header v%d header_size=%d kernel=%d ramdisk=%d os_ver=%#x" % (header_version, header_size, kernel_size, ramdisk_size, os_version))
        print("   cmdline: %s" % cmdline[:400])
        print("   reserved: %s" % (reserved,))
        page = 2048
        if header_version >= 3:
            off = header_size
            k = d[off:off+kernel_size]; off += (kernel_size + page - 1)//page*page
            r = d[off:off+ramdisk_size]
            print("   kernel head: %s" % k[:16].hex())
            print("   ramdisk head: %s" % r[:8].hex())
            # look for appended DTB / DT table inside kernel area
            idx = k.find(b'\xd0\x0d\xfe\xed')
            print("   FDT magic inside kernel blob at: %s" % (idx if idx>=0 else 'none'))
            if idx >= 0:
                dtb = k[idx:]
                open(p + '.dtb','wb').write(dtb); print("   wrote %s.dtb (%d bytes)" % (p, len(dtb)))
        else:
            off = 2048
            k = d[off:off+kernel_size]
            print("   kernel head: %s" % k[:16].hex())
            idx = k.find(b'\xd0\x0d\xfe\xed')
            if idx >= 0:
                open(p+'.dtb','wb').write(k[idx:]); print("   wrote %s.dtb" % p)
    elif magic == b'VNDRBOOT':
        header_version, page_size, kernel_addr, ramdisk_addr, vendor_ramdisk_size = struct.unpack('<IIIII', d[8:28])
        cmdline = d[28:28+2048].split(b'\x00')[0].decode('latin-1','replace')
        tags_addr, = struct.unpack('<I', d[2076:2080])
        name = d[2080:2144].split(b'\x00')[0].decode('latin-1','replace')
        header_size, dtb_size = struct.unpack('<II', d[2144:2152])
        dtb_addr, = struct.unpack('<Q', d[2152:2160])
        print("   vendor_boot v%d page=%d hdr=%d dtb_size=%d dtb_addr=%#x name=%s" % (header_version, page_size, header_size, dtb_size, dtb_addr, name))
        print("   cmdline: %s" % cmdline[:500])
        off = (header_size + page_size - 1)//page_size*page_size
        vr = d[off:off+vendor_ramdisk_size]; off += (vendor_ramdisk_size+page_size-1)//page_size*page_size
        dtb = d[off:off+dtb_size]
        print("   dtb head: %s" % dtb[:16].hex())
        open(p+'.dtb','wb').write(dtb)
        print("   wrote %s.dtb (%d bytes)" % (p, len(dtb)))
        if header_version >= 4:
            o2 = off + (dtb_size+page_size-1)//page_size*page_size
            tbl_size, n_ent, ent_size, bc_size = struct.unpack('<IIII', d[o2:o2+16])
            print("   ramdisk_table=%d entries=%d ent_size=%d bootconfig=%d" % (tbl_size, n_ent, ent_size, bc_size))
    elif magic[:4] == b'\xd7\xb7\xab\x1e' or True:
        # dtbo partition: may start with a raw DTB or a table
        print("   first16: %s" % d[:16].hex())
        idx = d.find(b'\xd0\x0d\xfe\xed')
        print("   FDT magic at %s" % idx)
        if idx >= 0:
            open(p+'.dtb','wb').write(d[idx:])
            print("   wrote %s.dtb" % p)

for p in sys.argv[1:]:
    if os.path.exists(p): parse_boot(p)
