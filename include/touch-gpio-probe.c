/* Independent mode-0 GPIO SPI identity probe for MT6833 / ILI7807S.
 * Only pins 12(MI),13(MO),97(CLK),98(CS) are changed; all are restored.
 * Does not trust SPI controller FIFO/completion registers and sends no firmware.
 */
#include <stdint.h>
#ifndef BB_RW_TEST
#define BB_RW_TEST 0
#endif
#if BB_RW_TEST
volatile uint32_t bb_rw_before=0xffffffffu, bb_rw_expected=0, bb_rw_read=0xffffffffu, bb_rw_after=0xffffffffu;
#endif

extern void original_probe(void);
extern void output_char(uint32_t c);
extern void output_hex(uint64_t n);
struct console { uint64_t base; uint32_t pitch,w,h,x,y,top,scale,fg,bg; };
extern volatile struct console console_state;
volatile uint32_t diag_rx = 0xffffffffu; /* original FIFO capture hook */
volatile uint32_t bb_ack = 0xffffffffu, bb_pid[3] = {0xffffffffu,0xffffffffu,0xffffffffu};
volatile uint32_t bb_flags = 0, bb_clocks = 0, bb_frames = 0;
volatile uint32_t bb_idle = 0, bb_modes_before[2] = {0,0}, bb_modes_after[2] = {0,0};
volatile uint32_t bb_ies[3] = {0,0,0};

#ifdef TOUCH_DIAG_HOST
extern uint32_t bb_read(uint64_t address);
extern void bb_write(uint64_t address, uint32_t value);
extern int bb_delay(unsigned us);
#define barrier() ((void)0)
#else
static uint32_t bb_read(uint64_t a) { return *(volatile uint32_t *)a; }
static void bb_write(uint64_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
#define barrier() __asm__ volatile("dsb sy" ::: "memory")
static int bb_delay(unsigned us)
{
    uint64_t start, now, frequency;
    __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(start));
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    uint64_t ticks = ((frequency ? frequency : 13000000u) * us + 999999u) / 1000000u;
    for (unsigned spin = 0; spin < 1000000u; spin++) {
        __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
        if (now - start >= ticks) return 1;
    }
    return 0;
}
#endif

#define GPIO 0x10005000u
#define MI (1u << 12)
#define MO (1u << 13)
#define CLK (1u << 1) /* bank 3: pin 97 */
#define CS (1u << 2)  /* bank 3: pin 98 */
#define MODE1_MASK 0x00ff0000u
#define MODE12_MASK 0x00000ff0u
/* mt6833_pin_ies_range pin12: i_base5(IOCFG_BL), +0x90, bit11. */
#define MI_IES 0x11e60090u
#define MI_IES_BIT (1u << 11)

static void level(unsigned pin, int high)
{
    uint64_t address = GPIO + 0x100u + (pin / 32u) * 0x10u + (high ? 4u : 8u);
    bb_write(address, 1u << (pin % 32u));
    barrier();
}

static int transfer(const uint8_t *tx, uint8_t *rx, unsigned n)
{
    if (!n || n > 16u) return 0;
    level(97, 0);
    level(98, 0);
    for (unsigned i = 0; i < n; i++) {
        uint8_t value = 0;
        for (int bit = 7; bit >= 0; bit--) {
            level(13, (tx[i] >> bit) & 1u);
            if (!bb_delay(10)) goto timeout;
            level(97, 1);
            if (!bb_delay(10)) goto timeout;
            value = (uint8_t)((value << 1) | ((bb_read(GPIO + 0x200u) >> 12) & 1u));
            level(97, 0);
            bb_clocks++;
        }
        if (rx) rx[i] = value;
    }
    level(98, 1);
    bb_frames++;
    return bb_delay(1000);
timeout:
    level(97, 0); level(98, 1);
    return 0;
}

#if BB_RW_TEST
/* Vendor ili_ic_dummy_check uses WDT9_DUMMY2 = 0x51024 as a scratch word.
 * Unlike the vendor check, preserve and verify its original value afterward. */
