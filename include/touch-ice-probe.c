/* Bounded ILI7807S ICE MCU-OFF identity probe. No firmware or bulk writes.
 * Called after the original probe configured SPI4 mode0 / clock / pinmux.
 * PID_ADDR and ICE commands match the fixed OPPO 654f1cb8 vendor source.
 */
#include <stdint.h>
#ifndef SPI_IRQ_ENABLE
#define SPI_IRQ_ENABLE 0
#endif
#ifndef SPI_RESET_READBACK
#define SPI_RESET_READBACK 0
#endif
#define SPI_NORMAL_CMD (0x3000u | (SPI_IRQ_ENABLE ? 0x30000u : 0))
volatile uint32_t ice_attempts = 0, ice_fail_stage = 0;
volatile uint32_t ice_fail_status0 = 0, ice_fail_status1 = 0, ice_fail_cmd = 0;
volatile uint32_t ice_pid[3] = { 0xffffffffu, 0xffffffffu, 0xffffffffu };
volatile uint32_t ice_status = 0;
volatile uint32_t ice_rx0 = 0xffffffffu, ice_rx1 = 0xffffffffu;

#ifdef TOUCH_DIAG_HOST
extern uint32_t ice_mmio_read(uint64_t address);
extern void ice_mmio_write(uint64_t address, uint32_t value);
extern void ice_wait(void);
#define barrier() ((void)0)
#else
static uint32_t ice_mmio_read(uint64_t a) { return *(volatile uint32_t *)a; }
static void ice_mmio_write(uint64_t a, uint32_t v) { *(volatile uint32_t *)a = v; }
#define barrier() __asm__ volatile("dsb sy" ::: "memory")
static void ice_wait(void)
{
    uint64_t start, now, frequency;
    __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(start));
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    uint64_t ticks = (frequency ? frequency : 13000000u) / 1000u + 1;
    do { __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now)); } while (now - start < ticks);
}
#endif

#define SPI 0x11018000u
#define RD(off) ice_mmio_read(SPI + (off))
#define WR(off, value) ice_mmio_write(SPI + (off), (value))

static void reset_controller(void)
{
#if SPI_RESET_READBACK
    uint32_t command = RD(0x18);
    WR(0x18, command | 4u);
    command = RD(0x18);
    WR(0x18, command & ~4u);
#else
    WR(0x18, 4); WR(0x18, 0);
#endif
}

static int transfer(const uint8_t *tx, uint8_t *rx, unsigned n)
{
    if (!n || n > 32) return 0;
    ice_attempts++;
    reset_controller(); /* reset FIFO at start of each CS, never mid-message */
    WR(0x28, 0x10001); WR(0, 0x10001); WR(0x24, 0);
    WR(0x18, SPI_NORMAL_CMD);
    WR(4, ((n - 1) << 16) | 1);
    (void)RD(0x1c); /* clear any stale read-to-clear completion before ACT */
    for (unsigned i = 0; i < n; i += 4) {
        uint32_t word = 0;
        for (unsigned j = 0; j < 4 && i + j < n; j++) word |= (uint32_t)tx[i + j] << (8 * j);
        WR(0x10, word);
    }
    barrier();
    WR(0x18, SPI_NORMAL_CMD | 1u);
    unsigned spin;
    uint32_t status = 0;
    for (spin = 0; spin < 2000000u; spin++) { status = RD(0x1c); if (status & 1u) break; }
    if (spin == 2000000u) {
        if (!ice_fail_stage) {
            ice_fail_stage = ice_attempts;
            ice_fail_status0 = status; ice_fail_status1 = RD(0x20); ice_fail_cmd = RD(0x18);
        }
        reset_controller(); WR(0x18, 0); return 0;
    }
    for (unsigned i = 0; i < n; i += 4) {
        uint32_t word = RD(0x14);
        if (rx) { if (!i) ice_rx0 = word; else ice_rx1 = word; }
        for (unsigned j = 0; j < 4 && i + j < n; j++) if (rx) rx[i + j] = word >> (8 * j);
    }
    return 1;
}

void touch_ice_probe(void)
{
    const uint8_t open[] = { 0x82, 0x25, 0x62, 0x10, 0x18 }; /* MCU OFF */
    const uint8_t address[] = { 0x82, 0x25, 0x9c, 0x00, 0x04 }; /* PID 0x4009c */
    const uint8_t read[] = { 0x83, 0, 0, 0, 0 };
    const uint8_t close[] = { 0x82, 0x1b, 0x62, 0x10, 0x18 };
    uint8_t rx[5];
    ice_status = 0;
    ice_attempts = ice_fail_stage = 0;
    ice_fail_status0 = ice_fail_status1 = ice_fail_cmd = 0;
    ice_rx0 = ice_rx1 = 0xffffffffu;
    for (unsigned i = 0; i < 3; i++) ice_pid[i] = 0xffffffffu;
    if (!transfer(open, 0, sizeof(open))) return;
    ice_status |= 1u;
    ice_wait();
    for (unsigned i = 0; i < 3; i++) {
        if (!transfer(address, 0, sizeof(address)) || !transfer(read, rx, sizeof(read))) break;
        /* ICE returns raw payload immediately after 0x83, with no slave offset. */
        ice_pid[i] = (uint32_t)rx[1] | ((uint32_t)rx[2] << 8) |
                     ((uint32_t)rx[3] << 16) | ((uint32_t)rx[4] << 24);
        ice_status |= 2u << i;
    }
    if (ice_pid[0] == ice_pid[1] && ice_pid[1] == ice_pid[2] &&
        (ice_pid[0] >> 16) == 0x7807u) ice_status |= 0x100u;
    /* Diagnostic only: resume MCU instead of leaving it halted; Android will
     * perform its normal firmware bootstrapping on the next return. */
    if (transfer(close, 0, sizeof(close))) ice_status |= 0x10u;
#if SPI_IRQ_ENABLE
    WR(0x18, RD(0x18) & ~0x30000u); /* stop IRQ assertion before XNU starts */
    (void)RD(0x1c);
#endif
}
