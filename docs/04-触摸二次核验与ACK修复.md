# 触摸二次核验与 ACK 修复（2026-11-10）

> 读取会话 `session-59f0f4c0-b22c-4be3-bf4f-169c55dee03a` 的原始事件、现存代码、v69 镜像，并独立对照厂商源。
> **当前结论：触摸尚未修通；旧的“硬件全绿、MISO 物理无信号”结论证据不足。** 已修复一个确定的 loader ACK 探针错误，v70 用户回报 `0x0x82`，下一步为带原始 RX 与门控读回的单变量对照。
> 本轮由用户操作设备；助手未执行刷写、重启或桌面接管。

## 1. 关键纠错

### 1.1 旧 ACK 探针只打出了 8 个时钟

[历史探针生成脚本](../scripts/patch_ilitek_mode0.py#L29-L50) 使用：

```c
uint8_t tx = 0x82, rx = 0;
spi_xfer(&tx, &rx, 1);
```

它在命令字节期间读取 RX[0]，没有为命令之后的 ACK 再产生时钟。最小 raw ACK 检查应为一次 CS 中的两个字节：

```c
uint8_t tx[2] = { 0x82, 0x00 }, rx[2] = { 0, 0 };
spi_xfer(tx, rx, 2);
ack = rx[1];
```

注意：这只是 raw ACK 检查，不是完整复制厂商 ESD helper。
[本地厂商 ESD 调用](../../vendor/ilitek_v3.c#L285-L296) 的 `n_tx=1,n_rx=1` 经过
[厂商 direct helper](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/input/touchscreen/ILITEK9882/ilitek_v3_spi.c#L179-L208) 后，在非 ICE 模式还加入两个 offset 字节：ACK 为 wire[1]，返回 payload 在 wire[3]。旧脚本把这种 API 调用误译成了一字节全双工。

实际 v69 镜像反汇编也确认：blob+0x7a5c 的 W8=1 被写入 CFG1，packet_length 字段为 0，表示一字节；blob+0x7af4 取 RX 低 8 位。

### 1.2 loader、现存 XNU 源码、镜像内 XNU 是三个不同对象

- 现存原工作树的 loader 仍是 MT6768 SPI2/TCM；旧会话改的是后来已不在原路径的 Downloads 副本。
- 现存 XNU 的 Goodix 文件名实际承载 ILITEK 驱动，其 SPI4_PHYS 已为 `0x11018000`、mode0，ACK 也已读第二字节。
- v69 内嵌的是 v43 系列旧 XNU，不等于现存 466 行驱动。其 `_touch_thread` 映射地址同样为 SPI4；两份 boot-args 都是 `touchscreen=0`，线程没有启用。
- [打包器](../scripts/make_v60_image.py#L35-L51) 明确只换 loader，[尾部逐字节验证](../scripts/make_v60_image.py#L81-L88) 保持 XNU 不变。

所以“v19–v66 所有 SPI 调试都在访问 SPI2”超出了已验证范围；loader 的错误不能直接套到内核。loader 修复也不等于桌面触摸驱动修复。

### 1.3 SPI clock mux 修复遗漏真实 PDN 位

[厂商时钟源码](../../vendor/clk-mt6833.c#L45-L74) 定义 MT6833 CFG6=0x70、SET=0x74、CLR=0x78，CFG9 才是 0xa0。
`MT_CCF_MUX_DISABLE=0`，应读实际选中分支的 [SPI mux 条目](../../vendor/clk-mt6833.c#L1560-L1564)：选择位 [17:16]、PDN bit23、UPDATE bit26。旧补丁引用的是未选中分支的 INV_BIT，未清 bit23。

这是**补丁不完整**的源码事实，尚不等于实机当时 bit23 为 1。SPI4 还有独立 infra 门控：`0x100010ac` bit25；CLR 地址为 `0x100010a8`。应先记录读回再做因果判定。

旧数值写 `0x68` 在本 SoC 实为 CFG5_CLR，影响 CAMTG5 字段，不是文档字面命名的 CFG2_CLR。继承自 LK 的时钟状态可能本来可用，旧代码写错 mux 也不证明 SPI 时钟从未运行。

### 1.4 实际 SPI4 引脚只有四根；PAD=0 有源码支持

[厂商板级 DT](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/arch/arm64/boot/dts/mediatek/oplus6833_210A0.dts#L1071-L1075) 指定：GPIO12 MI、GPIO13 MO、GPIO97 CLK、GPIO98 CS，均 function2。
[pinfunc 定义](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/include/dt-bindings/pinctrl/mt6833-pinfunc.h#L692-L710) 中 GPIO99/100 function2 是 SCP_SCL0/SCP_SDA0，不是 SPI。
旧补丁把 99/100 一并强制配置属于过宽改动，未来应保留其原值。此次 ACK 与 gate 实验暂不混改引脚。

[SoC DT](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/arch/arm64/boot/dts/mediatek/mt6833.dts#L5304-L5312) 给 SPI4 `pad-select=<0>`；[SPI 驱动](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/spi/spi-mt65xx.c#L377-L379) 把该值写入 +0x24。因此 PAD0 有软件依据，不再是无根据的剩余猜测。

### 1.5 读回值与物理线状态分开

- RX=0 只是软件读回值；旧单字节探针甚至没读到 ACK 时间窗。
- DONE/模式/复用值不证明 CS/SCK/MOSI 已到芯片，也不证明物理 MISO 恒低。
- dummy regulator 日志仅说明驱动未取得 regulator 对象，不证明任意启动阶段都已供电。
- DSI DONE 也不证明触摸核已激活或固件已运行。
- 本机是 legacy mt6765-spi，FIFO CMD=0x3000 不是“RX_EN/TX_EN 没开”的证据；[厂商寄存器定义](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/spi/spi-mt65xx.c#L63-L79) 没有新 IPM 的这些 enable 位。

## 2. 本轮已实施的最小修复

### v70：只修 ACK 帧

[源码补丁器](../scripts/patch_ilitek_ack2.py) 对已知历史函数做严格匹配，自动备份且支持重复运行；保留复位、引脚与时钟设置不变。
[镜像构建器](../scripts/make_touch_ack2_image.py) 校验完整输入 SHA256，只替换三条 ARM64 指令和等长标签。采用原 v69 二进制作为基线，是为了避开已丢失 Downloads 树与现存源码之间的分叉，避免用旧源重编时带入无关回归。

- 输入 SHA256：`2305a48d3127912364e6a020c13610c60a26e0e2f9c41ce6ba6bc59ab21bcd48`
- 输出：[v70 镜像](../../images/k9x-ios-v70-ACK2.img)，32 MiB
- 输出 SHA256：`bdb2e9b20f1ee6625beaf5f7406eb08e2f9991e53809dea47ab1a0248b6e6dbf`
- 解压 blob 只变 13 字节，均小于 0x40000。
- 0x10/0x28/0x30 头字段、Android Image、XNUP/XNU、ramdisk、recovery DTBO、DTB 均保留。
- VBMeta 字节沿用 v69，**未重新签名或宣称哈希描述符仍匹配**。
- 两份 `touchscreen=0` 保持不变。
- 用户在测试提问框回报原文：`0x0x82`；按已有双重 0x 打印方式解释为数值 0x82。尚无本轮照片，不等同于 A3，更不等同于有效 PID 或触摸工作。

### v71 G0 / v72 G1：观察与门控单变量对照

[诊断 C 源码](../include/touch-gate-diagnostic.c)、[FIFO 捕获 hook](../include/touch-capture-rx.S)、[构建器](../scripts/make_touch_gate_images.py)。

两者都继续调用 v70 原 probe，不重写 SPI 状态机，不新增 FIFO 读取：替换原本那一次 LDUR 的入口，捕获完整 RX32 后回到原下一条指令。新增 CLK6 / INFRA4 前后值、RX32、ACK1、CFG1、CFG2 输出。

- G0：只观察，无额外硬件寄存器写。
- G1：相对 G0 唯一功能变量为清 CFG6 bit23 并提交 UPDATE bit26；不改 infra 门控、不灌固件。
- 原始 BSS 清零范围由启动代码核实为 `[0x4008c000,0x400904d8)`；诊断代码放在 `0x400a0000`，避开 BSS、原程序、Android 回链和 XNU。
- 所有镜像保留 `touchscreen=0`。
- [v71 镜像](../../images/k9x-ios-v71-G0.img)：`e5ed6c878f3136ea8a05d5d8550e496697893e14ac6aec78f30cc7af48af865e`
- [v72 镜像](../../images/k9x-ios-v72-G1.img)：`aa15ccf890d3b2944cf1366fb70ca1f1dd5812541248778ac4f4cd1b13024685`
- 先测试 G0 并记录整屏；根据实际 bit23/bit25 再决定是否测试 G1。构建成功不等于已实测。

## 3. 验证与复现

[离线测试](../scripts/test_touch_ack2.py) 当前 11 项：源修复及幂等、未知/半补丁输入阻断、真实 C 编译执行、正确取第二字节且不把 echo 当 A3、ARM64 汇编字节一致、基线哈希、图像边界/组件、hook 保留原 FIFO 读与返回地址、G0 零写/G1 精确两次门控写。

```sh
# 在工作区根目录执行
python3 repo/scripts/test_touch_ack2.py
python3 repo/scripts/make_touch_ack2_image.py images/k9x-ios-v69-CLK.img images/NEW-ACK2.img
python3 repo/scripts/make_touch_gate_images.py images/k9x-ios-v69-CLK.img images/NEW-G0.img --gate-fix 0
```

首次 9 项结果：[v70 测试日志](../../logs/v70-offline-tests.txt)；
新增门控测试：[v71 测试日志](../../logs/v71-offline-tests.txt)；
独立反汇编与差异验证：[v70 校验日志](../../logs/v70-independent-verify.txt)。

## 4. 还没有落地到运行镜像的内核问题

现存 466 行源码另有 ICE/slave offset 混用、ICE MCU-OFF 命令/门控顺序、noflash 复位后缺少固件恢复、checksum 符号等问题。它不是镜像内 v43 源码，直接改它再声称 v70 已应用属于产物错配。

完整收尾顺序应是：有界进入 ICE MCU-OFF → raw ICE 读取 PID(0x4009c)并多次验证本机 7807 身份 → 校验固件与内存范围后下载 → CRC/读回验证 → 启动固件 → slave ACK → 正确 offset/checksum 的报告 → HID/坐标验收。

**目前仍处于 SPI/身份确认阶段。** 本轮不把 A3 当作 PID 的替代，也不恢复旧的 ACK-only 5312 次同步下载路径；未把“触摸已修复”作为结果。

## 5. v71 实机照片与 v73 大字身份探测

用户提供[原始照片副本](../../logs/v71-user-photo.jpg)。肉眼读到 `RX32=0x8200`、`ACK1=0x82`、`CFG1=0x10001`、`CFG2=0x10001`；CLK6 从 `0x1010000` 到 `0x1000000`，INFRA4 为 `0xa1fc01c0`。小字照片的 OCR 未可靠识别完整两行，数字以肉眼判读记录；大字版本用于后续复核。

这组 CLK6 的 PDN bit23 为 0，INFRA4 的 SPI4 bit25 也为 0。故 G1 暂不测试：已打开的门控不再当作本轮主因。RX32 的低两字节是 `00 82`，不是 A3；仅凭“等于发出的命令”仍不把物理短接或回环当成已证事实。

用户反馈字号太小，新增[大字诊断布局](../include/touch-gate-diagnostic.c)：关键数据用 32×64 字符（原 16×32 的宽高各两倍），每项一行。所有事务结束后才改变显示状态，报告结束恢复原光标和字号，保留原 25 秒拍照停留。

[v73 镜像](../../images/k9x-ios-v73-ICE-BIG.img) SHA256：`b5b4866440b9e23297090067f10388fec0e192e88264342b70143cfa9c255b26`。

[有界 ICE 探针](../include/touch-ice-probe.c) 在原 v70 ACK2 之后执行，最多 8 个短事务：MCU-OFF 进入 ICE 一次，PID 地址写/原始读各 3 次，退出 ICE 一次。不下载固件、不启用 XNU 触摸、不写任意触摸内存。每笔单独 CS，开始清 FIFO/陈旧完成位，超时上限 200 万次轮询并清理。

厂商[ICE 进入命令](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/input/touchscreen/ILITEK9882/ilitek_v3_ic.c#L244-L267) 证明 MCU-OFF 的首字节为 0x25，不是 0x1f；[PID 打印](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/input/touchscreen/ILITEK9882/ilitek_v3_ic.c#L1068-L1085) 把完整 PID 右移 8 位后打印，因此 Android 的 `78071f` 对应完整值 `0x78071fXX`，不是直接期待 `0x0078071f`。ICE 读丢弃命令期字节 rx[0]，从 rx[1..4] 拼小端 PID；三次稳定且 PID 高 16 位为 0x7807 才设置身份匹配标志。

- `ICE flags` bit0：进入命令事务完成；bit1/2/3：各次读事务完成；bit4：退出事务完成；bit8：三次 PID 相同且为 7807。
- 事务完成标志不等于芯片命令被确认；只有有效 PID 才支持身份判断。
- 大字页显示 PID0/1/2、flags、原始 ICE RX0/RX1。
- 新增 2 项本机 C mock 测试验证有效 PID、echo 非身份、限时退出、显示状态恢复；连同原 11 项共 13 项。
- v73 已实机拍照验证大字布局，flags=0x1、PID0/1/2 与 RX0/1 均为未覆盖的 0xffffffff 哨兵值；capture hook 本身仍不多读 FIFO，ICE 身份事务是明确新增的短事务。

## 6. v74/v75 实机收口（2026-11-10 23:15）

[厂商 SPI 准备流程](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/spi/spi-mt65xx.c#L362-L374) 始终打开 FINISH_IE/PAUSE_IE（bit16/17）。v74 只对新增 ICE 事务采用该设置并在返回前关闭；原 ACK2 对照保持不动。
[厂商软复位流程](https://github.com/oppo-source/android_kernel_oppo_mt6833/blob/654f1cb8a1516d446e19832e4da2aad314630469/drivers/spi/spi-mt65xx.c#L287-L298) 在设置 RST 后读回 CMD，再清 RST；v75 在 v74 上仅补齐这项复位读改写。

| 版本与实机证据 | XFER count | FAIL stage | FAIL ST0 | FAIL ST1 | FAIL CMD | PID结果 |
|---|---:|---:|---|---|---|---|
| [v73 大字页](../../logs/v73-user-photo.jpg) | 未加此字段 | 未加此字段 | — | — | — | flags 0x1；PID0/1/2 哨兵值 0xffffffff |
| [v74 事件位](../../logs/v74-user-photo.jpg) | 0x3 | 0x2 | 0x0 | 0x1 | 0x33000 | flags 0x1；尚未完成 PID 读取 |
| [v75 复位读回](../../logs/v75-user-photo.jpg) | 0x4 | 0x3 | 0x0 | 0x1 | 0x33000 | flags 0x1；尚未完成 PID 读取 |

阶段 1 为 ICE MCU-OFF 命令，阶段 2 为第一次 PID 地址命令，阶段 3 为第一次 SPI_READ 数据事务。close 清理失败也计入 XFER count，但 FAIL stage 只保留第一次失败。

**v75 这一轮推进到了第 3 笔，但没有得到有效 PID，触摸仍未通。** 单轮对照支持复位读回有帮助，尚不作跨冷/热启动的稳定性保证。0xffffffff 是软件初值，不是芯片读回 0xffffffff 的证据；flags 的事务完成位也不证明芯片接受了命令。

最新 [v75 实验镜像](../../images/k9x-ios-v75-RESET-BIG.img) SHA256：`32510ba2d0a8e5a40f99aba0c0ab6af0c72466b9e052f8fbe96316b2aa06f80b`。已用当前源码重建并逐字节确认一致，见[构建回执与源码哈希](../../logs/v75-build-receipt.json)。所有 13 项离线测试通过，见[ACK/门控测试](../../logs/v75-ack-gate-tests.txt)与[ICE/显示测试](../../logs/v75-ice-font-tests.txt)。离线测试验证软件契约，不取代真实 SPI 波形或触摸验收。

复现当前实验：

```sh
python3 repo/scripts/make_touch_gate_images.py images/k9x-ios-v69-CLK.img images/NEW-v75.img \
  --big-font --ice-probe --finish-ie --reset-readback
```

下一步收窄为：核实连续 FIFO 事务的完成/片选收尾语义与真实 CS/SCK/MOSI/MISO 波形，必要时采用硬件中断状态对照。先解决 PID 读事务，不扩展固件下载、DSI 或供电试探。本轮停止继续堆参数。所有照片已保存副本，原文件未改动；原工作树的未提交源修改保持原状。