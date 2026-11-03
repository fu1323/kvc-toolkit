# KVC Toolkit：KVC7 视频解码与转码验证工具

> 文档更新：2026-11-03。
>
> 本工具已对提供的 KVC7 样本完成端到端验证，支持在 Apple Silicon Mac 上通过 **Java / unidbg 执行原 Android 解码库**，将视频转为普通 H.264 MP4。也保留了先前的 USB 安卓解码方案。
>
> 这是针对特定库和样本规格的验证工具，不是通用视频转换器。请先阅读输入限制，尤其不要随意替换附带 `.so`。

## 目录

1. [这个工具到底做了什么](#1-这个工具到底做了什么)
2. [两种运行路线](#2-两种运行路线)
3. [目录和文件作用](#3-目录和文件作用)
4. [已验证环境及输入限制](#4-已验证环境及输入限制)
5. [推荐使用：Mac 本地 unidbg](#5-推荐使用mac-本地-unidbg)
6. [Java 解码器的工作流程](#6-java-解码器的工作流程)
7. [单独运行 Java：保留原始画面](#7-单独运行-java保留原始画面)
8. [备用方案：USB 安卓解码](#8-备用方案usb-安卓解码)
9. [时间戳、音轨与画质](#9-时间戳音轨与画质)
10. [测试结果及复核](#10-测试结果及复核)
11. [ABI、符号和库版本](#11-abi符号和库版本)
12. [编译与修改](#12-编译与修改)
13. [接入自己的 FFmpeg](#13-接入自己的-ffmpeg)
14. [常见问题](#14-常见问题)
15. [已知限制与后续改进](#15-已知限制与后续改进)
16. [来源与许可说明](#16-来源与许可说明)

## 1. 这个工具到底做了什么

原视频虽然使用 MP4 容器，但视频轨的 FourCC 是 `kvc7`，配置块是 `kvLC`，普通 FFmpeg 无法直接识别对应的私有解码器。

我们从用户自己的安卓手机提取了 ARM64 版本的 `libffmpeg.so`。这份库内含能解该样本的 KVC 实现，并暴露了一套可调用的 FFmpeg API。工具复用这个实现，而不是重新实现编码标准。

### 最容易混淆的四件事

| 问题 | 答案 |
|---|---|
| 是否把 KVC 算法反编译成了 C？ | **没有。** 真正的解码算法仍是原 `.so` 中的 ARM64 机器码 |
| `phone_decode.c` 是什么？ | 在安卓手机运行的调用外壳，不是 KVC 算法源码 |
| unidbg 不是 Java 吗？ | 是。`KvcProbe.java` 用 unidbg 模拟 Android 环境，加载并执行原 `.so` |
| 是否已经给上游 FFmpeg 打了补丁？ | 没有。当前是一个独立解码与转码工具 |

同样是 ARM64 指令集，也不代表 Android ELF 动态库能由 macOS 的原生程序直接 `dlopen`：二者的文件格式、动态链接器、系统调用及运行库环境不同。本工具使用 unidbg 解决运行环境问题。

## 2. 两种运行路线

### 路线 A：Mac 本地 unidbg，推荐

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

### 路线 B：USB 安卓解码，备用

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

两条路线都复用同一份原始 ARM64 解码库。区别是它在真实 Android 环境执行，还是在 Mac 的 unidbg 环境执行。

| 项目 | 路线 A：unidbg | 路线 B：USB |
|---|---|---|
| 主脚本 | `transcode_unidbg.py` | `transcode.py` |
| 解码控制程序 | Java | C 编译的 ARM64 可执行文件 |
| Java | 需要 | 不需要 |
| 手机／adb | 不需要 | 需要 |
| 解码运行位置 | Mac 的模拟环境 | 安卓手机 |
| 原始画面存储 | Mac 临时文件 | 经 USB 流式传输，不保存整段手机 YUV |
| 本次验证状态 | 完整通过 | 完整通过 |

## 3. 目录和文件作用

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
   ├─ validation.json          unidbg 路线输出的媒体信息
   ├─ verification.txt         耗时和逐帧比较结论
   └─ LICENSE-unidbg
```

`phone_decode` 是安卓程序，不能在 Mac 终端直接运行。`libffmpeg.so` 也不是可以替换 Homebrew FFmpeg 的 macOS 库。

运行预编译的 unidbg 版本不需要 Maven、不需要 Zig、不需要 Android NDK，也不需要用户再下载 APK。需要 Java、Python/PyAV，以及电脑上的 ffmpeg/ffprobe。

## 4. 已验证环境及输入限制

### 本次实际环境

| 组件 | 验证版本／配置 |
|---|---|
| 电脑 | Apple Silicon Mac，ARM64 |
| Java | Temurin 17.0.20.1，ARM64 |
| Python | 3.9.6 |
| PyAV | 15.1.0 |
| 命令行 FFmpeg | 9.0.1 |
| unidbg | `0.9.10-SNAPSHOT`，指定源码 commit 见文末 |
| 实际执行后端 | `DynarmicBackend64` |
| Android 兼容库解析 | `AndroidResolver(23)` |

这些是已验证版本，不是已证明的最低版本。没有验证 Intel Mac、Windows、Linux 或其他 Java/PyAV 组合的端到端兼容性。虽然依赖中可能包含其他平台组件，不代表本工具已在这些平台测试。

### 输入要求

Python 入口会检查：

- 首个视频轨 `codec_tag_string == kvc7`。
- 分辨率为 **1280×720**。
- 时间基为 **1/1000000**。

Java/C 端还依赖：

- 视频实际位于容器的 **第 0 条轨道**。Python 的首视频轨检查不等于这个条件已被自动验证。
- 解码输出为 **8-bit YUV420P**，附带库中像素格式值为 0。
- 视频使用该定制库可以解码的格式与配置。

当前的尺寸、格式和时间基限制是原型实现的边界，不是对 KVC 编码能力的推断。改掉一个尺寸检查并不足以安全支持 1080p、10-bit 或其他时间基。

## 5. 推荐使用：Mac 本地 unidbg

以下命令假设已经进入解压后的 `kvc-toolkit` 目录。

### 5.1 检查已有工具

```sh
uname -m
java -version
python3 --version
ffmpeg -version
ffprobe -version
```

本次验证的机器 `uname -m` 为 `arm64`。建议同时使用 ARM64 Java，避免无意中混用 Rosetta 的 x86_64 运行环境。

macOS 上可列出已安装 JDK：

```sh
/usr/libexec/java_home -V
```

如果系统缺少 Java 或 FFmpeg，需先安装。以下步骤不会代替系统软件安装。

### 5.2 创建独立 Python 环境

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "av==15.1.0"
```

固定 PyAV 15.1.0 是为了接近本次测试环境，不是保证其他版本不能运行。包管理器能否提供适合当前 Python 和系统的安装包取决于其支持范围。

检查导入与 H.264 编码器：

```sh
python -c 'import av; print(av.__version__); print(av.codec.Codec("libx264", "w"))'
```

**注意：PyAV 使用的 FFmpeg 库与命令行 `ffmpeg` 可能不是同一套。** 视频编码由 Python 进程中的 PyAV/libx264 完成；最后合并音轨才调用系统 `ffmpeg`。因此命令行能编码 H.264，不一定证明某个自定义 PyAV 构建也带 libx264。

### 5.3 执行转码

```sh
python transcode_unidbg.py \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

指定 Java：

```sh
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

输出文件已经存在时拒绝覆盖。没有 `--force`、`--crf`、`--threads`、`--backend` 或通用尺寸参数；不要把这些当作现成选项。

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

`codec=30005` 是十六进制输出，即 `0x30005`，不要当成十进制 30005。

最后的 `Completed` 表示 Java 解码、帧数／文件大小核验、H.264 编码与音轨合并均已完成。仅看到 `decoder open=0` 不代表视频已完整解码。

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
     ≈ 1.50 GB（十进制）／1.40 GiB
```

还要额外容纳编码后视频和模拟环境文件，建议至少留出 2 GB 可用临时空间。该估算只针对当前 36 秒样本。

Java 堆上限设置为 `-Xmx2g`，但模拟器还有堆外／native 内存，所以这不是整个进程总内存上限。Java 解码子进程超时为 300 秒；这不是整个转码流程的统一超时。

正常结束及普通 Python 异常退出会尝试删除临时目录；强制杀进程、断电或清理失败可能留下文件。最终输出若在合并阶段中断，也可能留下不完整文件。主脚本不提供保留临时目录选项，需要检查原始画面时使用下一节的 Java 命令。

## 6. Java 解码器的工作流程

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

本次没有调用 JNI_OnLoad，没有创建快手登录环境，也没有模拟快手的 Java 业务类。我们调用的是库导出的 native 函数，不是 App 的 Java 播放接口。

线程设置：

```c
av_opt_set_int(ctx, "threads", 1, 0);
av_opt_set(ctx, "kvc30_params", ":kvc30DecodeThreads=1", 1);
```

第二个调用最后的 1 对应搜索子对象选项。两个调用在实际测试中均返回 0。设置目的在于减少模拟环境中的并发复杂度；并不等于已经证明库内部完全不会创建任何线程。

## 7. 单独运行 Java：保留原始画面

这种方式只解码，不调用 Python/PyAV 编码，也不生成含音频的 MP4。适合检查首帧、核验原始 YUV、研究接口。

在工具包根目录执行：

```sh
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

**直接 Java 入口会覆盖同名 YUV 和 PTS 文件**，与 Python 入口拒绝覆盖最终 MP4 的行为不同。它也没有 Python 外层的 300 秒超时。示例明确传入两个 `-D` 属性及全部参数，避免触发源码中为原开发工作区保留的默认路径。

查看首帧：

```sh
ffmpeg -n \
  -f rawvideo -pixel_format yuv420p -video_size 1280x720 \
  -i "work/first.yuv" \
  -frames:v 1 "work/first.png"
```

原始 YUV 不包含宽高、像素格式、音频或时间戳，所以必须手动指定尺寸和格式。`pts.txt` 才是对应时间线；不能把 YUV 按固定 30fps 重编码后就认为精确保留了原始时间戳。

## 8. 备用方案：USB 安卓解码

### 8.1 条件

- 支持 ARM64 的 Android 手机。
- 已启用 USB 调试，并授权当前电脑。
- 电脑有 adb、Python/PyAV、ffmpeg、ffprobe。

库提取时使用了手机 root 权限，但已提取库后的独立解码程序在普通 adb shell 权限下运行成功。当前脚本本身不调用 `su`，不修改快手应用。

### 8.2 使用

```sh
adb devices -l
python transcode.py \
  --serial "设备序列号" \
  "/完整路径/input.mp4" \
  "/完整路径/output.mp4"
```

adb 不在 PATH 时：

```sh
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

脚本不会自动删除这些手机侧文件。复用该目录会覆盖之前的输入、库与日志，不要同时运行多个 USB 转码实例。

### 8.3 手机到电脑的数据协议

C 程序输出的不是 MP4 或 FLV，而是一串自定义记录：

```text
帧 0：8 字节小端有符号 PTS + Y 平面 + U 平面 + V 平面
帧 1：8 字节小端有符号 PTS + Y 平面 + U 平面 + V 平面
...
```

- PTS 在本样本中以微秒为单位。
- YUV 为紧密排列的 8-bit YUV420P，没有行尾填充。
- 每帧画面 1,382,400 字节；加时间戳后每条记录 1,382,408 字节。
- 诊断信息必须与二进制画面流分开，否则文本会被当成 PTS 或像素数据。

当前脚本用手机端 shell 将 stderr 重定向到 `decode.log`，再通过 `adb exec-out` 接收画面。不要直接删掉重定向后将混合日志的输出喂给编码器。

## 9. 时间戳、音轨与画质

### 9.1 不是无损转封装

KVC 压缩包先解码为原始画面，再编码为 H.264：

```text
KVC7 → YUV420P → libx264 CRF 18 / preset fast → H.264
```

默认 H.264 编码属于有损编码。CRF 18 不代表数学无损。脚本没有命令行画质选项，相关设置写在 Python 源码的 `stream.options` 中。

音频直接复制原文件第一个音频轨，没有重新压缩。本次原音轨为 AAC。其他音频编码能否直接封装进 MP4，需要另行确认。

### 9.2 PTS 处理

每帧使用解码器返回的 PTS，编码时间基设置为 `1/1000000`。虽然创建编码流时传了 `rate=30`，代码仍明确为各帧设置 PTS，不是简单按帧编号全部重建为等间隔 30fps。

源样本有一个重复显示时间戳：`14066000` 微秒。为了兼容输出封装，后一帧被调到 `14066001` 微秒，所有画面均保留。

通用处理规则是：

```python
if last_pts is not None and pts <= last_pts:
    pts = last_pts + 1
```

本次仅发生一次调整。对于严重倒退、缺失或不同时间基的时间戳，这条规则不是完整的时间线修复算法；不要把它当作任意坏文件的自动音画同步方案。

### 9.3 元数据范围

当前主要传递像素和 PTS，没有完整复制原始色彩空间、色彩范围、HDR 信息、旋转、字幕、章节及其他旁数据。只选择新视频和原始首音轨。不要假定所有 MP4 元数据、附加音轨或显示语义都被保留。

## 10. 测试结果及复核

### 10.1 样本结果

| 项目 | 结果 |
|---|---|
| 解码帧数 | 1084 / 1084 |
| 尺寸／输出格式 | 1280×720 / YUV420P |
| 输出视频编码 | H.264 |
| 视频时长 | 36.066666 秒 |
| 原 AAC 音轨时长 | 36.060998 秒 |
| 重复 PTS 调整 | 1 帧、增加 1 微秒 |
| unidbg 解码和 YUV 写出 | 约 10.774 秒 |
| unidbg 路线完整转码 | 约 18.07 秒 |

解码计时在解码器打开后开始，包含后续读包、解码与原始画面写出，不包含环境加载、H.264 编码和音轨合并。完整转码计时从输入预检后开始。两项都是本机单次样本测量，不是跨设备性能承诺。

### 10.2 两条路线的一致性

对 USB 路线和 unidbg 路线生成的 H.264 MP4，分别重新解码并生成 `framemd5`：逐帧画面哈希和时间戳文本完全一致。

这证明本样本两条转码路线的最终解码输出一致；不是 KVC 原压缩数据和 H.264 文件逐字节相同，也不能将它解释为 CRF 18 转码没有损失。

### 10.3 验证输出

```sh
ffprobe -v error -count_frames \
  -show_entries stream=codec_name,width,height,duration,nb_read_frames:format=duration \
  -of json "output.mp4"
```

完整视频解码检查：

```sh
ffmpeg -v error -i "output.mp4" \
  -map 0:v:0 -fps_mode passthrough \
  -enc_time_base 1:1000000 -f null -
```

单独检查音频：

```sh
ffmpeg -v error -i "output.mp4" -map 0:a:0 -f null -
```

如要比较两份输出：

```sh
ffmpeg -n -v error -i "output-a.mp4" -map 0:v:0 \
  -fps_mode passthrough -enc_time_base 1:1000000 \
  -f framemd5 "a.framemd5"

ffmpeg -n -v error -i "output-b.mp4" -map 0:v:0 \
  -fps_mode passthrough -enc_time_base 1:1000000 \
  -f framemd5 "b.framemd5"

cmp "a.framemd5" "b.framemd5"
```

默认的低精度输出时间基可能把相距 1 微秒的帧舍入成相同 DTS，导致 null 输出检查报非递增时间戳。上面的命令显式保留微秒时间精度。

## 11. ABI、符号和库版本

### 11.1 已确认的解码接口

- `kvc7` 对应这份定制库中的 codec ID `0x30005`。
- FFmpeg 解码器名称为 `libkvc30dec`。
- 导出解码器对象为 `ff_libkvc30_decoder`。
- 常用导出 API 包括 `avcodec_find_decoder_by_name`、`avcodec_alloc_context3`、`avcodec_parameters_to_context`、`avcodec_open2`、`avcodec_send_packet` 和 `avcodec_receive_frame`。
- 还导出 `kvc30dec_create`、`kvc30dec_decode`、`kvc30dec_destroy` 等底层函数，但当前工具并未直接调用它们。

底层函数名称与地址不等于已恢复的 C 头文件。底层参数、回调、输入输出结构及所有权规则尚未完整恢复，不能猜测签名调用。

### 11.2 定制结构体偏移

Java 与 C 两条路线都使用下列经反汇编及实际调用验证的布局：

| 对象 | 字节偏移 | 字段 |
|---|---:|---|
| AVFormatContext | 48 | streams 指针 |
| AVStream | 192 | codecpar 指针 |
| AVCodecParameters | 4 | codec_id |
| AVPacket | 36 | stream_index |
| AVFrame | 0 | data 指针数组，每个指针 8 字节 |
| AVFrame | 64 | linesize 数组，每个值 4 字节 |
| AVFrame | 112 | width |
| AVFrame | 116 | height |
| AVFrame | 124 | format |
| AVFrame | 144 | pts，64 位整数 |

偏移从对象起始地址计数，仅针对附带的 ARM64 定制库。上游 FFmpeg 的结构体布局不能直接套用。替换库后即便导出函数同名，也可能出现读取错误、崩溃或错误画面。

### 11.3 原始库哈希

```text
libffmpeg.so
SHA256 5de90ece1c5ddc3d06cf056c2d0e48c2eda6d9d3c824f7a308c7e972932677d9

libc++_shared.so
SHA256 3085a29268980b9e898ffafc0655fa51d5cdb51c3142e99fcc57be4d2d9d6a28
```

检查：

```sh
shasum -a 256 lib/libffmpeg.so lib/libc++_shared.so
```

附带库依赖 `libm.so`、`libz.so`、`libc++_shared.so`、`libdl.so`、`libc.so`。unidbg 路线通过其 Android 兼容环境解析系统依赖；USB 路线使用真实手机系统环境。

### 11.4 有没有 KVC 编码器？

实际枚举到的已注册编码器：`libk264`、`libkrtc265`、`libfdk_aac`、`libopus`、`mjpeg`、`png`、`rawvideo`。其中 `libkrtc265` 的 codec ID 为 173，即 HEVC，不是 KVC7。

查询 `avcodec_find_encoder(0x30005)` 返回空，没有找到可用的 KVC7 编码器。因此本工具不能反向将普通视频压成 KVC7。源码中存在通用编码函数，也不代表这个格式的编码实现已包含。

## 12. 编译与修改

### 12.1 重新编译 Java 调用程序

运行不需要编译。只有修改 `unidbg/KvcProbe.java` 后，才需要 JDK 中的 `javac`：

```sh
javac --release 8 \
  -cp "unidbg/deps/*" \
  -d "unidbg/classes" \
  "unidbg/KvcProbe.java"
```

该命令使用工具包中的依赖，不需要 Maven。`--release 8` 指定生成类的 Java 语言/API 目标，不代表整个依赖组合已经在 Java 8 上通过运行测试；实际使用 Java 17 验证。

Java 源码与 class 是两份文件，修改 `.java` 而不重新编译不会改变实际运行行为。

### 12.2 修改 Python 编码参数

两个 Python 脚本中的编码器设置为：

```python
stream.options = {"crf": "18", "preset": "fast"}
```

修改这些值会改变速度、体积和画质，旧的输出哈希一致性结论不再自动适用。若要更改编码格式，必须同时检查 PyAV 编码器可用性、像素格式和 MP4 封装支持。

### 12.3 重新编译 Android C 外壳

只有 USB 路线需要这个程序。它不是 KVC 算法源码，仅通过 `dlopen` / `dlsym` 调用库。

原构建使用 Zig 的交叉编译驱动，并用同一手机的 Android `libc.so` / `libdl.so` 作为链接输入：

```sh
ZIG_GLOBAL_CACHE_DIR="$PWD/zig-cache" python3 -m ziglang cc \
  -target aarch64-linux-android -nostdlib -fno-sanitize=all \
  -fno-stack-protector -fno-builtin -fPIE -pie -Wl,-e,_start \
  -Wl,--dynamic-linker=/system/bin/linker64 \
  -L"/完整路径/phone-system-libs" \
  phone_decode.c -l:libc.so -l:libdl.so -o phone_decode
```

需要先安装提供 `python3 -m ziglang` 的工具，并准备链接库。系统链接库没有放进交付包；原来从手机 `/system/lib64` 读取。普通使用无需执行这条命令，因为包内已有可执行文件。

## 13. 接入自己的 FFmpeg

当前可用工具不是上游 `libavcodec` 插件，也不是 `--enable-libkvc` 一开就能编译的源码包。

### 路径 A：独立进程桥接

最接近现有成果的方案是保留 Java/unidbg 进程，在它与主机 FFmpeg 之间传输画面、PTS 和媒体参数。

- 避免把 Android 定制 FFmpeg 与主机 FFmpeg 的同名符号混在一个地址空间。
- 可以从文件中转升级为管道，减少磁盘占用。
- 原始 rawvideo 管道不携带逐帧 PTS；还需要单独协议或带时间戳的合适封装。
- 当前 Java 输出的是 YUV 文件和 PTS 文件，**尚未实现通用管道输入模块或 FFmpeg 补丁**。

### 路径 B：恢复底层 KVC API，编写 wrapper

需要继续确认 `kvc30dec_*` 的函数签名、结构体、图像缓冲区归还、线程及 flush 等语义，再实现相应 FFmpeg 解码器和容器映射。

即使做完 wrapper，macOS 也不能因此直接加载 Android ELF 库，仍需兼容运行层或平台移植。

### 路径 C：把解码算法恢复成可移植源码

这是另一项规模大得多的工作：反编译伪 C 不能自动变成正确、可编译、可维护的解码器。还需恢复类型、内部算法、SIMD、线程和平台依赖，并用更多码流验证。

目前没有开展完整算法源码恢复。现有 C 文件不是这项工作的成果。

## 14. 常见问题

| 问题／提示 | 解释与处理 |
|---|---|
| `No module named av` | 当前 Python 没有 PyAV；确认已激活虚拟环境，并用同一个 Python 安装和运行 |
| `java` / `ffmpeg` / `ffprobe` 找不到 | 检查 PATH；Java 可用 `--java` 指定，另外两个工具由 PATH 查找 |
| `Could not find or load main class KvcProbe` | class 文件或 classpath 不正确；保留目录结构，优先从 Python 入口运行 |
| `UnsatisfiedLinkError` / native 库加载失败 | 检查 Java/主机架构和 JAR 完整性；不要只复制 Java 源文件而漏掉 native 后端依赖 |
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
| 默认 null 检查报非递增 DTS | 使用第 10 节的微秒时间基检查，避免把相邻帧舍入到同一时间 |
| 手机上 `unauthorized` | 在手机确认 USB 调试授权，再用 `adb devices -l` 检查 |
| USB 路线 `Truncated frame` | 数据流中断或与预期布局不一致；保留手机端 `decode.log` 排查 |
| 想将标准 HEVC `.slice` 交给本工具 | 这不是分片还原工具。前面分析的 `.slice` 应先用独立的 `restore_slice.py` 拆封装 |

## 15. 已知限制与后续改进

- 只验证了一个 KVC7 样本和一组原始库，不应扩展成“支持全部快手视频”的结论。
- 固定 1280×720、YUV420P、微秒时间基和第 0 轨视频；不支持分辨率中途变化、10-bit、其他像素布局。
- 只复制首音轨，不处理多音轨选择、字幕、完整色彩/HDR/旋转等旁数据。
- 结构体偏移硬编码，没有运行前自动哈希白名单检查；手动核对 `symbols.txt` 很重要。
- Java 子进程按帧数、字节数检查成功，不替代复杂码流的画质、色彩和音画同步验证。
- Java 在 EOF 后会 drain；但原型没有为所有 send/receive 背压和损坏输入设计完整恢复策略。
- C 路线将读取负返回值统一视为结束并 drain，未完整区分各种 I/O 错误。
- 多数 native 资源依赖短生命周期进程退出回收，并非适合长期驻留服务的资源管理实现。
- USB 路线固定手机目录，不支持并发；本地路线的独立临时目录也不等于已经做过多实例资源压力测试。
- 未实现 seek、批处理、进度百分比、断点续跑或流式 Java→FFmpeg 管道。
- 输入预检、异常提示和环境发现仍较简洁；当前脚本是可复核的验证原型。

若继续工程化，优先事项是动态获取媒体参数、去掉固定轨道假设、统一帧传输协议、完善错误与资源处理，然后再考虑 FFmpeg 集成。

## 16. 来源与许可说明

- unidbg 上游：[zhkl0228/unidbg](https://github.com/zhkl0228/unidbg)。
- 本次源码 commit：`e0d88a900ae9d197c325af8d6a5875ee9958b724`。
- 本地构建去除了与验证无关的源码包、文档、签名及发布插件，没有修改模拟器执行代码。
- unidbg 的 Apache 2.0 许可见 `unidbg/LICENSE-unidbg`；第三方依赖保留各 JAR 内的许可信息。
- `lib/` 中的 Android 库来自用户提供的设备，其来源和许可与 unidbg 不同。包含这些二进制不意味着它们自动适用 Apache 2.0，也不意味着已取得可移植的 KVC 源码。
- 原始视频未打包在工具包中。此工具包保留调用源码、预编译运行组件及验证记录，便于复核和后续研究。
# KVC 解码后的内存传输、原生 FFmpeg 编码与 RPC

> 本文整理自“5.5 MB 的 KVC 解码成约 1.5 GB YUV，能否放内存并交给本机原生 FFmpeg 编码”开始的讨论，涵盖内存缓冲、进程管道、Java/unidbg 与原生 FFmpeg 的通信，以及 RPC 的使用场景。
>
> 本文是原理和架构说明，不是新功能实现。已有工具实际验证的是先由 unidbg 写出 YUV 与 PTS 文件，再编码；本文讨论的管道、共享内存及 RPC 方案尚未在该工具中实现或测量。

## 1. 从问题出发

原问题是：

> 一个约 5.5 MB 的 KVC 视频，解码得到约 1.5 GB 的 YUV。能不能把这些画面放在内存里，直接让本机原生 FFmpeg 编码，而不经过大临时文件？

答案是：**可以。更适合顺序转码的方式是边解码、边传输、边编码，不必同时保留整段 YUV。**

这里可以拆成三个独立问题：

1. 解码后为什么会产生这么多数据？
2. 原始画面怎样从 Java/unidbg 交给本机原生 FFmpeg？
3. 这种通信需要 RPC 吗？

它们分别涉及媒体表示、进程间通信以及调用协议，不应混在一起理解。

## 2. 为什么 5.5 MB 会变成约 1.5 GB

KVC 文件中的视频经过压缩；YUV 是解码后的原始像素。文件大小悬殊是两种数据表示方式的差异，不是解码器异常地“把文件放大”。

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

## 3. 三种保存与传输方式

| 方式 | 流程 | 优点 | 代价 |
|---|---|---|---|
| 整段写磁盘 | 解完整段 YUV，再读取编码 | 易于检查、复现和重试 | 需要大临时文件；两个阶段通常串行 |
| 整段保存在内存 | 解完整段到内存，再交给编码器 | 可避免显式 YUV 文件读写 | 样本就需要约 1.5 GB 像素内存；长视频持续增长 |
| 有界流式传输 | 解出一批画面，立即交给编码器 | 缓冲可有界；解码和编码可以重叠 | 需要处理时间戳、背压、进程结束和错误 |

将整段 YUV 放入 JVM 堆也有额外成本：数组大小、对象管理和垃圾回收压力。直接内存或堆外内存能改变管理方式，但不会消除实际物理内存需求。内存压力过大时还可能发生交换，因此“放内存”不自动等于“完全没有磁盘活动”。

对于当前顺序转码需求，优先考虑流式传输。只有需要反复访问大量历史帧、做随机访问算法，或有其他明确用途时，整段缓存才可能值得。

### 小缓冲可以有多小？

例如缓存 10 帧：

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

## 4. 原生 FFmpeg 与 KVC 解码器可以分开

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

### 硬件加速发生在哪里？

- **前半段 KVC 解码**：仍由 unidbg 中的原 `.so` 执行；把输出交给主机 FFmpeg，并不会自动让 KVC 解码变成硬件解码。
- **后半段编码**：主机 FFmpeg 可以选择软件编码，或在硬件、构建与输入条件支持时使用硬件编码。

用户提供的 Mac FFmpeg 构建日志包含 VideoToolbox 支持，因此可以进一步探索该路径。但本文没有实际测试本样本的硬件编码表现，也没有证明全部像素格式和编码选项都能直接适配。

硬件编码不保证整条流程按相同比例提速。速度还受解码、格式转换、内存复制、编码设置以及磁盘输出等因素限制。软硬件编码器的质量、码率和选项也不是一一对应的。

## 5. 为什么 Java 可以把 `.so` 解出的画面交给原生程序

unidbg 里的 Android 环境不是另一台真实机器。它由运行在 Mac 上的 Java 进程及其 native 后端管理。

`.so` 解码后，画面位于它所看到的模拟 ARM64 地址空间。Java 通过 unidbg 的指针接口可以读取这些字节。

现有代码中的这一行就是数据出口：

```java
byte[] row = data.getByteArray((long) y * stride, pw);
```

这里的 `data` 表示模拟地址空间中的画面指针。`getByteArray` 将指定范围的字节读取成 Java 可用的数组；不能把模拟地址值当成本机 FFmpeg 可直接使用的进程地址。

现有程序接着把数组写到文件：

```text
模拟内存 → Java byte[] → YUV 文件
```

讨论中的流式方案改为：

```text
模拟内存 → Java byte[]／缓冲区 → 管道 → FFmpeg
```

真正需要改变的是输出通道及配套的时间戳协议，而不是把 KVC 算法改写成 Java 或 C。

## 6. 管道是什么：两个本机进程之间的字节通道

Java 和原生 FFmpeg 都是 Mac 上的进程。操作系统可以提供一个管道：

```text
Java 进程：写端
        ↓
macOS 管道缓冲区
        ↓
FFmpeg 进程：读端
```

管道不关心一端是 Java、一端是 C/C++ 程序。两边只要按照相同的数据约定写入和读取字节即可。

不需要联网，不需要 HTTP，也不需要为了连接两种语言而引入 RPC。

### 6.1 Java 启动 FFmpeg

Java 可以通过 `ProcessBuilder` 启动 FFmpeg 子进程，然后向子进程的标准输入写入画面。

以下仅说明接口关系，不是完整、可直接运行的转码代码：

```java
Process ffmpeg = new ProcessBuilder(/* FFmpeg 参数 */).start();
OutputStream ffmpegStdin = ffmpeg.getOutputStream();
ffmpegStdin.write(row);
```

容易混淆的是方法名：

| Java Process 接口 | 从 Java 视角看 | 对应子进程 |
|---|---|---|
| `getOutputStream()` | Java 向外写数据 | 子进程 stdin |
| `getInputStream()` | Java 读子进程输出 | 子进程 stdout |
| `getErrorStream()` | Java 读诊断信息 | 子进程 stderr |

FFmpeg 输入使用 `pipe:0` 时，读取的是它的 stdin。

### 6.2 由终端连接两个程序

也可以由终端创建连接：

```text
Java 解码程序的 stdout | FFmpeg 的 stdin
```

此时 Java 的 stdout 必须只包含约定的媒体字节。日志应写 stderr，否则一行 `frames=100` 也会成为像素流的一部分，导致画面错位。

当前工具的 Java 程序将进度输出到 stdout，并把 YUV 写文件，所以不能把现有程序直接加一个 `| ffmpeg` 就认为已经完成改造。

### 6.3 读取、写入和帧边界

管道是字节流，不是“帧队列”：

- 一次写入不保证对应对方的一次读取。
- 多次写入可能被一次读取合并。
- 一帧可能需要多次读取才完整。

如果约定输入始终是 1280×720 YUV420P，读取端可以每收齐 1,382,400 字节，就得到一帧。

这要求传输格式一致且没有混入日志、时间戳或其他未约定的字节。若尺寸或像素格式会变化，就需要额外的格式描述和帧边界协议。

## 7. 背压：为什么流式处理不必无限吃内存

假设解码器每秒生成 100 帧，而编码器每秒只能处理 50 帧。如果把画面不断塞进无界队列，内存会持续增长。

有界缓冲和阻塞管道可以让生产速度受消费速度约束：

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

这就是背压。它不是自动丢帧，也不是把剩余整段视频偷偷存起来，而是让上游等待。

如果另起一个线程解码，并让它写入无界队列，那么管道的背压只会阻塞发送线程，队列仍可能无限增长。要让总缓冲有界，整条生产链都必须遵守容量限制。

### 为什么仍可能死锁？

FFmpeg 的 stderr 也是一条输出通道。若 Java 一直写 stdin，但不消费 FFmpeg 大量输出的诊断日志，stderr 缓冲可能填满：

```text
Java 等待 FFmpeg 读取 stdin
FFmpeg 等待 Java 读取 stderr
```

实际实现需要并行消费日志或将其重定向到合适的位置，同时设计好取消与错误传播。管道结构简单，但完整进程管理不能省略。

## 8. 裸 YUV、时间戳和音轨是不同的信息

### 8.1 YUV 里没有什么？

裸 YUV 不记录：

- 宽高与像素格式。
- 每帧显示时间戳 PTS。
- 音轨。
- 色彩范围、色彩空间、HDR 或旋转等描述信息。

即使全部像素都传过去，时间线和其他信息也不会自动跟着过去。

### 8.2 固定帧率方案与保留 PTS 的方案

**方案一：声明固定 30fps。**

FFmpeg 根据帧编号生成时间线，操作相对简单。但对于可变帧率、重复 PTS、时间间隙或原始起始偏移，这可能改变播放节奏和音画关系。

**方案二：同时传输画面和原始 PTS。**

可以采用额外的时间戳通道、自定义帧协议，或由发送端生成 FFmpeg 能读取且能承载像素格式与逐帧时间戳的流式封装。具体封装需要确认与 rawvideo、像素格式和目标 FFmpeg 的兼容性。

如果使用自定义“时间戳 + 像素”协议，FFmpeg 的标准 rawvideo 输入不会自动识别它，还需要一层适配程序或对应输入模块。

现有 USB 原型使用的就是“8 字节 PTS + 一帧 YUV”的自定义记录，并由 Python 解析。不能直接将这串记录作为纯 rawvideo 输入。

### 8.3 音轨怎么处理？

当前样本的音轨可以从原文件直接拷贝，最后与重新编码的视频合并。需要维持两条轨道的相对起始时间和播放时间线。

“复制音频”只说明音频没有重新编码，不自动保证任意输入都能保持同步。尤其不能将视频时间线全部改成固定间隔后，仍假定原音轨一定与之完全对齐。

## 9. 管道与共享内存：都可避免大文件，但不是一回事

### 普通管道

数据可能经过：

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

优点是进程接口简单、天然适合顺序字节流、有阻塞机制。代价是仍有数据读取和复制，因此“走管道”不等于“零拷贝”。实际复制次数取决于运行环境和实现，不能仅凭图示断言固定次数。

### 共享内存

两个进程映射同一块内存区域，用它交换画面，另用同步机制告诉对方哪些帧已经就绪、哪些槽位可以复用。

它需要设计：

- 环形缓冲的槽位数量和最大帧大小。
- 帧序号、PTS、尺寸、像素格式和 stride。
- 读写完成通知及内存可见性。
- 缓冲区所有权与复用时机。
- 进程退出、崩溃、取消后的恢复。

共享内存可能减少部分进程间复制，但它不会让 unidbg 的模拟内存自动成为 FFmpeg 的共享帧内存，也不保证硬件编码器能直接使用该区域。硬件路径仍可能需要格式转换或复制到适合它的缓冲。

另外，普通 FFmpeg 命令行不会凭空理解一个自定义共享内存环形队列，仍需要输入适配层。

对当前样本，应先测量普通管道方案。只有数据传输与拷贝确实成为明显瓶颈，才有理由承担共享内存的额外复杂度。

## 10. RPC 是什么，解决什么问题

RPC 是 Remote Procedure Call，远程过程调用。它让一个进程请求另一个进程执行某项功能，并接收结果或错误。

“远程”不一定跨机器：两个本机进程之间也能使用 RPC。

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

### 适合 RPC 的情况

| 需求 | RPC 的价值 |
|---|---|
| 解码器在另一台电脑 | 通过网络调用远程能力 |
| Java、Python、C++ 共用服务 | 提供统一、跨语言的数据接口 |
| 解码环境需要常驻 | 复用已加载的库和模拟环境 |
| 多个客户端或多任务 | 按会话、任务 ID 区分资源与状态 |
| 需要打开、跳转、取消、查询进度 | 定义明确的操作、返回结果和错误 |
| 解码器独立部署或升级 | 客户端通过稳定接口使用服务 |

RPC 不自动实现这些业务能力。比如多会话隔离、排队、线程安全、取消和资源释放，仍需要服务端设计。

## 11. 管道与 RPC 不是二选一

二者位于不同层面：

| 概念 | 回答的问题 |
|---|---|
| 管道／socket／共享内存 | 数据怎样在进程间移动？ |
| RPC 协议 | 数据代表哪项调用、什么参数、怎样返回结果？ |

因此：

- RPC 可以运行在网络 socket 上。
- 本机 RPC 可以使用 Unix domain socket 等通道。
- 也可以在管道之上设计请求／响应式 RPC。
- 使用管道传 YUV，并不自动构成 RPC。

只有单向地连续发送像素，通常不需要完整的过程调用机制。若通过管道发送的是带调用 ID 的“打开、跳转、关闭”请求，并返回对应结果，那么它也可以承载 RPC。

RPC 需要考虑请求与响应匹配、消息边界、类型转换、错误处理、超时等问题。它不是一种天然更快的传输方式。

## 12. 控制通道与画面通道可以分开

常驻服务可以采用如下结构：

```text
客户端
    │
    ├─ 控制通道：RPC
    │     打开视频、查询参数、跳转、取消、关闭会话
    │
    └─ 数据通道：管道／共享内存／网络流
          大量像素、逐帧时间戳和必要的格式信息
```

原因是两类数据特性不同：

- 控制消息通常较小，强调语义、状态和错误反馈。
- 画面吞吐量大，强调连续传输、缓冲和背压。

分开后也需要关联规则，例如会话 ID、帧序号、跳转后的新时间线标识。否则可能把一次旧请求的画面误当成新会话的输出。

也可以使用支持流式传输的 RPC 系统同时承载画面，不是一定要拆成两条通道。但应评估消息大小限制、序列化开销、复制、流量控制以及取消行为，而不是默认它更适合视频。

若画面必须跨网络传输，原始 YUV 的带宽需求很大。对本例 1280×720 YUV420P、30fps：

```text
1,382,400 × 30 = 41,472,000 字节／秒
               ≈ 41.5 MB/s
               ≈ 332 Mb/s（未计协议开销）
```

因此远程解码服务还需要评估：是否应在解码所在机器直接编码，再传输压缩结果，而不是把原始 YUV 跨网络发送。这与本机管道的问题不同。

## 13. 对当前 KVC 工具，怎样选择合理

### 当前目标：单个文件顺序转码

优先考虑：

```text
unidbg 解码 → 有界流式通道 → 本机 FFmpeg 编码
```

需要把像素格式、尺寸、PTS、日志隔离、进程退出与背压处理清楚。没必要只因为 Java 与 FFmpeg 语言不同就引入 RPC。

### 后续目标：常驻、交互、多任务

若需要多个程序共用解码环境，并支持进度查询、跳转、取消和会话管理，可考虑：

```text
RPC 控制接口 + 适合大量帧的数据传输通道
```

### 后续目标：减少传输复制

先用测量确定瓶颈，再考虑共享内存或更深入的 native 集成。不要因为原始数据累计有 1.5 GB，就直接认定操作系统管道一定不够快。

## 14. 对性能的正确预期

让解码和编码重叠，通常能够减少等待，但不是无条件提速公式。

若两阶段顺序执行，可以粗略理解为：

```text
总耗时 ≈ 解码时间 + 编码时间 + 文件及其他处理时间
```

若能有效并行且资源充足，流水线耗时可能更接近：

```text
总耗时 ≈ 较慢阶段的时间 + 启动、排空和传输开销
```

这只是直观估计。实际两阶段会争用 CPU、内存带宽和其他资源；编码器还可能存在帧缓存及前瞻。因此并行后的每个阶段耗时不一定与单独运行相同。

已有工具曾验证本地 unidbg 能完整解码样本，但不能将此前“写文件”的测量直接当成新管道方案或硬件编码方案的性能结果。本文没有新增这类实测。

## 15. 讨论结论与实施边界

本次讨论确认的原理是：

1. 可以将 unidbg 解出的画面交给本机原生 FFmpeg 编码。
2. 没必要同时保存整段约 1.5 GB 的 YUV；有界流式处理更适合顺序转码。
3. Java 通过 unidbg 指针接口读取像素后，可以写入普通本机管道，不需要 RPC。
4. 本机编码器可以独立选择软件或硬件路径，但这不会自动加速前面的 KVC 解码。
5. 裸 YUV 不包含 PTS，准确时间线必须单独设计。
6. 管道不等于零拷贝，共享内存也不等于整个解码编码流程零拷贝。
7. RPC 适合有调用语义、会话和控制需求的服务；它与底层传输方式可以组合。

本文没有提供新的可执行转码管道，也没有修改 Java、Python、C 外壳或原始 `.so`。所有代码片段和架构图都用于解释原理；实际实施前仍需确定协议、时间线、缓冲容量和进程管理细节。
```
yuv 是裸像素数据，没有文件头，里面不记录宽高、像素格式、帧率或时间戳。ffprobe 无法自动知道这些参数，所以报了 Picture size 0x0 is invalid。

如果实际解码输出是 1280×720、YUV420P，这样检查：
ffprobe \
  -f rawvideo \
  -pixel_format yuv420p \
  -video_size 1280x720 \
  -framerate 30 \
  "/Users/fuchunming/Downloads/unidbg-kvc/work/unidbg-first.yuv"
如果你换了视频，必须使用 Java 输出的实际 w/h，不能继续填写 1280×720。

查看第一帧：
ffmpeg \
  -f rawvideo \
  -pixel_format yuv420p \
  -video_size 1280x720 \
  -i "/Users/fuchunming/Downloads/unidbg-kvc/work/unidbg-first.yuv" \
  -frames:v 1 \
  "/Users/fuchunming/Downloads/unidbg-kvc/work/first.png"
另外，你的 Java 程序默认只输出一帧。1280×720 的 YUV420P 单帧应为：
1280 × 720 × 1.5 = 1,382,400 字节
命令中的 -framerate 30 是人为指定的解释方式，不是从文件里检测出来的。要保留完整视频的原始时间线，需要配合程序输出的 PTS 文本；只读取 .yuv 无法恢复原始时间戳。
```

``` 魔数
分成两类：FFmpeg 错误码，以及这份 .so 的内存结构偏移。

① -541478725 是 AVERROR_EOF

FFmpeg 在头文件中定义：
#define AVERROR_EOF FFERRTAG('E', 'O', 'F', ' ')
将这四个字符按其规则组成整数再取负，得到：
-0x20464F45 = -541478725
也就是“到达结束”。FFmpeg 官方定义

所以代码：
if (r == -541478725) {
    drain = true;
}
表示输入包读完了，接下来让解码器输出内部剩余的帧。不是看到负数就一定意味着视频损坏。

可以命名以提高可读性：
static final int AVERROR_EOF = -541478725;
② 112、116、124、144 是 AVFrame 的字段偏移

fr 是库返回的 AVFrame 对象在模拟内存中的地址。
ptr(fr).getInt(112)
含义是：从 fr + 112 的位置读取 4 字节整数，不是读取第 112 个元素。

这份库中，我们确认的布局是：
相对 fr 的字节偏移	字段	读取方式
112	width，画面宽度	getInt，4 字节
116	height，画面高度	getInt，4 字节
124	format，像素格式枚举	getInt，4 字节
144	pts，显示时间戳	getLong，8 字节


相当于原生 C 代码：
int width  = frame->width;
int height = frame->height;
int format = frame->format;
int64_t pts = frame->pts;
但我们没有这份定制库的准确头文件，所以 Java 用地址和偏移直接读取。

③ 这些偏移当时怎么确认的？

我们结合了原生库分析和实际解码时的内存检查。针对画面字段，关键证据是第一次解码成功后打印出来的内容：
偏移 104：0
偏移 108：0
偏移 112：1280
偏移 116：720
偏移 120：0
偏移 124：0
最初按另一种布局读取，出现了：
width=0，height=0，format=720
这明显是字段位置错了。检查附近内存后，把宽高定位到 112、116，像素格式定位到 124，再通过实际写出 YUV、查看画面及完整解码验证。

144 处按 64 位读取的值，则通过逐帧时间戳与原视频时间线比对进行了验证。不是仅凭“某个位置看起来像数字”就确定字段。

④ 这些数能不能换库继续用？

不能保证。 结构体布局可能随 FFmpeg 版本、厂商修改、编译配置和 32/64 位架构改变。

需要区分：
- AVERROR_EOF：FFmpeg 定义的错误常量。
- 112 / 116 / 124 / 144：当前这份 ARM64 定制库的 ABI 布局，不是通用 FFmpeg 常量。
- pts 的单位：由时间基决定，不是因为用了 getLong(144) 就天然是微秒。当前工具按已验证样本的 1/1000000 时间基处理。
如果有完全匹配的 C 头文件，就可以用 offsetof(AVFrame, width) 等方式由编译器算偏移；目前这些硬编码值，是缺少准确头文件时采用的验证方案。

```