static int read_dummy(uint32_t *value)
{
    const uint8_t address[] = {0x82,0x25,0x24,0x10,0x05};
    const uint8_t read[] = {0x83,0,0,0,0};
    uint8_t rx[5];
    if (!transfer(address,0,5) || !transfer(read,rx,5)) return 0;
    *value=(uint32_t)rx[1]|((uint32_t)rx[2]<<8)|((uint32_t)rx[3]<<16)|((uint32_t)rx[4]<<24);
    return 1;
}
static int write_dummy(uint32_t value)
{
    uint8_t tx[9] = {0x82,0x25,0x24,0x10,0x05,0,0,0,0};
    for(unsigned i=0;i<4;i++) tx[5+i]=(uint8_t)(value>>(8*i));
    return transfer(tx,0,9);
}
static void dummy_check(void)
{
    uint32_t before, observed;
    bb_rw_before=bb_rw_read=bb_rw_after=0xffffffffu;
    if (!read_dummy(&before)) return;
    bb_rw_before=before; bb_flags|=0x2000u;
    uint32_t pattern=before==0xa55a5aa5u?0x5aa5a55au:0xa55a5aa5u;
    bb_rw_expected=pattern;
    if (write_dummy(pattern) && read_dummy(&observed)) {
        bb_rw_read=observed;
        if(observed==pattern) bb_flags|=0x800u;
    }
    /* Even a failed write could have clocked a partial payload; restore once. */
    if(write_dummy(before) && read_dummy(&observed)) {
        bb_rw_after=observed;
        if(observed==before) bb_flags|=0x1000u;
    }
}
#endif

static void restore_bits(uint64_t reg, uint32_t saved, uint32_t mask)
{
    bb_write(reg + 4, saved & mask);
    bb_write(reg + 8, (~saved) & mask);
}

static void run_gpio_probe(void)
{
    const uint8_t ack[] = {0x82,0}, open[] = {0x82,0x25,0x62,0x10,0x18};
    const uint8_t address[] = {0x82,0x25,0x9c,0,4}, read[] = {0x83,0,0,0,0};
    const uint8_t close[] = {0x82,0x1b,0x62,0x10,0x18};
    uint8_t rx[5];
    uint32_t m1 = bb_read(GPIO + 0x310u), m12 = bb_read(GPIO + 0x3c0u);
    uint32_t dir0 = bb_read(GPIO), dir3 = bb_read(GPIO + 0x30u);
    uint32_t out0 = bb_read(GPIO + 0x100u), out3 = bb_read(GPIO + 0x130u);
    uint32_t ies = bb_read(MI_IES);
    bb_ies[0] = ies;
    bb_write(MI_IES + 4, MI_IES_BIT);
    barrier();
    bb_ies[1] = bb_read(MI_IES);
    bb_ack = bb_idle = 0xffffffffu; bb_flags = bb_clocks = bb_frames = 0;
    for (unsigned i = 0; i < 3; i++) bb_pid[i] = 0xffffffffu;
    bb_modes_before[0] = m1; bb_modes_before[1] = m12;
    /* Preload CS high/CLK low/MO low before selecting GPIO to avoid glitches. */
    level(98, 1); level(97, 0); level(13, 0);
    bb_write(GPIO + 4, MO); bb_write(GPIO + 8, MI);
    bb_write(GPIO + 0x34u, CLK | CS);
    barrier();
    bb_write(GPIO + 0x310u, m1 & ~MODE1_MASK);
    bb_write(GPIO + 0x3c0u, m12 & ~MODE12_MASK);
    barrier();
    if ((bb_read(GPIO + 0x310u) & MODE1_MASK) || (bb_read(GPIO + 0x3c0u) & MODE12_MASK) ||
        (bb_read(GPIO) & (MI | MO)) != MO || (bb_read(GPIO + 0x30u) & (CLK | CS)) != (CLK | CS) ||
        !(bb_ies[1] & MI_IES_BIT)) goto restore;
    bb_flags |= 1u;
    if (!bb_delay(1000)) goto restore;
    bb_idle = (bb_read(GPIO + 0x200u) >> 12) & 1u;
    if (!transfer(ack, rx, 2)) goto restore;
    bb_ack = (uint32_t)rx[0] | ((uint32_t)rx[1] << 8);
    bb_flags |= 2u;
    if (rx[1] == 0xa3) bb_flags |= 0x400u;
    if (!transfer(open, 0, 5)) {
        /* A failed gap timer may follow a fully clocked ICE-open frame.
         * Attempt one bounded close before restoring pads in that case. */
        if (bb_frames >= 2u && transfer(close, 0, 5)) bb_flags |= 0x40u;
        goto restore;
    }
    bb_flags |= 4u;
    for (unsigned i = 0; i < 3; i++) {
        if (!transfer(address, 0, 5) || !transfer(read, rx, 5)) goto close_ice;
        bb_pid[i] = (uint32_t)rx[1] | ((uint32_t)rx[2] << 8) | ((uint32_t)rx[3] << 16) | ((uint32_t)rx[4] << 24);
        bb_flags |= 8u << i;
    }
    if (bb_pid[0] == bb_pid[1] && bb_pid[1] == bb_pid[2] && (bb_pid[0] >> 16) == 0x7807u) bb_flags |= 0x100u;
#if BB_RW_TEST
    if(bb_flags & 0x100u) dummy_check();
#endif
close_ice:
    if (transfer(close, 0, 5)) bb_flags |= 0x40u;
restore:
    level(97, 0); level(98, 1);
    /* Reattach the original SPI functions while CS is high, then restore
     * latent GPIO directions/output latches; unrelated pins remain untouched. */
    bb_write(GPIO + 0x310u, (bb_read(GPIO + 0x310u) & ~MODE1_MASK) | (m1 & MODE1_MASK));
    bb_write(GPIO + 0x3c0u, (bb_read(GPIO + 0x3c0u) & ~MODE12_MASK) | (m12 & MODE12_MASK));
    barrier();
    restore_bits(GPIO, dir0, MI | MO); restore_bits(GPIO + 0x30u, dir3, CLK | CS);
    restore_bits(GPIO + 0x100u, out0, MO); restore_bits(GPIO + 0x130u, out3, CLK | CS);
    bb_write(MI_IES + ((ies & MI_IES_BIT) ? 4u : 8u), MI_IES_BIT);
    barrier();
    bb_ies[2] = bb_read(MI_IES);
    bb_modes_after[0] = bb_read(GPIO + 0x310u); bb_modes_after[1] = bb_read(GPIO + 0x3c0u);
    if (((bb_modes_after[0] ^ m1) & MODE1_MASK) == 0 && ((bb_modes_after[1] ^ m12) & MODE12_MASK) == 0 &&
        ((bb_read(GPIO) ^ dir0) & (MI | MO)) == 0 && ((bb_read(GPIO + 0x30u) ^ dir3) & (CLK | CS)) == 0 &&
        ((bb_read(GPIO + 0x100u) ^ out0) & MO) == 0 && ((bb_read(GPIO + 0x130u) ^ out3) & (CLK | CS)) == 0 &&
        ((bb_ies[2] ^ ies) & MI_IES_BIT) == 0) bb_flags |= 0x200u;
}

