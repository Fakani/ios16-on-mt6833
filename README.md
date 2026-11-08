# iOS 16 在 MT6833（OPPO K9x / PGCM10）上的真机移植记录

> 一台天玑 810 的 Android 手机，跑起了 Apple 的 XNU 内核和 iOS 16 用户态，
> 桌面、显示、三个实体按键可用；触摸没通。
> 这份仓库是整个过程的技术记录：每一个版本改了什么、读数是什么、哪里卡住了。

---

## 结论先行

| 目标 | 状态 |
|---|---|
| 进入桌面（SpringBoard） | **已达成** |
| 显示（1125×2436 软件合成） | **已达成** |
| 按键（电源 / 音量上 / 音量下） | **已达成** |
| 触摸 | **未达成** |

这不是模拟器，也不是套壳：真机从 LK 引导链直接跳进 XNU，跑的是从 iPhone X IPSW 里提取的 iOS 16 用户态。

## 硬件

| 项 | 值 |
|---|---|
| 机型 | OPPO PGCM10 / OPD2A0（K9x，项目代号 210A0） |
| SoC | MT6833（天玑 810），2×Cortex-A76 + 6×Cortex-A55 |
| GPU | Mali-G57 MC2 |
| 存储 | UFS 2.2（`11270000.ufshci`） |
| 面板 | 1080×2400，ILI7807S TDDI（Tianma），C-PHY DSI 3-lane |
| 触摸 | ILITEK ILI7807S，SPI4 `11018000`，IRQ GPIO14 / RST GPIO15 |
| 帧缓冲 | LK 交接 `0x76720000`，stride 4352，a8r8g8b8 |
| 引导 | Android boot header v2，page 2048，内核入口 `0x40080000` |

## 引导链

```
MTK BootROM → preloader → LK → boot.img
                                  └─ mtkloader（裸机，0x40080000）
                                       ├─ 读 LK 留下的 FDT，构造 Apple DeviceTree
                                       ├─ 初始化面板（42 条 DCS over DSI VM_CMD）
                                       ├─ 加载 XNU Mach-O + ramdisk + iOS 根
                                       └─ jump_to_kernel
                                            └─ XNU 8796.121.2
                                                 ├─ MTK UFS 驱动（只读）
                                                 ├─ APFS 根（xnusys 分区）
                                                 ├─ MiniIOMobileFramebuffer（写 LK 的 framebuffer）
                                                 └─ launchd → backboardd → SpringBoard
```

每次跑 300 秒后 `loader_return_after` 把控制权交还 loader，warm reset 回 Android。

## 三个「不修就永远不可能通」的 bug

这是本次最重要的产出。前序两天的所有 SPI 调试都建立在这三个错误之上。

| # | 错误 | 正确 | 影响 |
|---|---|---|---|
| 1 | SPI 模式 3（`CPHA\|CPOL`） | 模式 0 | 时钟极性和相位全反 |
| 2 | `SPI2_BASE 0x11012000` | `0x11018000`（SPI4） | **一直在跟一个空控制器说话** |
| 2b | 引脚 25/26/27/28 | 12、13、97、98、99、100 | 复用到了别的模块上 |
| 3 | `CLK_CFG_2` bit24 / bit31 | `CLK_CFG_6` bit[17:16] + `CLK_CFG_UPDATE` bit26 | **SPI 时钟源从未被选中** |

第 3 条的出处：`drivers/clk/mediatek/clk-mt6833.c`

```c
MUX_CLR_SET_UPD(CLK_TOP_SPI_SEL, "spi_sel", spi_parents,
                CLK_CFG_6, CLK_CFG_6_SET, CLK_CFG_6_CLR,
                16 /* lsb */, 2 /* width */,
                INV_BIT, CLK_CFG_UPDATE, TOP_MUX_SPI_SHIFT /* 26 */);

static const char * const spi_parents[] = {
    "tck_26m_mx9_ck",   /* 索引 0，26 MHz */
    ...
};
```

