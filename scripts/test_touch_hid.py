#!/usr/bin/env python3
from pathlib import Path
import gzip
import json
import shutil
import subprocess
import tempfile
import unittest
from make_touch_hid_image import build_hid_image,BASE_SHA,locate_thread,WINDOW
from make_touch_ack2_image import parse_image,sha256,LOADER_LIMIT

HERE=Path(__file__).resolve().parent
BASELINE=HERE.parents[1]/'images/k9x-ios-v78-FW-BIG.img'

class HidTests(unittest.TestCase):
    def test_photographed_packet_is_negative_sum_pixel72(self):
        record=json.loads((HERE.parent/'tests/v80-real-packet-a.json').read_text())
        packet=bytes.fromhex(record['packet_hex'])
        self.assertEqual(len(packet),72);self.assertEqual(sum(packet)%256,0)
        self.assertEqual(packet[:3],bytes.fromhex('5b0048'))
        self.assertEqual(int.from_bytes(packet[4:6],'big'),231)
        self.assertEqual(int.from_bytes(packet[6:8],'big'),321)

    @unittest.skipUnless(shutil.which('clang'),'clang required')
    def test_pixel72_down_move_up_and_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'pixel-peer'
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I'+str(HERE.parent/'include'),
                            str(HERE.parent/'tests/ilitek_pixel72_peer.c'),'-o',str(out)],check=True,capture_output=True)
            subprocess.run([str(out)],check=True,capture_output=True)

    @unittest.skipUnless(shutil.which('clang'),'clang required')
    def test_kernel_gpio_transport_and_api_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'kernel-peer'
            for counter,profile in ((0,0),(0,1),(1,1)):
                subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_KERNEL_HOST',
                                '-DTOUCH_COUNTER_WAIT='+str(counter),'-DTOUCH_TIMING_LOG='+str(profile),
                                '-I'+str(HERE.parent/'include'),str(HERE.parent/'include/touch-kernel-thread.c'),
                                str(HERE.parent/'tests/kernel_gpio_peer.c'),'-o',str(out)],check=True,capture_output=True)
                subprocess.run([str(out)],check=True,capture_output=True)

    @unittest.skipUnless(BASELINE.exists() and shutil.which('clang') and shutil.which('ld.lld'),'local baseline and ARM64 tools required')
    def test_counter_wait_changes_only_the_existing_thread_window(self):
        base=BASELINE.read_bytes();working,_=build_hid_image(base);optimized,m=build_hid_image(base,1,1)
        _,pa,_,_=parse_image(working);_,pb,_,_=parse_image(optimized)
        a,b=gzip.decompress(pa[0]),gzip.decompress(pb[0]);pos=0x36c9b1c
        self.assertEqual(a[:pos],b[:pos]);self.assertEqual(a[pos+WINDOW:],b[pos+WINDOW:])
        self.assertTrue(m['counter_wait'] and m['timing_log'])
        self.assertEqual(m['idle_delay_us'],1000);self.assertEqual(m['nominal_half_period_us'],10)
        self.assertEqual(sha256(working),'f9f626032c96a7fb145e89137688b1ef812f36f88fdcaceb905466e9cc1372e1')

    def test_unexpected_image_rejected(self):
        with self.assertRaises(ValueError):build_hid_image(b'not tested v78')

    @unittest.skipUnless(BASELINE.exists() and shutil.which('clang') and shutil.which('ld.lld'),'local baseline and ARM64 tools required')
    def test_only_audited_kernel_window_and_two_bootargs_change(self):
        base=BASELINE.read_bytes();self.assertEqual(sha256(base),BASE_SHA)
        result,manifest=build_hid_image(base)
        _,a,vm0,_=parse_image(base);_,b,vm1,_=parse_image(result)
        before,after=gzip.decompress(a[0]),gzip.decompress(b[0]);position=locate_thread(before)
        self.assertEqual(before[LOADER_LIMIT:position],after[LOADER_LIMIT:position])
        self.assertEqual(before[position+WINDOW:],after[position+WINDOW:])
        self.assertEqual(before[0x20000:LOADER_LIMIT],after[0x20000:LOADER_LIMIT])
        self.assertEqual(a[1:],b[1:]);self.assertEqual(vm0,vm1)
        self.assertEqual(after[:LOADER_LIMIT].count(b'touchscreen=3'),2)
        self.assertEqual(after[:LOADER_LIMIT].count(b'touchscreen=0'),0)
        self.assertLess(manifest['replacement_bytes'],WINDOW)
        self.assertEqual(manifest['hardware_result'],'NOT TESTED')

if __name__=='__main__':unittest.main(verbosity=2)