static void text(const char *s) { while (*s) output_char((unsigned char)*s++); }
static void field(const char *name, uint32_t n) { text(name); output_hex(n); output_char('\n'); }

void touch_gate_diagnostic(void)
{
    original_probe();
    run_gpio_probe();
    uint32_t x = console_state.x, y = console_state.y, top = console_state.top, scale = console_state.scale;
    console_state.scale = 4; console_state.x = console_state.y = console_state.top = 0;
    output_char('\n'); text(BB_RW_TEST?"v77 RW - BIG\n":"v76 GPIO - BIG\n");
    field("FIFO RX32 ", diag_rx);
    field("BB ACK32 ", bb_ack);
    field("BB PID0 ", bb_pid[0]); field("BB PID1 ", bb_pid[1]); field("BB PID2 ", bb_pid[2]);
    field("BB flags ", bb_flags); field("BB bitsteps ", bb_clocks); field("BB frames ", bb_frames);
#if BB_RW_TEST
    field("RW before ",bb_rw_before); field("RW wanted ",bb_rw_expected);
    field("RW read ",bb_rw_read); field("RW restored ",bb_rw_after);
#endif
    field("MI idle ", bb_idle);
    field("MI IES in ", bb_ies[0]); field("MI IES active ", bb_ies[1]); field("MI IES out ", bb_ies[2]);
    field("MODE1 in ", bb_modes_before[0]); field("MODE1 out ", bb_modes_after[0]);
    field("MODE12 in ", bb_modes_before[1]); field("MODE12 out ", bb_modes_after[1]);
    console_state.x = x; console_state.y = y; console_state.top = top; console_state.scale = scale;
}
