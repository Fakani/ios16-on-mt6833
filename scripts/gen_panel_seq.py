#!/usr/bin/env python3
"""Parse tianma_panel_init() out of the OPPO panel driver and emit a C table for mtkloader."""
import re, sys, os

src_path = 'vendor/panel-oplus210a0_tianma_ili7807s_cphy_vdo.c'
src = open(src_path).read()
start = src.index('static void tianma_panel_init')
end = src.index('\n}', start)
body = src[start:end]

seq = []
for line in body.split('\n'):
    line = line.strip()
    m = re.match(r'tianma_dcs_write_seq_static\(ctx,\s*([^)]*)\)', line)
    if m:
        args = [a.strip() for a in m.group(1).split(',') if a.strip()]
        vals = []
        for a in args:
            a = a.split('//')[0].strip()
            vals.append(int(a, 16) if a.lower().startswith('0x') else int(a))
        cmd = vals[0]
        # tianma_dcs_write(): cmd < 0xB0 -> mipi_dsi_dcs_write_buffer, else generic write
        kind = 'DCS' if cmd < 0xB0 else 'GEN'
        seq.append((kind, vals, 0))
        continue
    m = re.match(r'msleep\((\d+)\)', line)
    if m:
        seq.append(('DELAY', [], int(m.group(1))))

out = []
out.append('/* auto-generated from %s : tianma_panel_init() -- do not edit */' % os.path.basename(src_path))
out.append('/* %d steps (%d writes, %d delays) */' % (len(seq),
           sum(1 for s in seq if s[0] != 'DELAY'), sum(1 for s in seq if s[0] == 'DELAY')))
out.append('#ifndef PANEL_ILI7807S_INIT_H')
out.append('#define PANEL_ILI7807S_INIT_H')
out.append('')
out.append('#include <stdint.h>')
out.append('')
out.append('enum { PANEL_SEQ_DCS = 0, PANEL_SEQ_GEN = 1, PANEL_SEQ_DELAY = 2 };')
out.append('')
out.append('struct panel_seq {')
out.append('    uint8_t  kind;      /* PANEL_SEQ_* */')
out.append('    uint8_t  len;       /* bytes in d[] (0 for a delay) */')
out.append('    uint16_t delay_ms;  /* for PANEL_SEQ_DELAY */')
out.append('    uint8_t  d[8];')
out.append('};')
out.append('')
out.append('static const struct panel_seq panel_ili7807s_init[] = {')
for kind, vals, dly in seq:
    if kind == 'DELAY':
        out.append('    { PANEL_SEQ_DELAY, 0, %d, {0} },' % dly)
    else:
        pad = vals + [0]*(8-len(vals))
        out.append('    { PANEL_SEQ_%s, %d, 0, {%s} },' % (kind, len(vals),
                   ', '.join('0x%02X' % v for v in pad)))
out.append('};')
out.append('')
out.append('#define PANEL_ILI7807S_INIT_LEN (sizeof(panel_ili7807s_init)/sizeof(panel_ili7807s_init[0]))')
out.append('')
out.append('#endif')
open('vendor/panel-ili7807s-init.h','w').write('\n'.join(out) + '\n')
print('\n'.join(out[:12]))
print('...')
print('total steps:', len(seq))
print('writes:', sum(1 for s in seq if s[0]!='DELAY'), 'delays:', sum(1 for s in seq if s[0]=='DELAY'))
