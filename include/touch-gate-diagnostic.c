/* v71/v72 observation wrapper around the original v70 ACK2 probe.
 * GATE_FIX=0 observes; GATE_FIX=1 clears only TOPCKGEN SPI PDN bit23.
 * All SPI transactions, GPIO setup and reset delays remain in the old probe.
 */
#include <stdint.h>
#ifndef GATE_FIX
#define GATE_FIX 0
#endif
#ifndef BIG_FONT
#define BIG_FONT 0
#endif
#ifndef ICE_PROBE
#define ICE_PROBE 0
#endif
#ifndef SPI_IRQ_ENABLE
#define SPI_IRQ_ENABLE 0
#endif
#ifndef SPI_RESET_READBACK
#define SPI_RESET_READBACK 0
#endif
#if ICE_PROBE
extern void touch_ice_probe(void);
extern volatile uint32_t ice_pid[3], ice_status, ice_rx0, ice_rx1;
extern volatile uint32_t ice_attempts, ice_fail_stage, ice_fail_status0, ice_fail_status1, ice_fail_cmd;
#endif
#if BIG_FONT
/* Exact fbcon layout and address independently checked in v69 disassembly. */
struct console {
    uint64_t base;
    uint32_t pitch, w, h, x, y, top, scale, fg, bg;
};
extern volatile struct console console_state;
#endif

extern void original_probe(void);
extern void output_char(uint32_t c);
extern void output_hex(uint64_t n);
volatile uint32_t diag_rx = 0xffffffffu;

#ifdef TOUCH_DIAG_HOST
extern uint32_t diag_read(uint64_t address);
extern void diag_write(uint64_t address, uint32_t value);
#define barrier() ((void)0)
#else
static uint32_t diag_read(uint64_t address) { return *(volatile uint32_t *)address; }
#if GATE_FIX
static void diag_write(uint64_t address, uint32_t value) { *(volatile uint32_t *)address = value; }
#endif
#define barrier() __asm__ volatile("dsb sy" ::: "memory")
#endif

static void text(const char *s) { while (*s) output_char((unsigned char)*s++); }
static void field(const char *name, uint32_t value) { text(name); output_hex(value); }

void touch_gate_diagnostic(void)
{
    uint32_t clock_before = diag_read(0x10000070u);
    uint32_t infra_before = diag_read(0x100010acu);
    diag_rx = 0xffffffffu;
#if GATE_FIX
    diag_write(0x10000078u, 1u << 23); /* CFG6_CLR: SPI PDN only */
    diag_write(0x10000004u, 1u << 26); /* latch SPI mux update */
    barrier();
#endif
    original_probe();
#if BIG_FONT
    uint32_t cfg1_ack = diag_read(0x11018004u), cfg2_ack = diag_read(0x11018028u);
#endif
#if ICE_PROBE
    touch_ice_probe();
#endif
#if BIG_FONT
    uint32_t x = console_state.x, y = console_state.y;
    uint32_t top = console_state.top, scale = console_state.scale;
    console_state.scale = 4; /* 32x64 glyphs, double v71's height and width */
    console_state.x = console_state.y = console_state.top = 0;
    output_char('\n');
    text(ICE_PROBE ? (SPI_RESET_READBACK ? "v75 RESET - BIG\n" : (SPI_IRQ_ENABLE ? "v74 IE - BIG\n" : "v73 ICE - BIG\n")) : "G0 - BIG\n");
    field("CLK6 in  ", clock_before); output_char('\n');
    field("CLK6 out ", diag_read(0x10000070u)); output_char('\n');
    field("INFRA in ", infra_before); output_char('\n');
    field("INFRA out ", diag_read(0x100010acu)); output_char('\n');
    field("ACK RX32 ", diag_rx); output_char('\n');
    field("ACK byte1 ", (diag_rx >> 8) & 0xffu); output_char('\n');
    field("ACK CFG1 ", cfg1_ack); output_char('\n');
    field("ACK CFG2 ", cfg2_ack); output_char('\n');
#if ICE_PROBE
    field("ICE PID0 ", ice_pid[0]); output_char('\n');
    field("ICE PID1 ", ice_pid[1]); output_char('\n');
    field("ICE PID2 ", ice_pid[2]); output_char('\n');
    field("ICE flags ", ice_status); output_char('\n');
    field("ICE RX0 ", ice_rx0); output_char('\n');
    field("ICE RX1 ", ice_rx1); output_char('\n');
    field("XFER count ", ice_attempts); output_char('\n');
    field("FAIL stage ", ice_fail_stage); output_char('\n');
    field("FAIL ST0 ", ice_fail_status0); output_char('\n');
    field("FAIL ST1 ", ice_fail_status1); output_char('\n');
    field("FAIL CMD ", ice_fail_cmd); output_char('\n');
#endif
    console_state.x = x; console_state.y = y;
    console_state.top = top; console_state.scale = scale;
#else
    text(GATE_FIX ? "v72 G1" : "v71 G0");
    field(" CLK6 before ", clock_before);
    field(" after ", diag_read(0x10000070u));
    field(" INFRA4 before ", infra_before);
    field(" after ", diag_read(0x100010acu));
    output_char('\n');
    field("wire RX32 ", diag_rx);
    field(" ACK1 ", (diag_rx >> 8) & 0xffu);
    field(" CFG1 ", diag_read(0x11018004u));
    field(" CFG2 ", diag_read(0x11018028u));
    output_char('\n');
#endif
}
