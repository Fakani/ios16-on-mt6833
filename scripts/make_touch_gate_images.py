#!/usr/bin/env python3
"""Build controlled SPI/GPIO diagnostics from the audited v69 baseline.

G0 only observes the original ACK2 transaction; G1 differs in clearing SPI
PDN bit23. Never enables kernel touch, downloads firmware, or contacts a device.
Requires clang and ld.lld. Only use with this exact baseline.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from make_touch_ack2_image import (BASE_SHA256, LOADER_LIMIT, PARTITION_SIZE,
                                  build_image, parse_image, require, sha256)

HERE = Path(__file__).resolve().parent
BASE = 0x40080000
INJECTION = 0x20000
INJECTION_LIMIT = 0x24000
CALL = 0x5CC4
CAPTURE = 0x7ACC


def branch(source, target, link=False):
    delta = target - source
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), 'branch out of range')
    return struct.pack('<I', (0x94000000 if link else 0x14000000) | ((delta // 4) & 0x3ffffff))


def compile_diagnostic(gate, tmp, big_font=0, ice_probe=0, finish_ie=0, reset_readback=0, gpio_probe=0, gpio_rw_test=0, firmware_load=0, report_capture=0):
    require(not report_capture or firmware_load, 'report capture requires live firmware loader')
    require(not firmware_load or (gpio_probe and gpio_rw_test and big_font and not ice_probe),
            'firmware load requires isolated GPIO and dummy gate')
    obj, capture, script, elf, binary = [tmp / x for x in ('diag.o', 'capture.o', 'link.ld', 'diag.elf', 'diag.bin')]
    common = ['clang', '--target=aarch64-linux-gnu', '-ffreestanding', '-nostdlib',
              '-fno-builtin', '-mgeneral-regs-only', '-mstrict-align', '-Oz', '-Wall', '-Wextra', '-Werror',
              '-DSPI_IRQ_ENABLE=' + str(finish_ie), '-DSPI_RESET_READBACK=' + str(reset_readback),
              '-DBB_RW_TEST=' + str(gpio_rw_test), '-DBB_FW_LOAD=' + str(firmware_load), '-DBB_REPORT_CAPTURE=' + str(report_capture)]
    diagnostic_source = 'touch-gpio-probe.c' if gpio_probe else 'touch-gate-diagnostic.c'
    subprocess.run(common + ['-DGATE_FIX=' + str(gate), '-DBIG_FONT=' + str(big_font),
                             '-DICE_PROBE=' + str(ice_probe), '-c',
                             str(HERE.parent / 'include' / diagnostic_source), '-o', str(obj)],
                   check=True, capture_output=True)
    extras = []
    if firmware_load:
        fw_object = tmp / 'firmware.o'
        subprocess.run(common + ['-c',str(HERE.parent/'include/touch-firmware-load.c'),
                                 '-o',str(fw_object)],check=True,capture_output=True)
        extras.append(str(fw_object))
    if report_capture:
        report_obj = tmp / 'report.o'
        subprocess.run(common + ['-c',str(HERE.parent/'include/touch-report-capture.c'),
                                 '-o',str(report_obj)],check=True,capture_output=True)
        extras.append(str(report_obj))
    if ice_probe:
        ice_obj = tmp / 'ice.o'
        subprocess.run(common + ['-c', str(HERE.parent / 'include/touch-ice-probe.c'),
                                 '-o', str(ice_obj)], check=True, capture_output=True)
        extras.append(str(ice_obj))
    subprocess.run(common + ['-c', str(HERE.parent / 'include/touch-capture-rx.S'), '-o', str(capture)], check=True, capture_output=True)
    script.write_text('''ENTRY(touch_gate_diagnostic)
SECTIONS {
 . = 0x400a0000;
 .text : { *(.text*) }
 .rodata : { *(.rodata*) }
 .data : { *(.data*) }
 /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
''')
    definitions = ['--defsym=original_probe=0x400878b0', '--defsym=output_char=0x40085dd8',
                   '--defsym=output_hex=0x40081168', '--defsym=probe_rx_continue=0x40087ad0',
                   '--defsym=console_state=0x4008c000',
                   '--defsym=fw_package=0x400bf000','--defsym=fw_data=0x400a4000']
    command = ['ld.lld', '-T', str(script)] + definitions + [str(obj), str(capture)] + extras
    subprocess.run(command + ['-o', str(elf)], check=True, capture_output=True)
    subprocess.run(command + ['--oformat=binary', '-o', str(binary)], check=True, capture_output=True)
    image = elf.read_bytes()
    require(image[:4] == b'\x7fELF' and image[4:6] == b'\x02\x01', 'expected ELF64 LE')
    entry = struct.unpack_from('<Q', image, 24)[0]
    shoff = struct.unpack_from('<Q', image, 40)[0]
    shentsize, shnum = struct.unpack_from('<HH', image, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', image, shoff + n * shentsize) for n in range(shnum)]
    for section in sections:
        if section[2] & 2 and section[5]:  # SHF_ALLOC, including zero-filled .bss
            require(BASE + INJECTION <= section[3] and
                    section[3] + section[5] <= BASE + INJECTION_LIMIT,
                    'allocated diagnostic section exceeds reserved slot')
    symbols = {}
    for sec in sections:
        if sec[1] != 2:
            continue
        names_section = sections[sec[6]]
        names = image[names_section[4]:names_section[4] + names_section[5]]
        for off in range(sec[4], sec[4] + sec[5], sec[9]):
            name, info, other, index, value, size = struct.unpack_from('<IBBHQQ', image, off)
            label = names[name:names.index(b'\0', name)].decode()
            symbols[label] = value
    require(entry == symbols['touch_gate_diagnostic'], 'ELF entry mismatch')
    payload = binary.read_bytes()
    require(len(payload) < INJECTION_LIMIT - INJECTION, 'diagnostic exceeds bounded slot')
    return payload, entry, symbols['capture_rx']


def repack(baseline, blob, allowed_tail_ranges=()):
    page, parts, vbmeta, _ = parse_image(baseline)
    old_blob = gzip.decompress(parts[0])
    require(len(blob)==len(old_blob),'blob length changed')
    cursor=LOADER_LIMIT
    for start,end in sorted(allowed_tail_ranges):
        require(cursor<=start<end<=len(blob),'invalid allowed tail window')
        require(blob[cursor:start]==old_blob[cursor:start],'change outside allowed kernel window')
        cursor=end
    require(blob[cursor:]==old_blob[cursor:],'Android / XNU tail changed')
    for o in (0x10, 0x28, 0x30):
        require(blob[o:o + 8] == old_blob[o:o + 8], 'loader header changed')
    parts[0] = gzip.compress(blob, 9, mtime=0)
    header = bytearray(baseline[:page])
    struct.pack_into('<I', header, 8, len(parts[0]))
    digest = hashlib.sha1()
    for p in parts:
        digest.update(p); digest.update(struct.pack('<I', len(p)))
    header[576:608] = digest.digest() + bytes(12)
    content = bytes(header) + b''.join(p + bytes(-len(p) % page) for p in parts)
    vo = (len(content) + page - 1) // page * page
    require(vo + len(vbmeta) <= PARTITION_SIZE - 64, 'partition overflow')
    out = bytearray(PARTITION_SIZE)
    out[:len(content)] = content
    out[vo:vo + len(vbmeta)] = vbmeta
    struct.pack_into('>4sIIQQQ', out, PARTITION_SIZE - 64, b'AVBf', 1, 0, vo, vo, len(vbmeta))
    _, check_parts, check_vbmeta, _ = parse_image(bytes(out))
    require(check_parts[1:] == parts[1:] and check_vbmeta == vbmeta, 'component mismatch')
    require(gzip.decompress(check_parts[0]) == blob, 'blob mismatch')
    return bytes(out)


def build_diagnostic(baseline, gate, big_font=0, ice_probe=0, finish_ie=0, reset_readback=0, gpio_probe=0, gpio_rw_test=0):
    require(not gpio_rw_test or gpio_probe, 'dummy read/write check requires GPIO mode')
    require(not gpio_probe or (big_font and not any((gate, ice_probe, finish_ie, reset_readback))),
            'GPIO diagnostic requires big font and excludes gate/PIO changes')
    require(not finish_ie or ice_probe, 'finish IE requires the isolated ICE probe')
    require(not ice_probe or big_font, 'ICE probe requires big-font reporting')
    require(sha256(baseline) == BASE_SHA256, 'baseline hash mismatch')
    ack2, _ = build_image(baseline)
    _, parts, _, _ = parse_image(ack2)
    blob = bytearray(gzip.decompress(parts[0]))
    require(blob[CALL:CALL + 4] == bytes.fromhex('fb060094'), 'probe caller changed')
    require(blob[CAPTURE:CAPTURE + 4] == bytes.fromhex('93c25fb8'), 'FIFO read changed')
    # Proven from entry code at 0x78/0x7c: clear [0x4008c000,0x400904d8).
    bss_start = struct.unpack_from('<Q', blob, 0xf88)[0]
    bss_end = struct.unpack_from('<Q', blob, 0xf90)[0]
    require((bss_start, bss_end) == (0x4008c000, 0x400904d8), 'BSS literals differ')
    require(bss_end < BASE + INJECTION, 'injection overlaps runtime BSS')
    require(not any(blob[INJECTION:INJECTION_LIMIT]), 'injection slot is not empty')
    with tempfile.TemporaryDirectory() as tmp:
        payload, entry, capture = compile_diagnostic(gate, Path(tmp), big_font, ice_probe, finish_ie, reset_readback, gpio_probe, gpio_rw_test)
    blob[INJECTION:INJECTION + len(payload)] = payload
    blob[CALL:CALL + 4] = branch(BASE + CALL, entry, link=True)
    blob[CAPTURE:CAPTURE + 4] = branch(BASE + CAPTURE, capture)
    result = repack(baseline, bytes(blob))
    manifest = {'gate_fix': gate, 'big_font': big_font, 'ice_probe': ice_probe, 'finish_ie': finish_ie,
                'reset_readback': reset_readback, 'gpio_probe': gpio_probe, 'gpio_rw_test': gpio_rw_test,
                'output_sha256': sha256(result), 'image_bytes': len(result),
                'injection_offset': hex(INJECTION), 'injection_bytes': len(payload),
                'entry': hex(entry), 'capture_rx': hex(capture),
                'bss_bounds': [hex(bss_start), hex(bss_end)],
                'android_xnu_tail_identical': True, 'touchscreen': 0,
                'capture_extra_fifo_reads': 0, 'max_ice_transactions': 8 if ice_probe else 0,
                'max_gpio_frames': (17 if gpio_rw_test else 9) if gpio_probe else 0,
                'gpio_pins': [12, 13, 97, 98] if gpio_probe else [],
                'hardware_result': 'NOT TESTED'}
    return result, manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--gate-fix', choices=(0, 1), type=int, default=0)
    p.add_argument('--big-font', action='store_true')
    p.add_argument('--ice-probe', action='store_true')
    p.add_argument('--finish-ie', action='store_true')
    p.add_argument('--reset-readback', action='store_true')
    p.add_argument('--gpio-probe', action='store_true')
    p.add_argument('--gpio-rw-test', action='store_true')
    a = p.parse_args()
    manifest_path = a.output.with_suffix('.manifest.json')
    require(not a.output.exists() and not manifest_path.exists(), 'output exists')
    result, manifest = build_diagnostic(a.baseline.read_bytes(), a.gate_fix, int(a.big_font), int(a.ice_probe), int(a.finish_ie), int(a.reset_readback), int(a.gpio_probe), int(a.gpio_rw_test))
    a.output.write_bytes(result)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
