#!/usr/bin/env python3
"""Build a single-variable ACK2 experiment from the exact local v69 image.

Only three ARM64 instructions and the same-length probe label change.
No firmware download, kernel enabling, flashing, or device operations.
Requires only Python's standard library.
"""
import argparse
import gzip
import hashlib
import json
import struct
from pathlib import Path

BASE_SHA256 = '2305a48d3127912364e6a020c13610c60a26e0e2f9c41ce6ba6bc59ab21bcd48'
LOADER_LIMIT = 0x40000
PARTITION_SIZE = 32 << 20
# Offsets in decompressed v69 blob, not offsets in boot.img.
# Replacements were independently assembled using clang --target=aarch64-linux-gnu.
PATCHES = (
    (0x7A40, bytes.fromhex('a90f8012'), bytes.fromhex('49108052'),
     'mov w9,#-126 -> mov w9,#0x82; FIFO TX bytes 82 ff -> 82 00'),
    (0x7A5C, bytes.fromhex('28008052'), bytes.fromhex('e8830032'),
     'mov w8,#1 -> mov w8,#0x10001; CFG1 packet_len 1 -> 2, CS idle unchanged'),
    (0x7AF4, bytes.fromhex('731e4092'), bytes.fromhex('733e48d3'),
     'and x19,x19,#0xff -> ubfx x19,x19,#8,#8; ACK from RX byte 1'),
    (0x9291, b'ilitek: 0x82 -> 0x', b'ilitek: ACK2 -> 0x',
     'same-length on-screen experiment label'),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_image(data):
    require(len(data) == PARTITION_SIZE, 'expected 32 MiB boot partition image')
    require(data[:8] == b'ANDROID!', 'Android boot magic missing')
    ks, ka, rs, ra, ss, sa, tags, page, version = struct.unpack_from('<9I', data, 8)
    require(version == 2 and page == 2048, 'expected header v2 / 2048-byte pages')
    require(data[-64:-60] == b'AVBf', 'AVB footer missing')
    rdo = struct.unpack_from('<I', data, 1632)[0]
    dtb = struct.unpack_from('<I', data, 1648)[0]
    sizes = [ks, rs, ss, rdo, dtb]
    at = page
    parts = []
    for size in sizes:
        require(at + size <= len(data) - 64, 'component exceeds partition')
        parts.append(data[at:at + size])
        at += (size + page - 1) // page * page
    major, minor, original_size, vo, vs = struct.unpack_from('>IIQQQ', data, len(data) - 60)
    require(major == 1 and minor == 0, 'unexpected AVB footer version')
    require(at <= vo and vo + vs <= len(data) - 64, 'invalid VBMeta placement')
    require(data[vo:vo + 4] == b'AVB0', 'VBMeta magic missing')
    return page, parts, data[vo:vo + vs], (original_size, vo, vs)


def patch_blob(blob):
    out = bytearray(blob)
    for offset, old, new, description in PATCHES:
        require(len(old) == len(new), 'patch length changes: ' + description)
        require(offset + len(old) < LOADER_LIMIT, 'patch outside loader')
        require(blob[offset:offset + len(old)] == old,
                'v69 instruction/string mismatch at 0x%x' % offset)
        out[offset:offset + len(new)] = new
    return bytes(out)


def build_image(data):
    require(sha256(data) == BASE_SHA256, 'input SHA256 is not the audited v69 baseline')
    page, parts, vbmeta, _ = parse_image(data)
    original = gzip.decompress(parts[0])
    patched = patch_blob(original)
    require(original[LOADER_LIMIT:] == patched[LOADER_LIMIT:], 'Android or XNU payload changed')
    for offset in (0x10, 0x28, 0x30):
        require(original[offset:offset + 8] == patched[offset:offset + 8], 'blob header changed')
    require(original.count(b'touchscreen=0') == patched.count(b'touchscreen=0') == 2,
            'expected two unchanged touchscreen=0 boot-args')
    require(b'touchscreen=3' not in patched[:LOADER_LIMIT], 'kernel touch enabled unexpectedly')
    parts[0] = gzip.compress(patched, compresslevel=9, mtime=0)
    header = bytearray(data[:page])
    struct.pack_into('<I', header, 8, len(parts[0]))
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part)
        digest.update(struct.pack('<I', len(part)))
    header[576:608] = digest.digest() + bytes(12)
    content = bytes(header) + b''.join(p + bytes(-len(p) % page) for p in parts)
    vo = (len(content) + page - 1) // page * page
    require(vo + len(vbmeta) <= PARTITION_SIZE - 64, 'image overflows partition')
    out = bytearray(PARTITION_SIZE)
    out[:len(content)] = content
    out[vo:vo + len(vbmeta)] = vbmeta
    struct.pack_into('>4sIIQQQ', out, PARTITION_SIZE - 64,
                     b'AVBf', 1, 0, vo, vo, len(vbmeta))
    result = bytes(out)
    _, checked_parts, checked_vbmeta, _ = parse_image(result)
    require(gzip.decompress(checked_parts[0]) == patched, 'round-trip blob mismatch')
    _, old_parts, old_vbmeta, _ = parse_image(data)
    require(checked_parts[1:] == old_parts[1:], 'ramdisk / second / recovery DTBO / DTB changed')
    require(checked_vbmeta == old_vbmeta, 'VBMeta bytes changed')
    changed = [i for i, (a, b) in enumerate(zip(original[:LOADER_LIMIT], patched[:LOADER_LIMIT])) if a != b]
    manifest = {
        'experiment': 'ACK2 only; touch input still disabled',
        'baseline_sha256': sha256(data), 'output_sha256': sha256(result),
        'image_bytes': len(result), 'blob_changed_bytes': len(changed),
        'blob_changed_offsets': changed,
        'patches': [{'offset': hex(o), 'before': a.hex(), 'after': b.hex(), 'reason': why}
                    for o, a, b, why in PATCHES],
        'blob_header_preserved': True, 'android_and_xnu_payload_identical': True,
        'other_boot_components_identical': True, 'vbmeta_identical': True,
        'avb_note': 'VBMeta copied, not re-signed; content hash descriptors may be stale, same as v69.',
        'hardware_result': 'NOT TESTED',
    }
    return result, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    require(args.baseline.resolve() != args.output.resolve(), 'keep the baseline separate')
    require(not args.output.exists(), 'output exists; use a new path')
    manifest_path = args.output.with_suffix('.manifest.json')
    require(not manifest_path.exists(), 'manifest exists; use a new output path')
    result, manifest = build_image(args.baseline.read_bytes())
    args.output.write_bytes(result)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
