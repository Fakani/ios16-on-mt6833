#!/usr/bin/env python3
"""Strictly inspect this panel's Oplus FwUp + ILITEK AF/B0 Intel HEX.

No device access or firmware writes. Firmware bytes stay outside the public repo.
Block mapping follows OPPO ILITEK9882 hostdl at commit 654f1cb8.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MAX_IMAGE = 160 * 1024
NAMES = {1: 'AP', 2: 'DATA', 3: 'TUNING', 4: 'GESTURE', 5: 'MP'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def crc32_mpeg2(data):
    crc = 0xffffffff
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ (0x04c11db7 if crc & 0x80000000 else 0)) & 0xffffffff
    return crc


def unwrap(raw):
    if raw.startswith(b':'):
        return raw, {'format': 'intel-hex', 'signature_verified': False}
    require(raw[:4] == b'FwUp' and len(raw) >= 208, 'unsupported firmware wrapper')
    version, reserved, size, flags = struct.unpack_from('<4I', raw, 4)
    require((version, reserved, flags) == (1, 0, 0x80000000), 'unsupported FwUp header')
    require(size > 0 and len(raw) == 80 + size + 128, 'FwUp payload length mismatch')
    name = raw[20:80].split(b'\0', 1)[0].decode('ascii')
    payload = raw[80:80 + size]
    require(payload.startswith(b':'), 'FwUp payload is not Intel HEX')
    return payload, {'format': 'oplus-fwup-v1', 'name': name, 'header_bytes': 80,
                     'payload_bytes': size, 'signature_trailer_bytes': 128,
                     'signature_verified': False}


def parse_firmware(raw):
    payload, wrapper = unwrap(raw)
    text = payload.decode('ascii')
    memory = bytearray(b'\xff' * MAX_IMAGE)
    written = bytearray(MAX_IMAGE)
    blocks, fixed = {}, {}
    base, eof, entry, records = 0, False, None, 0
    for number, line in enumerate(text.splitlines(), 1):
        require(line.startswith(':') and not eof, 'record after EOF or bad prefix at line %d' % number)
        try:
            record = bytes.fromhex(line[1:])
        except ValueError as error:
            raise ValueError('bad HEX at line %d' % number) from error
        require(len(record) >= 5 and len(record) == record[0] + 5, 'HEX record length mismatch')
        require(sum(record) % 256 == 0, 'HEX checksum mismatch at line %d' % number)
        count, address, kind = record[0], int.from_bytes(record[1:3], 'big'), record[3]
        data = record[4:-1]
        records += 1
        if kind == 0:
            offset = base + address
            require(offset + count <= MAX_IMAGE, 'HEX data exceeds firmware image bounds')
            for i, value in enumerate(data):
                require(not written[offset + i] or memory[offset + i] == value, 'conflicting HEX overlap')
                memory[offset + i], written[offset + i] = value, 1
        elif kind == 1:
            require(count == 0 and address == 0, 'invalid EOF record')
            eof = True
        elif kind == 4:
            require(count == 2 and address == 0, 'invalid linear-address record')
            base = int.from_bytes(data, 'big') << 16
        elif kind == 2:
            require(count == 2 and address == 0, 'invalid segment-address record')
            segment = int.from_bytes(data, 'big')
            require(segment & 0xfff == 0, 'segment address differs from vendor parser semantics')
            base = segment << 4
        elif kind in (3, 5):
            require(count == 4 and address == 0, 'invalid entry record')
            entry = ((int.from_bytes(data[:2], 'big') << 4) + int.from_bytes(data[2:], 'big')
                     if kind == 3 else int.from_bytes(data, 'big'))
        elif kind == 0xaf:
            require(count == 7, 'unsupported AF block descriptor length')
            start, end, ident = int.from_bytes(data[:3], 'big'), int.from_bytes(data[3:6], 'big'), data[6]
            require(1 <= ident <= 16 and ident not in blocks, 'invalid or duplicate block id')
            require(0 <= start <= end < MAX_IMAGE and end - start + 1 >= 4, 'invalid block extent')
            blocks[ident] = {'id': ident, 'name': NAMES.get(ident, 'BLOCK_%d' % ident),
                             'source_start': start, 'source_end': end, 'length': end - start + 1}
        elif kind == 0xb0:
            require(count == 4 and data[3] in blocks and data[3] not in fixed, 'invalid B0 mapping')
            fixed[data[3]] = int.from_bytes(data[:3], 'big')
        else:
            raise ValueError('unsupported record type 0x%x' % kind)
    require(eof and 1 in blocks, 'EOF or AP block missing')
    image_end = max(block['source_end'] for block in blocks.values()) + 1
    for ident, block in sorted(blocks.items()):
        start, end, length = block['source_start'], block['source_end'], block['length']
        crc = crc32_mpeg2(memory[start:end - 3])
        expected = int.from_bytes(memory[end - 3:end + 1], 'big')
        require(crc == expected, 'firmware block CRC mismatch: ' + block['name'])
        block['crc32'] = '0x%08x' % crc
        block['sha256'] = hashlib.sha256(memory[start:end + 1]).hexdigest()
        block['active_application'] = ident in (1, 2, 3)
        if ident in fixed:
            block['target_start'] = fixed[ident]
        elif ident == 1:
            block['target_start'] = 0
        elif ident == 2:
            block['target_start'] = 0x20610
        elif ident == 3:
            require(2 in blocks, 'TUNING without DATA mapping')
            block['target_start'] = blocks[2]['target_start'] + blocks[2]['length']
        else:
            block['target_start'] = None
        if block['active_application']:
            target = block['target_start']
            limit_lo, limit_hi = (0, 0x20000) if ident == 1 else (0x20000, 0x30000)
            require(limit_lo <= target and target + length <= limit_hi, 'application block outside expected IRAM')
    active = sorted((b for b in blocks.values() if b['active_application']), key=lambda b: b['target_start'])
    require(all(a['target_start'] + a['length'] <= b['target_start'] for a, b in zip(active, active[1:])),
            'application IRAM blocks overlap')
    manifest = {'wrapper': wrapper, 'raw_bytes': len(raw), 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                'payload_sha256': hashlib.sha256(payload).hexdigest(), 'hex_records': records,
                'entry_address': entry, 'decoded_bytes': image_end,
                'application_bytes': sum(b['length'] for b in active),
                'blocks': [blocks[i] for i in sorted(blocks)]}
    return bytes(memory[:image_end]), manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('firmware', type=Path)
    p.add_argument('--manifest', type=Path)
    args = p.parse_args()
    _, manifest = parse_firmware(args.firmware.read_bytes())
    result = json.dumps(manifest, indent=2) + '\n'
    if args.manifest:
        require(not args.manifest.exists(), 'manifest exists')
        args.manifest.write_text(result)
    print(result, end='')


if __name__ == '__main__':
    main()
