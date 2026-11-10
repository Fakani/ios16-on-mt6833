#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
HERE=Path(__file__).resolve().parent

class ReportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang'),'clang required')
    def test_stream_formats_filters_and_irq_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'report-peer'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_DIAG_HOST',
                            '-I'+str(HERE.parent/'include'),str(HERE.parent/'include/touch-report-capture.c'),
                            str(HERE.parent/'tests/ilitek_report_peer.c'),'-o',str(output)],
                           check=True,capture_output=True)
            subprocess.run([str(output)],check=True,capture_output=True)

    def test_capture_requires_verified_firmware_mode(self):
        from make_touch_gate_images import compile_diagnostic
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):compile_diagnostic(0,Path(tmp),report_capture=1)

if __name__=='__main__':unittest.main(verbosity=2)
