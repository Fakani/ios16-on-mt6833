#!/system/bin/sh
# 只读 dump，在设备上以 root 运行
echo "== gpio =="
cat /sys/kernel/debug/gpio 2>/dev/null | head -70
echo "== pinctrl dirs =="
ls /sys/kernel/debug/pinctrl/ 2>/dev/null
for P in /sys/kernel/debug/pinctrl/*; do
  [ -f "$P/pinconf-pins" ] || continue
  echo "== $P pinconf 12/13/14/15/97/98 =="
  grep -E "^pin (12|13|14|15|97|98) " "$P/pinconf-pins" 2>/dev/null
  echo "== $P pinmux 12/13/14/15/97/98 =="
  grep -E "^pin (12|13|14|15|97|98) " "$P/pinmux-pins" 2>/dev/null
done
echo "== interrupts =="
grep -iE "touch|spi4|11018000|mt-eint|kpd|pwrkey|mt-pmic" /proc/interrupts
echo "== clk spi =="
grep -iE "spi" /sys/kernel/debug/clk/clk_summary 2>/dev/null | head -20
echo "== regulator vio28/ldo =="
cat /sys/kernel/debug/regulator/regulator_summary 2>/dev/null | grep -iE "vio28|vcam|ldo" | head -25
echo "== ilitek ver =="
cat /proc/ilitek/ver_info 2>/dev/null
echo "== ilitek debug =="
cat /proc/ilitek/debug_level 2>/dev/null
echo "== spi4 driver debugfs =="
ls /sys/kernel/debug/ 2>/dev/null | grep -i spi
echo "== mtk spi register dump =="
for f in /sys/kernel/debug/mtk_spi*/*; do echo "-- $f"; head -40 "$f" 2>/dev/null; done
echo "== dmesg ilitek =="
dmesg 2>/dev/null | grep -aiE "ilitek|ili7807|touchpanel|spi4" | head -60
echo "== DONE =="
