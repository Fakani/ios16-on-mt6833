#!/usr/bin/env python3
"""E1: take the byte-exact v43 image, change ONLY the boot-arg touchscreen=3 -> touchscreen=0,
repack with the identical layout (header v2 / page 2048 / same ramdisk / dtb / AVB tail),
and prove the kernel blob differs by exactly one byte.

usage: make_e1_image.py <v43.img> <out.img>
"""
import gzip, hashlib, struct, sys, os

SRC, OUT = sys.argv[1], sys.argv[2]
d = open(SRC, 'rb').read()
assert d[:8] == b'ANDROID!', d[:8]
ks, ka, rs, ra, ss, sa, tags, page, hv = struct.unpack_from('<9I', d, 8)
rdo = struct.unpack_from('<I', d, 1632)[0]   # recovery_dtbo_size
dtb = struct.unpack_from('<I', d, 1648)[0]   # dtb_size
print('header v%d page=%d kernel=%d ramdisk=%d second=%d rdo=%d dtb=%d' % (hv, page, ks, rs, ss, rdo, dtb))

def pages(n): return (n + page - 1)//page*page
off = page
kernel = d[off:off+ks]; off += pages(ks)
ramdisk = d[off:off+rs]; off += pages(rs)
second  = d[off:off+ss]; off += pages(ss)
rdo_b   = d[off:off+rdo]; off += pages(rdo)
dtb_b   = d[off:off+dtb]

blob = gzip.decompress(kernel) if kernel[:2] == b'\x1f\x8b' else kernel
print('kernel blob: %d bytes, head %s' % (len(blob), blob[:4].hex()))
n = blob.count(b'touchscreen=3')
print('occurrences of "touchscreen=3":', n)
# v43 的 rodata 里有两份完整的 boot-args 串（一份给屏幕打印，一份真正传给 XNU），
# 两处都要改，否则语义不一致。
assert n == 2, 'expected exactly two boot-arg occurrences, got %d' % n
patched = blob.replace(b'touchscreen=3', b'touchscreen=0')
assert len(patched) == len(blob)

diff = [i for i in range(len(blob)) if blob[i] != patched[i]]
print('differing byte offsets:', diff, '->', [chr(blob[i]) for i in diff], '->', [chr(patched[i]) for i in diff])
assert len(diff) == n, 'only the digit must change'

new_kernel = gzip.compress(bytes(patched), 9, mtime=0)

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

# AVB tail, copied verbatim from the source image
sf = d[-64:]
mj, mn, ois, svo, svs = struct.unpack_from('>IIQQQ', sf, 4)
vbmeta = d[svo:svo+svs]
new_vo = (len(content) + 2047)//2048*2048
assert new_vo + svs + 64 <= 32 << 20, 'payload too large for 32 MiB boot'

img = bytearray(32 << 20)
img[:len(content)] = content
img[new_vo:new_vo+svs] = vbmeta
footer = bytearray(64)
struct.pack_into('>4sIIQQQ', footer, 0, b'AVBf', 1, 0, new_vo, new_vo, svs)
img[-64:] = footer
os.makedirs(os.path.dirname(OUT) or '.', exist_ok=True)
open(OUT, 'wb').write(img)

print('source vbmeta offset=%d size=%d -> new offset=%d' % (svo, svs, new_vo))
print('wrote %s (%d bytes)' % (OUT, len(img)))
print('sha256', hashlib.sha256(img).hexdigest())

# --- verification: re-parse the output and diff the kernel blobs ---
v = open(OUT, 'rb').read()
ks2 = struct.unpack_from('<I', v, 8)[0]
k2 = v[page:page+ks2]
b2 = gzip.decompress(k2)
d2 = [i for i in range(len(blob)) if blob[i] != b2[i]]
print('VERIFY: output kernel blob %d bytes (src %d), differing bytes: %d %s' % (len(b2), len(blob), len(d2), d2))
print('VERIFY: touchscreen=3 remaining:', b2.count(b'touchscreen=3'), '| touchscreen=0:', b2.count(b'touchscreen=0'))
# non-kernel sections must be byte identical
for name, a, b in (('ramdisk', ramdisk, v[page+pages(ks2): page+pages(ks2)+rs])):
    print('VERIFY: %s identical: %s' % (name, a == b))
