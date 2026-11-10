# AGENTS.md

> **v77 最新进展**：[本机固件与可逆读写](docs/06-本机固件分块与可逆读写.md)。实机 dummy 从0写A55A5AA5并读回，随后恢复0并读回；flags=0x3b7f。FW的FwUp包装、HEX记录与4块CRC已核验，正常模式AP/DATA/TUNING共90624字节；尚未加载运行，也未验收桌面触摸。
>
> **v76 通信进展**：[GPIO 身份打通记录](docs/05-GPIO触摸身份打通.md)。实机三次 PID=0x78071f05、flags=0x37f、寄存器恢复通过。旧“芯片不响应/MISO物理无信号”结论已被反证；当前转向本机固件分块/CRC/IRAM加载，再接报告与HID。桌面触摸尚未验收。
>
> **前一阶段证据（2026-11-10）**：[二次核验与 ACK 修复](docs/04-触摸二次核验与ACK修复.md)。下文旧的“MISO 恒 0”“引脚/供电/时钟已排除”“逻辑分析仪是唯一推进手段”不再作为已证明事实。先区分 loader、现存 XNU 源码与镜像内 XNU；v70 修正 ACK 时间窗后为 0x82；v75 实机失败在第 3 笔 PID 数据读取，ST0=0/ST1=1/CMD=0x33000。大字页有效，触摸仍待身份确认及完整固件/报告链路。

给继续做这件事的人 / AI 的工作约定。

先读 [README.md](README.md)，再读 [docs/00-复盘-从零到桌面.md](docs/00-复盘-从零到桌面.md)。
那两份里有的东西这里不重复。

---

## 1. 这个项目是什么

一台 **OPPO K9x（PGCM10 / MT6833 / 天玑 810）** 的 Android 手机，用自写的裸机 loader
从 LK 引导链直接跳进 Apple 的 **XNU 8796.121.2**，跑 **iOS 16.5 的 iPhone X 用户态**。

**当前状态**：桌面、显示、三个实体按键可用；GPIO SPI 已读到真实触摸芯片 PID（v76），固件与报告/HID 链路尚待收尾。

不是模拟器，不是套壳。每次运行 300 秒后自动回 Android。

---

## 2. 硬约束（违反了会浪费一整轮 10 分钟）

| # | 约束 | 后果 |
|---|---|---|
| 1 | **不能用 `fastboot boot`** | 实测原厂镜像也会让 LK 崩（`lk_crash`）。只能 `fastboot flash boot` |
| 2 | **boot 分区 32 MiB 是硬上限** | 超了刷不进去 |
| 3 | **AVB footer 必须保留** | 原厂镜像尾部有 `AVBf` + `VBMeta`，`build_v3.py` 会重建 |
| 4 | **替换 `mtkloader.bin` 后必须恢复 blob 头 `0x10` / `0x28` / `0x30`** | 不清零就是「payload 在偏移 0」→ 无限重启。踩过两次 |
| 5 | **DTB 必须保留 stock 节点骨架** | LK 会按节点名查找并叠 dtbo，缺了拒绝启动 |
| 6 | **framebuffer 的 reserved-memory 没有 `no-map`** | 内核要自己当 no-map 处理，否则 `ioremap_wc` 拒绝 |
| 7 | **`touchscreen=3` 会让启动卡 167 秒** | 那是 ILITEK host-download 在空转，不是死机。会自己回来 |
| 8 | **别同时改两个东西** | 前序会话在 v44–v58 就是这么做废了 12 个版本 |

---

## 3. 工作流（一次改动 = 一轮 10 分钟）

```
改源码
  → bash mtk/loader/build.sh -DXNU_WDT_SECONDS=0 -DMENU_DEFAULT_XNU=1 -DXNU_FLAT_BOOT=1 -DTOUCH_RESET_GPIO
  → python3 scripts/make_v60_image.py <新 mtkloader.bin> <out.img>      # 保留 blob 头字段
  → python3 scripts/verify_e1_image.py                                  # 逐字节确认差异范围
  → fastboot flash boot <out.img>
  → 观察屏幕 → 记录读数
```

**每轮必须记三件事**：改了什么（单变量）、屏幕读数、和上一版的差异。
没有记录的版本等于没做——前序会话 20 个版本里有 12 个因为没控制变量而作废。

