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
        harness = r'''
#include <stdint.h>
#include <string.h>
#include <assert.h>
extern void touch_gate_diagnostic(void);
extern volatile uint32_t diag_rx, bb_ack, bb_pid[3], bb_flags, bb_frames, bb_clocks;
struct console { uint64_t base; uint32_t pitch,w,h,x,y,top,scale,fg,bg; };
volatile struct console console_state = {0,4352,1080,2400,16,96,0,2,0,0};
static uint32_t regs[256], saved[256], ies_register, saved_ies;
static unsigned frames, bits, reply_bit, test_mode, delay_calls, fail_at, timer_failed, expected_frame;
static const uint8_t expected[9][5] = {
 {0x82,0}, {0x82,0x25,0x62,0x10,0x18},
 {0x82,0x25,0x9c,0,4}, {0x83,0,0,0,0},
 {0x82,0x25,0x9c,0,4}, {0x83,0,0,0,0},
 {0x82,0x25,0x9c,0,4}, {0x83,0,0,0,0},
 {0x82,0x1b,0x62,0x10,0x18}};
static int gpio(unsigned pin) { return ((regs[(0x300+(pin/8)*0x10)/4] >> ((pin%8)*4)) & 7u) == 0; }
static int output(unsigned pin) { return (regs[((pin/32)*0x10)/4] >> (pin%32)) & 1u; }
static int latch(unsigned pin) { return (regs[(0x100+(pin/32)*0x10)/4] >> (pin%32)) & 1u; }
static int cs(void) { return gpio(98) && output(98) ? latch(98) : 1; }
static int clk(void) { return gpio(97) && output(97) ? latch(97) : 0; }
static uint8_t response(unsigned frame, unsigned byte) {
 if (test_mode == 3) return 255;
 if (test_mode == 2) return 0;
 if (frame == 0) return byte == 1 ? (test_mode == 1 ? 0x82 : 0xa3) : 0;
 if (frame == 3 || frame == 5 || frame == 7) {
  static const uint8_t good[5] = {0,1,0x1f,7,0x78};
  if (test_mode == 1) return byte == 1 ? 0x83 : 0;
  return good[byte];
 }
 return 0;
}
uint32_t bb_read(uint64_t a) {
 if (a == 0x11e60090u) return ies_register;
 assert(a >= 0x10005000u && a < 0x10005400u);
 unsigned off = a - 0x10005000u;
 if (off == 0x200) {
  assert(gpio(12) && !output(12) && (ies_register & (1u<<11)));
  return (regs[off/4] & ~(1u<<12)) | ((cs() ? 1u : reply_bit) << 12);
 }
 return regs[off/4];
}
void bb_write(uint64_t a, uint32_t v) {
 if (a == 0x11e60094u || a == 0x11e60098u) {
  assert(v == (1u<<11));
  if (a == 0x11e60094u) ies_register |= v; else ies_register &= ~v;
  return;
 }
 assert(a >= 0x10005000u && a < 0x10005400u);
 unsigned off = a - 0x10005000u;
 int old_cs=cs(), old_clk=clk();
 if (off == 0x310 || off == 0x3c0) {
  uint32_t mask = off == 0x310 ? 0xff0000 : 0xff0;
  assert(((regs[off/4] ^ v) & ~mask) == 0);
  regs[off/4] = v;
 } else {
  unsigned alias=off%16, reg=off-alias;
  assert(alias == 4 || alias == 8);
  uint32_t mask;
  if (reg == 0) mask=(1u<<12)|(1u<<13);
  else if (reg == 0x30 || reg == 0x130) mask=6;
  else {assert(reg==0x100); mask=1u<<13;}
  assert(!(v & ~mask));
  if (alias == 4) regs[reg/4] |= v; else regs[reg/4] &= ~v;
 }
 int new_cs=cs(), new_clk=clk();
 if (old_cs && !new_cs) {assert(frames < 9); bits=0; expected_frame=(timer_failed && frames>=2)?8:frames;}
 if (!new_cs && !old_clk && new_clk) {
  assert(gpio(13) && output(13));
  unsigned byte=bits/8, bit=7-bits%8;
  unsigned limit=expected_frame==0?2:5; assert(byte<limit);
  assert(latch(13) == ((expected[expected_frame][byte]>>bit)&1u));
  reply_bit=(response(expected_frame,byte)>>bit)&1u; bits++;
 }
 if (!old_cs && new_cs) {
  if (!timer_failed) assert(bits == (frames==0?16:40));
  frames++;
 }
}
int bb_delay(unsigned us) {
 assert(us==10 || us==1000); delay_calls++;
 if (fail_at && delay_calls == fail_at) {timer_failed=1;return 0;}
 return 1;
}
void original_probe(void) { assert(console_state.scale==2); diag_rx=0x8200; }
void output_char(uint32_t c) { (void)c; assert(console_state.scale==4); }
void output_hex(uint64_t v) { (void)v; assert(console_state.scale==4); }
static void run(unsigned mode, unsigned fail, unsigned ies_on) {
 memset(regs,0,sizeof(regs));
 regs[0]=0x7654abcd; regs[0x30/4]=0x12e44930;
 regs[0x100/4]=0xabcdef01; regs[0x130/4]=0x55443320;
 regs[0x310/4]=0x220007; regs[0x3c0/4]=0x11122221;
 memcpy(saved,regs,sizeof(regs));
 ies_register = saved_ies = (0x24681357u & ~(1u<<11)) | (ies_on ? 1u<<11 : 0);
 frames=bits=reply_bit=delay_calls=timer_failed=0;test_mode=mode;fail_at=fail;
 touch_gate_diagnostic();
 assert(!memcmp(saved,regs,sizeof(regs)) && ies_register == saved_ies);
 assert(console_state.scale==2 && console_state.x==16 && console_state.y==96);
 assert(bb_flags&0x200u);
 if (fail) {
  assert(!(bb_flags&0x100u));
  if (fail<=34) assert(bb_ack==0xffffffffu); else assert(bb_ack==0xa300);
  if (fail==115 || fail==200) assert(bb_flags&0x40u);
  return;
 }
 assert(frames==9 && bb_frames==9 && bb_clocks==336);
 if (mode==0) {assert(bb_flags==0x77fu && bb_pid[0]==0x78071f01u && bb_ack==0xa300);}
 else {assert(!(bb_flags&0x500u));}
 if (mode==1) assert(bb_pid[0]==0x83 && bb_ack==0x8200);
 if (mode==2) assert(bb_pid[0]==0 && bb_ack==0);
 if (mode==3) assert(bb_pid[0]==0xffffffffu && bb_ack==0xffffu);
}
int main(void) {for(unsigned ies=0;ies<2;ies++){for(unsigned m=0;m<4;m++)run(m,0,ies);run(0,1,ies);run(0,3,ies);run(0,115,ies);run(0,200,ies);}return 0;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src,binary = Path(tmp)/'mock.c',Path(tmp)/'mock'
            src.write_text(harness)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DTOUCH_DIAG_HOST',
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
            self.assertEqual(entry,0x400a0000)
            self.assertLess(len(data),0x4000)
            self.assertIn(b'v76 GPIO - BIG',data)
            self.assertIn(b'BB bitsteps ',data)
            self.assertEqual(data[hook-entry:hook-entry+4],bytes.fromhex('93c25fb8'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
