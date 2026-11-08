import os, re
K = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel/mtk/loader')
SPI = os.path.join(K, 'mtkspi.h')
MAIN = os.path.join(K, 'mtkloader.c')

# ---- 1. SPI mode 3 -> mode 0 (Android: spi->mode = 0) ----
s = open(SPI).read()
old = "wr32(SPI2_BASE + SPI_CMD, SPI_CMD_CPHA | SPI_CMD_CPOL | SPI_CMD_TXMSBF | SPI_CMD_RXMSBF);"
new = "wr32(SPI2_BASE + SPI_CMD, SPI_CMD_TXMSBF | SPI_CMD_RXMSBF);   /* MODE 0: CPOL=CPHA=0, as Android's spi->mode = 0 */"
assert old in s, 'spi mode line not found'
s = s.replace(old, new, 1)
open(SPI, 'w').write(s)
print('mtkspi.h: SPI mode 3 -> 0')

# ---- 2. add ilitek_probe() and swap out the TCM bring-up ----
m = open(MAIN).read()
if 'ilitek_probe' in m:
    print('already patched'); raise SystemExit

BLOCK = r'''
/*
 * ILITEK ILI7807S, the way Android talks to it.
 *
 * ilitek_v3.h: SPI_WRITE 0x82, SPI_ACK 0xA3.  ilitek_v3.c's ESD check is exactly this:
 * send 0x82, read one byte, a live chip answers 0xA3.
 * ilitek_v3_mtk.c's ili_tp_reset() is: high 1 ms, low 5 ms, high 10 ms, then read.
 * The device tree's spi->mode is 0 (CPOL=0, CPHA=0) -- mtkspi.h used to drive mode 3.
 */
static void ilitek_probe(void)
{
	uint8_t tx = 0x82, rx = 0;

	/* ili_tp_reset(): high 1 ms, low 5 ms, high 10 ms -- "do not change it to msleep" */
	wr32(GPIO_BASE + 0x004, 1u << 15);      /* DIR0_SET  : output */
	wr32(GPIO_BASE + 0x104, 1u << 15);      /* DOUT0_SET : high */
	dbg_delay_ms(1);
	wr32(GPIO_BASE + 0x108, 1u << 15);      /* DOUT0_CLR : low  */
	dbg_delay_ms(5);
	wr32(GPIO_BASE + 0x104, 1u << 15);      /* DOUT0_SET : high */
	dbg_delay_ms(10);

	spi_pins_to_spi2();

	if (!spi_xfer(&tx, &rx, 1)) {
		out("ilitek: spi transfer did not complete\n");
		return;
	}
	out("ilitek: 0x82 -> 0x");
	out_hex(rx);
	out(rx == 0xA3 ? "  ACK, the chip is alive\n" : "  not ACK\n");
}
'''
anchor = 'static void panel_ili7807s_dsi_init(void)'
assert anchor in m
m = m.replace(anchor, BLOCK + '\n' + anchor, 1)

old_call = "\tpanel_ili7807s_dsi_init();\n\ttouch_bring_up();\n"
new_call = "\tpanel_ili7807s_dsi_init();\n\tilitek_probe();\n"
assert old_call in m, 'call site not found'
m = m.replace(old_call, new_call, 1)
open(MAIN, 'w').write(m)
print('mtkloader.c: added ilitek_probe(), replaced touch_bring_up()')
