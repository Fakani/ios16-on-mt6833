#!/usr/bin/env python3
"""Host mocks for bounded ICE/PID probing and large-font restoration."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class IceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('clang'), 'clang required')
    def test_pid_positive_echo_negative_and_timeout_are_bounded(self):
        harness = r'''
#include <stdint.h>
#include <assert.h>
#include <string.h>
extern void touch_ice_probe(void);
extern volatile uint32_t ice_pid[3], ice_status, ice_rx0, ice_rx1;
static unsigned mode, txwords, rxwords, length, active, transactions, reads, status_reads;
static uint32_t fifo[8], command_register;
uint32_t ice_mmio_read(uint64_t a) {
 assert(a >= 0x11018000u && a < 0x11018030u);
 if (a == 0x1101801cu) {
  status_reads++;
  if (mode == 2) return 0;
  if (active) { active = 0; return 1; }
  return 0;
 }
 if (a == 0x11018020u) return 0;
 if (a == 0x11018018u) return command_register & ~1u;
 assert(a == 0x11018014u);
 unsigned command = fifo[0] & 255u;
 uint32_t word = 0;
 if (command == 0x83) {
  if (mode == 1) word = rxwords ? 0 : 0x8300;
  else word = rxwords ? 0x78 : 0x071f0100;
 }
 rxwords++; return word;
}
void ice_mmio_write(uint64_t a, uint32_t v) {
 assert(a >= 0x11018000u && a < 0x11018030u);
 if (a == 0x11018018u) command_register = v;
 if (a == 0x11018018u && (v & 4u)) { txwords = rxwords = active = 0; }
 if (a == 0x11018004u) length = (v >> 16) + 1;
 if (a == 0x11018010u) { assert(txwords < 8); fifo[txwords++] = v; }
 if (a == 0x11018018u && (v & ~0x30000u) == 0x3001) {
#if SPI_IRQ_ENABLE
  assert((v & 0x30000u) == 0x30000u);
#else
  assert((v & 0x30000u) == 0);
#endif
  assert(length == 5 && txwords == 2);
  unsigned cmd = fifo[0] & 255u;
  if (!transactions) assert(fifo[0] == 0x10622582 && (fifo[1] & 255u) == 0x18);
  else if (cmd == 0x83) { assert(fifo[0] == 0x83 && fifo[1] == 0); reads++; }
  else if (transactions == 7) assert(fifo[0] == 0x10621b82 && (fifo[1] & 255u) == 0x18);
  else assert(fifo[0] == 0x009c2582 && fifo[1] == 4);
  transactions++; active = 1;
 }
}
void ice_wait(void) {}
int main(void) {
 touch_ice_probe();
 assert(ice_status == 0x11f && ice_pid[0] == 0x78071f01 && ice_pid[2] == ice_pid[0]);
 assert(transactions == 8 && reads == 3 && ice_rx0 == 0x071f0100 && ice_rx1 == 0x78);
 mode = 1; transactions = reads = status_reads = 0; touch_ice_probe();
 assert(ice_status == 0x1f && ice_pid[0] == 0x83 && transactions == 8 && reads == 3);
 mode = 2; transactions = reads = status_reads = 0; touch_ice_probe();
 assert(ice_status == 0 && ice_pid[0] == 0xffffffffu && transactions == 1 && reads == 0);
 assert(status_reads <= 2000001u);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src, binary = Path(tmp) / 'mock.c', Path(tmp) / 'mock'
            src.write_text(harness)
            for irq, reset in ((0, 0), (1, 0), (1, 1)):
                subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-DTOUCH_DIAG_HOST',
                                '-DSPI_IRQ_ENABLE=' + str(irq), '-DSPI_RESET_READBACK=' + str(reset),
                                str(HERE.parent / 'include/touch-ice-probe.c'), str(src), '-o', str(binary)],
                               check=True, capture_output=True)
                subprocess.run([str(binary)], check=True, capture_output=True)

    @unittest.skipUnless(shutil.which('clang'), 'clang required')
    def test_big_font_only_changes_display_after_transactions_then_restores(self):
        harness = r'''
#include <stdint.h>
#include <assert.h>
struct console { uint64_t base; uint32_t pitch,w,h,x,y,top,scale,fg,bg; };
volatile struct console console_state = {0,4352,1080,2400,16,100,32,2,0,0};
extern void touch_gate_diagnostic(void);
extern volatile uint32_t diag_rx;
static unsigned calls, big_chars;
uint32_t diag_read(uint64_t a) { (void)a; return 0x10001; }
void diag_write(uint64_t a, uint32_t v) { (void)a; (void)v; assert(0); }
void original_probe(void) { assert(console_state.scale == 2); calls++; diag_rx=0x8200; }
void output_char(uint32_t c) { (void)c; assert(console_state.scale == 4); big_chars++; }
void output_hex(uint64_t v) { (void)v; assert(console_state.scale == 4); }
int main(void) {
 touch_gate_diagnostic();
 assert(calls == 1 && big_chars > 40);
 assert(console_state.scale == 2 && console_state.x == 16 && console_state.y == 100 && console_state.top == 32);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            src, binary = Path(tmp) / 'mock.c', Path(tmp) / 'mock'
            src.write_text(harness)
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-DTOUCH_DIAG_HOST', '-DBIG_FONT=1',
                            str(HERE.parent / 'include/touch-gate-diagnostic.c'), str(src), '-o', str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
