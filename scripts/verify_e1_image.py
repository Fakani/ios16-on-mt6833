import struct, os
A = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/isoA-iosboot-20261105-lab/k9x-ios-v43-GATED.img')
B = 'images/k9x-ios-v43-TS0.img'
a = open(A,'rb').read(); b = open(B,'rb').read()
print('sizes', len(a), len(b))
page = struct.unpack_from('<I', a, 0x24)[0]
# header field-by-field
fields = [('magic',0,8),('kernel_size',8,4),('kernel_addr',12,4),('ramdisk_size',16,4),('ramdisk_addr',20,4),
          ('second_size',24,4),('tags_addr',32,4),('page_size',36,4),('header_version',40,4),
          ('os_version',44,4),('name',48,16),('cmdline',64,512),('id',576,32),('extra_cmdline',608,1024)]
for n,o,l in fields:
    if a[o:o+l] != b[o:o+l]:
        print('HEADER DIFF', n, a[o:o+l].hex(), '->', b[o:o+l].hex())
# sections
ka = struct.unpack_from('<I', a, 8)[0]; kb = struct.unpack_from('<I', b, 8)[0]
rs = struct.unpack_from('<I', a, 16)[0]
rdo = struct.unpack_from('<I', a, 1632)[0]; dtb = struct.unpack_from('<I', a, 1648)[0]
def pages(n): return (n+page-1)//page*page
ra = a[page+pages(ka): page+pages(ka)+rs]
rb = b[page+pages(kb): page+pages(kb)+rs]
print('ramdisk identical:', ra == rb, len(ra))
oa = page+pages(ka)+pages(rs)
ob = page+pages(kb)+pages(rs)
print('dtb identical:', a[oa:oa+dtb] == b[ob:ob+dtb], dtb)
print('avb footer identical:', a[-64:] == b[-64:])
# whole-file diff map
diffs = [i for i in range(min(len(a),len(b))) if a[i] != b[i]]
print('total differing bytes in file:', len(diffs))
if diffs:
    print('first', diffs[0], 'last', diffs[-1])
    # group
    groups=[]; s=diffs[0]; p=diffs[0]
    for i in diffs[1:]:
        if i != p+1: groups.append((s,p)); s=i
        p=i
    groups.append((s,p))
    print('diff groups:', groups[:10], '...' if len(groups)>10 else '')
