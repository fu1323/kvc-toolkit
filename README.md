<p align="center">
  <a href="README.md">简体中文</a> | <a href="README_EN.md">English</a>
</p>

<div align="center">

# KVC Toolkit：快乐的小手 KVC7 视频解码 · 转码分析 · Android 逆向 · 流媒体逆向 · Unidbg

使用 unidbg 调用快手内部集成了解码器的 `libffmpeg.so`，把 KVC7 视频解成 YUV，再转为普通 H.264 MP4。

</div>

> [!NOTE]
> **2026-11-04 新增：带逐帧 PTS 的流式转码已实现。**
> `KvcProbe_ffmpeg` 现在自动启动 Python/PyAV 桥接，把逐帧 PTS 和 YUV 封装为 NUT 后送入本机 FFmpeg，**不落盘完整 YUV**。
> 运行 `./run_pts.sh 输入.mp4 输出.mp4`；环境准备、IDEA 参数和时间戳处理见 [第 7 章](#route-c)，原理见 [第 11 章](#pts-deep-dive)。
> 旧的 `transcode_unidbg.py` / `KvcProbe.java` 路线（[第 5 章](#route-a)）保留原有行为。

> [!WARNING]
> 此项目仅为自己学习用途而设，**请勿用于批量爬取**。
> 说实话，本工具目前还不具备大批量解码转码的能力；仅学习研究用途，可以完整解开 KVC 为 YUV。
> 文档更新：2026-11-03（第一版）、2026-11-04（PTS 流式版）。

本工具已对提供的 KVC7 样本完成端到端验证：支持在 Apple Silicon Mac 上通过 **Java / unidbg 执行原 Android 解码库**，将视频转为普通 H.264 MP4；同时保留了先前的 USB 安卓解码方案。

---

## 导航

### 我想……该看哪里

| 我想…… | 去看 |
|---|---|
| 弄清这个工具到底做了什么、哪些事容易误解 | [第 1 章](#intro) |
| 在三条路线里选一条 | [第 2 章](#routes) |
| 不连手机，直接把 KVC7 转成 MP4 | [第 5 章 路线 A](#route-a) |
| 不落盘完整 YUV，并且保留原始逐帧时间戳 | [第 7 章 路线 C](#route-c) |
| 只解码出 YUV，检查首帧 / 原始像素 | [第 8 章](#decode-only) |
| 手上有已 root 提取过库的安卓手机，走 USB | [第 6 章 路线 B](#route-b) |
| 搞懂 unidbg 里到底怎么调用 `.so` | [第 9 章](#decode-internals) |
| 搞懂 1.5 GB YUV、管道、背压、RPC | [第 10 章](#data-transport) |
| 搞懂 Java → Python → NUT → FFmpeg 的 PTS 方案 | [第 11 章](#pts-deep-dive) |
| 查结构体偏移、符号、库哈希、有没有 KVC 编码器 | [第 12 章](#abi-notes) |
| 看测试结果、复核命令 | [第 13 章](#verification) |
| 改代码、重新编译、换库、接入自己的 FFmpeg | [第 14 章](#build)、[第 15 章](#ffmpeg-integration) |
| 遇到报错 | [第 16 章](#faq) |
| 了解边界与许可 | [第 17 章](#limitations)、[第 18 章](#license) |

### 完整目录

**Part I　概览**

1. [项目简介](#intro)
2. [三条运行路线总览](#routes)
3. [仓库结构与文件作用](#layout)
4. [已验证环境与输入限制](#env)

**Part II　使用指南**

5. [路线 A：本地 unidbg 转码](#route-a)
6. [路线 B：USB 安卓解码（备用）](#route-b)
7. [路线 C：带逐帧 PTS 的流式转码](#route-c)
8. [只解码：保留原始画面](#decode-only)

**Part III　原理与设计**

9. [KVC 解码链路：unidbg 里到底发生了什么](#decode-internals)
10. [解码之后的数据去哪：内存、管道、共享内存与 RPC](#data-transport)
11. [流式转码详解：Java、Python、NUT 与逐帧 PTS](#pts-deep-dive)

**Part IV　逆向笔记与验证**

12. [逆向笔记：ABI、符号与原始库](#abi-notes)
13. [验证与测试结果](#verification)

**Part V　开发、扩展与支持**

14. [编译与修改](#build)
15. [接入自己的 FFmpeg](#ffmpeg-integration)
16. [常见问题](#faq)
17. [已知限制与后续改进](#limitations)
18. [来源、许可与致谢](#license)

---

# Part I　概览

<a id="intro"></a>

## 1. 项目简介

### 1.1 这个工具到底做了什么

原视频虽然使用 MP4 容器，但视频轨的 FourCC 是 `kvc7`，配置块是 `kvLC`，普通 FFmpeg 无法直接识别对应的私有解码器。

我们从用户自己的安卓手机提取了 ARM64 版本的 `libffmpeg.so`。这份库内含能解该样本的 KVC 实现，并暴露了一套可调用的 FFmpeg API。**工具复用这个实现，而不是重新实现编码标准。**

一句话概括整条链路：

```text
KVC7 的 MP4  →  unidbg 模拟 Android 环境，执行原 libffmpeg.so 解码  →  YUV420P + PTS
             →  libx264 编码为 H.264（音轨直接复制）  →  普通 MP4
```

### 1.2 最容易混淆的四件事

| 问题 | 答案 |
|---|---|
| 是否把 KVC 算法反编译成了 C？ | **没有。** 真正的解码算法仍是原 `.so` 中的 ARM64 机器码 |
| `phone_decode.c` 是什么？ | 在安卓手机运行的调用外壳，不是 KVC 算法源码 |
| unidbg 不是 Java 吗？ | 是。`KvcProbe.java` 用 unidbg 模拟 Android 环境，加载并执行原 `.so` |
| 是否已经给上游 FFmpeg 打了补丁？ | 没有。当前是一个独立解码与转码工具 |

同样是 ARM64 指令集，也不代表 Android ELF 动态库能由 macOS 的原生程序直接 `dlopen`：二者的文件格式、动态链接器、系统调用及运行库环境不同。本工具使用 unidbg 解决运行环境问题。

### 1.3 用途与能力边界

- 仅为学习研究用途，不用于批量爬取；目前也不具备大批量解码转码的能力。
- 只验证了一个 KVC7 样本和一组原始库，**不应扩展成“支持全部快手视频”的结论**。
- 完整边界清单见 [第 17 章](#limitations)；`lib/` 中二进制的来源与许可说明见 [第 18 章](#license)。

---

<a id="routes"></a>

## 2. 三条运行路线总览

三条路线**都复用同一份原始 ARM64 解码库**。区别在于：解码在哪里运行、原始画面怎样交给编码器、时间戳怎样保留。

### 路线 A：本地 unidbg（原推荐路线，落盘 YUV）

> [!WARNING]
> 作者备注：`transcode_unidbg.py` 自己需要修改下，**有 bug**；核心在 Java 项目，**Java unidbg 经过验证可以跑通**。

```text
transcode_unidbg.py                     Python：流程控制
    │
    ├─ ffprobe                         读取原 MP4 的轨道信息
    │
    ├─ 启动 Java 进程
    │     └─ KvcProbe.class            Java：调用 unidbg
    │          └─ unidbg / Dynarmic     模拟 ARM64 Android 环境
    │               └─ libffmpeg.so    原始 KVC 解码算法
    │                    ├─ frames.yuv
    │                    └─ pts.txt
    │
    ├─ PyAV / libx264                  编码 H.264 视频
    └─ ffmpeg -c copy                  合并新视频与原始音轨
          └─ output.mp4
```

不连接手机，不调用 adb，不启动快手，也不执行 `phone_decode`。Java 进程中的 native 后端仍是本地机器代码组件，因此“Java 程序”不等于完全与主机架构无关。

### 路线 B：USB 安卓解码（备用）

```text
transcode.py                           Mac 上的 Python
    ├─ adb 推送库、视频副本和 phone_decode
    ├─ 安卓手机执行 phone_decode       从 phone_decode.c 编译
    │    └─ Android 动态链接器加载 libffmpeg.so
    │         └─ 输出 PTS + YUV
    ├─ adb 将画面数据传回 Mac
    ├─ PyAV / libx264 编码
    └─ ffmpeg 合并原音轨
```

### 路线 C：带逐帧 PTS 的流式转码（2026-11-04 新增）

```text
Java / unidbg：Android libffmpeg.so 解码 KVC
    ↓ 当前帧 PTS + 紧凑排列的 YUV420P，二进制管道（KVCP0001 协议）
pts_bridge.py：PyAV 将原始视频包封装成 NUT
    ↓ NUT 管道，含尺寸、像素格式、时间基和逐帧时间戳
本机 ffmpeg：libx264 CRF18 / preset fast 编码，复制原文件第一条音轨
    ↓
H.264 + AAC MP4
```

不创建完整 YUV 或 NUT 临时文件，也不先把全部帧加载进内存。

### 对比表

| 项目 | 路线 A：unidbg（落盘） | 路线 B：USB | 路线 C：unidbg + PTS 流式 |
|---|---|---|---|
| 入口 | `transcode_unidbg.py` | `transcode.py` | `./run_pts.sh` / `xin.chunming.KvcProbe_ffmpeg` |
| 解码控制程序 | Java（`KvcProbe`） | C 编译的 ARM64 可执行文件 | Java（`KvcProbe_ffmpeg`） |
| 需要 Java | 需要 | 不需要 | 需要（Java 17、Maven） |
| 需要手机 / adb | 不需要 | 需要 | 不需要 |
| 解码运行位置 | Mac 的模拟环境 | 安卓手机 | Mac 的模拟环境 |
| 原始画面存储 | Mac 临时文件（整段 YUV） | 经 USB 流式传输，不保存整段手机 YUV | 不落盘，进程管道流式传输 |
| 逐帧 PTS 处理 | 读取 `pts.txt`，重复值后移 1 µs | 8 字节 PTS + YUV 的自定义记录 | PTS 随帧传入，封装 NUT，按时间基保留 |
| 最终编码 | PyAV / libx264 | PyAV / libx264 | 本机 `ffmpeg` / libx264 |
| 验证状态 | 完整通过 | 完整通过 | 样片完整通过（2026-11-04） |

> [!TIP]
> 简单选择：**没有手机** → 路线 A 或 C；**想省磁盘、想保留原始时间线** → 路线 C；**只想看原始像素** → [第 8 章](#decode-only)；**手机在手且习惯 adb** → 路线 B。

---

<a id="layout"></a>

## 3. 仓库结构与文件作用

### 3.1 当前仓库根目录

| 路径 | 作用 |
|---|---|
| `lib/` | 原始定制库：`libffmpeg.so`（含 KVC 解码实现）与配套的 `libc++_shared.so` |
| `src/main/java/xin/chunming/` | Java 源码；PTS 流式入口 `KvcProbe_ffmpeg.java` 在这里 |
| `pom.xml`、`kvc-toolkit.iml`、`.idea/` | Maven 工程与 IDEA 配置 |
| `transcode_unidbg.py` | 路线 A 的 Python 转码入口（见路线 A 的 bug 备注） |
| `pts_bridge.py` | 路线 C：读 KVCP0001 协议、校验 / 微调 PTS、封装 NUT、启动并等待本机 FFmpeg |
| `run_pts.sh` | 路线 C：使用项目 `.venv/bin/python`，自动编译并运行 Java |
| `requirements-pts.txt` | 路线 C 的 Python 依赖，当前固定 `av==15.1.0` |
| `test_pts_bridge.py` | 不依赖 KVC 库的桥接集成测试（见 [13.5](#verification)） |
| `symbols.txt` | 库哈希、依赖和 KVC 导出符号 |
| `encoders.txt` | 实际枚举到的已注册编码器 |
| `validation.json` | 输出媒体信息的验证记录 |
| `USB/` | 原 README 未对该目录做说明（疑与路线 B 相关）——**待补充** |

> [!NOTE]
> 路线 C 运行过程中还会用到（但不一定提交在仓库里）：`work/pts-validation.csv`（逐帧时间戳记录）、`work/pts-validation.log`（运行日志）、`work/pts-validation.mp4`（验证视频）。

### 3.2 第一版交付包的目录结构（历史记录）

下面是第一版（2026-11-03）交付包的结构，描述的是文件**作用**；其中 `unidbg/`、`phone_decode*`、`transcode.py` 等的实际位置已与当前仓库根目录不同，**待按现状核对**。

```text
kvc-toolkit/
├─ README.md
├─ transcode_unidbg.py          推荐：无需手机的转码入口
├─ transcode.py                 备用：USB 转码入口
├─ phone_decode.c               Android C 调用外壳源码
├─ phone_decode                 已编译的 Android ARM64 程序
├─ lib/
│  ├─ libffmpeg.so              原始定制库，含 KVC 解码实现
│  └─ libc++_shared.so          与它配套的 Android C++ 运行库
├─ symbols.txt                  库哈希、依赖和 KVC 导出符号
├─ encoders.txt                 实际枚举的已注册编码器
├─ validation.json              USB 路线输出的媒体信息
└─ unidbg/
   ├─ KvcProbe.java             本地解码程序源码
   ├─ classes/KvcProbe.class    已编译 Java 类
   ├─ deps/*.jar                unidbg、后端和其他 Java 运行依赖
   ├─ validation.json           unidbg 路线输出的媒体信息
   ├─ verification.txt          耗时和逐帧比较结论
   └─ LICENSE-unidbg
```

### 3.3 容易误用的文件

- `phone_decode` 是安卓程序，**不能在 Mac 终端直接运行**。
- `libffmpeg.so` 也**不是**可以替换 Homebrew FFmpeg 的 macOS 库。
- 运行预编译的 unidbg 版本（路线 A）**不需要** Maven、Zig、Android NDK，也不需要用户再下载 APK；需要 Java、Python/PyAV，以及电脑上的 `ffmpeg` / `ffprobe`。
- 路线 C 需要 Java 17、Maven、本机 ffmpeg/ffprobe、Python 3.9+，以及当前项目 `lib/` 中匹配的 ARM64 库。

---

<a id="env"></a>

## 4. 已验证环境与输入限制

### 4.1 本次实际环境

| 组件 | 验证版本 / 配置 |
|---|---|
| 电脑 | Apple Silicon Mac，ARM64 |
| Java | Temurin 17.0.20.1，ARM64 |
| Python | 3.9.6 |
| PyAV | 15.1.0 |
| 命令行 FFmpeg | 9.0.1 |
| unidbg | 路线 A：`0.9.10-SNAPSHOT`，指定源码 commit 见 [第 18 章](#license)；路线 C 验证记录为 0.9.9 |
| 实际执行后端 | `DynarmicBackend64` |
| Android 兼容库解析 | `AndroidResolver(23)` |

这些是**已验证版本，不是已证明的最低版本**。没有验证 Intel Mac、Windows、Linux 或其他 Java / PyAV 组合的端到端兼容性。虽然依赖中可能包含其他平台组件，不代表本工具已在这些平台测试。

### 4.2 输入要求

Python 入口（路线 A）会检查：

- 首个视频轨 `codec_tag_string == kvc7`。
- 分辨率为 **1280×720**。
- 时间基为 **1/1000000**。

Java / C 端还依赖：

- 视频实际位于容器的 **第 0 条轨道**。Python 的“首视频轨”检查不等于这个条件已被自动验证。
- 解码输出为 **8-bit YUV420P**，附带库中像素格式值为 0。
- 视频使用该定制库可以解码的格式与配置。

> [!IMPORTANT]
> 当前的尺寸、格式和时间基限制是**原型实现的边界**，不是对 KVC 编码能力的推断。改掉一个尺寸检查并不足以安全支持 1080p、10-bit 或其他时间基。

---

# Part II　使用指南

<a id="route-a"></a>

## 5. 路线 A：本地 unidbg 转码

以下命令假设已经进入解压后的 `kvc-toolkit` 目录。

### 5.1 检查已有工具

```bash
uname -m
java -version
python3 --version
ffmpeg -version
ffprobe -version
```

本次验证的机器 `uname -m` 为 `arm64`。建议同时使用 ARM64 Java，避免无意中混用 Rosetta 的 x86_64 运行环境。

macOS 上可列出已安装 JDK：

```bash
/usr/libexec/java_home -V
```

如果系统缺少 Java 或 FFmpeg，需先安装。以上步骤不会代替系统软件安装。

### 5.2 创建独立 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "av==15.1.0"
```

固定 PyAV 15.1.0 是为了接近本次测试环境，不是保证其他版本不能运行。包管理器能否提供适合当前 Python 和系统的安装包取决于其支持范围。

检查导入与 H.264 编码器：

```bash
python -c 'import av; print(av.__version__); print(av.codec.Codec("libx264", "w"))'
```

> [!WARNING]
> **PyAV 使用的 FFmpeg 库与命令行 `ffmpeg` 可能不是同一套。** 视频编码由 Python 进程中的 PyAV / libx264 完成；最后合并音轨才调用系统 `ffmpeg`。因此命令行能编码 H.264，不一定证明某个自定义 PyAV 构建也带 libx264。

### 5.3 执行转码

```bash
python transcode_unidbg.py \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

指定 Java：

```bash
python transcode_unidbg.py \
  --java "/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home/bin/java" \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

上面的 Java 路径是本次机器的示例，其他机器请替换成实际路径。

参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `input` | 是 | 原始 KVC7 MP4 路径 |
| `output` | 是 | 新 MP4 路径；父目录应已存在 |
| `--java` | 否 | Java 可执行文件，默认从 PATH 查找 `java` |

输出文件已经存在时拒绝覆盖。**没有** `--force`、`--crf`、`--threads`、`--backend` 或通用尺寸参数；不要把这些当作现成选项。

### 5.4 预期日志

```text
LOADED libffmpeg.so backend=class ...DynarmicBackend64
open=0
codec=30005
parameters=0
threads option=0
kvc option=0
decoder open=0
frames=100
...
frames=1000
SUCCESS frames=1084 seconds=...
Completed 1084 frames, 1 timestamp adjustments, ...s total: ...
```

- `codec=30005` 是**十六进制**输出，即 `0x30005`，不要当成十进制 30005。
- 最后的 `Completed` 表示 Java 解码、帧数 / 文件大小核验、H.264 编码与音轨合并均已完成。**仅看到 `decoder open=0` 不代表视频已完整解码。**

### 5.5 临时空间、资源与清理

脚本通过 `TemporaryDirectory` 创建临时目录，其中包括：

```text
frames.yuv       全部解码画面
pts.txt          每帧显示时间戳，一行一个整数
video.mp4        编码完成但尚未合并音轨的视频
root/            unidbg 虚拟文件系统工作目录
```

本样本 YUV 大小：

```text
每帧 = 1280 × 720 × 3 / 2 = 1,382,400 字节
总量 = 1,382,400 × 1084 = 1,498,521,600 字节
     ≈ 1.50 GB（十进制）／ 1.40 GiB
```

还要额外容纳编码后视频和模拟环境文件，**建议至少留出 2 GB 可用临时空间**。该估算只针对当前 36 秒样本。

- Java 堆上限设置为 `-Xmx2g`，但模拟器还有堆外 / native 内存，所以这不是整个进程总内存上限。
- Java 解码子进程超时为 **300 秒**；这不是整个转码流程的统一超时。
- 正常结束及普通 Python 异常退出会尝试删除临时目录；强制杀进程、断电或清理失败可能留下文件。最终输出若在合并阶段中断，也可能留下不完整文件。
- 主脚本不提供保留临时目录选项；需要检查原始画面时，使用 [第 8 章](#decode-only) 的 Java 命令。

### 5.6 输出特性：画质、时间戳、音轨与元数据

**不是无损转封装。** KVC 压缩包先解码为原始画面，再编码为 H.264：

```text
KVC7 → YUV420P → libx264 CRF 18 / preset fast → H.264
```

默认 H.264 编码属于有损编码。CRF 18 不代表数学无损。脚本没有命令行画质选项，相关设置写在 Python 源码的 `stream.options` 中（见 [14.2](#build)）。

**音频**直接复制原文件第一个音频轨，没有重新压缩。本次原音轨为 AAC。其他音频编码能否直接封装进 MP4，需要另行确认。

**PTS 处理**：每帧使用解码器返回的 PTS，编码时间基设置为 `1/1000000`。虽然创建编码流时传了 `rate=30`，代码仍明确为各帧设置 PTS，**不是**简单按帧编号全部重建为等间隔 30 fps。

源样本有一个重复显示时间戳：`14066000` 微秒。为了兼容输出封装，后一帧被调到 `14066001` 微秒，所有画面均保留。通用处理规则：

```python
if last_pts is not None and pts <= last_pts:
    pts = last_pts + 1
```

本次仅发生一次调整。对于严重倒退、缺失或不同时间基的时间戳，这条规则**不是完整的时间线修复算法**；不要把它当作任意坏文件的自动音画同步方案。（路线 C 对这些情况有更严格的处理，见 [7.4](#route-c)。）

**元数据范围**：当前主要传递像素和 PTS，没有完整复制原始色彩空间、色彩范围、HDR 信息、旋转、字幕、章节及其他旁数据。只选择新视频和原始首音轨。不要假定所有 MP4 元数据、附加音轨或显示语义都被保留。

---

<a id="route-b"></a>

## 6. 路线 B：USB 安卓解码（备用）

### 6.1 条件

- 支持 ARM64 的 Android 手机。
- 已启用 USB 调试，并授权当前电脑。
- 电脑有 adb、Python/PyAV、ffmpeg、ffprobe。

库提取时使用了手机 root 权限，但已提取库后的独立解码程序在**普通 adb shell 权限**下运行成功。当前脚本本身不调用 `su`，不修改快手应用。

### 6.2 使用

```bash
adb devices -l
python transcode.py \
  --serial "设备序列号" \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

adb 不在 PATH 时：

```bash
python transcode.py \
  --adb "/完整路径/adb" \
  --serial "设备序列号" \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

手机侧固定工作目录为 `/data/local/tmp/kvc-probe`，包含：

- `phone_decode`：程序。
- `libffmpeg.so`、`libc++_shared.so`：库。
- `input.mp4`：输入副本。
- `decode.log`：程序诊断日志。

脚本不会自动删除这些手机侧文件。复用该目录会覆盖之前的输入、库与日志，**不要同时运行多个 USB 转码实例**。

### 6.3 手机到电脑的数据协议

C 程序输出的不是 MP4 或 FLV，而是一串自定义记录：

```text
帧 0：8 字节小端有符号 PTS + Y 平面 + U 平面 + V 平面
帧 1：8 字节小端有符号 PTS + Y 平面 + U 平面 + V 平面
...
```

- PTS 在本样本中以微秒为单位。
- YUV 为紧密排列的 8-bit YUV420P，没有行尾填充。
- 每帧画面 1,382,400 字节；加时间戳后每条记录 1,382,408 字节。
- **诊断信息必须与二进制画面流分开**，否则文本会被当成 PTS 或像素数据。

当前脚本用手机端 shell 将 stderr 重定向到 `decode.log`，再通过 `adb exec-out` 接收画面。**不要直接删掉重定向后将混合日志的输出喂给编码器。**

> [!NOTE]
> 这里的“8 字节 PTS + 一帧 YUV”自定义记录**不能**直接当作纯 rawvideo 输入；路线 C 的 KVCP0001 协议（大端、含流头与完成记录）与它是两套不同的协议，见 [11.7](#pts-deep-dive)。

---

<a id="route-c"></a>

## 7. 路线 C：带逐帧 PTS 的流式转码

更新：2026-11-04。本方案修改的是 `xin.chunming.KvcProbe_ffmpeg`。原有 `KvcProbe.java` 和 `transcode_unidbg.py` 保留原行为；**旧 Python 脚本不会自动使用新流程。**

### 7.1 数据路径

```text
Java / unidbg：Android libffmpeg.so 解码 KVC
    ↓ 当前帧 PTS + 紧凑排列的 YUV420P，二进制管道
pts_bridge.py：PyAV 将原始视频包封装成 NUT
    ↓ NUT 管道，含尺寸、像素格式、时间基和逐帧时间戳
本机 ffmpeg：libx264 CRF18 / preset fast 编码，复制原文件第一条音轨
    ↓
H.264 + AAC MP4
```

- 不创建完整 YUV 或 NUT 临时文件，也不先把全部帧加载进内存。
- 桥接层缓存相邻帧，以计算持续时间；管道满时写入会等待下游消费。Java、解码器和 x264 还会各自使用工作内存，**因此总内存不等于两帧大小**。
- PyAV 在这里**只负责封装**，不使用 Python 环境中的 H.264 编码器；实际编码由 PATH 上的本机 `ffmpeg` 完成。

### 7.2 准备和运行

需要：Java 17、Maven、本机 ffmpeg/ffprobe、Python 3.9+，以及当前项目 `lib/` 中匹配的 ARM64 库。

在项目根目录首次配置：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-pts.txt
```

运行：

```bash
./run_pts.sh /Users/fuchunming/Downloads/input.mp4 /Users/fuchunming/Downloads/output-pts.mp4
```

- 输出存在时会拒绝覆盖。
- 脚本自动编译 Java，并使用项目 `.venv/bin/python`。
- 不给参数时，默认读取 `/Users/fuchunming/Downloads/input.mp4`，输出到项目根目录中的 `output_pts_<时间>.mp4`。
- 复制项目到其他机器时，需要为该机器重新建立环境，并准备对应平台的本机工具。

**保留逐帧核对表（可选）：**

```bash
KVC_PTS_AUDIT=/tmp/kvc-pts.csv ./run_pts.sh /Users/fuchunming/Downloads/input.mp4 /Users/fuchunming/Downloads/output-pts.mp4
```

CSV 只有帧号、原 PTS、修正后 PTS、时间基，不含像素；默认不生成；CSV 也不覆盖已有文件。示例：

```csv
frame,original_pts,output_pts,time_base
...
423,14066000,14066000,1/1000000
424,14066000,14066001,1/1000000
...
```

CSV 只是核对日志，**不是**传给 FFmpeg 的时间戳来源；即使不生成 CSV，PTS 也已经通过二进制帧记录和 NUT 自动传递。

**使用别的 Python 环境：**

```bash
KVC_PYTHON=/absolute/path/to/venv/bin/python ./run_pts.sh input.mp4 output.mp4
```

### 7.3 在 IDEA 里运行

继续运行 `xin.chunming.KvcProbe_ffmpeg`，**工作目录设为本项目根目录**。程序参数填 `输入文件 输出文件`，含空格的路径用引号包裹。默认自动选择项目 `.venv/bin/python`；找不到时才尝试 `python3`。

如果运行目录不同，需要通过 VM options 指定路径：

```text
-Dkvc.python=/absolute/path/to/.venv/bin/python
-Dkvc.bridge=/absolute/path/to/pts_bridge.py
-Dkvc.libdir=/absolute/path/to/lib
-Dkvc.rootdir=/absolute/path/to/work/kvc-root
```

可选 VM options：

```text
-Dkvc.ffmpeg=/opt/homebrew/bin/ffmpeg
-Dkvc.ffprobe=/opt/homebrew/bin/ffprobe
-Dkvc.pts.audit=/tmp/kvc-pts.csv
```

`kvc.python` 必须是**可执行文件路径**，不是带额外参数的 shell 命令。

### 7.4 PTS 如何自动传递，以及异常 PTS 的规则

**传递流程（速览，详解见 [第 11 章](#pts-deep-dive)）：**

1. Java 成功收到一个 AVFrame 后，读取本库 ABI 的 `frame + 144` 处的 int64 PTS。
2. 读取同一帧的宽、高和像素格式。第一帧启动 Python 后继续发送自身，不会被丢弃。
3. Java 先写当前 PTS 和帧字节数，再按行去掉 stride padding，写 Y、U、V 像素。
4. Python 用本机 ffprobe 读取输入文件的第 0 轨 `time_base`。例如 `1/1000000` 表示一 tick 是一微秒，**不能对所有文件写死这个单位**。
5. Python 创建 rawvideo AVPacket，设置 `pts = dts = 当前帧 PTS` 和 `packet.time_base`，然后封装成 NUT。这里 rawvideo 没有 B 帧重排，所以 PTS/DTS 相同；后续 x264 自行产生编码后的 DTS。
6. 本机 FFmpeg 使用 `-fps_mode:v passthrough -enc_time_base:v demux`，保持逐帧时间信息，不强制重新按 30 fps 排列。

桥接器读取原视频名义帧率，用于视频流描述和末帧时长估计，**不把中间帧改造成固定帧率**。可取得源轨结尾时会优先用它计算末帧包时长；最终显示时长还取决于编码器及 MP4 封装，样片已实测核对。

**重复、缺失和倒退的 PTS：**

| 情况 | 行为 |
|---|---|
| 正常递增 | 原样保留 |
| 原始 PTS 相等 | 保留帧，令输出 `max(原 PTS, 上一输出 PTS + 1)`，记录修正；连续重复则逐 tick 前移，紧随其后的帧若与修正后时间冲突，同样作最小修正 |
| 原始 PTS 真正倒退 | 报错，不悄悄排序或改成固定帧率 |
| `AV_NOPTS_VALUE` | 报错，不猜测时间戳 |
| 负视频 PTS | 当前拒绝；需要统一平移音视频时间轴后才能扩展支持，不能只平移视频 |

样片第 423、424 帧原 PTS 都是 14066000；只把第 424 帧改为 14066001，即 +1 微秒。修正意味着这一帧不再逐值等同于原始 PTS，日志和可选 CSV 会明确记录。

### 7.5 音视频同步

- FFmpeg 使用 `-copyts`，不单独减去视频首帧时间，也不对两个输入分别 `-start_at_zero`。输入视频 PTS 和原音轨保持在同一条时间线上。
- 输出复制第一条音轨：`-map 1:a:0? -c:a copy`；没有音轨也可以运行。**不使用 `-shortest`** 截断音频。
- 若来源音频不能直接装入 MP4，需要另行增加音频转码；这版默认样本是 AAC 路径。
- 对原文件，系统 FFmpeg 可能仍打印 `unknown codec kvc7`，因为第二个输入包含 KVC 视频轨；它只复制其中的音频，实际视频来自 NUT，所以这个提示本身不代表失败。

### 7.6 管道协议（简述）

Java 与 Python 之间采用本项目自定义的 **KVCP0001** 二进制协议，整数均为大端：16 字节流头（`KVCP0001` + 宽 + 高）→ 每帧 12 字节记录头（int64 PTS + uint32 字节数）+ 紧凑 YUV420P → 12 字节完成记录（int64 帧数 + uint32 0）→ 关闭 stdin。

完成记录用于区分正常结束与异常断管：缺字节、没有完成记录、完成计数不符都会报错。Java 只有在 Python 和本机 FFmpeg 都成功退出后才打印 `SUCCESS`。中途失败可能留下未完成的 MP4，应检查日志并另选输出名，或自行删除失败文件后重试。

字段级细节见 [11.7](#pts-deep-dive)。

### 7.7 路线 C 的限制（摘要）

针对现有 ARM64 `.so` ABI；视频须在流索引 0；仅固定尺寸、偶数宽高 8-bit YUV420P；单视频 + 第一条可选音轨；不含网络 RPC，也不是零拷贝；编码仍是本机 CPU libx264。完整清单见 [第 17 章](#limitations)。

---

<a id="decode-only"></a>

## 8. 只解码：保留原始画面

这种方式**只解码**，不调用 Python/PyAV 编码，也不生成含音频的 MP4。适合检查首帧、核验原始 YUV、研究接口。

### 8.1 命令

在工具包根目录执行：

```bash
mkdir -p work
java \
  -Xmx2g \
  -Dkvc.libdir="$PWD/lib" \
  -Dkvc.rootdir="$PWD/work/root" \
  -cp "unidbg/classes:unidbg/deps/*" \
  KvcProbe \
  "/完整路径/input.mp4" \
  "$PWD/work/first.yuv" \
  1 \
  "$PWD/work/first-pts.txt"
```

Java 参数顺序：

| 位置 | 内容 |
|---|---|
| 1 | 输入视频路径 |
| 2 | 原始 YUV 输出路径 |
| 3 | 最多输出的帧数；`1` 为首帧，`0` 为全部 |
| 4 | PTS 文本输出路径 |

解码所有帧时将 `1` 改成 `0`，并给输出选择合适的文件名。

> [!WARNING]
> - **直接 Java 入口会覆盖同名 YUV 和 PTS 文件**，与 Python 入口拒绝覆盖最终 MP4 的行为不同。
> - 它也没有 Python 外层的 300 秒超时。
> - 示例明确传入两个 `-D` 属性及全部参数，避免触发源码中为原开发工作区保留的默认路径。

### 8.2 查看首帧

```bash
ffmpeg -n \
  -f rawvideo -pixel_format yuv420p -video_size 1280x720 \
  -i "work/first.yuv" \
  -frames:v 1 "work/first.png"
```

原始 YUV **不包含宽高、像素格式、音频或时间戳**，所以必须手动指定尺寸和格式。`pts.txt` 才是对应时间线；不能把 YUV 按固定 30 fps 重编码后就认为精确保留了原始时间戳。

### 8.3 检查裸 YUV：为什么 ffprobe 报 `Picture size 0x0 is invalid`

YUV 是裸像素数据，没有文件头，里面不记录宽高、像素格式、帧率或时间戳，所以 ffprobe 无法自动知道这些参数，会报 `Picture size 0x0 is invalid`。

如果实际解码输出是 1280×720、YUV420P，这样检查：

```bash
ffprobe \
  -f rawvideo \
  -pixel_format yuv420p \
  -video_size 1280x720 \
  -framerate 30 \
  "/Users/fuchunming/Downloads/unidbg-kvc/work/unidbg-first.yuv"
```

查看第一帧：

```bash
ffmpeg \
  -f rawvideo \
  -pixel_format yuv420p \
  -video_size 1280x720 \
  -i "/Users/fuchunming/Downloads/unidbg-kvc/work/unidbg-first.yuv" \
  -frames:v 1 \
  "/Users/fuchunming/Downloads/unidbg-kvc/work/first.png"
```

- 如果换了视频，**必须使用 Java 输出的实际宽高**，不能继续填写 1280×720。
- Java 程序默认只输出一帧。1280×720 的 YUV420P 单帧应为：`1280 × 720 × 1.5 = 1,382,400` 字节。
- 命令中的 `-framerate 30` 是**人为指定的解释方式，不是从文件里检测出来的**。要保留完整视频的原始时间线，需要配合程序输出的 PTS 文本；只读取 `.yuv` 无法恢复原始时间戳。

---

# Part III　原理与设计

<a id="decode-internals"></a>

## 9. KVC 解码链路：unidbg 里到底发生了什么

### 9.1 Java 解码器的工作流程

`KvcProbe.java` 的主要步骤如下：

1. 创建 64 位 Android 模拟环境。
2. 优先注册 Dynarmic，另注册 Unicorn2 作为备选后端；本次实际使用 Dynarmic。
3. 使用 `AndroidResolver(23)`，开启 unidbg 线程调度兼容。
4. 将模拟环境中的 `/input.mp4` 映射到传入的本地视频文件。
5. 依次加载 `libc++_shared.so` 和 `libffmpeg.so`。
6. 调用 `avformat_open_input`，读取第 0 条轨道的 codecpar。
7. 用 `avcodec_find_decoder_by_name("libkvc30dec")` 获取解码器。
8. 创建 context，复制轨道参数，设置线程选项并打开解码器。
9. 读取压缩包，使用 `avcodec_send_packet` / `avcodec_receive_frame` 解码。
10. 按每个平面的有效宽度逐行写 YUV，去掉可能存在的行尾填充；同时保存 PTS。
11. 到达 EOF 后发送空包，取出解码器剩余画面。

**本次没有调用 `JNI_OnLoad`，没有创建快手登录环境，也没有模拟快手的 Java 业务类。** 我们调用的是库导出的 native 函数，不是 App 的 Java 播放接口。

线程设置：

```c
av_opt_set_int(ctx, "threads", 1, 0);
av_opt_set(ctx, "kvc30_params", ":kvc30DecodeThreads=1", 1);
```

第二个调用最后的 `1` 对应“搜索子对象”选项。两个调用在实际测试中均返回 0。设置目的在于减少模拟环境中的并发复杂度；**并不等于已经证明库内部完全不会创建任何线程**。

### 9.2 传给解码器的到底是什么：指针

> 现在的代码传的就是指针。但它必须是 **unidbg 模拟地址空间里的指针**，不能直接把 Java 对象地址交给 `.so`。
> 还要区分：当前代码调用的是 FFmpeg 的解码接口，**没有直接调用 `kvc30dec_decode`**；底层 KVC 函数由库内部调用。

**① 现在传给解码器的是什么？**

```java
call("avcodec_send_packet", ptr(ctx), ptr(pkt));
```

对应的 C 接口：

```c
avcodec_send_packet(AVCodecContext *ctx, const AVPacket *pkt);
```

两个参数都是模拟内存中的指针：

```text
ctx → AVCodecContext
      解码配置、内部状态等

pkt → AVPacket
      ├─ data → 压缩码流所在内存
      ├─ size   码流字节数
      ├─ pts    显示时间戳
      ├─ dts    解码时间戳
      └─ 其他信息
```

所以它不是只收一个 `byte[]`，而是收一个**描述压缩数据的结构体指针**。结构体里面再指向真正的数据。

**② 视频数据是怎样进入内存的？**

```text
Mac 上的 MP4 文件
    ↓ Java 文件映射
.so 调用 avformat_open_input
    ↓
av_read_frame(fmt, pkt)
    ↓ .so 的解封装器读取文件、解析 MP4
AVPacket 中填入压缩包及时间戳
    ↓
avcodec_send_packet(ctx, pkt)
```

当前**不需要 Java 自己把每个压缩包转换为字节数组再传进去**。解封装和包内存管理主要由模拟环境中的库完成。

返回画面时也是指针：

```java
call("avcodec_receive_frame", ptr(ctx), ptr(fr));
```

库把结果填进 `fr` 指向的 AVFrame，其中 `data[]` 再指向各个像素平面。Java 随后读取这些内存。

**③ 能否自己读到内存，再把指针交给 `.so`？** 可以，但分两种情况。

*A. 手上是已经解封装的压缩视频包。* 可以：

```text
Java 获得一个压缩包
    ↓
在模拟环境中分配 AVPacket 及其数据缓冲
    ↓
将压缩字节写入这个模拟缓冲
    ↓
设置包长度、PTS 等信息
    ↓
传 AVPacket 指针给 avcodec_send_packet
```

应优先使用库的 `av_packet_alloc`、`av_new_packet` 等接口，让库建立正确的包和缓冲结构，避免手动拼整个结构体。

*B. 手上是完整 MP4 文件的字节。* 也可以放到内存，但**不能把整个 MP4 直接交给视频解码函数**。MP4 里面还有轨道、索引、音频、解码配置等信息。这时通常需要提供内存读取接口，例如自定义 AVIO，让解封装器从内存读：

```text
内存中的 MP4 → 解封装 → AVPacket → 解码
```

在 unidbg 中做回调还要适配模拟环境，复杂度高于目前的文件映射。

**④ 哪种“指针”能传？**

| 对象 | 能否直接交给模拟 `.so` |
|---|---|
| Java `byte[]` 对象本身 | 不能当作 native 数据指针直接使用 |
| 本机 JVM / native 内存地址 | 不能直接当作模拟地址 |
| unidbg 分配的模拟内存指针 | 可以，前提是数据布局符合接口 |
| `.so` 自己分配并返回的指针 | 可以在对应模拟环境和生命周期内使用 |

这里不存在“给一个地址，库就自动知道长度和格式”。指针只是地址，**长度、格式、所有权和生命周期都由函数接口约定**。尤其不能刚传进去就随意释放或改写缓冲：解码器可能保留引用；应使用对应 API 的引用计数和释放规则。

### 9.3 解码一共调用了几个函数

按当前 Java 版本，显式调用了 **15 种**不同的 `.so` 导出函数：

| 阶段 | 函数 |
|---|---|
| 日志设置 | `av_log_set_level` |
| 打开容器 | `avformat_open_input` |
| 查找解码器 | `avcodec_find_decoder_by_name` |
| 创建上下文 | `avcodec_alloc_context3` |
| 复制轨道配置 | `avcodec_parameters_to_context` |
| 设置选项 | `av_opt_set_int`、`av_opt_set` |
| 打开解码器 | `avcodec_open2` |
| 创建输入 / 输出对象 | `av_packet_alloc`、`av_frame_alloc` |
| 读取压缩包 | `av_read_frame` |
| 送入压缩包 | `avcodec_send_packet` |
| 取得解码画面 | `avcodec_receive_frame` |
| 释放当前包 / 帧引用 | `av_packet_unref`、`av_frame_unref` |

核心解码接口只有两个：

```c
avcodec_send_packet(ctx, pkt);   // 送入压缩数据
avcodec_receive_frame(ctx, fr);  // 取出解码画面
```

但**不是每帧只调用一次就一定有结果**：解码器可能需要缓存多个包，也可能一次送包后要多次取帧。输入结束后，还需要送空包，让它吐出缓存的剩余画面。

这 15 种函数不是总调用次数；循环中的函数会反复调用，而且 `.so` 内部还会进一步执行真正的 KVC 解码函数。

### 9.4 `kvLC` 配置块如何进入解码器

文件里的 `kvLC`，**大小写要区分**。它是 KVC 在 MP4 里的配置块标识，**没有证据表明它与 VideoLAN 的 VLC 播放器有关**，不能把这四个字符拆成“k + VLC”来理解。VLC 播放器是另一个独立项目。

在当前 Java 代码里，配置传递被 `libffmpeg.so` 内部处理了，所以看不到手动读取 `kvLC` 的代码。整体路径：

```text
MP4 文件
  ├─ kvc7：标识视频编码类型
  ├─ kvLC：解码配置数据
  └─ 视频压缩数据
          │
          ▼
avformat_open_input()
  解复用器读取 MP4 头、建立视频轨参数
          │
          ▼
AVStream.codecpar
  包含 codec_id、宽高、extradata 等
          │
          ▼
avcodec_parameters_to_context()
  把参数和 extradata 复制到解码器上下文
          │
          ▼
avcodec_open2()
  初始化 libkvc30dec，使其可以使用这些配置
          │
          ▼
avcodec_send_packet() / avcodec_receive_frame()
  输入压缩包，输出解码帧
```

对应代码最关键的两句：

```java
// 将视频轨参数（包括附加配置数据）交给解码器上下文
call("avcodec_parameters_to_context", ptr(ctx), par);

// 使用已经设置好的上下文打开解码器
call("avcodec_open2", ptr(ctx), ptr(dec), 0);
```

`avcodec_parameters_to_context()` 不只是复制宽高：FFmpeg 的实现会为 `extradata` 分配内存、复制内容，并设置 `extradata_size`（[FFmpeg 源码](https://ffmpeg.org/doxygen/trunk/group__lavc__core.html)）。

这里要区分两个层次：

- **接口层已经清楚**：视频轨配置通过 `codecpar → ctx` 传入；无需在 Java 里再单独发送一次配置块。
- **KVC 私有实现尚未逐字节确认**：`kvLC` 内容是否原样进入 `extradata`、中间是否转换，以及底层在 `avcodec_open2()` 时还是首包到来时完成全部解析，还需要跟踪这份 `.so`。不能仅凭接口调用就断言它的具体字段布局和解析时机。

可以把 `kvLC` 理解为这路压缩视频的“**解码说明书**”：后面的压缩包是具体内容。它在用途上类似 H.264 的 `avcC`、HEVC 的 `hvcC`，但这不代表它们内部格式相同。

所以：使用现在的 `libffmpeg.so` 解复用再解码，这些工作由库处理；如果以后**绕过解复用器**、直接调用底层 `kvc30dec_*`，就必须查清楚这份配置应该如何交给底层解码器。

---

<a id="data-transport"></a>

## 10. 解码之后的数据去哪：内存、管道、共享内存与 RPC

> 本章整理自“5.5 MB 的 KVC 解码成约 1.5 GB YUV，能否放内存并交给本机原生 FFmpeg 编码”开始的讨论，涵盖内存缓冲、进程管道、Java/unidbg 与原生 FFmpeg 的通信，以及 RPC 的使用场景。
>
> **本章是原理和架构说明，不是新功能实现。** 已有工具实际验证的是：路线 A 先由 unidbg 写出 YUV 与 PTS 文件再编码；路线 C 把管道方案落成了实现（见第 7、11 章）。本章讨论的**共享内存、RPC** 等方案尚未在该工具中实现或测量。

### 10.1 从问题出发

原问题：

> 一个约 5.5 MB 的 KVC 视频，解码得到约 1.5 GB 的 YUV。能不能把这些画面放在内存里，直接让本机原生 FFmpeg 编码，而不经过大临时文件？

答案是：**可以。更适合顺序转码的方式是边解码、边传输、边编码，不必同时保留整段 YUV。**

这里可以拆成三个独立问题：

1. 解码后为什么会产生这么多数据？（媒体表示）
2. 原始画面怎样从 Java/unidbg 交给本机原生 FFmpeg？（进程间通信）
3. 这种通信需要 RPC 吗？（调用协议）

它们分别涉及媒体表示、进程间通信以及调用协议，不应混在一起理解。

### 10.2 为什么 5.5 MB 会变成约 1.5 GB

KVC 文件中的视频经过压缩；YUV 是解码后的原始像素。文件大小悬殊是两种数据表示方式的差异，**不是解码器异常地“把文件放大”**。

对当前样本的 1280×720、8-bit YUV420P：

```text
Y 平面：1280 × 720        = 921,600 字节
U 平面： 640 × 360        = 230,400 字节
V 平面： 640 × 360        = 230,400 字节
---------------------------------------
每帧                     = 1,382,400 字节
```

样本共有 1084 帧：

```text
1,382,400 × 1084 = 1,498,521,600 字节
                 ≈ 1.50 GB（十进制）
                 ≈ 1.40 GiB（二进制）
```

以上不包含音频、时间戳和其他元数据，只计算紧密排列、不带行尾填充的像素。

**1.5 GB 是整段视频累计产生的数据量，不是必须同时驻留的内存量。** 顺序处理时，前面的画面编码并释放后，其缓冲空间可以供后面的画面复用。

对于偶数宽高，一般公式：

```text
Y：W × H 字节
U：(W / 2) × (H / 2) 字节
V：(W / 2) × (H / 2) 字节
```

### 10.3 三种保存与传输方式

| 方式 | 流程 | 优点 | 代价 |
|---|---|---|---|
| 整段写磁盘 | 解完整段 YUV，再读取编码 | 易于检查、复现和重试 | 需要大临时文件；两个阶段通常串行 |
| 整段保存在内存 | 解完整段到内存，再交给编码器 | 可避免显式 YUV 文件读写 | 样本就需要约 1.5 GB 像素内存；长视频持续增长 |
| 有界流式传输 | 解出一批画面，立即交给编码器 | 缓冲可有界；解码和编码可以重叠 | 需要处理时间戳、背压、进程结束和错误 |

将整段 YUV 放入 JVM 堆也有额外成本：数组大小、对象管理和垃圾回收压力。直接内存或堆外内存能改变管理方式，但不会消除实际物理内存需求。内存压力过大时还可能发生交换，因此“放内存”不自动等于“完全没有磁盘活动”。

对于当前顺序转码需求，**优先考虑流式传输**。只有需要反复访问大量历史帧、做随机访问算法，或有其他明确用途时，整段缓存才可能值得。

**小缓冲可以有多小？** 例如缓存 10 帧：

```text
1,382,400 × 10 = 13,824,000 字节 ≈ 13.8 MB
```

这只是应用层额外排队的像素量。整个程序还会占用：

- unidbg 模拟内存与执行后端内存。
- KVC 解码器的参考帧、内部工作区和线程资源。
- JVM 堆及 native 内存。
- 操作系统管道缓冲。
- FFmpeg、编码器的参考帧、前瞻和重排序缓冲。
- 硬件编码路径可能需要的像素缓冲区。

因此“缓存 10 帧”不等于“全系统只占 13.8 MB”，但可以避免额外保留整段 1.5 GB 原始视频。

### 10.4 原生 FFmpeg 与 KVC 解码器可以分开

这两个阶段不必由同一份 FFmpeg 库完成：

```text
KVC 压缩数据
    ↓
Java / unidbg 中的 Android libffmpeg.so
负责 KVC 解码
    ↓ 原始像素 + 时间戳
Mac 本机原生 FFmpeg
负责 H.264／HEVC 编码
    ↓
普通视频文件
```

当前库中的 KVC 解码能力与本机 FFmpeg 的编码能力是独立的。主机 FFmpeg 不需要理解 KVC，只需能够理解输入的像素格式和时间线。

**硬件加速发生在哪里？**

- **前半段 KVC 解码**：仍由 unidbg 中的原 `.so` 执行；把输出交给主机 FFmpeg，并不会自动让 KVC 解码变成硬件解码。
- **后半段编码**：主机 FFmpeg 可以选择软件编码，或在硬件、构建与输入条件支持时使用硬件编码。

用户提供的 Mac FFmpeg 构建日志包含 VideoToolbox 支持，因此可以进一步探索该路径。但**没有实际测试本样本的硬件编码表现**，也没有证明全部像素格式和编码选项都能直接适配。

硬件编码不保证整条流程按相同比例提速。速度还受解码、格式转换、内存复制、编码设置以及磁盘输出等因素限制。软硬件编码器的质量、码率和选项也不是一一对应的。

### 10.5 为什么 Java 可以把 `.so` 解出的画面交给原生程序

unidbg 里的 Android 环境不是另一台真实机器。它由运行在 Mac 上的 Java 进程及其 native 后端管理。

`.so` 解码后，画面位于它所看到的**模拟 ARM64 地址空间**。Java 通过 unidbg 的指针接口可以读取这些字节。现有代码中的这一行就是数据出口：

```java
byte[] row = data.getByteArray((long) y * stride, pw);
```

这里的 `data` 表示模拟地址空间中的画面指针。`getByteArray` 将指定范围的字节读取成 Java 可用的数组；**不能把模拟地址值当成本机 FFmpeg 可直接使用的进程地址**。

路线 A 把数组写到文件：

```text
模拟内存 → Java byte[] → YUV 文件
```

流式方案（路线 C）改为：

```text
模拟内存 → Java byte[]／缓冲区 → 管道 → FFmpeg（经 Python 桥接）
```

真正需要改变的是**输出通道及配套的时间戳协议**，而不是把 KVC 算法改写成 Java 或 C。

### 10.6 管道：两个本机进程之间的字节通道

Java 和原生 FFmpeg 都是 Mac 上的进程。操作系统可以提供一个管道：

```text
Java 进程：写端
        ↓
macOS 管道缓冲区
        ↓
FFmpeg 进程：读端
```

管道不关心一端是 Java、一端是 C/C++ 程序。两边只要按照相同的数据约定写入和读取字节即可。**不需要联网，不需要 HTTP，也不需要为了连接两种语言而引入 RPC。**

**Java 启动 FFmpeg。** Java 可以通过 `ProcessBuilder` 启动 FFmpeg 子进程，然后向子进程的标准输入写入画面。以下仅说明接口关系，不是完整、可直接运行的转码代码：

```java
Process ffmpeg = new ProcessBuilder(/* FFmpeg 参数 */).start();
OutputStream ffmpegStdin = ffmpeg.getOutputStream();
ffmpegStdin.write(row);
```

容易混淆的是方法名：

| Java `Process` 接口 | 从 Java 视角看 | 对应子进程 |
|---|---|---|
| `getOutputStream()` | Java 向外写数据 | 子进程 stdin |
| `getInputStream()` | Java 读子进程输出 | 子进程 stdout |
| `getErrorStream()` | Java 读诊断信息 | 子进程 stderr |

FFmpeg 输入使用 `pipe:0` 时，读取的是它的 stdin。

**由终端连接两个程序。** 也可以由终端创建连接：

```text
Java 解码程序的 stdout | FFmpeg 的 stdin
```

此时 Java 的 stdout **必须只包含约定的媒体字节**。日志应写 stderr，否则一行 `frames=100` 也会成为像素流的一部分，导致画面错位。当前工具的 Java 程序（路线 A）将进度输出到 stdout，并把 YUV 写文件，所以**不能把现有程序直接加一个 `| ffmpeg` 就认为已经完成改造**。

**读取、写入和帧边界。** 管道是**字节流，不是“帧队列”**：

- 一次写入不保证对应对方的一次读取。
- 多次写入可能被一次读取合并。
- 一帧可能需要多次读取才完整。

如果约定输入始终是 1280×720 YUV420P，读取端可以每收齐 1,382,400 字节，就得到一帧。这要求传输格式一致且没有混入日志、时间戳或其他未约定的字节。若尺寸或像素格式会变化，就需要额外的格式描述和帧边界协议。（路线 C 的 `read_exact()` 正是为此而设，见 [11.8](#pts-deep-dive)。）

### 10.7 背压：为什么流式处理不必无限吃内存

假设解码器每秒生成 100 帧，而编码器每秒只能处理 50 帧。如果把画面不断塞进无界队列，内存会持续增长。有界缓冲和阻塞管道可以让生产速度受消费速度约束：

```text
编码器较慢
    ↓
管道／有界队列逐渐填满
    ↓
写入操作等待
    ↓
解码端暂停继续生产
    ↓
编码器消费后释放空间，双方继续
```

这就是**背压**。它不是自动丢帧，也不是把剩余整段视频偷偷存起来，而是让上游等待。

如果另起一个线程解码，并让它写入无界队列，那么管道的背压只会阻塞发送线程，队列仍可能无限增长。要让总缓冲有界，整条生产链都必须遵守容量限制。

**为什么仍可能死锁？** FFmpeg 的 stderr 也是一条输出通道。若 Java 一直写 stdin，但不消费 FFmpeg 大量输出的诊断日志，stderr 缓冲可能填满：

```text
Java 等待 FFmpeg 读取 stdin
FFmpeg 等待 Java 读取 stderr
```

实际实现需要并行消费日志或将其重定向到合适的位置，同时设计好取消与错误传播。**管道结构简单，但完整进程管理不能省略。**

### 10.8 裸 YUV、时间戳和音轨是不同的信息

**YUV 里没有什么？** 裸 YUV 不记录：

- 宽高与像素格式。
- 每帧显示时间戳 PTS。
- 音轨。
- 色彩范围、色彩空间、HDR 或旋转等描述信息。

即使全部像素都传过去，时间线和其他信息也不会自动跟着过去。

**固定帧率方案与保留 PTS 的方案：**

- **方案一：声明固定 30 fps。** FFmpeg 根据帧编号生成时间线，操作相对简单。但对于可变帧率、重复 PTS、时间间隙或原始起始偏移，这可能改变播放节奏和音画关系。
- **方案二：同时传输画面和原始 PTS。** 可以采用额外的时间戳通道、自定义帧协议，或由发送端生成 FFmpeg 能读取且能承载像素格式与逐帧时间戳的流式封装。具体封装需要确认与 rawvideo、像素格式和目标 FFmpeg 的兼容性。

如果使用自定义“时间戳 + 像素”协议，FFmpeg 的标准 rawvideo 输入不会自动识别它，还需要一层适配程序或对应输入模块。现有 USB 原型使用的就是“8 字节 PTS + 一帧 YUV”的自定义记录，并由 Python 解析；不能直接将这串记录作为纯 rawvideo 输入。**路线 C 采用的正是方案二**（Python/PyAV 作为适配层，输出 NUT）。

**音轨怎么处理？** 当前样本的音轨可以从原文件直接拷贝，最后与重新编码的视频合并。需要维持两条轨道的相对起始时间和播放时间线。“复制音频”只说明音频没有重新编码，不自动保证任意输入都能保持同步；尤其不能将视频时间线全部改成固定间隔后，仍假定原音轨一定与之完全对齐。

### 10.9 管道与共享内存：都可避免大文件，但不是一回事

**普通管道。** 数据可能经过：

```text
模拟器内存
    ↓
Java 数组／缓冲
    ↓
操作系统管道
    ↓
FFmpeg 输入缓冲
    ↓
编码器所需的帧缓冲
```

优点是进程接口简单、天然适合顺序字节流、有阻塞机制。代价是仍有数据读取和复制，因此“走管道”**不等于“零拷贝”**。实际复制次数取决于运行环境和实现，不能仅凭图示断言固定次数。

**共享内存。** 两个进程映射同一块内存区域，用它交换画面，另用同步机制告诉对方哪些帧已经就绪、哪些槽位可以复用。它需要设计：

- 环形缓冲的槽位数量和最大帧大小。
- 帧序号、PTS、尺寸、像素格式和 stride。
- 读写完成通知及内存可见性。
- 缓冲区所有权与复用时机。
- 进程退出、崩溃、取消后的恢复。

共享内存可能减少部分进程间复制，但它**不会**让 unidbg 的模拟内存自动成为 FFmpeg 的共享帧内存，也不保证硬件编码器能直接使用该区域。硬件路径仍可能需要格式转换或复制到适合它的缓冲。另外，普通 FFmpeg 命令行不会凭空理解一个自定义共享内存环形队列，仍需要输入适配层。

对当前样本，**应先测量普通管道方案**。只有数据传输与拷贝确实成为明显瓶颈，才有理由承担共享内存的额外复杂度。

### 10.10 RPC 是什么，解决什么问题

RPC 是 Remote Procedure Call，远程过程调用。它让一个进程请求另一个进程执行某项功能，并接收结果或错误。“远程”不一定跨机器：两个本机进程之间也能使用 RPC。

如果将 KVC 解码器做成常驻服务，可以定义：

```text
openVideo(path)
  → sessionId、宽高、像素格式、时间基

readNextFrame(sessionId)
  → PTS、画面数据，或 EOF

seek(sessionId, targetTime)
  → 成功、失败，或实际定位位置

closeVideo(sessionId)
  → 释放会话资源
```

这些调用包含操作名、参数、返回值、错误和会话归属。RPC 框架或自定义协议可以组织这些信息，而不是要求每个调用方直接操作解码器内部结构。

**适合 RPC 的情况：**

| 需求 | RPC 的价值 |
|---|---|
| 解码器在另一台电脑 | 通过网络调用远程能力 |
| Java、Python、C++ 共用服务 | 提供统一、跨语言的数据接口 |
| 解码环境需要常驻 | 复用已加载的库和模拟环境 |
| 多个客户端或多任务 | 按会话、任务 ID 区分资源与状态 |
| 需要打开、跳转、取消、查询进度 | 定义明确的操作、返回结果和错误 |
| 解码器独立部署或升级 | 客户端通过稳定接口使用服务 |

RPC 不自动实现这些业务能力。比如多会话隔离、排队、线程安全、取消和资源释放，仍需要服务端设计。

**管道与 RPC 不是二选一**，二者位于不同层面：

| 概念 | 回答的问题 |
|---|---|
| 管道 / socket / 共享内存 | 数据怎样在进程间移动？ |
| RPC 协议 | 数据代表哪项调用、什么参数、怎样返回结果？ |

因此：

- RPC 可以运行在网络 socket 上。
- 本机 RPC 可以使用 Unix domain socket 等通道。
- 也可以在管道之上设计请求 / 响应式 RPC。
- 使用管道传 YUV，并不自动构成 RPC。

只有单向地连续发送像素，通常不需要完整的过程调用机制。若通过管道发送的是带调用 ID 的“打开、跳转、关闭”请求，并返回对应结果，那么它也可以承载 RPC。RPC 需要考虑请求与响应匹配、消息边界、类型转换、错误处理、超时等问题。**它不是一种天然更快的传输方式。**

**控制通道与画面通道可以分开。** 常驻服务可以采用如下结构：

```text
客户端
    │
    ├─ 控制通道：RPC
    │     打开视频、查询参数、跳转、取消、关闭会话
    │
    └─ 数据通道：管道／共享内存／网络流
          大量像素、逐帧时间戳和必要的格式信息
```

原因是两类数据特性不同：控制消息通常较小，强调语义、状态和错误反馈；画面吞吐量大，强调连续传输、缓冲和背压。分开后也需要关联规则，例如会话 ID、帧序号、跳转后的新时间线标识，否则可能把一次旧请求的画面误当成新会话的输出。

也可以使用支持流式传输的 RPC 系统同时承载画面，不是一定要拆成两条通道。但应评估消息大小限制、序列化开销、复制、流量控制以及取消行为，而不是默认它更适合视频。

**网络传输的带宽。** 若画面必须跨网络传输，原始 YUV 的带宽需求很大。对本例 1280×720 YUV420P、30 fps：

```text
1,382,400 × 30 = 41,472,000 字节／秒
               ≈ 41.5 MB/s
               ≈ 332 Mb/s（未计协议开销）
```

因此远程解码服务还需要评估：是否应在解码所在机器直接编码，再传输压缩结果，而不是把原始 YUV 跨网络发送。这与本机管道的问题不同。

### 10.11 对当前 KVC 工具，怎样选择合理

| 目标 | 建议 |
|---|---|
| **单个文件顺序转码**（当前目标） | `unidbg 解码 → 有界流式通道 → 本机 FFmpeg 编码`。需要把像素格式、尺寸、PTS、日志隔离、进程退出与背压处理清楚。没必要只因为 Java 与 FFmpeg 语言不同就引入 RPC |
| **常驻、交互、多任务**（后续） | 若需要多个程序共用解码环境，并支持进度查询、跳转、取消和会话管理：`RPC 控制接口 + 适合大量帧的数据传输通道` |
| **减少传输复制**（后续） | 先用测量确定瓶颈，再考虑共享内存或更深入的 native 集成。不要因为原始数据累计有 1.5 GB，就直接认定操作系统管道一定不够快 |

### 10.12 对性能的正确预期

让解码和编码重叠，通常能够减少等待，但不是无条件提速公式。若两阶段顺序执行，可以粗略理解为：

```text
总耗时 ≈ 解码时间 + 编码时间 + 文件及其他处理时间
```

若能有效并行且资源充足，流水线耗时可能更接近：

```text
总耗时 ≈ 较慢阶段的时间 + 启动、排空和传输开销
```

这只是直观估计。实际两阶段会争用 CPU、内存带宽和其他资源；编码器还可能存在帧缓存及前瞻。因此并行后的每个阶段耗时不一定与单独运行相同。

已有工具曾验证本地 unidbg 能完整解码样本，但**不能将此前“写文件”的测量直接当成新管道方案或硬件编码方案的性能结果**。

### 10.13 讨论结论与实施边界

本次讨论确认的原理是：

1. 可以将 unidbg 解出的画面交给本机原生 FFmpeg 编码。
2. 没必要同时保存整段约 1.5 GB 的 YUV；有界流式处理更适合顺序转码。
3. Java 通过 unidbg 指针接口读取像素后，可以写入普通本机管道，不需要 RPC。
4. 本机编码器可以独立选择软件或硬件路径，但这不会自动加速前面的 KVC 解码。
5. 裸 YUV 不包含 PTS，准确时间线必须单独设计。
6. 管道不等于零拷贝，共享内存也不等于整个解码编码流程零拷贝。
7. RPC 适合有调用语义、会话和控制需求的服务；它与底层传输方式可以组合。

本章没有提供新的可执行转码管道（那是第 7 章路线 C 的内容），也没有修改 Java、Python、C 外壳或原始 `.so`。所有代码片段和架构图都用于解释原理；实际实施前仍需确定协议、时间线、缓冲容量和进程管理细节。

---

<a id="pts-deep-dive"></a>

## 11. 流式转码详解：Java、Python、NUT 与逐帧 PTS

日期：2026-11-04。本章记录从“Java 输出裸 YUV，FFmpeg 按固定 30 fps 编码”改为“Java 输出帧及 PTS，Python 封装 NUT，本机 FFmpeg 按实际时间戳编码”的设计、实现和验证。代码片段来自当前实现，省略部分参数时会注明。

> [!IMPORTANT]
> 最关键的结论：**Java 完全可以传递时间戳。原先的问题出在 rawvideo 输入格式没有携带逐帧 PTS 的位置。Python 的作用，是调用 PyAV，把我们自定义的帧记录转换成 FFmpeg 能理解的 NUT 数据流。**

### 11.1 这次解决的具体问题

旧流程已经可以让原始像素不落盘：

```text
KVC 文件 → unidbg 解码 → Java 写裸 YUV → 管道 → 本机 FFmpeg → H.264 MP4
```

但是旧命令指定了：

```bash
-f rawvideo -pixel_format yuv420p -video_size 1280x720 -framerate 30 -i pipe:0
```

FFmpeg 只收到一段连续的像素字节，因此按照帧序号和 30 fps 为输入生成时间戳。**原视频中每一帧真正的 PTS 没有被传递。**

例如，下面这组显示时间：

```text
原时间：0 ms，33 ms，67 ms，120 ms
```

如果只提供四帧像素并声明固定 30 fps，接收端会按近似如下的时间解释：

```text
新时间：0 ms，33.333 ms，66.667 ms，100 ms
```

第四帧的时间已经改变。固定帧率输入对原本严格固定帧率、且时间起点已经正确处理的视频可能足够，但无法表达一般的逐帧时间信息。

新的流程补齐了这部分：

```text
KVC 文件
   ↓
Java / unidbg：解出画面，同时读取 PTS
   ↓ 自定义二进制记录
Python / PyAV：把画面和 PTS 封装为 NUT
   ↓ 标准媒体流
本机 FFmpeg：读取 NUT，编码为 H.264，并复制原文件音频
   ↓
MP4
```

变化发生在**传输格式和封装层**。KVC 解码算法仍由原 Android 库执行，最终视频编码仍由本机 FFmpeg 完成。

### 11.2 三个进程与三套 FFmpeg 相关组件

持续处理视频时，主要有三个宿主机进程：

| 进程 | 主要任务 | 关键数据 |
|---|---|---|
| Java / JVM | 运行 unidbg，调用 Android KVC 解码库 | AVFrame、PTS、YUV 像素 |
| Python | 读取自定义帧记录，调用 PyAV 做 NUT 封装 | 原始视频包及其时间戳 |
| 本机 `ffmpeg` | 解复用 NUT、H.264 编码、音频复制、MP4 封装 | 最终编码包和输出 MP4 |

Python 启动时还会短暂运行一次本机 `ffprobe`，读取原文件的轨道信息。

这里有三套容易混淆的组件：

| 组件 | 在哪里运行 | 这次负责什么 |
|---|---|---|
| Android `libffmpeg.so` | Java 进程里的 unidbg 模拟环境 | 读取 KVC 文件、执行私有解码器 |
| PyAV 使用的本机 FFmpeg 动态库 | Python 进程 | 构造原始视频包、生成 NUT |
| 系统安装的 `ffmpeg` 可执行程序 | 独立的本机进程 | 使用 libx264 编码并生成 MP4 |

PyAV 是 Python 对 FFmpeg 库的绑定。调用 `container.mux()` 时，实际封装工作主要发生在原生库中。

**PyAV 使用的库不必与 PATH 中 `ffmpeg` 的库版本一致。** 两个进程之间传递的是标准 NUT 字节流，而不是跨版本共享 FFmpeg 的内存结构。本次 PyAV 15.1.0 与系统 FFmpeg 9.0.1 已配合运行成功。

unidbg 的模拟环境也不是另一个独立 Android 进程。它位于 JVM 进程内部；模拟器里的地址不能直接作为 Python 或本机 FFmpeg 的有效内存地址。

### 11.3 两根管道实际连接在哪里

```text
Java ProcessBuilder 启动 Python
    Java 持有 Python 的 stdin 写入端
                  │
                  │ KVCP0001 格式
                  ▼
             Python 的 stdin
                  │
       Python subprocess.Popen 启动 ffmpeg
       PyAV 写入 ffmpeg 的 stdin
                  │
                  │ NUT 格式
                  ▼
              ffmpeg 的 stdin
                  │
                  ▼
               输出 MP4
```

Java 中：

```java
process = pb.start(); // 此处启动的是 Python
out = new DataOutputStream(
    new BufferedOutputStream(process.getOutputStream(), 1024 * 1024)
);
```

`process.getOutputStream()` 是父进程写入子进程标准输入的接口，因此这里写入的内容由 Python 从 `sys.stdin.buffer` 读取。

Python 中：

```python
process = subprocess.Popen(command, stdin=subprocess.PIPE)  # 启动本机 ffmpeg
container = av.open(process.stdin, mode='w', format='nut', ...)
```

`process.stdin` 对应 FFmpeg 的标准输入。PyAV 的封装结果直接写入这个对象。

本实现**没有把 Python 的 stdout 当作 NUT 管道**，也没有让 Java 再转发一次 NUT。Python 直接写自己的 FFmpeg 子进程 stdin。

日志走独立通道：Java 的打印不会混入它写给 Python 的 stdin；Python 诊断主要写 stderr；本机 FFmpeg 的日志也不混入 NUT 输入。

**这是不是 RPC？** 目前是两个具有约定格式的顺序数据流，没有设计 `open`、`seek`、`cancel` 等带请求编号的远程调用接口，因此不需要 RPC 框架。管道是传输方式；RPC 是调用协议。以后要做常驻解码服务时可以另加 RPC，但它不会自动解决媒体时间戳的封装问题。

### 11.4 为什么裸 YUV 无法传递原始 PTS

YUV420P 描述的是像素怎样存储。对于偶数宽高，1280×720 的一帧是：

```text
1280 × 720 × 3 / 2 = 1,382,400 字节
```

裸 rawvideo 输入按指定尺寸和格式，从字节流中每取够一帧的字节数，就得到一幅画面。它没有“接下来这 8 字节是 PTS”的约定。如果直接这样写给旧的 rawvideo 输入：

```java
out.writeLong(pts);
out.write(yuv);
```

FFmpeg 会把这 8 字节也当成像素。随后帧边界会错位，可能出现画面损坏或帧大小错误。

同样，单独准备一个 `pts.txt`，再给 FFmpeg 加一个普通 `-i pts.txt`，也不会自动把文本中的第 N 行绑定到第 N 帧。必须有理解这种对应关系的程序、专门输入实现或时间戳处理逻辑。**这次使用 Python，正是为了完成“读懂对应关系，并转换为标准媒体流”这一步。**

### 11.5 PTS、DTS、duration 与时间基

**PTS 是显示时间戳，必须配合单位。** PTS 是整数；`time_base` 表示一个整数单位对应多少秒：

```text
显示时间（秒）= PTS × time_base
```

| PTS | time_base | 显示时间 |
|---:|---|---:|
| 33333 | 1/1000000 | 0.033333 秒 |
| 3000 | 1/90000 | 0.033333… 秒 |
| 1 | 1/30 | 0.033333… 秒 |

因此，**不能看到 `33333` 就认为它必然是微秒**。样片使用 `1/1000000`，所以这里一 tick 恰好是一微秒。

当前 Python 从同一个输入文件的第 0 轨读取 `time_base`：

```python
tb = Fraction(video['time_base'])
```

用 `Fraction` 保持有理数表示，避免在内部把时间基先转换成不精确的浮点数。当前 Java 输出帧 PTS 使用原视频轨时间基的约定已经在此库和样片上验证。更换私有库、解复用流程或增加会改时间戳的处理后，应重新核对这个约定。

**DTS 是解码时间戳。** 带 B 帧的压缩视频可能需要先解码后面才显示的参考帧，因此压缩包的解码顺序和显示顺序可能不同。桥接器接收的是已经解码的完整画面，按解码器输出顺序写入，且要求显示 PTS 非递减。每个 rawvideo 包都能独立还原为一帧，没有跨包参考关系，因此本层设置：

```python
packet.pts = packet.dts = pts
```

这只针对中间的 rawvideo/NUT 层。最终 H.264 编码器可以使用 B 帧，并自行生成适合压缩视频的 DTS，最终 MP4 中 PTS 与 DTS 不必相同。

**duration 是持续多久。** PTS 回答“什么时候显示”，duration 回答“持续多久”，它们也有时间基：

```text
本帧 PTS：100000
下帧 PTS：133333
本帧估算 duration：33333 tick
```

当前桥接器会暂存上一帧，看到下一帧 PTS 后再计算它的 duration。末帧的处理见 [11.10](#pts-deep-dive)。

**不同层的整数可能不同，实际时间应相同。** 例如，源时间基是 `1/90000`，某一层输出使用 `1/180000`：

```text
原 PTS 3000 × 1/90000
新 PTS 6000 × 1/180000
```

两者对应同一时刻。这种转换称为时间基换算。通用核对应该比较 `PTS × time_base`，不能只比较整数。在样片中，源视频和最终视频都是 `1/1000000`，所以可以直接逐项比较 PTS 整数。

### 11.6 Java 如何取出同一帧的像素与 PTS

收到解码帧后，当前代码读取：

```java
int w = ptr(fr).getInt(112);
int h = ptr(fr).getInt(116);
int pix = ptr(fr).getInt(124);
long pts = ptr(fr).getLong(144);
```

这些数字是当前 ARM64 私有库的 AVFrame 字段偏移，**不是任意 FFmpeg 版本通用的常量**（来龙去脉见 [12.3](#abi-notes)）。随后把同一帧传给写入函数：

```java
pipe.writeFrame(fr, w, h, pts);
count++;
call("av_frame_unref", ptr(fr));
```

顺序很重要：**先读取并发送这帧需要的数据，再解除该 AVFrame 对解码缓冲的引用。**

**首帧启动后不会丢失。** 第一帧到达时，程序先得到尺寸，再启动 Python，写入流头；接着在同一次 `writeFrame()` 调用中继续写这帧的记录头和像素：

```text
收到首帧
  → 读取宽、高、格式、PTS
  → 启动 Python
  → 写流头
  → 写首帧 PTS 和像素
  → 返回解码循环
  → av_frame_unref
```

启动进程后没有提前 `return`，所以不会跳过第一帧。

**为什么逐行写，而不是直接复制一个连续大块。** AVFrame 的每个平面都有 `linesize`，它可能比有效像素行更宽，额外空间用于内存对齐：

```java
Pointer data = ptr(frame).getPointer(plane * 8);
int stride = ptr(frame).getInt(64 + plane * 4);

for (int y = 0; y < ph; y++) {
    out.write(data.getByteArray((long) y * stride, pw));
}
```

`y * stride` 定位到该行的实际起始地址；`pw` 是这一行要发送的有效像素字节数。这样输出的是**紧凑排列的 Y、U、V**，而不是把内存中的行尾填充也带进协议。

**解除 AVFrame 引用时，FFmpeg 还没收到会不会出错？** 不会因为这个顺序而丢失像素：`getByteArray()` 已经把模拟内存中的数据复制成 Java 字节数组，`out.write()` 随后把它交给 Java 缓冲或管道。写入函数返回后，下游需要的数据已不依赖原 AVFrame 的像素缓冲。数据可能还在 Java 的缓冲区或操作系统管道中，但那是另一份数据。这也是本实现不能称为零拷贝的原因。

### 11.7 Java 到 Python 的二进制协议：KVCP0001

Java 和 Python 之间采用本项目定义的 `KVCP0001` 协议。**它不是 NUT、不是 MP4，也不是 FFmpeg 原生支持的输入格式。** 整数均为**大端**，与 Java `DataOutputStream` 一致。

**流头（16 字节）：**

| 偏移 | 字节数 | 类型 | 含义 |
|---:|---:|---|---|
| 0 | 8 | ASCII | 固定标识 `KVCP0001` |
| 8 | 4 | uint32 | 宽度 |
| 12 | 4 | uint32 | 高度 |

Java 写入：

```java
out.writeBytes("KVCP0001");
out.writeInt(w);
out.writeInt(h);
```

Python 读取：

```python
magic, width, height = struct.unpack('>8sII', read_exact(source, 16))
```

**每帧记录（12 字节记录头，加像素）：**

| 偏移 | 字节数 | 类型 | 含义 |
|---:|---:|---|---|
| 0 | 8 | int64 | 当前帧 PTS |
| 8 | 4 | uint32 | 后续像素字节数 |
| 12 | 按尺寸计算 | bytes | 紧凑 YUV420P 像素 |

Java：

```java
out.writeLong(pts);
out.writeInt((int) bytes);
// 接着逐行写入像素
```

Python：

```python
original, size = struct.unpack('>qI', read_exact(source, 12))
pixels = read_exact(source, size)
```

符号解释：`>` 大端字节序，高位字节在前；`q` 8 字节有符号整数；`I` 4 字节无符号整数；`8s` 8 字节字符串。Java 没有独立的 uint32 类型，但这里尺寸和字节数都被限制在正数范围内，写出的位模式与 Python 读取的 uint32 一致。

**完成记录（12 字节）：** 正常结束时，Java 发送：

```java
out.writeLong(count);
out.writeInt(0);
out.close();
```

大小为 0 时，这条记录不是视频帧；前面的 int64 表示总帧数。Python 检查总帧数是否与自己收到的帧数一致，并确认后面没有多余字节。因此整个流类似：

```text
[KVCP0001 + 宽 + 高]
[PTS_0 + 字节数 + YUV_0]
[PTS_1 + 字节数 + YUV_1]
...
[总帧数 + 0]
[EOF]
```

一个 1280×720 YUV420P 帧为 1382400 字节。每帧 PTS 单位取原文件第 0 轨的时间基，不是固定微秒。

> [!WARNING]
> `out.writeLong(pts)` 只能写给这个 Python 桥接器，**不能写进旧的 `-f rawvideo` 输入**。NUT 是由 PyAV 生成的真正容器，不是给原始像素加一个自定义头就能让 FFmpeg 识别。

**哪些信息没有放进这个协议？** 当前协议只在流头传宽高；像素格式由双方约定为 YUV420P。时间基没有放入 KVCP0001 流头，而是由 Python 根据 `--input` 指定的同一个原文件读取。色彩参数、名义帧率和源轨道时长也来自该文件。所以，**这一版自定义管道不是完全自描述的通用视频协议**，调用方必须提供正确的原文件。以后若要脱离原文件或跨机器运行，应给协议增加版本化的时间基、像素格式、轨道信息等字段。

### 11.8 Python 如何正确读取管道

管道是连续的字节流，不保证 Java 一次 `write()` 恰好对应 Python 一次 `read()`。Java 写入一条记录，操作系统可能分多次交付；Java 分几次写入的数据，也可能被一次读取拿到。因此程序使用 `read_exact()`：

```python
def read_exact(source, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = source.read(size - len(chunks))
        if not part:
            raise EOFError('Java stream truncated ...')
        chunks.extend(part)
    return bytes(chunks)
```

它把“读取一个精确长度的字段或帧”建立在普通字节流之上。读取像素之前，程序会检查记录声明的字节数是否与宽高对应：

```python
frame_size = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
```

若协议错位、格式不匹配或尺寸不对，会报错，而不是拿错长度继续处理后续所有帧。这是为什么协议中既有宽高，又保留每帧字节数：对当前固定格式而言，字节数可以计算出来，但显式记录方便逐帧校验。

### 11.9 PyAV 如何把像素和 PTS 封装成 NUT

**先创建一个写向 FFmpeg stdin 的 NUT 输出。** 关键代码：

```python
container = av.open(
    process.stdin,
    mode='w',
    format='nut',
    options={
        'avoid_negative_ts': 'disabled',
        'flush_packets': '1',
    },
)

stream = container.add_stream('rawvideo', rate=rate)
stream.width = width
stream.height = height
stream.pix_fmt = 'yuv420p'
stream.time_base = tb
stream.codec_context.time_base = tb
container.start_encoding()
```

这里的容器输出目标是一个可写的管道对象，不是磁盘文件名。`rawvideo` 在这里表示 NUT 中的视频流装的是原始像素。它与旧流程的“直接以 rawvideo 为输入格式读裸字节”有区别：

| 形式 | 像素 | 容器中的尺寸、格式、时间戳 |
|---|---|---|
| 裸 YUV / rawvideo 字节流 | 有 | 无逐帧 PTS，尺寸格式需另外指定 |
| NUT 中的 rawvideo 视频流 | 有 | 有标准容器结构来描述 |

`container.start_encoding()` 这个名字容易误解。此处调用它是为了初始化输出并写容器头，可能伴随相关 codec context 初始化；**这不表示已经在做 H.264 压缩**。代码没有调用 `stream.encode(frame)` 来压缩这些像素。

**每一帧生成一个 rawvideo 包：**

```python
packet = av.Packet(pixels)
packet.stream = stream
packet.pts = packet.dts = pts
packet.time_base = tb
packet.duration = duration
packet.is_keyframe = True
container.mux(packet)
```

| 操作 | 作用 |
|---|---|
| `av.Packet(pixels)` | 创建携带这帧紧凑像素数据的视频包 |
| `packet.stream = stream` | 指定它属于哪个输出视频流 |
| 设置 `pts`、`dts` | 指定该 rawvideo 包的时间 |
| 设置 `time_base` | 指定这些整数的时间单位 |
| 设置 `duration` | 提供该帧持续时间信息 |
| `is_keyframe = True` | 表明这个原始视频包可独立解码 |
| `container.mux(packet)` | 由封装器生成标准 NUT 字节并写出 |

这里把每个 rawvideo 包标记为关键帧，**不会迫使最终 H.264 每帧都是 I 帧**。H.264 编码器会对收到的画面重新做帧型选择和帧间预测。

**赋值 PTS 和写出 PTS 是两步。** `packet.pts = pts` 只是修改 Python 绑定的底层包结构中的字段，此时下游 FFmpeg 还没有因为这句赋值收到任何时间戳；`container.mux(packet)` 才会让 NUT 封装器把包的时间信息转换成符合 NUT 规则的字节表示，接收端的 NUT 解复用器按同一规则恢复出包和时间戳。因此，**不能用“把 AVPacket 结构体直接 memcpy 到管道”替代 mux**：结构体中可能包含指针，而且布局依赖 ABI；容器格式才是跨进程、跨版本交换媒体数据的约定。

**Python 为什么不需要自己理解全部 NUT 字节格式？** 当前 Python 负责准备字段、调用 API。包头、时间戳编码、同步结构等具体格式，由 PyAV 背后的 FFmpeg NUT 封装器处理。这就是采用 Python/PyAV 的主要便利：无需在 Java 里实现并维护一套 NUT 写入器。

**NUT 不会让 1.5 GB 的像素变成几 MB。** 本例中 NUT 封装的仍是原始 YUV，数据量接近 YUV 总量，加上少量容器结构。它解决的是可解析的帧与时间信息传输。把视频压缩到最终大小的是后面的 libx264。因为 NUT 走管道而不是写文件，所以不需要为整个中间流准备同样大小的磁盘空间。

**为什么选择 NUT。** NUT 可以承载原始视频和时间戳，FFmpeg 有现成的读写支持，本方案已验证可通过不可寻址的管道使用。它不是唯一可选容器。其他容器需要考虑原始视频兼容性、时间精度、流式写入和接收端支持，不能只把 `-f nut` 改成另一个名字就认为具有相同表现。MP4 也不能笼统地说“不能用于管道”：碎片化 MP4 等模式可以流式写入。但对本次未压缩 YUV 的中间传输，当前 NUT 方案已经满足需求。

### 11.10 重复时间戳与帧持续时间

**样片的 PTS 并非全程等间隔。** 提供的 PTS 文件共 1084 项。相邻时间戳差值统计如下，单位为源时间基的 tick：

| 相邻差值 | 次数 |
|---:|---:|
| 33333 | 721 |
| 33334 | 359 |
| 32667 | 1 |
| 0 | 1 |
| 667 | 1 |

其中第 423、424 帧的 PTS 都是 `14066000`。仅依据视频看起来大约 30 fps，就按 `N / 30` 重建时间戳，会忽略这些实际信息。

**本实现如何处理重复值。** 代码保留画面，并做最小的整数时间修正：

```python
pts = original if last_output is None else max(original, last_output + 1)
```

对于样片：

```text
第 423 帧：14066000 → 14066000
第 424 帧：14066000 → 14066001
```

时间基为 `1/1000000`，所以改动是 1 微秒。这是一项明确的实现策略：为了给当前链路提供严格递增的显示时间，避免重复时间戳引起后续处理歧义，保留帧并微调时间。它不意味着所有容器和所有编码器在任何场景都绝对禁止重复 PTS。也不能称为“所有原 PTS 一字不改”。准确说法是：**输出匹配经过记录的最小修正时间线，样片只修正了一帧。** 连续重复时，会逐 tick 推进；如果紧接着的原始 PTS 被前面的修正追上，也会作同样的最小修正，并记录。

哪些情况报错、哪些情况修正，汇总表见 [7.4](#route-c)。若未来要支持负视频 PTS，需要设计音视频共同时间平移，以及容器对负时间的处理；只给视频加一个偏移会破坏它与原音轨的相对关系。

**为什么要缓存上一帧。** 收到当前帧后，可以知道上一帧应该持续多久：

```python
if pending is not None:
    mux(pending, pts - pending[0])
pending = (pts, pixels)
```

```text
收到 A，PTS=100000：先保存 A
收到 B，PTS=133333：给 A duration=33333，写出 A，保存 B
收到 C，PTS=200000：给 B duration=66667，写出 B，保存 C
```

这会带来一帧左右的等待，但不会要求先读取完整视频。

**末帧没有下一帧，怎么办？** 当前实现先按名义帧率估算末帧时长：

```python
duration = max(1, round(1 / rate / tb))
```

若原轨道提供起点和总时长，并且算出的剩余时长为正，就优先使用：

```text
末帧 duration = 原轨道 start_pts + duration_ts - 末帧 PTS
```

这些信息依赖源文件元数据，并非所有文件都一定准确。NUT、解码器、编码器和最终 MP4 也可能重新推导持续时间；设置中间 `packet.duration` 不等于保证最终每一帧 duration 都逐值照抄。因此，验证时同时检查输出逐帧显示时间和轨道结尾。样片最终视频时长为 36.066666 秒，符合预期。

### 11.11 本机 FFmpeg 如何接收和保留时间信息

当前命令的核心结构如下（省略按输入补充的色彩和像素比例参数）：

```bash
ffmpeg -hide_banner -nostdin -n -copyts \
  -f nut -i pipe:0 \
  -i input.mp4 \
  -map 0:v:0 -map '1:a:0?' \
  -c:v libx264 -crf 18 -preset fast \
  -fps_mode:v passthrough \
  -enc_time_base:v demux \
  -video_track_timescale 1000000 \
  -c:a copy -avoid_negative_ts disabled \
  -movflags +faststart output.mp4
```

上面的 `1000000` 是样片示例；程序实际从源时间基的分母取得，不是对所有文件写死。

| 参数 | 在本流程中的作用 |
|---|---|
| `-f nut -i pipe:0` | 把标准输入按 NUT 解复用，读到尺寸、格式及时间戳 |
| 第二个 `-i input.mp4` | 从原文件取得音频 |
| `-map 0:v:0` | 视频来自 NUT 输入 |
| `-map 1:a:0?` | 音频来自原文件第一条音轨，没有则跳过 |
| `-copyts` | 尽量保留输入时间信息，不默认把输入时间起点消掉 |
| `-fps_mode:v passthrough` | 不为了凑固定帧率而主动补帧或丢帧 |
| `-enc_time_base:v demux` | 编码时间基采用输入解复用器提供的时间基 |
| `-video_track_timescale` | 指定 MP4 视频轨时间刻度，保留所需时间精度 |
| `-c:a copy` | 复制音频压缩包，不重新编码音频 |
| `-avoid_negative_ts disabled` | 禁用这一层为了避免负时间而自动移动时间线的策略 |
| `-movflags +faststart` | 输出完成时把 MP4 索引移到前面，便于播放读取 |

- `-copyts` 不是独立的“保真开关”。输入是否正确传来时间戳、帧率同步策略、编码时间基和封装时间刻度都影响结果，必须一起检查。
- `-nostdin` 禁用的是 FFmpeg 从标准输入读取交互命令的机制，不会阻止显式指定的 `pipe:0` 媒体输入。
- 新流程不再需要手工指定输入 `-video_size`、`-pixel_format`、`-framerate 30`，因为 NUT 头携带了视频流描述。
- `-enc_time_base` 选择足够细的刻度很重要。如果采用 `1/30`，1 微秒的差异根本无法用整数 tick 表达，可能被量化掉。本方案还设置 MP4 视频时间刻度，以免封装时再次丢失需要的精度。

### 11.12 音视频为什么仍能对齐

视频来自 Java 解码后的时间线，音频来自原文件。如果两者都保留原来的时间坐标，它们的相对位置就保持不变。例如，原文件是：

```text
视频首帧：5.000 秒
音频起点：5.020 秒
```

音频应比视频晚 20 毫秒。保留两者的时间，或者统一减去 5 秒，都能保留这个关系。但如果只对视频执行：

```python
video_pts = video_pts - first_video_pts
```

同时原样复制音频，那么会变成：

```text
视频首帧：0.000 秒
音频起点：5.020 秒
```

原本 20 毫秒的偏移会被错误改成 5.020 秒。当前实现不单独减去视频首帧 PTS，并使用 `-copyts` 保留共同时间坐标。额外测试覆盖了非零起点下的音频时间及压缩包一致性。

**为什么 native FFmpeg 还打开一次 KVC 文件？** 它需要读取原音频。命令明确映射：

```text
输入 0 的视频 → 输出视频
输入 1 的音频 → 输出音频
```

本机 FFmpeg 无需解码输入 1 中的 KVC 视频，只需能够解析容器和读取 AAC 包。因此它可能仍提示输入 1 的 `kvc7` 视频编码未知，但整体转码可以成功。原文件会被两个不同组件读取：Android 库用于 KVC 解码，本机 FFmpeg 用于音频复制；Python 的 ffprobe 也会读取其轨道元数据。

**音频比视频略短是否就是不同步？** 不一定。样片视频为 36.066666 秒，音频为 36.060998 秒，存在几毫秒长度差。这与音频压缩帧粒度、轨道时长记录等有关，不能单凭总时长不完全相等认定同步失败。更直接的检查是：音视频起点、视频显示时间线、音频每包 PTS/DTS、结尾及必要时实际播放表现。

### 11.13 内存、背压、吞吐与压缩率

**累计经过 1.5 GB，不等于同时占用 1.5 GB。** 样片每帧 1,382,400 字节，总共 1084 帧，累计约 1.50 GB（算式见 [10.2](#data-transport)）。流式处理时，前面的帧被消费后，后面才继续生产。当前桥接代码保存上一帧和正在读取的当前帧，不建立存放整段视频的列表。

不过，“桥接层逻辑上保存相邻帧”不等于整个进程只有两帧内存：还包括 Python 的临时复制、PyAV 包、Java 行数组和缓冲、操作系统管道、解码器参考帧、x264 前视及参考帧等。**应把它理解为不会随视频长度线性积累完整 YUV，而不是一个已经测得的固定总内存上限。**

**背压怎样限制生产速度：**

```text
FFmpeg 编码变慢
   ↓
Python 写往 FFmpeg 的管道暂时写不进去
   ↓
Python 暂停读取 Java 的下一帧
   ↓
Java 写往 Python 的管道逐渐填满
   ↓
Java 的 write() 等待，解码循环暂停推进
```

这种由下游处理速度向上游传递的等待就是背压。操作系统管道有容量限制，当前程序没有在它们前面增加无限增长的内存队列。某次写入暂时阻塞不一定是死锁，也可能只是正常等待编码器消费；若下游异常退出，则应结合进程状态和错误日志判断。

**这是不是零拷贝？** 不是。至少存在以下数据转换或复制环节：

```text
模拟器内存 → Java byte[] → Java/系统管道缓冲
→ Python 字节对象 → PyAV 包/原生缓冲 → 另一根管道
→ 本机 FFmpeg
```

具体实现可能在某些环节复用内存，但整个链路没有建立跨 JVM、Python、FFmpeg 的共享帧缓冲。优化这类复制需要单独设计共享内存或原生接口，不能只把 Java 数组换成一个数字指针。

**能否按 PTS `sleep`，再继续输出裸 YUV？** 这样只能改变数据抵达速度，不能替代媒体时间戳。旧的 rawvideo 输入仍按照声明的帧率产生时间戳。线程调度、解码耗时和管道缓冲还会让实际到达时间产生抖动，并可能把本可快于实时完成的转码拖慢到实时。如果某种输入机制特意用墙钟生成时间戳，那也是另一种设计，记录的是到达时间，而不是当前需要保留的原视频显示时间。

**一帧一帧写入会不会影响帧间预测？** 不会因为“逐帧传输”本身失去帧间预测。编码器本来就是接收一帧一帧画面，然后在内部保存参考帧、做前视和选择 I/P/B 帧。NUT 中的每个 rawvideo 包可独立解码，与最终 libx264 是否使用帧间预测是不同层次。本次完整输出的编码日志包含：

```text
I 帧：12
P 帧：327
B 帧：745
合计：1084
```

这也直接表明最终 H.264 并非全 I 帧编码。

**最终文件为什么可能比 KVC 大很多？** 当前参数 `libx264 -crf 18 -preset fast` 以质量为目标，不承诺与原 KVC 相同码率或体积。编码算法、质量目标、编码速度设置、画面内容及原视频处理方式都会影响码率。桥接器增加的 NUT 字节不会直接成为最终 H.264 压缩码流。本次最终文件约 31.27 MB；这个大小不能单独证明管道妨碍了预测。调整压缩率属于编码参数选择，和“怎样正确传 PTS”是两个可以分别处理的问题。

### 11.14 完成、异常与资源释放

**正常完成的顺序：**

```text
Java 读到输入结束
  → 给解码器发送空包，取出缓存中的剩余帧
  → 发送所有帧记录
  → 发送总帧数完成记录
  → 关闭 Python stdin
Python
  → 核对完成计数和 EOF
  → 写出暂存的末帧
  → 关闭 NUT 输出
  → 关闭 FFmpeg stdin
FFmpeg
  → 排空编码器中的延迟帧
  → 完成 MP4 封装及 faststart
  → 返回退出码
Python
  → 检查 FFmpeg 退出码
  → 返回退出码
Java
  → 检查 Python 退出码
  → 关闭模拟器，打印 SUCCESS
```

“像素写完了”并不等于“输出 MP4 已经完成”。最后还可能有编码器缓存帧和容器尾部工作，因此必须等待退出结果。

**为什么 EOF 之外还需要完成记录？** 如果 Java 在发送了几帧后崩溃，Python 也会看到 EOF。仅把 EOF 当正常结束，就可能把半段视频误报为成功。当前协议要求明确的完成记录和正确帧数。缺记录、帧字节不足、计数不符都会失败。

**出错后可能留下什么？** 中途失败可能留下不完整的 MP4 和部分审计 CSV。当前程序不会把所有失败输出自动删除，也没有使用“临时输出成功后再原子改名”的发布机制。输出名已存在时会拒绝覆盖。重试时应根据日志确认失败原因，并选新的输出名，或自行处理上次失败文件。

Python 会在异常路径尝试结束 FFmpeg 子进程；Java 也会结束失败或未正常完成的桥接子进程。正常结束阶段配置了 120 秒等待，异常清理阶段先等待 5 秒，再按需要强制结束。这些等待限制不是完整视频任务的总时限。

**当前 Java 解码循环的边界。** 这次重点改动是传输和封装。现有解码器的 ABI 偏移、流索引选择等约定仍然存在。当前 `avcodec_send_packet()` 遇到负返回值会直接报错，没有实现所有解码器都适用的 `EAGAIN` 重试状态机。样片已经跑通，但不能仅凭这次验证把外壳称为可适配任意 FFmpeg 解码器的通用实现。

### 11.15 为什么选 Python，如何改成 Java

**Java 能直接做吗？** 能。Java 可以写任意二进制格式，也可以调用本机 FFmpeg 库。问题不是语言能力，而是需要有人承担以下工作：

```text
拿到像素与 PTS
  → 建立视频流描述
  → 构造携带时间戳的包
  → 按 NUT 标准封装
  → 把结果交给本机 FFmpeg
```

当前把中间几步交给 PyAV，是因为它已有可调用的封装接口，而且项目已经有可验证的 Python/PyAV 环境。

**三种实现方式对比：**

| 路线 | 中间封装由谁负责 | 主要代价 | 当前状态 |
|---|---|---|---|
| Java → Python/PyAV → NUT | PyAV 背后的本机 FFmpeg 库 | 多一个 Python 进程和环境 | 已实现、已验证 |
| Java → JavaCPP/JNI → NUT | Java 调用本机 FFmpeg 库 | 本机库依赖、指针生命周期、输出回调 | 仅讨论，尚未实现 |
| Java 自己写 NUT 字节 | Java 实现 NUT 写入器 | 需要维护正确的协议实现 | 仅讨论，尚未实现 |

第二条路线可以去掉 Python 进程和第一段自定义字节协议，但不会自动把整条链路变成零拷贝。模拟器像素仍需要进入宿主机封装器可用的内存；若最后仍使用独立 FFmpeg 进程，也还需要管道传输。第三条路线能够减少原生封装依赖，但要处理真实 NUT 格式中的头、包编码和校验等规则。**不能用当前 `KVCP0001` 的十几字节记录头冒充标准 NUT。**

**JavaCPP 调用的是哪套库？** 如果采用 JavaCPP/JNI，本段需要的是适合宿主机平台的本机库，例如 macOS arm64 FFmpeg 库。Android 的 ELF `.so` 已由 unidbg 运行；它与 macOS 本机库有不同的运行环境。模拟器里的 AVFrame 地址不能直接塞给宿主机 FFmpeg 的函数。也可以进一步研究通过 unidbg 调用 Android 库里的封装函数，但那会涉及该库是否提供相应 muxer、模拟环境中的 I/O 回调、更多 ABI 和模拟执行开销。本次没有实现这条路线。

**为什么不直接让 PyAV 编 H.264？** 技术上可以，也可以得到“Java 解码 → Python/PyAV 编码并封装”的另一种流程。这次选定的目标是继续使用本机 `ffmpeg` 可执行程序来编码，所以 Python 只做 NUT 封装。这样编码器选择、系统 FFmpeg 的构建能力和命令行参数都集中在最后一步。当前最后一步仍是 CPU libx264。若以后换成 VideoToolbox，需要另行修改编码参数并验证时间精度、质量和兼容性；KVC 解码部分不会因此自动变成硬件解码。

### 11.16 运行、调试与核对

运行与配置见 [第 7 章](#route-c)。核对命令（查看最终视频逐帧时间、轨道信息、音频包哈希）与独立桥接测试见 [第 13 章](#verification)。相关文件：

| 文件 | 作用 |
|---|---|
| [`src/main/java/xin/chunming/KvcProbe_ffmpeg.java`](src/main/java/xin/chunming/KvcProbe_ffmpeg.java) | 解码，读取 PTS，写自定义协议，管理 Python 子进程 |
| [`pts_bridge.py`](pts_bridge.py) | 读协议、校验及微调 PTS、封装 NUT、启动和等待本机 FFmpeg |
| [`requirements-pts.txt`](requirements-pts.txt) | 当前固定 `av==15.1.0` |
| [`run_pts.sh`](run_pts.sh) | 使用项目 Python 环境，编译并运行 Java |
| [`test_pts_bridge.py`](test_pts_bridge.py) | 不依赖 KVC 库的桥接集成测试 |

---

# Part IV　逆向笔记与验证

<a id="abi-notes"></a>

## 12. 逆向笔记：ABI、符号与原始库

### 12.1 已确认的解码接口

- `kvc7` 对应这份定制库中的 codec ID `0x30005`。
- FFmpeg 解码器名称为 `libkvc30dec`。
- 导出解码器对象为 `ff_libkvc30_decoder`。
- 常用导出 API 包括 `avcodec_find_decoder_by_name`、`avcodec_alloc_context3`、`avcodec_parameters_to_context`、`avcodec_open2`、`avcodec_send_packet` 和 `avcodec_receive_frame`。
- 还导出 `kvc30dec_create`、`kvc30dec_decode`、`kvc30dec_destroy` 等底层函数，但**当前工具并未直接调用它们**。

> [!WARNING]
> 底层函数名称与地址不等于已恢复的 C 头文件。底层参数、回调、输入输出结构及所有权规则尚未完整恢复，**不能猜测签名调用**。

### 12.2 格式映射表里的 5 个 KVC 标记

| 视频格式标记 | 这份库中的 codec ID |
|---|---|
| `kvc2` | `0x30001` |
| `kvc3` | `0x30002` |
| `kvc5` | `0x30004` |
| `kvc6` | `0x30006` |
| `kvc7` | `0x30005` |

（配置块标识 `kvLC` 的含义见 [9.4](#decode-internals)。）

### 12.3 定制结构体偏移

Java 与 C 两条路线都使用下列经反汇编及实际调用验证的布局：

| 对象 | 字节偏移 | 字段 |
|---|---:|---|
| `AVFormatContext` | 48 | `streams` 指针 |
| `AVStream` | 192 | `codecpar` 指针 |
| `AVCodecParameters` | 4 | `codec_id` |
| `AVPacket` | 36 | `stream_index` |
| `AVFrame` | 0 | `data` 指针数组，每个指针 8 字节 |
| `AVFrame` | 64 | `linesize` 数组，每个值 4 字节 |
| `AVFrame` | 112 | `width` |
| `AVFrame` | 116 | `height` |
| `AVFrame` | 124 | `format` |
| `AVFrame` | 144 | `pts`，64 位整数 |

偏移从对象起始地址计数，**仅针对附带的 ARM64 定制库**。上游 FFmpeg 的结构体布局不能直接套用。替换库后即便导出函数同名，也可能出现读取错误、崩溃或错误画面。

**这些数字是什么意思？** `fr` 是库返回的 AVFrame 对象在模拟内存中的地址。`ptr(fr).getInt(112)` 的含义是：从 `fr + 112` 的位置读取 4 字节整数，**不是读取第 112 个元素**：

| 相对 `fr` 的字节偏移 | 字段 | 读取方式 |
|---:|---|---|
| 112 | `width`，画面宽度 | `getInt`，4 字节 |
| 116 | `height`，画面高度 | `getInt`，4 字节 |
| 124 | `format`，像素格式枚举 | `getInt`，4 字节 |
| 144 | `pts`，显示时间戳 | `getLong`，8 字节 |

相当于原生 C 代码：

```c
int width  = frame->width;
int height = frame->height;
int format = frame->format;
int64_t pts = frame->pts;
```

但我们没有这份定制库的准确头文件，所以 Java 用地址和偏移直接读取。

**这些偏移当时怎么确认的？** 结合了原生库分析和实际解码时的内存检查。针对画面字段，关键证据是第一次解码成功后打印出来的内容：

```text
偏移 104：0
偏移 108：0
偏移 112：1280
偏移 116：720
偏移 120：0
偏移 124：0
```

最初按另一种布局读取，出现了 `width=0，height=0，format=720`，这明显是字段位置错了。检查附近内存后，把宽高定位到 112、116，像素格式定位到 124，再通过实际写出 YUV、查看画面及完整解码验证。144 处按 64 位读取的值，则通过逐帧时间戳与原视频时间线比对进行了验证。**不是仅凭“某个位置看起来像数字”就确定字段。**

**这些数能不能换库继续用？** 不能保证。结构体布局可能随 FFmpeg 版本、厂商修改、编译配置和 32/64 位架构改变。需要区分：

- `AVERROR_EOF`：FFmpeg 定义的错误常量（见下）。
- `112 / 116 / 124 / 144`：当前这份 ARM64 定制库的 ABI 布局，**不是通用 FFmpeg 常量**。
- `pts` 的单位：由时间基决定，不是因为用了 `getLong(144)` 就天然是微秒。当前工具按已验证样本的 `1/1000000` 时间基处理。

如果有完全匹配的 C 头文件，就可以用 `offsetof(AVFrame, width)` 等方式由编译器算偏移；目前这些硬编码值，是缺少准确头文件时采用的验证方案。

### 12.4 `-541478725` 是 `AVERROR_EOF`

FFmpeg 在头文件中定义（[官方定义](https://ffmpeg.org/doxygen/trunk/error_8h.html)）：

```c
#define AVERROR_EOF FFERRTAG('E', 'O', 'F', ' ')
```

将这四个字符按其规则组成整数再取负，得到：

```text
-0x20464F45 = -541478725
```

也就是“到达结束”。所以代码：

```java
if (r == -541478725) {
    drain = true;
}
```

表示输入包读完了，接下来让解码器输出内部剩余的帧。**不是看到负数就一定意味着视频损坏。** 可以命名以提高可读性：

```java
static final int AVERROR_EOF = -541478725;
```

### 12.5 原始库哈希与依赖

```text
libffmpeg.so
SHA256 5de90ece1c5ddc3d06cf056c2d0e48c2eda6d9d3c824f7a308c7e972932677d9

libc++_shared.so
SHA256 3085a29268980b9e898ffafc0655fa51d5cdb51c3142e99fcc57be4d2d9d6a28
```

检查：

```bash
shasum -a 256 lib/libffmpeg.so lib/libc++_shared.so
```

附带库依赖 `libm.so`、`libz.so`、`libc++_shared.so`、`libdl.so`、`libc.so`。unidbg 路线通过其 Android 兼容环境解析系统依赖；USB 路线使用真实手机系统环境。

### 12.6 有没有 KVC 编码器？

实际枚举到的已注册编码器：`libk264`、`libkrtc265`、`libfdk_aac`、`libopus`、`mjpeg`、`png`、`rawvideo`。其中 `libkrtc265` 的 codec ID 为 173，即 HEVC，不是 KVC7。

查询 `avcodec_find_encoder(0x30005)` **返回空**，没有找到可用的 KVC7 编码器。因此**本工具不能反向将普通视频压成 KVC7**。源码中存在通用编码函数，也不代表这个格式的编码实现已包含。

---

<a id="verification"></a>

## 13. 验证与测试结果

### 13.1 路线 A（unidbg）样本结果

| 项目 | 结果 |
|---|---|
| 解码帧数 | 1084 / 1084 |
| 尺寸 / 输出格式 | 1280×720 / YUV420P |
| 输出视频编码 | H.264 |
| 视频时长 | 36.066666 秒 |
| 原 AAC 音轨时长 | 36.060998 秒 |
| 重复 PTS 调整 | 1 帧、增加 1 微秒 |
| unidbg 解码和 YUV 写出 | 约 10.774 秒 |
| unidbg 路线完整转码 | 约 18.07 秒 |

解码计时在解码器打开后开始，包含后续读包、解码与原始画面写出，不包含环境加载、H.264 编码和音轨合并。完整转码计时从输入预检后开始。两项都是**本机单次样本测量，不是跨设备性能承诺**。

### 13.2 两条路线（A / B）的一致性

对 USB 路线和 unidbg 路线生成的 H.264 MP4，分别重新解码并生成 `framemd5`：**逐帧画面哈希和时间戳文本完全一致**。

这证明本样本两条转码路线的最终解码输出一致；**不是** KVC 原压缩数据和 H.264 文件逐字节相同，也不能将它解释为 CRF 18 转码没有损失。

### 13.3 路线 C（PTS 流式）样片验证

2026-11-04，使用项目 unidbg 0.9.9、Java 17、PyAV 15.1.0、本机 FFmpeg 9.0.1：

| 项目 | 结果 |
|---|---|
| 视频尺寸 / 帧数 | 1280×720 / 1084 |
| 源与输出视频时间基 | 1/1000000 |
| 输出显示 PTS | 与审计 CSV 的修正后 PTS **逐项一致** |
| 原始解码 PTS | Java 读取的 1084 个原 PTS 与提供的 PTS 文本完全一致 |
| 时间戳修正 | 仅 1 次：第 424 帧 +1 微秒 |
| 音频包数 | 779；逐包 SHA-256、PTS、DTS、duration 均与输入一致 |
| 视频时长 / 音频时长 | 36.066666 秒 / 36.060998 秒；两轨起点均为 0 |
| 最终文件大小 | 31,269,026 字节 |
| 编码帧型（libx264 日志） | I 帧 12 / P 帧 327 / B 帧 745，合计 1084 |
| 原输入文件 | 与验证前的副本 SHA-256 一致 |
| 耗时（记录一） | 约 13.7 秒（样片端到端转码，此次运行，不含 JVM 初始化） |
| 耗时（记录二） | 约 13.21 秒（项目入口实测，解码循环开始后计时，含桥接和等待编码完成，不含 Maven 编译、JVM 启动和解码器初始化） |

两条耗时记录来自不同口径 / 不同次运行，**是本机这次样片的观测值，不是所有视频的性能保证。**

这些结果证明了该样片的帧数、显示时间和音频包传递正确。最终 H.264 使用 CRF18 有损编码，因此**不能把它描述为相对原始解码像素的无损转码**。

### 13.4 核对命令

**检查输出视频：**

```bash
ffprobe -v error -count_frames \
  -show_entries stream=codec_name,width,height,duration,nb_read_frames:format=duration \
  -of json "output.mp4"
```

**完整视频解码检查：**

```bash
ffmpeg -v error -i "output.mp4" \
  -map 0:v:0 -fps_mode passthrough \
  -enc_time_base 1:1000000 -f null -
```

**单独检查音频：**

```bash
ffmpeg -v error -i "output.mp4" -map 0:a:0 -f null -
```

**比较两份输出：**

```bash
ffmpeg -n -v error -i "output-a.mp4" -map 0:v:0 \
  -fps_mode passthrough -enc_time_base 1:1000000 \
  -f framemd5 "a.framemd5"

ffmpeg -n -v error -i "output-b.mp4" -map 0:v:0 \
  -fps_mode passthrough -enc_time_base 1:1000000 \
  -f framemd5 "b.framemd5"

cmp "a.framemd5" "b.framemd5"
```

默认的低精度输出时间基可能把相距 1 微秒的帧舍入成相同 DTS，导致 null 输出检查报非递增时间戳。上面的命令显式保留微秒时间精度。

**查看最终视频的逐帧时间**（路线 C）：

```bash
ffprobe -v error -select_streams v:0 \
  -show_frames \
  -show_entries frame=pts,pts_time,duration \
  -of json output-pts.mp4
```

对视频使用 `-show_frames`，可以按解码后的显示帧核对。最终 H.264 含 B 帧时，若只按压缩包读取顺序逐项比较 PTS，容易把解码顺序与显示顺序混淆。

**检查轨道时间基和时长：**

```bash
ffprobe -v error \
  -show_entries stream=index,codec_name,time_base,start_time,duration,nb_frames \
  -of json output-pts.mp4
```

**检查音频包的内容和时间：**

```bash
ffprobe -v error -select_streams a:0 \
  -show_packets -show_data_hash sha256 \
  -show_entries packet=pts,dts,duration,data_hash \
  -of json output-pts.mp4
```

对原文件执行同一音频命令后，可以逐包比较。**只检查最终 MP4 文件哈希没有意义**，因为容器和视频编码都已经改变。

### 13.5 独立桥接测试

```bash
.venv/bin/python -m unittest -v test_pts_bridge.py
```

当前 5 个测试方法覆盖：

- 非零视频起点下，变帧间隔、重复 PTS 修正及音频包一致性。
- `1/90000` 时间基及没有音轨的输入。
- 缺少完成记录的异常断流不能当作成功。
- 真正倒退的 PTS 被拒绝。
- 已有输出文件不会被覆盖。

测试使用临时目录中的极小视频完成，**不需要运行 KVC 解码器，不会生成完整样片的 YUV**。

---

# Part V　开发、扩展与支持

<a id="build"></a>

## 14. 编译与修改

### 14.1 重新编译 Java 调用程序（路线 A）

运行不需要编译。只有修改 `unidbg/KvcProbe.java` 后，才需要 JDK 中的 `javac`：

```bash
javac --release 8 \
  -cp "unidbg/deps/*" \
  -d "unidbg/classes" \
  "unidbg/KvcProbe.java"
```

该命令使用工具包中的依赖，不需要 Maven。`--release 8` 指定生成类的 Java 语言 / API 目标，**不代表整个依赖组合已经在 Java 8 上通过运行测试**；实际使用 Java 17 验证。Java 源码与 class 是两份文件，修改 `.java` 而不重新编译不会改变实际运行行为。

> 路线 C 的 `KvcProbe_ffmpeg` 由 `./run_pts.sh` 自动编译（基于仓库根目录 `pom.xml`，需要 Maven）。

### 14.2 修改 Python 编码参数

两个 Python 脚本中的编码器设置为：

```python
stream.options = {"crf": "18", "preset": "fast"}
```

修改这些值会改变速度、体积和画质，**旧的输出哈希一致性结论不再自动适用**。若要更改编码格式，必须同时检查 PyAV 编码器可用性、像素格式和 MP4 封装支持。

路线 C 的编码参数位于传给本机 `ffmpeg` 的命令中（`-c:v libx264 -crf 18 -preset fast`，见 [11.11](#pts-deep-dive)）。

### 14.3 重新编译 Android C 外壳（仅路线 B）

只有 USB 路线需要这个程序。它不是 KVC 算法源码，仅通过 `dlopen` / `dlsym` 调用库。

原构建使用 Zig 的交叉编译驱动，并用同一手机的 Android `libc.so` / `libdl.so` 作为链接输入：

```bash
ZIG_GLOBAL_CACHE_DIR="$PWD/zig-cache" python3 -m ziglang cc \
  -target aarch64-linux-android -nostdlib -fno-sanitize=all \
  -fno-stack-protector -fno-builtin -fPIE -pie -Wl,-e,_start \
  -Wl,--dynamic-linker=/system/bin/linker64 \
  -L"/完整路径/phone-system-libs" \
  phone_decode.c -l:libc.so -l:libdl.so -o phone_decode
```

需要先安装提供 `python3 -m ziglang` 的工具，并准备链接库。系统链接库没有放进交付包；原来从手机 `/system/lib64` 读取。**普通使用无需执行这条命令**，因为包内已有可执行文件。

---

<a id="ffmpeg-integration"></a>

## 15. 接入自己的 FFmpeg

当前可用工具**不是**上游 `libavcodec` 插件，也不是 `--enable-libkvc` 一开就能编译的源码包。

### 接入方案一：独立进程桥接（最接近现有成果）

保留 Java/unidbg 进程，在它与主机 FFmpeg 之间传输画面、PTS 和媒体参数。

- 避免把 Android 定制 FFmpeg 与主机 FFmpeg 的同名符号混在一个地址空间。
- 可以从文件中转升级为管道，减少磁盘占用。
- 原始 rawvideo 管道不携带逐帧 PTS；还需要单独协议或带时间戳的合适封装。
- ✅ **更新（2026-11-04）：** 这一方案现已由路线 C 实现为“Java → KVCP0001 → Python/PyAV → NUT → 本机 FFmpeg”（见第 7、11 章）。**通用的管道输入模块或 FFmpeg 补丁仍未实现。**

### 接入方案二：恢复底层 KVC API，编写 wrapper

需要继续确认 `kvc30dec_*` 的函数签名、结构体、图像缓冲区归还、线程及 flush 等语义，再实现相应 FFmpeg 解码器和容器映射。

即使做完 wrapper，macOS 也不能因此直接加载 Android ELF 库，仍需兼容运行层或平台移植。

### 接入方案三：把解码算法恢复成可移植源码

这是另一项规模大得多的工作：反编译伪 C 不能自动变成正确、可编译、可维护的解码器。还需恢复类型、内部算法、SIMD、线程和平台依赖，并用更多码流验证。

**目前没有开展完整算法源码恢复。** 现有 C 文件不是这项工作的成果。

---

<a id="faq"></a>

## 16. 常见问题

### 16.1 报错与现象速查

| 问题 / 提示 | 解释与处理 |
|---|---|
| `No module named av` | 当前 Python 没有 PyAV；确认已激活虚拟环境，并用同一个 Python 安装和运行 |
| `java` / `ffmpeg` / `ffprobe` 找不到 | 检查 PATH；Java 可用 `--java` 指定，另外两个工具由 PATH 查找 |
| `Could not find or load main class KvcProbe` | class 文件或 classpath 不正确；保留目录结构，优先从 Python 入口运行 |
| `UnsatisfiedLinkError` / native 库加载失败 | 检查 Java / 主机架构和 JAR 完整性；不要只复制 Java 源文件而漏掉 native 后端依赖 |
| `No SLF4J providers were found` | 本次验证也出现过该日志提示，未阻止解码；不等同于 KVC 库加载失败 |
| `Verified prototype requires ...` | 输入不符合当前明确限制；不要仅删除检查后当作通用支持 |
| `Unexpected frame` | 解码返回的尺寸或像素格式不符合硬编码布局 |
| `no decoder` | 库不对或版本不同，找不到 `libkvc30dec` |
| `decoder open` 负值 | 需要排查库版本、输入配置、平台依赖与调用参数，不能仅凭数值判定文件损坏 |
| `Frame count/size verification failed` | 输出帧数、PTS 行数或 YUV 字节数不一致，工具会拒绝继续 |
| `TimeoutExpired` | Java 解码超过 300 秒；不保证其他机器或长视频能在这个时间内完成 |
| `No space left on device` | 本地路线需要保存整段原始画面，检查系统临时目录空间 |
| 输出文件已存在 | 换一个文件名；脚本默认不覆盖 |
| `nb_frames` 为 `N/A` 后报整数转换错误 | 当前原型只处理正常整数或缺失字段，未通用处理所有 ffprobe 输出情况 |
| `could not find codec parameters ... kvc7` | 原视频的 KVC 轨被系统 FFmpeg 探测时可能出现；仅合并原音轨阶段出现时，不等于 Java 解码失败，需结合最终退出状态判断 |
| 默认 null 检查报非递增 DTS | 使用 [13.4](#verification) 的微秒时间基检查，避免把相邻帧舍入到同一时间 |
| 手机上 `unauthorized` | 在手机确认 USB 调试授权，再用 `adb devices -l` 检查 |
| USB 路线 `Truncated frame` | 数据流中断或与预期布局不一致；保留手机端 `decode.log` 排查 |
| 想将标准 HEVC `.slice` 交给本工具 | 这不是分片还原工具。前面分析的 `.slice` 应先用独立的 `restore_slice.py` 拆封装 |
| 路线 C：`unknown codec kvc7` 提示 | 原文件第二个输入含 KVC 视频轨，只复制音频，实际视频来自 NUT，提示本身不代表失败（见 [7.5](#route-c)） |
| 路线 C：输出中途失败留下不完整 MP4 | 当前没有“成功后原子改名”机制；看日志确认原因，换输出名或手动删除失败文件（见 [11.14](#pts-deep-dive)） |

### 16.2 概念问答（Java / Python / NUT / PTS）

**Python 是不是又解码了一遍 KVC？**
没有。Python 收到的是解码后的像素。它调用 ffprobe 读取源轨道信息，并使用 PyAV 生成 NUT；私有 KVC 解码仍由 Java/unidbg 中的 Android 库执行。

**NUT 里放 rawvideo，FFmpeg 还会显示 rawvideo 解码，这是为什么？**
它需要把 rawvideo 包按宽高和像素格式解释成帧，供编码器使用。这不是重新执行 KVC 解码，也不是对像素再进行一次有损解压。

**能不能让 Java 输出标准 NUT，就去掉 Python？**
可以。必须在 Java 一侧增加真实的 NUT 封装实现，或者调用本机封装库。仅仅保留当前 `writeLong(pts)` 和像素写入逻辑，还不构成 NUT。

**能不能把 native 指针写到管道里？**
写一个指针数值只会传输这个整数，不会传输它指向的内存。JVM、Python、FFmpeg 以及模拟器的地址空间含义不同；需要明确的数据复制或专门的共享内存设计。

**PTS 到了 FFmpeg，还需要 `-fps_mode` 吗？**
需要明确输出时间策略。输入有时间戳，不代表后续默认同步策略一定不会补帧、丢帧或量化。当前使用 passthrough 并设置编码时间基，再通过输出检查确认结果。

**为什么不用 `-fps_mode vfr`？**
FFmpeg 的 `vfr` 策略可以为了避免相同时间戳而丢帧。当前选择在桥接层保留全部帧并记录最小时间修正，再使用 passthrough；这是与本任务目标一致的选择。

**Python 增加了一个进程，速度一定更慢吗？**
它增加了协议解析、复制和封装开销，但多个阶段也能并行工作。总体速度取决于最慢阶段和资源竞争。当前已经测得整条链路表现，不能只凭语言名称断言瓶颈。要继续优化应分别测量解码、桥接和编码耗时。

---

<a id="limitations"></a>

## 17. 已知限制与后续改进

### 17.1 通用限制

- 只验证了一个 KVC7 样本和一组原始库，不应扩展成“支持全部快手视频”的结论。
- 固定 1280×720（路线 A 入口检查）/ 固定尺寸偶数宽高（路线 C）、8-bit YUV420P、微秒时间基（路线 A）和第 0 轨视频；不支持分辨率中途变化、10-bit、其他像素布局。
- 结构体偏移硬编码（针对当前 ARM64 私有库的 ABI），没有运行前自动哈希白名单检查；手动核对 `symbols.txt` 很重要。`AVFrame + 144` 等偏移不能直接套用于其他版本。
- 多数 native 资源依赖短生命周期进程退出回收，并非适合长期驻留服务的资源管理实现。
- 输入预检、异常提示和环境发现仍较简洁；当前脚本是可复核的**验证原型**。

### 17.2 音视频与元数据

- 只复制首音轨，不处理多音轨选择、字幕、附件、旋转矩阵、完整色彩 / HDR 等旁数据。
- 路线 C 传递已声明的色彩范围、色彩空间等参数及非方形像素比例；未验证 HDR / 10-bit。
- 默认音频直接复制；若源音频不能装进 MP4，需要另外增加转码策略。
- 按当前完整文件转码路径估算末帧持续时间；不提供剪辑、seek、实时直播等完整时间轴处理。
- Java 子进程按帧数、字节数检查成功，不替代复杂码流的画质、色彩和音画同步验证。

### 17.3 解码与错误处理

- Java 在 EOF 后会 drain；但原型没有为所有 send/receive 背压和损坏输入设计完整恢复策略；当前 `avcodec_send_packet()` 遇到负返回值直接报错，没有实现 `EAGAIN` 重试状态机。
- C 路线将读取负返回值统一视为结束并 drain，未完整区分各种 I/O 错误。
- 视频 PTS 缺失、为负或真正倒退时（路线 C）失败。

### 17.4 并发、规模与流程

- USB 路线固定手机目录，不支持并发；本地路线的独立临时目录也不等于已经做过多实例资源压力测试。
- 未实现 seek、批处理、进度百分比、断点续跑。
- 路线 C 中间流不落盘，但最终 MP4、可选 CSV、测试日志和运行环境文件仍会写磁盘；不包含网络 RPC，也不是零拷贝；编码仍是本机 CPU libx264。
- 路线 C 的管道协议不是自描述的通用视频协议：时间基、色彩参数等依赖同一个原文件（见 [11.7](#pts-deep-dive)）。

### 17.5 后续改进方向

若继续工程化，优先事项是：**动态获取媒体参数、去掉固定轨道假设、统一帧传输协议、完善错误与资源处理**，然后再考虑 FFmpeg 集成（[第 15 章](#ffmpeg-integration)）。

---

<a id="license"></a>

## 18. 来源、许可与致谢

### 18.1 来源与许可

- unidbg 上游：[zhkl0228/unidbg](https://github.com/zhkl0228/unidbg)。
- 本次源码 commit：`e0d88a900ae9d197c325af8d6a5875ee9958b724`。
- 本地构建去除了与验证无关的源码包、文档、签名及发布插件，没有修改模拟器执行代码。
- unidbg 的 Apache 2.0 许可见 `unidbg/LICENSE-unidbg`；第三方依赖保留各 JAR 内的许可信息。
- `lib/` 中的 Android 库来自用户提供的设备，其来源和许可与 unidbg 不同。**包含这些二进制不意味着它们自动适用 Apache 2.0，也不意味着已取得可移植的 KVC 源码。**
- 原始视频未打包在工具包中。此工具包保留调用源码、预编译运行组件及验证记录，便于复核和后续研究。

### 18.2 参考资料

本 README 的协议、参数和结果以当前项目源码及本机验证为依据。以下官方资料用于解释相关通用概念，不是 KVC 私有格式规范：

- [FFmpeg 命令文档](https://ffmpeg.org/ffmpeg.html)：`copyts`、`fps_mode`、`enc_time_base` 等参数。
- [FFmpeg 格式文档](https://ffmpeg.org/ffmpeg-formats.html)：rawvideo、NUT、MP4 的输入输出约定。
- [FFmpeg NUT 文档](https://ffmpeg.org/nut.html)：NUT 和 rawvideo 等媒体类型的相关说明。
- [PyAV 时间说明](https://pyav.org/docs/stable/api/time.html)：时间整数、time_base 及时间基换算。该页面显示较旧版本的文档，具体行为以本项目验证的 PyAV 15.1.0 为准。
- [PyAV 容器接口](https://pyav.org/docs/stable/api/container.html)：创建输出流和 mux 等接口。

### 18.3 项目源码

- [Java 解码与发送代码：`KvcProbe_ffmpeg.java`](src/main/java/xin/chunming/KvcProbe_ffmpeg.java)
- [Python 桥接代码：`pts_bridge.py`](pts_bridge.py)
- [桥接测试：`test_pts_bridge.py`](test_pts_bridge.py)
- [运行脚本：`run_pts.sh`](run_pts.sh)

### 18.4 致谢

感谢 ChatGPT。感谢 [unidbg](https://github.com/zhkl0228/unidbg)。
