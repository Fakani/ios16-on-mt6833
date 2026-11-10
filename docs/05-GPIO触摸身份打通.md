# GPIO SPI 打通 ILI7807S 身份读取（v76，2026-11-10）

> 接续[二次核验与 v70–v75 记录](04-触摸二次核验与ACK修复.md)。
> **v76 实机三次读到完整 PID `0x78071f05`，且 GPIO 状态恢复检查通过。触摸报告与 HID 尚未验收。**

## 1. 实机证据

[原始照片副本](../../logs/v76-user-photo.jpg)，[重建回执与源码哈希](../../logs/v76-build-receipt.json)。

```text
FIFO RX32   0x8200
BB ACK32    0x8200
BB PID0     0x78071f05
BB PID1     0x78071f05
BB PID2     0x78071f05
BB flags    0x37f
BB bitsteps 0x150
BB frames   0x9
MI idle     0x0
MI IES in   0xffffffff
MI IES active 0xffffffff
MI IES out  0xffffffff
MODE1 in    0x220007
MODE1 out   0x220007
MODE12 in   0x11122221
MODE12 out  0x11122221
```

PID 高16位=0x7807，芯片类型字节=0x1f，版本字节=0x05。厂商 Android 打印 PID 时右移8位，正好得到既有日志中的 `78071f`。发送的测试命令中没有这个 PID 常量，结果不是把待测身份写进了接收缓冲区。

`flags=0x37f` 包含三次身份一致且匹配7807（0x100）和寄存器恢复读回通过（0x200）。没有设置 A3 标志（0x400），所以 raw ACK=0x82 仍不称为 A3 应答。**裸 ROM 下 A3 阴性不再作为阻止 ICE 身份探测的条件。**

bitsteps=336 是程序完成的采样步数，不是逻辑分析仪测量；frames=9 也只说明软件走完9个片选事务。有效 PID 才是本轮通信证据。IES 全1保留为原始读数，不对保留位或未实现位作扩展解释。

## 2. 独立链路

[GPIO 探针源码](../include/touch-gpio-probe.c) 保留原 v70 FIFO 探针作对照，然后暂时切 GPIO12/13/97/98 为 mode0：MI输入、MO/CLK/CS输出。

- GPIO12：MI；GPIO13：MO；GPIO97：CLK；GPIO98：CS，未改99/100。
- MODE1=0x10005310，仅改[23:16]；MODE12=0x100053c0，仅改[11:4]。
- GPIO每32pin一组，组间0x10；97/98在bank3，不使用 `1u<<97` 这类错误移位。
- GPIO12 IES：IOCFG_BL `0x11e60090` bit11，SET=+4、CLR=+8，保存并恢复。
- Mode0、MSB-first、软件半周期10us，约50kHz（未用外部仪器测量）；帧间留1ms。
- 一次raw ACK、一次ICE MCU-OFF、三次PID地址写/读、一次ICE关闭，共9帧。
- RX数据读取自GPIO DIN0 bit12，不依赖 SPI FIFO 或 STATUS0 完成标志。
- 正常及异常路径均恢复复用、方向、输出锁存和IES；所有改动均为易失状态，不写固件。

## 3. 源码交叉核验

厂商固定 commit：`654f1cb8a1516d446e19832e4da2aad314630469`，仓库 `oppo-source/android_kernel_oppo_mt6833`。

- [GPIO寄存器字段与IES](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/pinctrl/mediatek/pinctrl-mt6833.c#L26-L105)：MODE、DIR、DI、DO、pin12 IES index5/+0x90/bit11。
- [IOCFG地址与reg_bases顺序](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/arch/arm64/boot/dts/mediatek/mt6833.dts#L968-L1001)：index5=IOCFG_BL 0x11e60000。
- [ICE命令](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/input/touchscreen/ILITEK9882/ilitek_v3_ic.c#L244-L267)：MCU-OFF为0x25，不是0x1f。
- [SPI read偏移](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/input/touchscreen/ILITEK9882/ilitek_v3_spi.c#L179-L208)：ICE raw payload在rx[1]开始，不套slave offset+3。

审计还指出后续工程化事项：显式加强IES/方向/复用组间屏障；可采用厂商MWR避免共享字段RMW竞争；raw两字节ACK不是完整四字节ESD helper；1ms帧间隔不是厂商协议给出的最大时限。它们尚不抹去本轮已拍到的三次有效PID，后续修改仍应单变量控制。

## 4. 对旧结论的更正

- “芯片完全不响应 / MISO物理无信号”已被有效身份读取反证。
- “进入ICE前必须收到A3”不成立于这次启动状态。
- v75 超时位于控制器路径，不等于芯片身份无效。
- 同类 MTK 公共驱动把 STATUS1 bit0 命名为 BUSY，并等待它出现；它不是空闲判据。是否粘滞还需启动前后读回，不把单个1直接扩展为永久BUSY。
- 厂商 IRQ handler按STATUS0 bit1处理PAUSE并选择RESUME；现有PIO探针仅接受FINISH，仍有状态处理缺口待核实。

## 5. 构建与测试

[v76 实验镜像](../../images/k9x-ios-v76-GPIO-BIG.img)，SHA256：

```text
140a9efb70058ff5423cf6d4b4a0ced3f0bab1a205262a6ea43f61185184c297
```

[构建器](../scripts/make_touch_gate_images.py) 的GPIO模式与PIO/gate/IRQ实验互斥；包括.bss在内的所有ALLOC区段均校验在预留槽内。输入基线、原loader头字段、Android回链、XNU与启动参数保持一致；当前仍 `touchscreen=0`。

```sh
python3 repo/scripts/test_touch_ack2.py
python3 repo/scripts/test_touch_ice.py
python3 repo/scripts/test_touch_gpio.py
python3 repo/scripts/make_touch_gate_images.py images/k9x-ios-v69-CLK.img images/NEW-GPIO.img --big-font --gpio-probe
```

共16项测试通过。[GPIO mock](../scripts/test_touch_gpio.py) 逐个上升沿检查MSB顺序、命令和片选帧，覆盖真实格式PID、echo、全0、全1、首阶段与帧中计时失败、ICE打开后计时失败、IES初始开/关两种状态以及所有寄存器恢复。软件mock不替代真实电气量测，故另保留本轮实机照片。

## 6. 下一步

在这条已验证的GPIO路径上，核对本机固件格式、AF/B0块映射、CRC和启动顺序；先做小块写入/读回及撤销，再决定完整IRAM加载。有效PID门控必须保留，A3不作裸ROM前置条件。固件运行后仍需接通报告读取和HID，暂不把本轮称为“触摸已修复”。
