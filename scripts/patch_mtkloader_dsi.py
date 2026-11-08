#!/usr/bin/env python3
"""Patch mtkloader.c: add MTK DSI VM_CMD writes + the ILI7807S panel init sequence."""
import os, shutil, sys

K = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel')
SRC = os.path.join(K, 'mtk/loader/mtkloader.c')
HDR = os.path.join(K, 'mtk/loader/panel-ili7807s-init.h')

# 0. back up once
bak = SRC + '.pre-dsi'
if not os.path.exists(bak):
    shutil.copy2(SRC, bak)
    print('backup ->', bak)

# 1. install the generated table
shutil.copy2('vendor/panel-ili7807s-init.h', HDR)
print('installed', HDR)

src = open(SRC).read()
if 'panel_ili7807s_dsi_init' in src:
    print('already patched; nothing to do'); sys.exit(0)

# 2. include the table
anchor = '#include "../../xnuloader/identity.h"'
assert anchor in src, 'include anchor not found'
src = src.replace(anchor, anchor + '\n#include "panel-ili7807s-init.h"   /* generated from the OPPO panel driver */', 1)

BLOCK = r'''
/* ------------------------------------------------------------------ *
 * DSI: walk the panel's own init sequence before XNU starts.
 *
 * LK lights this panel (video mode) and leaves it scanning out our
 * framebuffer, but it never walks ILITEK's vendor pages: the LK image
 * carries no 0xFF 78 07 xx command at all (byte-checked against the LK
 * dump), while Android's panel driver sends 42 of them.  The touch half
 * of this TDDI sits behind those pages, so without them the chip never
 * leaves its bare-die state and never drives MISO -- which is exactly
 * what every SPI probe so far has measured.
 *
 * These go out as VM_CMD packets, the path the vendor driver uses while
 * the link is in video mode: put the payload in DSI_VM_CMD_DATA*, then
 * set VM_CMD_EN | TS_VFP_EN in DSI_VM_CMD_CON and the engine sends it
 * in the next vertical blank.
 * ------------------------------------------------------------------ */
#ifndef PANEL_DSI_INIT
#define PANEL_DSI_INIT 1
#endif

#define DSI0_BASE              0x14013000u
#define DSI_INTSTA             0x0cu
#define DSI_VM_CMD_CON         0x130u
#define DSI_VM_CMD_DATA0       0x134u

#define VM_CMD_EN              (1u << 0)
#define VM_LONG_PACKET         (1u << 1)
#define TS_VFP_EN              (1u << 5)
#define DSI_INTSTA_VM_CMD_DONE (1u << 5)

#define DSI_DCS_SHORT_WRITE_1  0x15u
#define DSI_GENERIC_LONG_WRITE 0x29u

static void dsi_vm_cmd_wait(void)
{
	/* INTSTA bit 5 latches when the packet left the engine.  Poll it, but
	 * never fail the boot over it: a missing ack only means a slower panel. */
	for (uint32_t i = 0; i < 40; i++) {
		uint32_t st = rd32(DSI0_BASE + DSI_INTSTA);
		if (st & DSI_INTSTA_VM_CMD_DONE) {
			wr32(DSI0_BASE + DSI_INTSTA, st);        /* write 1 to clear */
			return;
		}
		dbg_delay_ms(1);
	}
}

static void dsi_send_short(uint8_t cmd, uint8_t param)
{
	uint32_t v = ((uint32_t)param << 24) | ((uint32_t)cmd << 16) |
		     ((uint32_t)DSI_DCS_SHORT_WRITE_1 << 8);
	wr32(DSI0_BASE + DSI_VM_CMD_CON, v | VM_CMD_EN | TS_VFP_EN);
	dsi_vm_cmd_wait();
}

static void dsi_send_long(const uint8_t *d, uint32_t n)
{
	uint32_t i, j;
	if (n > 16)
		return;
	for (i = 0; i < n; i += 4) {
		uint32_t v = 0;
		for (j = 0; j < 4 && i + j < n; j++)
			v |= (uint32_t)d[i + j] << (8 * j);
		wr32(DSI0_BASE + DSI_VM_CMD_DATA0 + i, v);
	}
	{
		uint32_t v = (n << 16) | ((uint32_t)DSI_GENERIC_LONG_WRITE << 8) | VM_LONG_PACKET;
		wr32(DSI0_BASE + DSI_VM_CMD_CON, v | VM_CMD_EN | TS_VFP_EN);
	}
	dsi_vm_cmd_wait();
}

static void panel_ili7807s_dsi_init(void)
{
#if PANEL_DSI_INIT
	uint32_t i, sent = 0;

	out("panel: ILI7807S DSI init, ");
	out_dec(PANEL_ILI7807S_INIT_LEN);
	out(" steps\n");
	for (i = 0; i < PANEL_ILI7807S_INIT_LEN; i++) {
		const struct panel_seq *s = &panel_ili7807s_init[i];
		if (s->kind == PANEL_SEQ_DELAY) {
			dbg_delay_ms(s->delay_ms);
			continue;
		}
		if (s->kind == PANEL_SEQ_DCS && s->len == 2)
			dsi_send_short(s->d[0], s->d[1]);
		else
			dsi_send_long(s->d, s->len);
		sent++;
	}
	out("panel: sent ");
	out_dec(sent);
	out(" DCS/generic writes, INTSTA ");
	out_hex(rd32(DSI0_BASE + DSI_INTSTA));
	out("\n");
#endif
}
'''
anchor2 = 'static uint8_t touch_bring_up_once(void)'
assert anchor2 in src, 'function anchor not found'
src = src.replace(anchor2, BLOCK + '\n' + anchor2, 1)

# 3. call it in the boot path, just before the touch probe
call_anchor = '\ttouch_bring_up();\n\tbig_cores_clock();'
assert call_anchor in src, 'call site not found'
src = src.replace(call_anchor, '\tpanel_ili7807s_dsi_init();\n' + call_anchor, 1)

open(SRC, 'w').write(src)
print('patched', SRC)
print('  + include')
print('  + %d bytes of DSI code' % len(BLOCK))
print('  + call before touch_bring_up()')
