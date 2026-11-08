#!/bin/bash
# Android 侧触摸链路只读 dump —— 用来和 HakiOS 侧逐项对比
# 全部只读，不写任何寄存器。设备需要有 root（Magisk）。
# 用法： sh android-touch-dump.sh > touch-dump.txt
set +e
S() { adb shell "su -c '$1'" 2>&1; }

echo "==================== 0. 设备 ===================="
adb shell getprop ro.product.model; adb shell getprop ro.board.platform
S "uname -a"
echo

echo "==================== 1. 触摸驱动 / 芯片 ===================="
echo "--- /sys/bus/spi/devices ---"
S "ls -l /sys/bus/spi/devices/"
echo "--- spi4.0 driver / of_node ---"
S "readlink -f /sys/bus/spi/devices/spi4.0/driver"
S "readlink -f /sys/bus/spi/devices/spi4.0/of_node"
echo "--- 输入设备 ---"
S "for d in /sys/class/input/input*/name; do echo -n \"\$d: \"; cat \$d; done"
echo "--- ABS 上限（坐标归一化用）---"
S "for d in /sys/class/input/input*/capabilities/abs; do echo \$d; cat \$d; done"
echo "--- /proc/ilitek ---"
S "ls /proc/ilitek/ 2>/dev/null"
for f in ver_info fw_version tp_info; do
  echo "--- /proc/ilitek/$f ---"; S "cat /proc/ilitek/$f 2>/dev/null" | head -20
done
echo

echo "==================== 2. SPI4 控制器状态 ===================="
echo "--- 平台设备 ---"
S "ls -d /sys/devices/platform/11018000.spi4 2>/dev/null && cat /sys/devices/platform/11018000.spi4/modalias 2>/dev/null"
echo "--- clk_summary 里的 spi4 ---"
S "grep -iE 'spi4|spi_sel|spi' /sys/kernel/debug/clk/clk_summary 2>/dev/null" | head -20
echo "--- 时钟门控（infra）---"
S "cat /sys/kernel/debug/clk/clk_summary 2>/dev/null | grep -iE 'ifrao|infra' | head -10"
echo

echo "==================== 3. GPIO / pinctrl ===================="
echo "--- gpio debugfs ---"
S "cat /sys/kernel/debug/gpio 2>/dev/null" | head -60
echo "--- pinctrl 控制器 ---"
S "ls /sys/kernel/debug/pinctrl/ 2>/dev/null"
P=$(adb shell su -c "ls /sys/kernel/debug/pinctrl/ 2>/dev/null | head -1" | tr -d '\r')
echo "--- pinmux-pins（前 80 行）---"
S "cat /sys/kernel/debug/pinctrl/$P/pinmux-pins 2>/dev/null" | head -80
echo "--- pinconf-pins 中 12/13/14/15/97/98 ---"
S "cat /sys/kernel/debug/pinctrl/$P/pinconf-pins 2>/dev/null" | grep -E 'pin (12|13|14|15|97|98) '
echo

echo "==================== 4. 中断 ===================="
S "grep -iE 'touch|spi4|11018000|mt-eint|kpd|pwrkey' /proc/interrupts" | head -20
echo

echo "==================== 5. 电源 / PMIC ===================="
S "cat /sys/kernel/debug/regulator/regulator_summary 2>/dev/null" | grep -iE 'vio28|vcn|ldo|vmc' | head -30
echo "--- mt6359 相关 sysfs ---"
S "ls /sys/devices/platform/10026000.pwrap*/ 2>/dev/null | head -20"
echo

echo "==================== 6. 设备树里触摸节点 ===================="
for f in compatible chip-name spi-max-frequency reset-gpio irq-gpio \
         touchpanel,tx-rx-num touchpanel,panel-coords touchpanel,display-coords \
         firmware_name incell_screen; do
  echo "--- $f ---"
  S "cat '/sys/firmware/devicetree/base/spi4@11018000/touchscreen@0/$f' 2>/dev/null | tr -d '\\000'" | head -3
  echo
done
echo "--- reset-gpio / irq-gpio 原始字节 ---"
S "xxd /sys/firmware/devicetree/base/spi4@11018000/touchscreen@0/reset-gpio 2>/dev/null"
S "xxd /sys/firmware/devicetree/base/spi4@11018000/touchscreen@0/irq-gpio 2>/dev/null"
echo

echo "==================== 7. dmesg 关键行 ===================="
adb shell su -c dmesg 2>/dev/null | grep -aiE \
  'ilitek|ili7807|touch|spi4|11018000|pinctrl|mt6359|pwrap|vio28' | head -120
echo

echo "==================== 8. 面板驱动参数 ===================="
S "cat /proc/cmdline" | tr ' ' '\n' | grep -iE 'lcm|lcdgateic|fps'
echo

echo "==================== DONE ===================="