---

## 4. 调试通道

| 通道 | 怎么用 |
|---|---|
| **屏幕停留** | loader 里有 `--- holding 25 s for a photo ---`，专门留拍照窗口。改 `dbg_delay_ms(25000)` 调时长 |
| **黄色日志** | 内核跑完 300 秒后，loader 把 XNU 日志尾 60 行打在屏幕上，停 240 秒 |
| **周期计时** | 一轮固定 **602 秒**（300 内核 + 240 停留 + 重启）。三轮实测 602/602/601，是很好的基线 |
| **Android 侧 dump** | `scripts/android-touch-dump.sh`，纯只读，不需要刷机 |
| **pstore** | `/sys/fs/pstore/console-ramoops`（Android 侧） |
| **寄存器回读** | loader 里 `out_hex(rd32(...))`，比猜快一百倍 |

**能读寄存器就别猜。** 本次三个 bug 里有两个是靠回读和厂商源码对出来的，不是试出来的。

---

## 5. 历史排除清单（以二次核验证据为准）

```
SPI 控制器超时 / FIFO 分段      → STA0 DONE 置位，成功率 99.4%
SPI 模式 CPOL/CPHA             → 已改为模式 0，无变化（但必须是对的）
引脚复用                        → MODE1/MODE12 与 Android 逐位一致
IES（输入使能）                 → 全开，与 Android 一致
触摸复位 GPIO15                 → 已按 Android ili_tp_reset 时序拉过
供电轨                          → Android 驱动自己用 dummy regulator，硬件常开
面板 DSI 初始化                 → 42 条 DCS 已发出，INTSTA 0x7b2
芯片是否上电                    → Android 复位后 16 ms 读到 PID 78071f
```

完整列表见 README 的「已经排除的清单」。

---

## 6. 下一步（按性价比排序）

### 6.1 逻辑分析仪量 SPI4（与连续事务状态机核验并行）

在 Android 下抓「复位后 16 ms 读 PID」的完整波形，再和 iOS 侧对比。
四根线上有没有信号、CLK 频率对不对、MISO 有没有被拉起来——一次全清楚。
**不需要刷机，不需要改代码。**

### 6.2 帧率实验（零风险，纯收益）

`fb_threads=1` → `4`，看能否从 10 fps 回到 21 fps。

### 6.3 `SPI_PAD_SEL` 对照

Android 侧 debugfs 挂不上（`/sys/kernel/debug` 建不出来），只能从厂商 `pinctrl-mt6833.c` 读定义。

---

## 7. 不要做的事

- **不要在没读寄存器的情况下改 SPI 时序**。前序两天的 5312 次 IRAM 写入、四相位探针、
  ICE 协议逆向，全部是在跟一个空控制器（SPI2）说话。先确认地址、时钟、引脚，再谈协议。
- **不要把「某次进桌面」当成「这个版本稳定」**。v43 曾被认为稳定，隔天同一个字节不差的镜像就起不来。
- **不要一次刷超过一版**。每版之间隔 10 分钟，等它自己回来。
- **不要在没备份的情况下碰 preloader / lk / seccfg**。只碰 `boot`。

---

## 8. 回滚

```sh
adb reboot bootloader
fastboot flash boot stock-boot.img
fastboot reboot
```

原厂 `boot.img` 的 SHA-256：

```
f3d902857d8138a491f02107e42e310bbf33050e5fa107880dd36ca04392efbb
```

卡在循环重启：长按电源 15 秒 → 按住音量下 → 插 USB → fastboot。

---

## 9. 记录要求

每次改动请更新 `docs/00-复盘-从零到桌面.md` 的对应小节，格式：

```
| 版本 | 改动 | 结果 |
|---|---|---|
| vNN | 一句话说清单变量 | 屏幕读数 / 现象 |
```

**读数要原文照抄，不要转述。** 例如写 `MODE1 0x220007` 而不是「引脚对了」。

---

## 10. 边界

- 本仓库**不含**任何 Apple 二进制、不含设备固件。需要 iOS 用户态请自行从 Apple 的 IPSW 提取。
- 设备是机主自己的，bootloader 已解锁。
- 只碰 `boot` 分区。`preloader` / `lk` / `seccfg` / `nvram` / `persist` 一律不动。
