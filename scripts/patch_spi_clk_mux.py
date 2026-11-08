import os
p = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel/mtk/loader/mtkspi.h')
s = open(p).read()
if 'CLK_CFG_6_CLR' in s:
    print('already patched'); raise SystemExit

old_defs = """#define CLK_CFG_2_CLR        0x68
#define CLK_CFG_2_SET        0x64
#define CLK_CFG_2            0x60
#define SPI_SEL_FIELD        (3u << 24)
#define SPI_SEL_PDN          (1u << 31)"""
new_defs = """/*
 * The SPI mux is in CLK_CFG_6, not CLK_CFG_2, and its field is bits 16..17.
 * clk-mt6833.c:
 *   MUX_CLR_SET_UPD(CLK_TOP_SPI_SEL, "spi_sel", spi_parents,
 *                   CLK_CFG_6, CLK_CFG_6_SET, CLK_CFG_6_CLR,
 *                   16  lsb, 2  width, INV_BIT, CLK_CFG_UPDATE, TOP_MUX_SPI_SHIFT=26)
 *   spi_parents[0] = "tck_26m_mx9_ck"    <- 26 MHz, the one we want
 * The old CLK_CFG_2 / bit 24 / bit 31 values are another SoC's and touch an
 * unrelated mux, so the SPI clock was never selected at all.
 */
#define CLK_CFG_6            0x070
#define CLK_CFG_6_SET        0x074
#define CLK_CFG_6_CLR        0x078
#define CLK_CFG_UPDATE       0x004
#define SPI_SEL_LSB          16
#define SPI_SEL_WIDTH        2
#define TOP_MUX_SPI_SHIFT    26"""
assert old_defs in s, 'old clock defines not found'
s = s.replace(old_defs, new_defs, 1)

old_write = "\twr32(TOPCKGEN_BASE + CLK_CFG_2_CLR, SPI_SEL_FIELD | SPI_SEL_PDN);"
new_write = """\t/* CLK_CFG_6[17:16] = 0 -> spi_sel = tck_26m_mx9_ck, then commit */
\twr32(TOPCKGEN_BASE + CLK_CFG_6_CLR, ((1u << SPI_SEL_WIDTH) - 1) << SPI_SEL_LSB);
\twr32(TOPCKGEN_BASE + CLK_CFG_6_SET, 0u);
\twr32(TOPCKGEN_BASE + CLK_CFG_UPDATE, 1u << TOP_MUX_SPI_SHIFT);"""
assert old_write in s, 'clock write not found'
s = s.replace(old_write, new_write, 1)
open(p, 'w').write(s)
print('mtkspi.h: SPI clock mux CLK_CFG_2/bit24 -> CLK_CFG_6/bit16, parent 0 = 26 MHz')
