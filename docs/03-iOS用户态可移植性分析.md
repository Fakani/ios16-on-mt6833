# 把 iOS 16.5 用户态跑在非 Apple 内核 / 非 Apple SoC 上：逐层可行性与硬阻塞

> 目标：iPhone10,3/10,6（iPhone X，A11/T8015）的 iOS 16.5 (20F66) IPSW → 联发科天玑 810（MT6833，2×Cortex-A76 + 6×A55，Mali-G57 MC2）。
>
> 结论先行：**这不是「移植 iOS」，而是「把 Darwin 用户态搬到 MTK 上」**。引导链（iBoot）、GPU 驱动（AGX）、安全子系统（SEP）三处是硬阻塞；用户态本身可原样跑，前提是重写整个 SoC 移植层。已有先例：HakiOS 把 XNU 8796.121.2（= iOS 16.5 内核）跑在骁龙 778G 上，SpringBoard 起得来；另有 MT6768（Helio G85，Mali-G52）端口。

---

## 0. 先修正题设里的三处事实

| 题设说法 | 实际 | 依据 |
|---|---|---|
| kernelcache 里有 AppleDCP | **A11 没有 DCP**。DCP 自 **A14** 起才有；iPhone X 的显示路径是 AppleCLCD + display-pmu,acorn + DART + IOMobileFramebuffer | [iPhone Wiki: DCP](https://www.theiphonewiki.com/wiki/DCP)、[Asahi: Add DCP display driver](https://github.com/AsahiLinux/linux/commit/41e8ee7a909bf4dff03fb3557814ca9fbf3e6144) |
| iBoot「能不能在非 Apple 硬件上跑」 | 问题问反了：**iBoot 根本不该出现在这条路上**。闭源 + 加密 + 按 Apple 寄存器写死，正确做法是**不用它**，自写 loader 链式加载 XNU | 见 §1、§7 |
| Mali 上「没有任何 Metal 实现」 | 上游（Mesa）确实没有；但**存在私有实现**：HakiOS 的 MT6768 端口用 Mali-G52 + panfrost + 自写 Metal 驱动，CoreAnimation 走 Metal 画壁纸 | [hakios-mt6768](https://github.com/oosexgang/hakios-mt6768) |

---

## 1. 引导层：iBoot 是加密的，而且它假设的世界只有 Apple SoC

### 1.1 iBoot 加密与 IMG4 家族

- **加密**：量产设备的 LLB/iBoot/iBSS 等 im4p 载荷**用 GID 密钥加密**。GID 是熔丝在 SoC 内的 AES-256 密钥，**永不出芯片**，只能把 KBAG 喂给片内 AES 引擎当解密 oracle。
  - Apple 官方：启动链每级由 Apple 签名、逐级校验（[Boot process](https://support.apple.com/guide/security/boot-process-for-ipad-and-iphone-devices-secb3000f149/web)）。
  - KBAG/GID/AES 引擎机制：[Anatomy of the macOS Boot Chain](https://stack.int.mov/a-reverse-engineers-anatomy-of-the-macos-boot-chain-security-architecture)。
  - A11 属 checkm8 范围（A5–A11），可用 BootROM 漏洞 + AES 引擎把 iBoot/iBSS/ramdisk **解出明文**（[CERT VU#941987](https://www.kb.cert.org/vuls/id/941987/)、[ipwndfu](https://github.com/axi0mX/ipwndfu)）。但**只在真 A11 上成立**，明文对 MTK 毫无用处（见 1.3）。

IMG4/IM4P 结构（ASN.1 DER）：

    IM4P ::= SEQUENCE {
        type     IA5String,   -- ibot / ibss / krnl / dtre / rsep / sepi
        desc     IA5String,
        payload  OCTET STRING,               -- 加密时是密文
        keybag   [0] OCTET STRING OPTIONAL   -- KBAG：类型字节 + IV(16) + 被 GID 包裹的 AES key(32)
    }
    IM4R ::= SEQUENCE { INTEGER ... }   -- restore info：boot nonce 等
    IM4M ::= SEQUENCE { ... }           -- manifest：每组件 digest + ApNonce + 芯片/板号 + 签名
    IMG4 ::= SEQUENCE { IM4P, IM4M }

- 工具链：img4tool 的 -e -o（拆 payload）、--iv/--key（解密）、-n rkrn（改类型）、-c ... -m（合成 IMG4）见 [img4tool](https://github.com/tihmstar/img4tool)；现代替代是 pyimg4 / ipsw（blacktop）。
- **personalization**：TSS 按 ECID/chip-id/board-id + ApNonce 签发 IM4M，iBoot 校验 manifest 里每个组件的 hash + nonce 与本次启动一致。换设备刷同一 im4p 必然失败——不是加密强度问题，是**每台机器一张票**。

### 1.2 iBoot 对硬件的假设（真正的墙）

iBoot 是裸机程序，直接按**固定物理地址**操作 Apple 外设。A11（T8015）的硬件地图在 Linux 上游 Apple DTS 里写得很清楚：

- AIC 中断控制器 interrupt-controller@232100000（apple,t8015-aic）；iBoot 设备树里写作 aic / aic,1。
- PMGR 电源/时钟 power-management@232000000（apple,t8015-pmgr）。
- PMU/PMIC：spmi@235180700（apple,t8015-spmi，Dialog）、watchdog@2352b0000、pinctrl@233100000。
- 存储：apple,t8015-sart（IOMMU）+ apple,t8015-nvme-ans2（ANS2 NVMe）。
- AOP 邮箱：mbox@257008000（apple,t8015-asc-mailbox）。
- 显示：display-pmu,acorn + dart-disp0（dart,t8015）+ AppleCLCD。
- 安全：sep 节点、effective-security-mode-sep（SEP 握手在 iBoot 阶段已开始）。

来源：[linux t8015.dtsi](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/apple/t8015.dtsi)、[iPhone X (D22AP) 设备树转储](https://gist.github.com/freedomtan/1bbada7f19b7eb058e380e9d219ab268)。

iBoot 至少要：初始化 AIC 与异常向量、配 PMGR/PMU 上电时序、初始化 ANS2 + SART 才能读盘、拉起 AOP、校验并跳转 SEP 固件、读 DeviceTree im4p（Apple 私有 DT，不是 FDT/DTS）。**MT6833 上这些 IP 一个都不存在**：MTK 用 ARM GICv3 + generic timer + PSCI + 自家 PMIC/display/UFS/IOMMU。

### 1.3 结论

**硬阻塞（不可绕过，只能弃用）。** 三条独立理由，任一条都够：

1. 信任根不同：iBoot 的上一级是 SecureROM，MTK 的上一级是 BootROM → preloader → LK（[U-Boot README.mediatek](https://qemu.googlesource.com/u-boot/+/refs/heads/master/doc/README.mediatek)）。MTK 的 preloader/LK 不认识 IMG4、不验 Apple 签名，只加载 Android boot image。
2. 即使解密出明文（只能在真 A11 上做），写死的寄存器地址在 MT6833 上是空洞或别的 IP——第一条 MMIO 写就挂死，串口都来不及打印。
3. 没有 Apple 的 AES/GID 引擎，iBoot 里「解密下一级」的逻辑没有执行环境。

**唯一正确路线：不用 iBoot。** 自写 loader（裸机或 UEFI 应用），从 MTK 的 boot 分区链式启动 XNU：建 XNU 期望的设备树、布局内存、加载 kernel+ramdisk、传 boot-args。HakiOS 的 xnuloader / mtkloader 就是这个（[架构](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/concepts/architecture.md)）。

---

## 2. 内核层：kernelcache 能解，XNU 能编，缺的是整个 platform 层

### 2.1 kernelcache 的封装与解包

- 形态：kernelcache.release.iphone10b = IM4P（type krnl）→ **LZSS 压缩**（Apple 变体）→ Mach-O（arm64e，含 kext collection / __PRELINK_INFO / KLD 段）。
  - iPhone10b 的 LZSS 且 im4p 未标注，有明确记录：[blacktop/ipsw issue #1324](https://github.com/blacktop/ipsw/issues/1324)。
- 解包：img4tool -e -o → LZSS 解压 → Mach-O；或一步用 pyimg4 / ipsw kernel extract / ktool。
- 解出来能干什么：拿 kext 列表、符号、字符串（例如 AGXMetalA11、IOAcceleratorES 的匹配名），做逆向分析——**仅此而已**。这份二进制是按 A11 的 MMIO 布局编译的，不能「改个地址」就跑。

### 2.2 kext 清单（A11 实际存在的）

AppleARMPE（platform expert）、AppleAIC（中断）、ApplePMGR（电源/时钟）、AppleSEPManager（SEP 通信）、AppleANS2Controller（NVMe）、AppleCLCD（显示）、SART/DART、AppleM68Touch / AppleMultitouchSPI（触摸）、AGX 系列（GPU，系统里是 AGXMetalA11.bundle）。**没有 AppleDCP**（A14 起）。

共同点：**闭源、直接操作 Apple 私有寄存器、无开源替代**。所以「把 kernelcache 里的驱动拿来用」不存在；能用的只有**开源的 XNU 本体**（xnu-8796.121.2 正是 iOS 16.5 的内核，APSL 开源）。

### 2.3 「把 platform expert 换成 MTK」到底要做什么

先纠正一个误解：不是「替换一个类」。开源 XNU 里 IOPlatformExpert 只是抽象基类，Apple 真机的实现是**闭源 kext AppleARMPlatform**。没有它，IOKit 直接 panic——HakiOS 的 GenericARMPE.cpp 开头原话：

> On Apple hardware the platform expert comes from a closed kext (AppleARMPlatform). Without one, IOKit falls through to IOPanicPlatform ("Unable to find driver for this platform").

（[GenericARMPE.cpp](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/xnu/files/iokit/Kernel/GenericARMPE.cpp)）

真实工作量清单（按 HakiOS 的实际文件表，[xnu/README.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/xnu/README.md)）：

| 要做的东西 | 说明 | 难度 |
|---|---|---|
| GenericARMPE + 设备树解析 | 发布 DT 节点成 nub，命名机器 | 中 |
| GICv3 + generic timer + PSCI 多核 | gic_v3_irq.c / generic_arm64_support.c / psci_smp.c | 中（MTK 正好 GICv3） |
| minicrypto | 替代闭源 corecrypto（MD5/SHA/HMAC/DRBG/AES） | 中 |
| APFS 只读 + ramfs | 读 SSV 根卷；libzbitmap/libdeflate 解 decmpfs | 大 |
| AMFI + Sandbox 桩 | kern_minimac.c，否则用户态起不来 | 中 |
| AppleKeyStore 桩 | keybag/钥匙串（见 §5） | 中 |
| IOSurface / IOMobileFramebuffer 桩 | 见 §6 | 大 |
| 存储/输入/GPU/网络/音频驱动 | UFS、触摸、GPU、Wi-Fi、ADSP | 很大 |

**工作量级别：人年级，团队级。** 参照 HakiOS：4 人以上团队 + loader + UEFI 移植 + 数十个驱动 + Metal 编译器。它的 **MT6768 端口**（Helio G85，比天玑 810 更弱）目前状态：4 核、只读 eMMC 系统镜像、720×1640 显示、SPI 触摸、Mali-G52 + panfrost + Metal 驱动、Wi-Fi 可用；**音频/相机/蜂窝/蓝牙全缺**（[hakios-mt6768](https://github.com/oosexgang/hakios-mt6768)）。不是「周末项目」量级。

### 2.4 arm64e / PAC

iOS 16.5 系统盘同时带 dyld_shared_cache_arm64 与 _arm64e。非 Apple 核上最省事的做法是**走 arm64 切片**（HakiOS 文档明确用 20F66__iPhone10,3_6/dyld_shared_cache_arm64），绕开 arm64e ABI 与 PAC 密钥设置；Bergamota 则专门做了 arm64e/pointer-authentication gap 工具（[comparison.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/comparison.md)）。**结论：PAC 不是阻塞，选 arm64 切片即可。**

---

## 3. 用户态层：几乎「可移植」，但要靠内核喂饱它

### 3.1 iOS 16 的 rootfs 结构

- 根卷是 **APFS + SSV（Signed System Volume）**：只读、带 seal、启动时验证（[Apple: Signed system volume security](https://support.apple.com/guide/security/signed-system-volume-security-secd698747c9/web)）。
- iOS 16 起系统内容分装在 **cryptex**：/System/Cryptexes/OS/...（系统 cryptex，dyld 共享缓存就在下面）、/System/Cryptexes/App/...（App cryptex，Safari/WebKit 等可独立更新组件）。
- dyld 共享缓存的真实路径，Apple 自己的 dyld 源码写得很直白：

    /System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e   // iPhone/iPad
    /System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64    // 老设备

  来源：[apple-oss-distributions/dyld libdyld/utils.cpp](https://github.com/apple-oss-distributions/dyld/blob/main/libdyld/utils.cpp)。
- /private/preboot/ 存 cryptex 与启动状态；用户数据卷是独立 APFS 卷，受 Data Protection 保护（§5）。
- 文件大量使用 **decmpfs** 压缩（HakiOS 为此引入 libzbitmap/libdeflate）。

### 3.2 启动链与 SpringBoard 的依赖

launchd → logd / notifyd / cfprefsd / runningboardd → backboardd → SpringBoard → App（HakiOS README 的原话顺序）。

SpringBoard 能起来，内核必须提供这些 IOKit 服务（HakiOS 的替换清单就是「缺什么补什么」的实证）：

- IOPlatformExpert / IODeviceTree
- IOAcceleratorES / IOAcceleratorFamily2（GPU 发现入口，见 §4）
- IOMobileFramebuffer（显示）
- IOSurface / IOSurfaceRoot（所有跨进程图像缓冲）
- IOHIDFamily + HID event service（触摸/按键；backboardd 靠它收事件）
- AppleKeyStore（keybag/钥匙串，见 §5）
- IOMedia / IOBlockStorageDriver（根卷）
- 网络栈（IONetworkStack / en0）、音频（CoreAudio driver）、传感器

**判定：用户态「可移植」（二进制一个字节都不用改），但它是被动的——内核缺一个服务，它就卡在那里。** 这一层的工作量全记在内核账上。

---

## 4. 图形层：AGX 是死路，Metal 可以用「假设备」绕，Mali 上只有私有实现

### 4.1 iOS 的 UI 栈怎么落到 GPU

UIKit / CoreAnimation(QuartzCore) → 首选 **Metal**，回退 **OpenGL ES** → 系统 GPU 驱动（闭源 kext + 用户态 bundle）→ AGX。

iOS 16.5 里可验证的实物（HakiOS 对同一份 20F66 / iPhone10,3 系统的分析，[docs/ru/metal.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/ru/metal.md)）：

- 系统里有 **10 个 .metallib**，其中 5 个在 AGXMetalA11.bundle 里（那是 AGX 驱动自己的内部库，不是 AIR）；AppleMetalGLRenderer.bundle/default.metallib 是 1,111,748 字节、**274 个 shader 模块**；QuartzCore 还有 default.pipelinelib 指向一个系统里并不存在的 default.metallib。
- Metal 的**设备发现链**（逆向出来的 5 步）：
  1. MTLRegisterDevices → IOServiceMatching("IOAcceleratorES")
  2. 读服务属性 MetalPluginName
  3. 打开 /System/Library/Extensions/<name>.bundle
  4. 读 MetalPluginClassName，类必须是私有基类 _MTLDevice 的子类
  5. [[cls alloc] initWithAcceleratorPort:service] → 这就是「设备」

**含义**：Metal 不是内核里长出来的，而是「内核给一个 IOKit 服务 + 一个用户态 bundle」。所以**换 GPU 不需要改 Metal 框架，只需要自己实现一个 _MTLDevice 家族**——HakiOS 统计 Apple 自己的实现是 **53 个类、约 1200 个方法**。

### 4.2 Mali-G57 上有什么、没什么

- **有 GLES**：Mesa 的 panfrost 在 **Mali-G52 / G57 / G610 上是 GLES 合规**的（[Mesa panfrost](https://docs.mesa3d.org/drivers/panfrost.html)）。G57 是 Valhall，panfrost 的 Valhall 后端足以跑 CoreAnimation。
- **有 Vulkan**：panvk（Bifrost 及之后，含 Valhall），成熟度低于 GL。
- **没有 Metal**：Mesa 不提供 Metal，上游没有任何 Metal on Mali。方向相反的东西倒是有：**MoltenVK 是把 Metal API 实现在 Vulkan 上**（且已被 Khronos 标记 deprecated，[MoltenVK](https://github.com/KhronosGroup/MoltenVK)）。它证明「Metal API 可以软件实现」，但它不能直接在 Mali 上跑（它要的是 Vulkan + Apple 平台语义）。
- **有人做过 Metal on Mali 吗？有，但不是通用方案**：HakiOS 的 MT6768 端口自述「Mali-G52 brought up from the kernel (hakios.mali.c, hakios.mali.cpp), Mesa's panfrost, **a Metal driver: CoreAnimation draws through Metal**, iOS 16's own wallpaper」（[hakios-mt6768](https://github.com/oosexgang/hakios-mt6768)）。这是**项目自述、未独立验证**，但方向明确：假 _MTLDevice + AIR→NIR→Valhall 后端 + 内核命令提交。
- 另一条已验证的路：**UniXNU 的 AdrenoMetal + metal2vulkan + Turnip**，在 Adreno 740 上把 Metal 翻成 Vulkan（[comparison.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/comparison.md)）。

### 4.3 真正的难点不是驱动，是着色器编译器

Metal 的 shader 以 **AIR**（Apple 的 LLVM 位码）存在 .metallib 里。好消息（已量化）：

- .metallib 容器 = MTLB + 函数表 + 位码段；每个函数是标准 LLVM bitcode 包装（0x0B17C0DE 外壳 + BC\xC0\xDE），**456 个模块全部能被原版 llvm-dis 读出**。
- AIR 与普通 LLVM IR 只差三件事：triple（air64-apple-ios16.5.0）、三个地址空间、九种 !air.* 元数据；**283/456（62%）模块完全不调用任何 air.* intrinsic**。
- HakiOS 已把 **321/456 模块翻译到 Mesa NIR 并编到 Adreno 的 ir3**，54 个在真机 GPU 上跑过（[air-report.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/air-report.md)、[metal-plan.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/metal-plan.md)）。
- 换到 Mali：**AIR→NIR 前端可复用，NIR→ir3 换成 NIR→Valhall（panfrost 的编译器）**。这是「重写后端」，不是「重写全部」。

### 4.4 结论

- **AGX 驱动：0% 可复用，硬阻塞。** 它绑死 A11 的 GPU 寄存器、固件、命令流；Mali 是另一套 ISA。
- **Metal 这层：需重写，但可绕。** 目标不是「完整 Metal」，而是「系统自己的 Metal 客户端」（窗口服务器合成器、CoreImage、相机取景）能画。**游戏别想**——HakiOS 自己的结论就是 games — a firm no。
- **现实默认路径：CoreAnimation 走 panfrost 的 GLES**（HakiOS 在 Adreno 上默认也是 GLES，metal=1 才切 Metal）。在天玑 810 上，**GLES 路线是唯一能在数月内出画面的路线**。

---

## 5. SEP：没有它，iOS 只剩一个「永不锁屏的演示机」

### 5.1 SEP 在 iOS 16 里承担什么

- **keybag / class keys**：文件与钥匙串的 Data Protection 类密钥都收在 keybag 里，只有所有 class key 都能解封，设备才算「已解锁」（[Apple: Keybags for Data Protection](https://support.apple.com/guide/security/keybags-for-data-protection-sec6483d5760/web)）。
- **Keychain**：securityd 通过 AppleKeyStore（内核侧）向 SEP 要 wrap/unwrap。
- **attestation**：DeviceCheck / App Attest / FairPlay，App Store 与 Apple ID 登录链路。
- **启动期握手**：iBoot 阶段就要校验并跳转 sep-firmware（SEPOS），内核里 AppleSEPManager 维持 mailbox 通信。SEP 固件本身是 IPSW 里的独立 im4p（[HEXACON 2025: Inside SEP](https://2025.hexacon.fr/slides/inside_secure_enclave_processor_in_2025.pdf)）。
- A11 的 SEP **没有公开的 SEPROM 利用**：Blackbird 覆盖 A8/A9/A10/T2（[Blackbird](https://theapplewiki.com/wiki/Blackbird_Exploit)），连「在真机上 dump SEP 内部」都做不到。

### 5.2 没有 SEP 会发生什么

| 子系统 | 结果 |
|---|---|
| 锁屏密码 / Data Protection | 无法建立：没有 class key，用户数据卷解不开 |
| Keychain | AppleKeyStore 请求失败；securityd 反复重试/降级 |
| App Store / Apple ID / iMessage / FairPlay | 直接失败（HakiOS：App Store content and Apple ID sign-in — no Secure Enclave; FairPlay daemon exits） |
| 部分守护进程 | 依赖 SEP 的服务起不来或反复重启；严重时内核 panic（AppleSEPManager 拿不到 mailbox 响应） |

### 5.3 实践中的「绕法」（这才是可执行的答案）

HakiOS 的 MiniAppleKeyStore.cpp 把话说得非常清楚：

> a stand-in for Apple's AppleKeyStore (the kernel side of the keybag, **which on real hardware talks to the Secure Enclave**) ... It describes one fixed situation: **a device that has no passcode — never locked, unlocked since boot. No keys exist here.** ... the wrapping is a reversible transformation and **protects nothing** (and the keychain lives in /private/var, in memory, and is gone at the next start).

即：**假装设备无密码、永不锁定**；wrap/unwrap 用可逆变换糊弄；keychain 放内存、重启即失；创建/加载真 bag 的请求一律拒绝。

**判定：真安全 = 硬阻塞；让系统跑起来 = 需重写（假 keybag），代价是安全模型归零、Apple 服务全废。**

---

## 6. 显示与触摸：中等工作量，坑在时序和固件

### 6.1 显示

- A11 真实架构：AppleCLCD（显示控制器）+ display-pmu,acorn（显示电源域）+ DART（IOMMU）+ IOMobileFramebuffer（用户态 ABI）。**没有 DCP**。
- 到 MT6833：写一个 MiniIOMobileFramebuffer，把 IOMFB 的 ABI（swap、VSYNC、surface 格式、缩放、亮度）映射到 MTK 的 disp/DSI 驱动。分辨率也要适配：iPhone X 是 1125×2436@3x，天玑 810 机器多是 1080×2400 或 720×1640 —— iOS 的 display-scale / display-rotation 来自设备树，需按目标屏重写。
- 难度：**中**。HakiOS 的 MiniIOMobileFramebuffer.cpp 就是现成范本（还带 metal=1 时才挂 MetalPluginName 的开关设计）。

### 6.2 触摸

- iPhone X：Apple 自家 multitouch 控制器挂在 **SPI0** 上（设备树里有 multi-touch 节点和 function-spi0_* 一类函数），驱动是 AppleMultitouchSPI / AppleM68Touch，事件经 IOHIDFamily 到 backboardd。
- 换 Goodix（GT9916 之类）要写：
  1. SPI/I2C 传输 + 上电/复位/中断时序；
  2. 固件下载（很多 Goodix 需要 host 侧送 firmware，HakiOS 的 loader 就负责这件事）；
  3. 报告解析（多点、压力、手势、唤醒）；
  4. 把事件注入 iOS 的 HID 栈——HakiOS 的做法是 /dev/hakios-touch + 往 backboardd 注入虚拟 HID 服务。
- 难度：**2–6 周/器件**（有现成同类实现时）；从零逆向一个 controller 是月级。

---

## 7. 类比：Darling 走到哪、为什么救不了 iOS，真正该类比的是谁

### 7.1 Darling 做到什么程度

- 原理：Mach-O 不能直接被 Linux 的 binfmt 加载，所以 Darling 起一个 ELF loader，在自己的地址空间里映射 Mach-O 和**自己的 dyld**；内核语义靠 darlingserver 做 RPC（Mach port、Mach exception、kqueue、commpage 都要自己实现）。XNU 有三张 syscall 表（BSD / Mach / machine-dependent），Darling 全都要接（[Darling: System call emulation](https://docs.darlinghq.org/internals/basics/system-call-emulation.html)）。
- 水平：能跑 echo、uname（输出 Darwin）、sw_vers（报 macOS 10.14）这类 CLI；文档明确分了 Known working / partially working / **non-functional** 三档（[What to try](https://docs.darlinghq.org/what-to-try.html)）。
- 它模拟的是 **macOS 10.14 世代的用户态 ABI**，不是 iOS 16。

### 7.2 能不能用它加载 SpringBoard？不能

四个独立原因，每个都够：

1. **没有 IOKit 驱动栈**：Darling 模拟 Mach port，但没有 IOPlatformExpert / IOHIDFamily / IOAcceleratorES 这套真实驱动模型；SpringBoard 起来第一件事就是找这些服务。
2. **没有 launchd/XPC 的真实语义**：iOS 16 的 runningboardd / backboardd / SpringBoard 靠 Mach bootstrap 与 XPC 互联，Darling 只有近似实现。
3. **没有 GPU 栈**：Darling 不带 Metal，也不带 AGX/Mali 驱动；CoreAnimation 没有落点。
4. **没有 SSV / cryptex / SEP**：iOS 16.5 的系统盘是签名只读卷 + cryptex，Darling 连这套布局都不认。

**结论：Darling 证明「用户态 ABI 可以在非原生内核上跑」，但它止步于 CLI。iOS 全栈要的是「真 XNU」路线，不是「翻译层」路线。**

### 7.3 Wine vs Darling

- Wine 实现的是 **Win32 API 层**（PE 加载器 + 一大批 DLL），它**不需要**模拟 NT 内核对象模型——只要把 Win32 调用翻译到 POSIX。
- Darling 实现的是 **Darwin 的内核个性**：Mach port 是内核对象、task/thread 语义、kqueue、commpage、posix_spawn 细节，所以它必须写一个「半个内核」（darlingserver）。
- 一句话：Wine 是「API 翻译」，Darling 是「内核语义模拟」。**后者难得多，也解释了为什么 Darling 十年了还在 CLI 阶段。**

### 7.4 真正该拿来类比的三个项目

| 项目 | 做了什么 | 对你的意义 |
|---|---|---|
| **HakiOS**（OOSEX GANG） | XNU 8796.121.2（= iOS 16.5 内核）+ 自写 loader/驱动，跑 iOS 16.5 用户态到 SpringBoard；Adreno 上 Metal 合成器 100–104 fps；**有 MT6768（Mali-G52）端口** | **这就是你要做的事的已完成版本**（换 SoC 而已）。先读它的 docs/，别从零开始 |
| **ios-sweet / Bergamota** | 单机型 bring-up（SM7150 / SDM845），CPU 光栅 20–30 fps；Bergamota 还做了 arm64e/PAC 工具 | 小规模、可读的实现，适合当「最小可行」参照 |
| **UniXNU** | 通用 UEFI 层 + 组件目录（234 个设备条目）+ AdrenoMetal/metal2vulkan | 证明「Metal on 非 Apple GPU」可工程化 |

（三家对比见 [HakiOS comparison.md](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/comparison.md)。）

另外两个「能跑但不是移植」的参照：**Corellium** 用 Type-1 hypervisor 在 ARM 服务器上虚拟 iOS（还是模拟 Apple SoC，[Corellium](https://www.corellium.com/custom-device-modeling-corellium)）；**iOS-on-QEMU**（Aleph Research）用 QEMU 模拟 Apple SoC 起 iOS 到 bash（[alephsecurity](https://alephsecurity.com/2019/06/17/xnu-qemu-arm64-1/)）。两者都说明：**能跑的前提是「假装自己是 Apple SoC」，而不是「把 iOS 塞进别的 SoC」。**

---

## 8. 结论表与最小可行里程碑

### 8.1 逐层判定

| 层 | 判定 | 关键依据 | 备注 |
|---|---|---|---|
| 1 引导（iBoot/IMG4） | **硬阻塞**（不可移植）→ **需重写（绕过）** | iBoot 加密 + 固定 Apple MMIO + 信任根是 SecureROM；MTK 是 BootROM→preloader→LK | 正确做法：自写 loader 链式加载 XNU |
| 2 内核（XNU） | **需重写（platform 层）**，但**可行** | AppleARMPlatform 闭源，缺了直接 panic；GICv3/PSCI/APFS/minicrypto/AMFI 全套要自己来 | 有 HakiOS 范本；人年级 |
| 3 用户态（rootfs/launchd/SpringBoard） | **可移植**（二进制不改） | HakiOS 原样跑 iOS 16.5 用户态 | 被动层，取决于内核喂服务 |
| 4 图形（AGX/Metal） | AGX = **硬阻塞**；Metal = **需重写**；GLES = **可移植（panfrost）** | AGX 绑死 A11；Metal 靠 IOAcceleratorES + _MTLDevice 可替换；G57 GLES 合规 | 默认走 GLES，Metal 只做系统合成器 |
| 5 SEP | **硬阻塞**（真安全）→ **需重写（假 keybag）** | keybag/class key/attestation 全在 SEP；A11 SEP 无公开利用 | 假 keybag = 安全归零 + Apple 服务全废 |
| 6 显示/触摸 | **需重写（中等）** | A11 是 CLCD + display-pmu + DART，无 DCP；触摸是 SPI + Apple 私有 controller | 2–6 周/器件（有范本时） |
| 7 Darling 路线 | **不可行**（结论性否定） | 无 IOKit / GPU / launchd 语义 / SSV | 只能到 CLI |

### 8.2 最小可行里程碑

**不要把「iBoot 在 MTK 上跑」当里程碑——那是不可能事件。** 建议这样切：

| 里程碑 | 内容 | 验收标准 | 预估 |
|---|---|---|---|
| **M0 引导** | 解锁 bootloader，写/移植 loader（LK 之后 chainload，或 fastboot boot 等价物），串口日志 | loader 能打印版本、读分区、跳转内核 | 2–6 周 |
| **M1 内核起** | XNU + GenericARMPE + GICv3 + timer + PSCI，4×A76，ramfs | 内核 banner + kern.hakios.version，QEMU 与真机都能起 | 2–4 人月 |
| **M2 用户态起** | 只读 APFS 根（SSV 镜像）+ launchd + backboardd + framebuffer | 屏幕出画面（哪怕只是黑底 + 状态栏） | 2–4 人月 |
| **M3 首屏** | panfrost GLES 或 CPU 光栅 + Goodix 触摸注入 + 按键 | SpringBoard 首屏、能滑动、能开设置 | 3–6 人月 |
| **M4 Metal 合成器** | 假 _MTLDevice + AIR→NIR→Valhall + 内核命令提交 | 窗口服务器走 Metal，帧率可测（对标 HakiOS 的 100 fps） | 6–12 人月 |
| **M5（明确不做）** | 游戏、相机、蜂窝、音频、Apple 服务 | — | 不建议投入 |

**最低可宣称「成功」的点：M3。** 到 M3 为止，「iOS 16.5 的用户态跑在非 Apple 内核 + 非 Apple SoC 上」这句话就成立（HakiOS 在 MT6768 上已做到，甚至到了 M4）。M4 之后是「体验工程」，不是可行性问题。

### 8.3 三条最容易被低估的坑

1. **触摸固件**：Goodix 类控制器常需要 host 送 firmware，loader 阶段就要做，否则内核起来后屏幕是死的。
2. **decmpfs**：iOS 系统盘大量文件是压缩的，APFS 读驱动不带 libzbitmap/libdeflate 会读出一堆空文件。
3. **arm64 vs arm64e**：一开始就选 arm64 切片，别在 PAC 上耗时间；等 M4 再考虑 arm64e。

---

## 附：核心参考链接

- Apple 启动链与 SSV：[Boot process](https://support.apple.com/guide/security/boot-process-for-ipad-and-iphone-devices-secb3000f149/web)、[Signed system volume](https://support.apple.com/guide/security/signed-system-volume-security-secd698747c9/web)、[Keybags](https://support.apple.com/guide/security/keybags-for-data-protection-sec6483d5760/web)
- IMG4 工具与格式：[img4tool](https://github.com/tihmstar/img4tool)、[ipsw #1324（iPhone10b 的 LZSS）](https://github.com/blacktop/ipsw/issues/1324)、[KBAG/GID 拆解](https://stack.int.mov/a-reverse-engineers-anatomy-of-the-macos-boot-chain-security-architecture)
- A11 硬件地图：[linux t8015.dtsi](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/apple/t8015.dtsi)、[D22AP 设备树转储](https://gist.github.com/freedomtan/1bbada7f19b7eb058e380e9d219ab268)
- checkm8 / SEP：[CERT VU#941987](https://www.kb.cert.org/vuls/id/941987/)、[Blackbird](https://theapplewiki.com/wiki/Blackbird_Exploit)、[HEXACON 2025 SEP](https://2025.hexacon.fr/slides/inside_secure_enclave_processor_in_2025.pdf)
- 图形：[Mesa panfrost](https://docs.mesa3d.org/drivers/panfrost.html)、[MoltenVK](https://github.com/KhronosGroup/MoltenVK)、[Asahi AGX](https://asahilinux.org/docs/hw/soc/agx)
- 先例项目：[HakiOS 主仓](https://github.com/oosexgang/hackios-xnu-kernel)、[架构](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/concepts/architecture.md)、[Metal 计划](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/metal-plan.md)、[AIR 报告](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/air-report.md)、[MT6768 端口](https://github.com/oosexgang/hakios-mt6768)、[对比表](https://github.com/oosexgang/hackios-xnu-kernel/blob/main/docs/comparison.md)
- 类比：[Darling syscall 模拟](https://docs.darlinghq.org/internals/basics/system-call-emulation.html)、[Darling what-to-try](https://docs.darlinghq.org/what-to-try.html)、[Corellium](https://www.corellium.com/custom-device-modeling-corellium)、[iOS on QEMU](https://alephsecurity.com/2019/06/17/xnu-qemu-arm64-1/)
- MTK 引导链：[U-Boot README.mediatek](https://qemu.googlesource.com/u-boot/+/refs/heads/master/doc/README.mediatek)
