#!/usr/bin/env python3
"""Local-device fixture tests for the guarded IRAM loading core."""
from pathlib import Path
import gzip
import shutil
import struct
import subprocess
import tempfile
import unittest
from make_touch_firmware_image import firmware_package,build_firmware_image
from make_touch_ack2_image import parse_image,LOADER_LIMIT

HERE=Path(__file__).resolve().parent
FIRMWARE=HERE.parents[1]/'assets/device/touch/FW_NF_ILI7807S_TIANMA.img'
BASELINE=HERE.parents[1]/'images/k9x-ios-v69-CLK.img'


class LoadTests(unittest.TestCase):
    def test_unexpected_firmware_rejected(self):
        with self.assertRaises(ValueError):firmware_package(b'not device firmware')

    @unittest.skipUnless(FIRMWARE.exists() and shutil.which('clang'),'local firmware and clang required')
    def test_write_readback_crc_failure_gates_and_live_handshake(self):
        data,package,_=firmware_package(FIRMWARE.read_bytes())
        words=struct.unpack('<20I',package)
        header=['const uint8_t fw_data[]={'+','.join('0x%02x'%b for b in data)+'};']
        header.append('const struct touch_fw_package fw_package={'+','.join(hex(w)+'u' for w in words[:6])+',{' + ','.join(hex(w)+'u' for w in words[6:8])+'},{'+','.join('{'+','.join(hex(w)+'u' for w in words[8+i*4:12+i*4])+'}'for i in range(3))+'}};')
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'firmware_fixture.h').write_text('\n'.join(header))
            executable=tmp/'load-test'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_DIAG_HOST',
                            '-I'+str(HERE.parent/'include'),'-I'+str(tmp),
                            str(HERE.parent/'include/touch-firmware-load.c'),
                            str(HERE.parent/'tests/ilitek_iram_peer.c'),'-o',str(executable)],
                           check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,capture_output=True)

    @unittest.skipUnless(shutil.which('clang'),'clang required')
    def test_long_gpio_frames_preserve_every_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable=Path(tmp)/'long-frame'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_DIAG_HOST',
                            '-DBB_RW_TEST=1','-DBB_FW_LOAD=1','-I'+str(HERE.parent/'include'),
                            str(HERE.parent/'include/touch-gpio-probe.c'),
                            str(HERE.parent/'tests/gpio_long_frame.c'),'-o',str(executable)],
                           check=True,capture_output=True)
            subprocess.run([str(executable)],check=True,capture_output=True)

    @unittest.skipUnless(FIRMWARE.exists() and BASELINE.exists() and shutil.which('clang') and shutil.which('ld.lld'),'local artifacts and ARM64 tools required')
    def test_boot_components_and_runtime_package_boundaries(self):
        baseline=BASELINE.read_bytes();firmware=FIRMWARE.read_bytes()
        result,manifest=build_firmware_image(baseline,firmware)
        _,before,vm0,_=parse_image(baseline);_,after,vm1,_=parse_image(result)
        a,b=gzip.decompress(before[0]),gzip.decompress(after[0])
        self.assertEqual(a[LOADER_LIMIT:],b[LOADER_LIMIT:])
        self.assertEqual(before[1:],after[1:]);self.assertEqual(vm0,vm1)
        for o in (0x10,0x28,0x30):self.assertEqual(a[o:o+8],b[o:o+8])
        data,package,_=firmware_package(firmware)
        self.assertEqual(b[0x24000:0x24000+len(data)],data)
        self.assertEqual(b[0x3f000:0x3f000+80],package)
        self.assertLessEqual(0x24000+len(data),0x3f000)
        self.assertEqual(manifest['touchscreen'],0)
        self.assertFalse(manifest['flash_writes'])
        self.assertEqual(b.count(b'touchscreen=0'),2)


if __name__=='__main__':unittest.main(verbosity=2)
