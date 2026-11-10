# IRAM 固件加载、全量读回和活体握手打通（v78）

> 2026-11-11 00:43 实机结果：三块90,624字节全部写入、逐字节读回及CRC通过；code reset后收到A3/0x20真实TP信息回复。**固件已运行，桌面触摸/HID尚待收尾。**

[原始照片副本](../../logs/v78-user-photo.jpg)、[源码哈希与逐字节重建回执](../../logs/v78-build-receipt.json)。

```text
BB PID0/1/2  0x78071f05
BB flags     0x3b7f
BB bitsteps  0x171730
BB frames    0x861
FW phase     0x7
FW error     0x0
FW verified  0x7
FW written   0x16200
FW readback  0x16200
CRC AP       0xbb7b8d39
CRC DATA     0x061ef7ef
CRC TUN      0x7532981c
FW ack       0xa3
FW reply     0x20
FW TP x      0x7ff
FW TP y      0x7ff
FW ms        0xae61
```

`0x16200=90624`，`0xae61=44641ms`。内部TP参数上限2047不直接当成像素报告坐标上限；43/72字节格式、checksum和坐标缩放仍须真实报告证据。

## 实现与边界

[固件加载核心](../include/touch-firmware-load.c)、[包结构](../include/touch-firmware-package.h)、[打包器](../scripts/make_touch_firmware_image.py)。

1. 三次PID严格为78071f05，dummy读写及原值恢复通过后才进入。
2. 固定本机固件SHA、FwUp解包、AF/B0映射、3个运行块CRC；MP不加载。
3. 128字节分包写入AP/DATA/TUNING；每块所有字节（含尾4CRC字节）逐字节读回比较，并对读回数据独立计算CRC32/MPEG-2。
4. **本版没有使用DMA CRC**，不把软件全量读回称作DMA结果；未写flash、WDT控制或DMA寄存器。
5. 所有块通过后才写0x40040=AE进行code reset，再退出ICE、等100ms。
6. 真实发送非ICE F6 20预命令、20查询、读取TP回复，检查ACK A3、payload头20及非零尺寸；未用info_from_hex缓存冒充运行状态。
7. 60秒全局时限；写/校验失败不启动半写固件，保留MCU停止状态，恢复GPIO交回系统；启动后的握手失败单独标错。
8. GPIO恢复检查通过。两份touchscreen=0未改，所以本版尚未让XNU读取报告。

## Boot镜像保真

- 代码槽在解压blob+0x20000，全部ALLOC区段（含.bss）限制在0x20000..0x24000。
- 运行块数据在0x24000..0x3a200，元数据在0x3f000..0x3f050。
- 均在原loader padding内，与原BSS、Android Image、XNUP/XNU无重叠。
- loader头0x10/0x28/0x30、Android回链、XNU、ramdisk、DTB等字节保持；VBMeta沿用，未宣称重新签名。

[v78镜像](../../images/k9x-ios-v78-FW-BIG.img) SHA256：`66a413df7488859ca828134ace5e32e6e2f2db604d5d66b88230535e7e1ffad2`，已从当前源码逐字节重建一致。固件字节只在本地设备证据/镜像，未加入公开Git。

## 测试

28项离线测试全部通过：原24项加[固件核心4项](../scripts/test_touch_firmware_load.py)。

[IRAM peer](../tests/ilitek_iram_peer.c) 用本机真实固件生成临时只读fixture，验证所有目标和字节、校验前不reset/exit、读回损坏、超时、错误PID/dummy、传输失败、live回复无效等路径；[长帧peer](../tests/gpio_long_frame.c) 逐位验证129/133字节帧及边界。软件测试之外，另有本轮真实读回与活体回复照片。

```sh
python3 repo/scripts/test_touch_firmware_load.py
python3 repo/scripts/make_touch_firmware_image.py images/k9x-ios-v69-CLK.img assets/device/touch/FW_NF_ILI7807S_TIANMA.img images/NEW-FW.img
```

## 接下来

先抓真实手指报告，区分43字节12-bit与72字节高分辨率、确认负和校验；然后仅替换镜像内旧Goodix触摸线程，跳过GPIO15硬复位和旧host-download，保留已运行固件，走既有hakios_touch_post/HID。不得照抄旧的32字节读/43字节校验错配，也不得混用ICE offset1与slave offset3。
