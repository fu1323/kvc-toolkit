# KVC7 解码工具：已加入无需手机的 unidbg 版本

## 推荐：Mac 本地 unidbg 转码

已在这台 Apple Silicon Mac 上用 unidbg + Dynarmic 完整解码样本 1084 帧。无需连接手机或启动快手。原始解码与写出 YUV 实测约 10.8 秒（36.07 秒视频；不含编码），仅代表此机器与此样本。

```sh
pip install av
python3 transcode_unidbg.py input.mp4 output.mp4
```

需要 Java（本次使用 Temurin 17 ARM64）、Python、ffmpeg/ffprobe。可用 `--java /完整路径/bin/java` 指定 Java。脚本需要约 1.5 GB 临时空间保存样本原始画面，正常结束自动清理；解码进程设 300 秒超时。与旧版一样，此原型限制 kvc7、1280×720、时间基 1/1000000、视频为第一个轨道，不是通用格式转换器。

`unidbg/KvcProbe.java` 是解码端源码，`unidbg/classes` 为已编译类，`unidbg/deps` 是运行依赖。底层原始库仍在 `lib/`。`transcode_unidbg.py` 负责启动本地模拟、核验帧数、按原 PTS 编码 H.264，并直接拷贝 AAC 音轨。

unidbg 源码：https://github.com/zhkl0228/unidbg ，本次 commit：`e0d88a900ae9d197c325af8d6a5875ee9958b724`。只在构建 POM 中去除了本地运行不需要的发布/文档/签名插件，未修改模拟器执行代码。Apache 2.0 许可见 `unidbg/LICENSE-unidbg`；第三方运行依赖保留各自 JAR 内的许可信息。

实际单线程设置：`av_opt_set_int(ctx, "threads", 1, 0)` 和 `av_opt_set(ctx, "kvc30_params", ":kvc30DecodeThreads=1", AV_OPT_SEARCH_CHILDREN)`；两个调用均返回 0，启用了 unidbg 线程调度兼容。无需 JNI_OnLoad 或 Java 业务环境。

这里仍不是反编译恢复的 C 解码器，也不是 FFmpeg 源码补丁。可用此独立解码进程作为后续 FFmpeg 外部桥接的基础。

## 旧版：USB Android 解码桥


下文旧版 USB 工具使用用户手机中提取的 ARM64 Android `libffmpeg.so`，在手机的独立进程解码，在电脑上用 FFmpeg（PyAV/libx264）编码并拷贝原音轨。不是 macOS 原生 KVC 解码器，也不是已经完成的 FFmpeg 源码补丁。

## 已确认的接口与格式

- 样本为 `kvc7`，私有 codec ID `0x30005`，配置块 `kvLC`。
- 手机库导出 `ff_libkvc30_decoder`，通过 `avcodec_find_decoder_by_name("libkvc30dec")` 可取得解码器。
- 使用 `avformat_open_input` → `avcodec_parameters_to_context` → `avcodec_open2` → `avcodec_send_packet` / `avcodec_receive_frame`，已得到 1280×720 YUV420P 画面。
- 本库也导出 `kvc30dec_create/decode/destroy` 等底层接口。完整符号与 SHA256 见 `symbols.txt`。这些接口的结构体定义尚未恢复，不能仅凭函数名称声明调用。
- 之前提供的 armeabi-v7a 安装包与手机 ARM64 版本不同。前者的静态编解码器列表没有此解码器；手机版本包含。不能据此认定所有快手包都包含或都不包含解码器。
- 修改视频副本的 `kvc7`→`vvc1`、`kvLC`→`vvcC` 后，标准 VVC 解码器在 SPS 参数上失败。因此改 FourCC 不是此样本的解决方案；未证明所有 VVC 衍生码流均不可兼容。

## 使用

需要：支持 ARM64 的 Android 手机、USB 调试，电脑上的 Python、adb、ffmpeg、ffprobe，以及 `pip install av`。库提取使用了 root；此独立解码程序在 adb shell 普通权限下运行成功。

```sh
python3 transcode.py --serial 手机序列号 input.mp4 output.mp4
```

