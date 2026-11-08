#!/bin/bash
# mkboot-mt6833.sh -- 给 OPPO PGCM10 (MT6833 / k6833v1_64) 打 header v2 boot.img
#
# 依据：本机实测 boot.img 头 + a22x-mainline/boot/mkboot.sh 的做法
#   - header v2, page 2048
#   - base 0x40000000, kernel_offset 0x00080000 (LK 硬断言内核落在 0x40080000)
#   - ramdisk_offset 0x11100000 (0x51100000), tags_offset 0x07c80000 (0x47c80000)
#   - dtb 段必须是 Android DT table (magic 0xd7b7ab1e)
#   - AVB hash footer, algorithm NONE, 补到 32 MiB boot 分区
#   - mainline Image 的 text_offset=0 需要 2 MiB 对齐 -> 前置 0x180000 字节 shim
#
# 用法：
#   KERNEL=... DTB=... RAMDISK=... ./mkboot-mt6833.sh <tag>
#   ./mkboot-mt6833.sh linux-simplefb
#
# 依赖：mkbootimg, unpack_bootimg, avbtool (AOSP), python3, gzip, shasum

set -euo pipefail
cd "$(dirname "$0")"

BOOT_PART_SIZE=33554432          # 32 MiB，实测 boot 分区大小
BASE=0x40000000
KERNEL_OFFSET=0x00080000
RAMDISK_OFFSET=0x11100000
TAGS_OFFSET=0x07c80000
PAGE_SIZE=2048

TAG=${1:-test}
IMAGES=${IMAGES:-images}
OUT=${OUT:-out}
KERNEL=${KERNEL:-$OUT/arch/arm64/boot/Image.gz}
DTB=${DTB:-$OUT/arch/arm64/boot/dts/mediatek/mt6833-oplus-pgcm10.dtb}
RAMDISK=${RAMDISK:-initramfs.cpio.gz}

# cma=96M: 原生 DSI 管线需要
# fbcon=logo-count:0 + vt.global_cursor_default=0: 别让内核日志糊住面板
# clk_ignore_unused pd_ignore_unused: 厂商时钟策略
EXTRA_CMDLINE=${EXTRA_CMDLINE-cma=96M}

CMD="bootopt=64S3,32N2,64N2 earlycon=mt6833uart,0x11002000 console=ttyS0,921600n8 \
fbcon=logo-count:0 vt.global_cursor_default=0 loglevel=8 ignore_loglevel \
clk_ignore_unused pd_ignore_unused printk.devkmsg=on${EXTRA_CMDLINE:+ $EXTRA_CMDLINE}"

mkdir -p "$IMAGES"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== kernel : $KERNEL"
echo "== dtb    : $DTB"
echo "== ramdisk: $RAMDISK"

# ---------- 1. DTB -> Android DT table ----------
python3 - "$DTB" "$WORK/dtb.table" <<'PY'
import struct, sys
dtb = open(sys.argv[1], 'rb').read()
assert dtb[:4] == b'\xd0\x0d\xfe\xed', 'not an FDT: %r' % dtb[:4]
hdr, ent = 0x20, 0x20
off = hdr + ent
total = off + len(dtb)
table = struct.pack('>8I', 0xd7b7ab1e, total, hdr, ent, 1, hdr, 2048, 0)
table += struct.pack('>8I', len(dtb), off, 0, 0, 0, 0, 0, 0)
open(sys.argv[2], 'wb').write(table + dtb)
print('   DT table: %d bytes (dtb %d)' % (total, len(dtb)))
PY

# ---------- 2. Image.gz -> 加 0x180000 shim ----------
python3 - "$KERNEL" "$WORK/Image.gz" <<'PY'
import gzip, struct, sys
raw = open(sys.argv[1], 'rb').read()
img = gzip.decompress(raw) if raw[:2] == b'\x1f\x8b' else raw
if img[0x38:0x3c] != b'ARMd':
    sys.exit('not an arm64 Image (magic at 0x38 != ARMd)')
pad = 0x180000
text_offset, image_size, flags = struct.unpack('<QQQ', img[8:32])
if text_offset != 0:
    print('   text_offset=%#x, no shim needed' % text_offset)
    shimmed = img
else:
    hdr = struct.pack('<IIQQQQQQII', 0x14000000 | (pad >> 2), 0, 0,
                      pad + image_size, flags, 0, 0, 0, 0x644d5241, 0)
    shimmed = hdr + bytes(pad - len(hdr)) + img
    print('   shim added: 0x%x bytes' % pad)
with gzip.open(sys.argv[2], 'wb', compresslevel=9) as f:
    f.write(shimmed)
PY

# ---------- 3. 兼容 LK 的 decap_dtb_from_kernel 回退路径 ----------
cat "$WORK/Image.gz" "$DTB" > "$WORK/Image.gz-dtb"

# ---------- 4. mkbootimg ----------
mkbootimg \
  --header_version 2 \
  --os_version 12.0.0 --os_patch_level 2025-01 \
  --kernel "$WORK/Image.gz-dtb" \
  --ramdisk "$RAMDISK" \
  --dtb "$WORK/dtb.table" \
  --pagesize $PAGE_SIZE \
  --base $BASE \
  --kernel_offset $KERNEL_OFFSET \
  --ramdisk_offset $RAMDISK_OFFSET \
  --tags_offset $TAGS_OFFSET \
  --dtb_offset $TAGS_OFFSET \
  --cmdline "$CMD" \
  -o "$IMAGES/boot-mt6833-$TAG.img.raw"

raw_size=$(wc -c < "$IMAGES/boot-mt6833-$TAG.img.raw")
if [ "$raw_size" -gt $((BOOT_PART_SIZE - 65536)) ]; then
    echo "ERROR: image too large: $raw_size > $((BOOT_PART_SIZE - 65536))" >&2
    exit 1
fi

# ---------- 5. AVB hash footer ----------
cp "$IMAGES/boot-mt6833-$TAG.img.raw" "$IMAGES/boot-mt6833-$TAG.img"
SALT=$(shasum -a 256 "$IMAGES/boot-mt6833-$TAG.img.raw" | cut -d' ' -f1)
avbtool add_hash_footer \
  --image "$IMAGES/boot-mt6833-$TAG.img" \
  --partition_name boot \
  --partition_size $BOOT_PART_SIZE \
  --algorithm NONE \
  --salt "$SALT"
rm -f "$IMAGES/boot-mt6833-$TAG.img.raw"

unpack_bootimg --boot_img "$IMAGES/boot-mt6833-$TAG.img" --out "$WORK/unpacked" 2>/dev/null \
  | grep -E "header version|kernel load|ramdisk load|tags load|dtb (size|address)|page size|command line" || true

ls -l "$IMAGES/boot-mt6833-$TAG.img"
shasum -a 256 "$IMAGES/boot-mt6833-$TAG.img"

cat <<EOF

刷写（**只能 flash，不能 boot**；实测 fastboot boot 会崩 LK）：

  adb reboot bootloader
  fastboot flash boot $IMAGES/boot-mt6833-$TAG.img
  fastboot reboot

回滚：

  fastboot flash boot assets/device/backup/boot.img
  fastboot reboot
EOF
