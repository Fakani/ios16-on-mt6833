#!/usr/bin/env python3
"""Offline tests; never contact, reset, or flash a device."""
import ast
import gzip
import hashlib
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


source_fix = load('patch_ilitek_ack2')
image_fix = load('make_touch_ack2_image')


def historical_probe():
    tree = ast.parse((HERE / 'patch_ilitek_mode0.py').read_text())
    block = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'BLOCK' for t in node.targets))
    return block[block.index('static void ilitek_probe(void)'):]


class SourceTests(unittest.TestCase):
    def test_correction_and_idempotence(self):
        original = historical_probe()
        corrected = source_fix.patch_source(original)
        self.assertIn('spi_xfer(tx, rx, 2)', corrected)
        self.assertIn('out_hex(rx[1])', corrected)
        self.assertIn('out(rx[1] == 0xA3 ?', corrected)
        self.assertEqual(corrected, source_fix.patch_source(corrected))

    def test_keep_surrounding_code(self):
        before = '// unrelated prefix\n'
        after = '\nstatic void other(void) { /* untouched */ }\n'
        corrected = source_fix.patch_source(before + historical_probe() + after)
        self.assertTrue(corrected.startswith(before))
        self.assertTrue(corrected.endswith(after))

    def test_unknown_and_partial_source_fail_closed(self):
        with self.assertRaises(ValueError):
            source_fix.patch_source('int other;')
        with self.assertRaises(ValueError):
            source_fix.patch_source(historical_probe().replace('out_hex(rx);', 'out_hex(0);'))

    @unittest.skipUnless(shutil.which('clang'), 'clang is required for C-level mock execution')
    def test_compiled_probe_uses_second_byte_not_echo(self):
        harness = r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
#define GPIO_BASE 0x10005000u
static unsigned clocks, calls, delays, resets, value, matched;
static uint8_t response[2];
static void wr32(uint32_t a, uint32_t v) { (void)a; (void)v; resets++; }
static void dbg_delay_ms(unsigned n) { delays += n; }
static void spi_pins_to_spi2(void) {}
static int spi_xfer(const uint8_t *tx, uint8_t *rx, uint32_t n) {
    assert(n == 2 && tx[0] == 0x82 && tx[1] == 0);
    clocks += n * 8; calls++; rx[0] = response[0]; rx[1] = response[1]; return 1;
}
static void out(const char *s) { if (strstr(s, "ACK, the chip is alive")) matched++; }
static void out_hex(unsigned n) { value = n; }
'''
        main = r'''
int main(void) {
    response[0] = 0; response[1] = 0xa3; ilitek_probe();
    assert(value == 0xa3 && matched == 1 && clocks == 16);
    response[0] = 0xa3; response[1] = 0; ilitek_probe();
    assert(value == 0 && matched == 1);
    response[0] = 0; response[1] = 0x82; ilitek_probe();
    assert(value == 0x82 && matched == 1);
    assert(calls == 3 && clocks == 48 && delays == 48 && resets == 12);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'probe.c'
            binary = Path(tmp) / 'probe-test'
            path.write_text(harness + source_fix.patch_source(historical_probe()) + main)
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)


class InstructionTests(unittest.TestCase):
    def test_patch_windows_and_frame_parameters(self):
        fake = bytearray(image_fix.LOADER_LIMIT)
        for offset, before, after, _ in image_fix.PATCHES:
            fake[offset:offset + len(before)] = before
        patched = image_fix.patch_blob(bytes(fake))
        self.assertEqual(len(patched), len(fake))
        for offset, before, after, _ in image_fix.PATCHES:
            self.assertEqual(patched[offset:offset + len(after)], after)
        allowed = {i for o, a, b, _ in image_fix.PATCHES for i in range(o, o + len(a))}
        self.assertTrue(all(i in allowed for i, (a, b) in enumerate(zip(fake, patched)) if a != b))
        # UBFX X19,X19,#8,#8: UBFM immr=8, imms=15, src=dst=19.
        inst = struct.unpack_from('<I', patched, 0x7AF4)[0]
        self.assertEqual((inst >> 16) & 63, 8)
        self.assertEqual((inst >> 10) & 63, 15)
        self.assertEqual(inst & 31, 19)
        self.assertEqual((inst >> 5) & 31, 19)

    def test_wrong_instruction_fails_closed(self):
        with self.assertRaises(ValueError):
            image_fix.patch_blob(bytes(image_fix.LOADER_LIMIT))

    @unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld'), 'ARM64 assembler/linker required')
    def test_replacement_words_match_real_arm64_assembler(self):
        assembly = '.text\n.global ack_fix\nack_fix:\n mov w9, #0x82\n mov w8, #0x10001\n ubfx x19, x19, #8, #8\n'
        with tempfile.TemporaryDirectory() as tmp:
            src, obj, binary = [Path(tmp) / x for x in ('fix.S', 'fix.o', 'fix.bin')]
            src.write_text(assembly)
            subprocess.run(['clang', '--target=aarch64-linux-gnu', '-c', str(src), '-o', str(obj)], check=True, capture_output=True)
            subprocess.run(['ld.lld', '--oformat', 'binary', '--image-base=0', '-Ttext=0', '-e', 'ack_fix', str(obj), '-o', str(binary)], check=True, capture_output=True)
            self.assertEqual(binary.read_bytes(), b''.join(p[2] for p in image_fix.PATCHES[:3]))


