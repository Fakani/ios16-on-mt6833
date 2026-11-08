import os
p = os.path.expanduser('~/Downloads/isoA-touch-work-20261107/ios16-k9x/hakios-xnu-kernel/mtk/loader/mtkloader.c')
s = open(p).read()
if 'PHOTO HOLD' in s:
    print('already patched')
    raise SystemExit
old = "\tpanel_ili7807s_dsi_init();\n\ttouch_bring_up();\n"
new = ("\tpanel_ili7807s_dsi_init();\n\ttouch_bring_up();\n"
       "\t/* PHOTO HOLD: keep the panel/touch status on screen long enough to photograph */\n"
       "\tout(\"--- holding 12 s for a photo ---\\n\");\n"
       "\tdbg_delay_ms(12000);\n")
assert old in s, 'anchor not found'
s = s.replace(old, new, 1)
open(p, 'w').write(s)
print('patched with 12 s hold')