三个都修好之后，引脚复用（`GPIO_MODE1 = 0x00220007`、`GPIO_MODE12 = 0x11122221`）
和控制器配置（`CMD = 0x3000`、`STA0` DONE 置位）都和 Android 完全一致——
**但 MISO 仍然是 `0x0`**。

## 版本时间线

| 版本 | 改动 | 结果 |
|---|---|---|
| v17 | 首个进桌面的镜像 | SpringBoard 出现，用户目视确认 |
| v33–v39 | 三个按键 + SPI 探针 | 按键全通；触摸 MISO 恒 0 |
| v43 | ACK 门控 host-download | 21 fps，但门控判据是 MOSI 回环，形同虚设 |
| v60–v61 | 首次在 loader 里发 DSI | **循环重启**——打包脚本覆盖了 blob 头 0x28/0x30 |
| v62 | 修好打包 + 42 条 DCS | 正常进桌面，**5 surfaces** |
| v64b | 加触摸复位 GPIO15 | `RESET (GPIO15) done`，但仍无 ACK |
| v66 | SPI 模式 3 → 0 | 仍 0 |
| v67 | SPI2 → SPI4 + 正确引脚 | 仍 0；且 loader 起不来（引脚冲突） |
| v68 | 加寄存器回读 | MODE1/MODE12 待验 |
| **v69** | **修 SPI 时钟 mux** | 引脚/控制器全对，**MISO 仍 0** |

## 目录

```
docs/      完整复盘、总体方案、设备实测档案、可移植性分析
scripts/   镜像打包、IPSW 解剖、寄存器探针、Android 侧 dump
include/   panel-ili7807s-init.h —— 从厂商面板驱动提取的 44 步初始化表
dts/       simple-framebuffer 片段
logs/      Android 侧触摸链路实测输出（序列号已脱敏）
vendor-reference/  面板驱动原文（GPL-2.0，来自 OPPO 开源内核）
```

## 复现要点

1. **`fastboot boot` 在这台机器上不可用**，实测原厂镜像也会让 LK 崩溃（`bootreason=lk_crash`）。只能 `fastboot flash boot`。
2. **boot 分区 32 MiB 是硬上限**，AVB footer 必须保留（`build_v3.py` 的做法）。
3. **loader 的 arm64 Image 头里 0x10/0x28/0x30 三个字段是打包器写的**，直接替换 `mtkloader.bin` 会清零它们，导致「payload 在偏移 0」→ 无限重启。
4. **LK 会按节点名找 stock 节点并叠 dtbo**，DTB 必须保留骨架。
5. framebuffer 的 reserved-memory 没有 `no-map`，内核要自己当 no-map 处理。

## 还没做完的

MISO 恒 0，只剩三种可能：

1. `SPI_PAD_SEL` 取值不对（没有 Android 侧对照数据，debugfs 挂不上）
2. 芯片的 SPI 从机在等某个使能（厂商私有 DCS，或 TDDI touch 部分独立供电域）
3. MISO 线上确实没信号

**下一步应该用逻辑分析仪量 SPI4 四根线**，在 Android 下抓「复位后 16 ms 读 PID」的波形，和 iOS 侧对比。
这能把三种可能一次分开，且不需要再刷机。

## 参考

- [hakios-mt6768](https://github.com/oosexgang/hakios-mt6768) —— MTK + Mali + iOS 16.5 的先行者
- [ios-sweet](https://github.com/0xSojalSec/ios-sweet) —— SM7150，工程日志最详细
- [oppo-source/android_kernel_oppo_mt6833](https://github.com/oppo-source/android_kernel_oppo_mt6833) —— 本机内核源码（branch `oppo/mt6833_s_12.1_oppo_k10_5g`）
- [Dodaskot/a22x-mainline](https://github.com/Dodaskot/a22x-mainline) —— 同 SoC 的 Linux 移植

## 许可

本仓库的分析、脚本、文档：MIT。
`vendor-reference/` 下的文件来自 OPPO 开源内核，遵循 GPL-2.0。
不含任何 Apple 二进制、不含设备固件。
