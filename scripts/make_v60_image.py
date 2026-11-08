#!/usr/bin/env python3
"""v60 = E1 image with ONLY the loader replaced (loader now sends the 42 panel DCS).
Everything else in the kernel blob (Android Image + XNU payload) stays byte-identical."""
import gzip, hashlib, struct, sys, os

SRC = 'images/k9x-ios-v43-TS0.img'
LOADER = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    '~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel/mtk/loader/mtkloader.bin')
OUT = sys.argv[2] if len(sys.argv) > 2 else 'images/k9x-ios-v60-DSI.img'
CHAIN_OFFSET = 0x40000

d = open(SRC,'rb').read()
assert d[:8] == b'ANDROID!'
ks, ka, rs, ra, ss, sa, tags, page, hv = struct.unpack_from('<9I', d, 8)
rdo = struct.unpack_from('<I', d, 1632)[0]
dtb = struct.unpack_from('<I', d, 1648)[0]
def pages(n): return (n + page - 1)//page*page
off = page
kernel = d[off:off+ks]; off += pages(ks)
ramdisk = d[off:off+rs]; off += pages(rs)
second  = d[off:off+ss]; off += pages(ss)
rdo_b   = d[off:off+rdo]; off += pages(rdo)
dtb_b   = d[off:off+dtb]

blob = bytearray(gzip.decompress(kernel))
orig_blob = bytes(blob)
print('E1 kernel blob: %d bytes' % len(blob))
new = open(LOADER,'rb').read()
assert len(new) <= CHAIN_OFFSET, 'loader too big'
old = bytes(blob[:CHAIN_OFFSET])
# how much of the old loader region was non-zero
old_len = max(i for i,v in enumerate(old) if v) + 1
print('old loader region non-zero up to 0x%x (%d bytes); new loader %d bytes' % (old_len, old_len, len(new)))

tail_before = bytes(blob[CHAIN_OFFSET:])
# The loader's own arm64 Image header lives at 0x00..0x40 -- inside the region we
# are about to overwrite.  chainboot/build_v3.py patches three of those fields
# AFTER the loader is in place (0x10 image_size, 0x28 Android Image length,
# 0x30 payload offset).  A freshly built mtkloader.bin has zeros there, so
# dropping it in without restoring them makes the loader read res2=0/res3=0 and
# jump into nothing -> reboot loop.  Keep the values the E1 blob carries.
hdr_patch = {0x10: struct.unpack_from('<Q', blob, 0x10)[0],
             0x28: struct.unpack_from('<Q', blob, 0x28)[0],
             0x30: struct.unpack_from('<Q', blob, 0x30)[0]}
print('preserving blob header fields: ' + ', '.join('0x%02x=0x%x' % kv for kv in hdr_patch.items()))
blob[:CHAIN_OFFSET] = new + bytes(CHAIN_OFFSET - len(new))
for off, val in hdr_patch.items():
    struct.pack_into('<Q', blob, off, val)
tail_ok = bytes(blob[CHAIN_OFFSET:]) == tail_before
print('android Image + payload untouched:', tail_ok, '(%d bytes)' % len(tail_before))
assert tail_ok

new_kernel = gzip.compress(bytes(blob), 9, mtime=0)
hdr = bytearray(d[:page])
struct.pack_into('<I', hdr, 8, len(new_kernel))
sha = hashlib.sha1()
for p in (new_kernel, ramdisk, second, rdo_b, dtb_b):
    sha.update(p); sha.update(struct.pack('<I', len(p)))
hdr[576:608] = (sha.digest() + b'\0'*32)[:32]

content = (bytes(hdr)
           + new_kernel + b'\0'*(-len(new_kernel) % page)
           + ramdisk    + b'\0'*(-len(ramdisk) % page)
           + second     + b'\0'*(-len(second) % page)
           + rdo_b      + b'\0'*(-len(rdo_b) % page)
           + dtb_b      + b'\0'*(-len(dtb_b) % page))
sf = d[-64:]
mj, mn, ois, svo, svs = struct.unpack_from('>IIQQQ', sf, 4)
vbmeta = d[svo:svo+svs]
new_vo = (len(content) + 2047)//2048*2048
img = bytearray(32 << 20)
img[:len(content)] = content
img[new_vo:new_vo+svs] = vbmeta
footer = bytearray(64)
struct.pack_into('>4sIIQQQ', footer, 0, b'AVBf', 1, 0, new_vo, new_vo, svs)
img[-64:] = footer
open(OUT,'wb').write(img)
print('wrote %s (%d bytes)' % (OUT, len(img)))
print('sha256', hashlib.sha256(img).hexdigest())

# verify: decompressed blob differs only inside [0, CHAIN_OFFSET)
v = open(OUT,'rb').read()
ks2 = struct.unpack_from('<I', v, 8)[0]
b2 = gzip.decompress(v[page:page+ks2])
assert len(b2) == len(orig_blob)
diffs = [i for i in range(len(orig_blob)) if orig_blob[i] != b2[i]]
print('VERIFY differing bytes: %d, range %s' % (len(diffs), (min(diffs), max(diffs)) if diffs else None))
assert max(diffs) < CHAIN_OFFSET, 'change leaked past the loader region'
print('VERIFY: every difference is inside the loader region  OK')
print('VERIFY: touchscreen=0 count', b2.count(b'touchscreen=0'), '| touchscreen=3 count', b2.count(b'touchscreen=3'))
print('VERIFY: panel table present:', b'panel: ILI7807S DSI init' in b2)