adb 不在 PATH 时加 `--adb /绝对路径/adb`。输出已存在时拒绝覆盖。

此验证版有意限制为 kvc7、1280×720、时间基 1/1000000，并假定视频是第一个轨道。它在 `/data/local/tmp/kvc-probe` 中存放库、输入副本和日志；不修改快手。不要同时运行多个实例。

输出为 H.264（libx264、CRF 18）+ 原音轨，属于有损视频转码；没有重新压缩音频。保留逐帧 PTS，遇到相同或倒退 PTS 时调整为上一帧加 1 微秒。当前样本有一个重复 PTS（14066000）；脚本打印调整次数。手机向电脑传输未压缩 YUV，36 秒样本约 1.5 GB USB 数据，但不在手机保存整段 YUV。

## ABI 注意事项

`phone_decode.c` 使用经过反汇编及实际帧验证的定制库布局：

| 对象 | 字节偏移 | 字段 |
|---|---:|---|
| AVFormatContext | 48 | streams |
| AVStream | 192 | codecpar |
| AVPacket | 36 | stream_index |
| AVFrame | 0 / 64 | data / linesize |
| AVFrame | 112 / 116 / 124 | width / height / format |
| AVFrame | 144 | pts |

这些偏移只针对附带库。不能拿上游 FFmpeg 头文件直接强转其结构体，也不要替换库后继续使用硬编码偏移。程序是样本验证原型，不具备通用媒体工具所需的全部错误恢复与资源释放逻辑。

## 自己 patch FFmpeg 的路径

1. Android ARM64：最直接的是复用整个定制库，像本工具一样走其公开 avcodec API。若必须和自己的新版 FFmpeg 共存，应使用独立进程桥接，避免相同符号及不同 ABI 冲突。
2. 真正的 libavcodec wrapper：先恢复 `kvc30dec_*` 的输入包、输出画面、配置和生命周期 ABI，再添加解码器、codec ID、MOV FourCC / kvLC 解析，并落实 PTS、缓冲区归还、flush 和线程处理。当前尚未交付这个补丁。
3. macOS 原生：Android ARM64 ELF 不能直接被 macOS Mach-O 进程 dlopen。即使都是 ARM64，也需要平台移植或 Android 兼容运行层；仅改 codec_tag 映射不能解决。当前验证可用的是 USB Android 解码桥。

## 文件

- `phone_decode.c` / `phone_decode`：ARM64 Android 端源码与可执行文件。
- `lib/`：从用户设备提取的原始库。
- `transcode.py`：电脑端传输、时间戳处理、视频编码、音频合并。
- `symbols.txt`：库哈希与 KVC 导出符号。

编译时使用 Zig 的交叉编译驱动及手机的 libc.so/libdl.so 链接：

```sh
ZIG_GLOBAL_CACHE_DIR="$PWD/zig-cache" python3 -m ziglang cc \
  -target aarch64-linux-android -nostdlib -fno-sanitize=all \
  -fno-stack-protector -fno-builtin -fPIE -pie -Wl,-e,_start \
  -Wl,--dynamic-linker=/system/bin/linker64 -L/path/to/phone-system-libs \
  phone_decode.c -l:libc.so -l:libdl.so -o phone_decode
```

附带可执行文件已经编译好。这里的 Android 系统链接库未包含在交付包中；重新编译可从同一设备 `/system/lib64` 读取。

## 本次验证结果

最终脚本已完整运行：1084/1084 帧，H.264 1280×720，36.066666 秒，原 AAC 音轨 36.060998 秒。逐包比较输出 PTS 与原视频排序后的 PTS，仅第 424 帧从 14066000 调为 14066001 微秒，其他均一致。用微秒编码时间基完整解码输出视频无错误：

```sh
ffmpeg -v error -i decoded-h264.mp4 -map 0:v:0 \
  -fps_mode passthrough -enc_time_base 1:1000000 -f null -
```

使用默认 30fps 时间基的 null 输出检查会把间隔极短的帧时间戳舍入到同一个值，产生非递增 DTS 提示；上面的检查保留实际时间精度。