class ImageTests(unittest.TestCase):
    baseline = HERE.parent.parent / 'images/k9x-ios-v69-CLK.img'

    def test_wrong_image_hash_fails_closed(self):
        with self.assertRaises(ValueError):
            image_fix.build_image(bytes(image_fix.PARTITION_SIZE))

    @unittest.skipUnless(baseline.exists(), 'local v69 image not included in public repository')
    def test_real_baseline_build_and_invariants(self):
        data = self.baseline.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), image_fix.BASE_SHA256)
        result, manifest = image_fix.build_image(data)
        p, before_parts, before_vbmeta, _ = image_fix.parse_image(data)
        p2, after_parts, after_vbmeta, _ = image_fix.parse_image(result)
        before = gzip.decompress(before_parts[0])
        after = gzip.decompress(after_parts[0])
        self.assertEqual(p, p2)
        self.assertEqual(before[image_fix.LOADER_LIMIT:], after[image_fix.LOADER_LIMIT:])
        self.assertEqual(before_parts[1:], after_parts[1:])
        self.assertEqual(before_vbmeta, after_vbmeta)
        self.assertEqual(len(result), 32 << 20)
        self.assertEqual(manifest['hardware_result'], 'NOT TESTED')
        with self.assertRaises(ValueError):
            image_fix.build_image(result)


class GateDiagnosticTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang'), 'clang required')
    def test_wrapper_has_exactly_the_intended_gate_writes(self):
        harness = r'''
#include <stdint.h>
#include <assert.h>
extern void touch_gate_diagnostic(void);
extern volatile uint32_t diag_rx;
static uint32_t clk = 0x83abcd, infra = 0x1234, calls, writes;
uint32_t diag_read(uint64_t a) {
 if (a == 0x10000070u) return clk;
 if (a == 0x100010acu) return infra;
 if (a == 0x11018004u) return 0x10001;
 if (a == 0x11018028u) return 0x10001;
 assert(0); return 0;
}
void diag_write(uint64_t a, uint32_t v) {
 if (writes == 0) { assert(a == 0x10000078u && v == (1u << 23)); clk &= ~v; }
 else { assert(writes == 1 && a == 0x10000004u && v == (1u << 26)); }
 writes++;
}
void original_probe(void) { calls++; assert(diag_rx == 0xffffffffu); diag_rx = 0x8200; }
void output_char(uint32_t c) { (void)c; }
void output_hex(uint64_t v) { (void)v; }
int main(void) {
 touch_gate_diagnostic();
 assert(calls == 1 && diag_rx == 0x8200 && infra == 0x1234);
#if GATE_FIX
 assert(writes == 2 && clk == 0x03abcd);
#else
 assert(writes == 0 && clk == 0x83abcd);
#endif
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source, binary = Path(tmp) / 'mock.c', Path(tmp) / 'mock'
            source.write_text(harness)
            for gate in (0, 1):
                subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                '-DTOUCH_DIAG_HOST', '-DGATE_FIX=' + str(gate),
                                str(HERE.parent / 'include/touch-gate-diagnostic.c'),
                                str(source), '-o', str(binary)], check=True, capture_output=True)
                subprocess.run([str(binary)], check=True, capture_output=True)

    @unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld'), 'ARM64 tools required')
    def test_compiled_hook_preserves_original_fifo_load_and_returns(self):
        gate_fix = load('make_touch_gate_images')
        with tempfile.TemporaryDirectory() as tmp:
            for gate in (0, 1):
                payload, entry, hook = gate_fix.compile_diagnostic(gate, Path(tmp))
                self.assertEqual(entry, gate_fix.BASE + gate_fix.INJECTION)
                hook_offset = hook - entry
                self.assertEqual(payload[hook_offset:hook_offset + 4], bytes.fromhex('93c25fb8'))
                instruction = struct.unpack_from('<I', payload, hook_offset + 12)[0]
                self.assertEqual(instruction >> 26, 5)  # B, not BL (keep LR)
                imm = instruction & 0x3ffffff
                if imm & (1 << 25): imm -= 1 << 26
                self.assertEqual(hook + 12 + imm * 4, 0x40087ad0)
                self.assertLess(len(payload), 0x4000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
