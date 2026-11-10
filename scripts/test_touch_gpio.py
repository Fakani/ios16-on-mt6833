#!/usr/bin/env python3
"""Simulate GPIO banks and a mode-0 SPI peer; never access a real device."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class GpioTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang'), 'clang required')
    def test_protocol_edges_identity_and_restoration(self):
        harness = (HERE.parent / 'tests/mt6833_gpio_peer.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            src,binary = Path(tmp)/'mock.c',Path(tmp)/'mock'
            src.write_text(harness)
            for rw in (0, 1):
                subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_DIAG_HOST',
                                '-DBB_RW_TEST=' + str(rw),
                                str(HERE.parent/'include/touch-gpio-probe.c'),str(src),'-o',str(binary)],
                               check=True,capture_output=True)
                subprocess.run([str(binary)],check=True,capture_output=True)


    def test_gpio_and_fifo_modes_are_mutually_exclusive(self):
        from make_touch_gate_images import build_diagnostic
        with self.assertRaises(ValueError):
            build_diagnostic(b'',0,big_font=1,ice_probe=1,gpio_probe=1)
        with self.assertRaises(ValueError):
            build_diagnostic(b'',1,big_font=1,gpio_probe=1)
        with self.assertRaises(ValueError):
            build_diagnostic(b'',0,big_font=0,gpio_probe=1)

    @unittest.skipUnless(shutil.which('clang') and shutil.which('ld.lld'), 'ARM64 tools required')
    def test_arm64_image_contains_independent_probe_within_reserved_slot(self):
        from make_touch_gate_images import compile_diagnostic
        with tempfile.TemporaryDirectory() as tmp:
            data,entry,hook=compile_diagnostic(0,Path(tmp),big_font=1,gpio_probe=1)
            self.assertGreaterEqual(entry,0x400a0000)
            self.assertLess(entry,0x400a4000)
            self.assertLess(len(data),0x4000)
            self.assertIn(b'v76 GPIO - BIG',data)
            self.assertIn(b'BB bitsteps ',data)
            self.assertEqual(data[hook-0x400a0000:hook-0x400a0000+4],bytes.fromhex('93c25fb8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
