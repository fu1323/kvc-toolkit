<p align="center">
  <a href="README.md">简体中文</a> | <a href="README_EN.md">English</a>
</p>

<div align="center">

# KVC Toolkit: Kuaishou KVC7 Video Decoding · Transcoding · Android Reverse Engineering · unidbg

Run the KVC-capable decoder inside Kuaishou's Android `libffmpeg.so` with **unidbg**, decode KVC7 video into YUV, and transcode it to a conventional H.264 MP4.

</div>

> [!NOTE]
> **Added November 4, 2026: streaming transcoding with per-frame PTS.**
> `KvcProbe_ffmpeg` starts a Python/PyAV bridge automatically. It wraps YUV frames and their original presentation timestamps in NUT and feeds native FFmpeg, without writing a complete YUV file to disk.
> Run `./run_pts.sh input.mp4 output.mp4`. See [Route C](#route-c) and [PTS internals](#pts-deep-dive).
> The older `transcode_unidbg.py` / `KvcProbe.java` path remains unchanged.

> [!WARNING]
> This project is for personal learning and research **only**. Do not use it for bulk scraping. It is a research prototype, not a mass-transcoding service. Documentation dates: November 3, 2026 (initial release), November 4, 2026 (PTS streaming update).

End-to-end decoding and transcoding have been verified on a supplied KVC7 sample using an Apple Silicon Mac, Java/unidbg, and the original Android ARM64 decoder. A separate USB-connected Android decoding path is also retained.

## Contents

**Part I — Overview**

1. [Introduction](#intro)
2. [Three execution routes](#routes)
3. [Repository layout](#layout)
4. [Verified environment and input constraints](#env)

**Part II — Usage**

5. [Route A: Local unidbg transcoding](#route-a)
6. [Route B: USB Android decoding](#route-b)
7. [Route C: Streaming transcoding with PTS](#route-c)
8. [Decode only: inspect raw YUV](#decode-only)

**Part III — Architecture**

9. [How the decoder works inside unidbg](#decode-internals)
10. [Moving decoded data: memory, pipes, shared memory, RPC](#data-transport)
11. [Java → Python → NUT → FFmpeg and timestamps](#pts-deep-dive)

**Part IV — Reverse-engineering notes and verification**

12. [ABI, symbols, and original libraries](#abi-notes)
13. [Validation and test results](#verification)

**Part V — Development and support**

14. [Building and modifying](#build)
15. [Integrating with native FFmpeg](#ffmpeg-integration)
16. [FAQ](#faq)
17. [Known limitations](#limitations)
18. [Sources, licenses, and acknowledgments](#license)

---

# Part I — Overview

<a id="intro"></a>
## 1. Introduction

### What does this toolkit do?

The input uses an MP4 container, but its video track has FourCC `kvc7` and a `kvLC` configuration box. Ordinary FFmpeg builds do not provide a decoder for this proprietary format. The toolkit loads an ARM64 `libffmpeg.so` extracted from the user's own Android device, where a working KVC decoder and callable FFmpeg APIs are present. **It reuses the original machine-code implementation; it does not reimplement KVC.**

```text
KVC7 MP4 → unidbg emulates Android and executes libffmpeg.so
         → YUV420P frames + PTS → libx264 H.264 encoding
         → original audio track copied → conventional MP4
```

Important distinctions:

| Question | Answer |
|---|---|
| Was the KVC algorithm decompiled into C? | **No.** The decoder still runs as ARM64 instructions from the original `.so`. |
| Is `phone_decode.c` the decoder source? | **No.** It is an Android-side wrapper that calls the library. |
| What does Java do? | `KvcProbe.java` configures unidbg and calls exported native APIs. |
| Is this a patch for upstream FFmpeg? | **No.** It is a standalone decoder/transcoder. |

Android ELF shared libraries cannot be loaded directly into macOS applications with `dlopen`, even on ARM64 Macs: their binary format, dynamic linker, syscalls, and runtime environment differ. unidbg bridges that environment gap.

Only **one KVC7 sample** and **one matching set of native libraries** were verified. This is not evidence that every Kuaishou video is supported.

<a id="routes"></a>
## 2. Three execution routes

All three routes use the same original ARM64 decoding library; they differ in where decoding runs, how decoded frames are transferred, and how timestamps are handled.

### Route A — Local unidbg, intermediate YUV files

> [!WARNING]
> The author notes that `transcode_unidbg.py` has a bug and may need modification. The underlying Java/unidbg decoder **has been verified to work**.

```text
transcode_unidbg.py (Python orchestration)
 ├─ ffprobe: inspect input tracks
 ├─ Java KvcProbe → unidbg / Dynarmic → libffmpeg.so
 │   ├─ frames.yuv
 │   └─ pts.txt
 ├─ PyAV / libx264: encode H.264
 └─ ffmpeg: copy original audio into output.mp4
```

No phone, ADB, Kuaishou application, or `phone_decode` process is required.

### Route B — USB Android device

```text
transcode.py on Mac
 ├─ adb: push libraries, input, and phone_decode
 ├─ Android: phone_decode loads libffmpeg.so and emits PTS + YUV
 ├─ adb exec-out: stream frame records back to Mac
 ├─ PyAV / libx264: encode H.264
 └─ ffmpeg: mux original audio
```

### Route C — Streaming with original per-frame PTS

```text
Java / unidbg → Android libffmpeg.so KVC decoder
  ↓ KVCP0001 binary pipe: per-frame PTS + packed YUV420P
pts_bridge.py / PyAV: mux rawvideo packets into NUT
  ↓ NUT pipe: dimensions, pixel format, time base, PTS
Native ffmpeg: libx264 CRF 18 / preset fast + audio stream copy
  ↓
H.264 + AAC MP4
```

No complete YUV/NUT intermediate file is written and the full video is not held in RAM.

| Feature | Route A | Route B | Route C |
|---|---|---|---|
| Entry point | `transcode_unidbg.py` | `transcode.py` | `./run_pts.sh` or `xin.chunming.KvcProbe_ffmpeg` |
| Decoder host | Mac, emulated Android | Physical Android phone | Mac, emulated Android |
| Java needed | Yes | No | Yes (Java 17 + Maven) |
| Phone/ADB needed | No | Yes | No |
| Frame transport | Complete temporary YUV | USB frame stream | Bounded process pipes |
| Timestamp handling | `pts.txt`, adjust duplicate by 1 µs | 8-byte PTS + frame | Per-frame PTS in NUT time base |
| Encoder | PyAV/libx264 | PyAV/libx264 | Native FFmpeg/libx264 |
| Verification | End-to-end | End-to-end | Sample passed Nov 4, 2026 |

**Quick choice:** no phone → A or C; preserve PTS and save disk space → C; inspect raw pixels → [section 8](#decode-only); already have an Android/ADB workflow → B.

<a id="layout"></a>
## 3. Repository layout

| Path | Purpose |
|---|---|
| `lib/` | Original Android `libffmpeg.so` with KVC decoder, and matching `libc++_shared.so` |
| `src/main/java/xin/chunming/` | Java source, including `KvcProbe_ffmpeg.java` |
| `pom.xml`, `kvc-toolkit.iml`, `.idea/` | Maven and IntelliJ IDEA project configuration |
| `transcode_unidbg.py` | Route A orchestration (see bug warning) |
| `pts_bridge.py` | Route C KVCP0001 parser, PTS validation, NUT muxing, FFmpeg subprocess |
| `run_pts.sh` | Route C build-and-run script, uses project `.venv` |
| `requirements-pts.txt` | Python dependencies, currently `av==15.1.0` |
| `test_pts_bridge.py` | Bridge integration tests without requiring the KVC library |
| `symbols.txt` | Library hashes, dependencies, exported symbols |
| `encoders.txt` | Enumerated registered encoders |
| `validation.json` | Recorded output media properties |
| `USB/` | Not documented in the original README; needs confirmation |

The initial November 3 distribution also described `phone_decode.c`, the compiled Android `phone_decode`, `transcode.py`, and an `unidbg/` folder containing `KvcProbe.java`, compiled classes, dependency JARs, and verification records. Their locations in the current repository need checking. Route C may produce `work/pts-validation.csv`, `.log`, and `.mp4` during validation; these are not necessarily committed.

**Do not confuse platforms:** `phone_decode` is an Android executable, not a macOS binary. Android `libffmpeg.so` cannot replace Homebrew FFmpeg. Prebuilt Route A does not require Maven, Zig, or the Android NDK; Route C does require Maven and a working Java/Python/FFmpeg environment.

<a id="env"></a>
## 4. Verified environment and input constraints

| Component | Tested setup |
|---|---|
| Machine | Apple Silicon Mac (ARM64) |
| Java | Temurin 17.0.20.1 ARM64 |
| Python | 3.9.6 |
| PyAV | 15.1.0 |
| CLI FFmpeg | 9.0.1 |
| unidbg | Route A `0.9.10-SNAPSHOT`; Route C verification noted 0.9.9 |
| Execution backend | `DynarmicBackend64` |
| Android resolver | `AndroidResolver(23)` |

These are **tested versions, not established minimum requirements**. Intel Macs, Windows, Linux, and other version combinations have not been verified end-to-end.

The Route A Python wrapper checks that the first video track has `codec_tag_string == kvc7`, resolution **1280×720**, and time base **1/1000000**. Java/C code also assumes that the video is **stream index 0**, that output is **8-bit YUV420P** (library pixel format value 0), and that the specific library supports the input configuration. These are prototype constraints, not claims about KVC's inherent capabilities.

---

# Part II — Usage

<a id="route-a"></a>
## 5. Route A: Local unidbg transcoding

### Check dependencies

```bash
uname -m
java -version
python3 --version
ffmpeg -version
ffprobe -version
/usr/libexec/java_home -V
```

Use an ARM64 JDK on Apple Silicon to avoid accidentally running under Rosetta. Install any missing tools separately.

### Set up Python

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "av==15.1.0"
python -c 'import av; print(av.__version__); print(av.codec.Codec("libx264", "w"))'
```

PyAV and the `ffmpeg` executable may be linked to **different FFmpeg builds**. The CLI supporting x264 does not prove that PyAV has the encoder.

### Transcode

```bash
python transcode_unidbg.py "/absolute/path/input.mp4" "/absolute/path/output.mp4"

# Optional: choose a specific Java executable
python transcode_unidbg.py \
  --java "/Library/Java/JavaVirtualMachines/temurin-17.jdk/Contents/Home/bin/java" \
  "/absolute/path/input.mp4" "/absolute/path/output.mp4"
```

`input` and `output` are required; `--java` is optional. The output directory must exist. Existing output files are **not overwritten**. There are no `--force`, `--crf`, `--threads`, `--backend`, or general resolution flags in this script.

Expected diagnostics include `LOADED libffmpeg.so`, `decoder open=0`, frame progress, and finally `SUCCESS frames=1084` / `Completed 1084 frames`. `codec=30005` is a hexadecimal representation (`0x30005`). Merely seeing `decoder open=0` does **not** establish that the entire file was decoded.

### Temporary storage and output characteristics

The script creates a temporary directory containing `frames.yuv`, `pts.txt`, intermediate `video.mp4`, and an emulated `root/` filesystem. For the tested sample:

```text
1280 × 720 × 3/2 = 1,382,400 bytes/frame
1,382,400 × 1084 = 1,498,521,600 bytes ≈ 1.50 GB ≈ 1.40 GiB
```

Allow at least **2 GB** of temporary free space for this sample. Java uses `-Xmx2g`, which does not cap native/unidbg allocations. The Java decoder subprocess has a **300-second timeout**, not a global pipeline timeout. Interrupted runs may leave temporary or partial output files.

The video is **decoded and re-encoded**, not losslessly remuxed: `KVC7 → YUV420P → libx264 CRF 18 / preset fast → H.264`. The first source audio track is stream-copied; the sample uses AAC. Per-frame PTS values are used with time base `1/1000000`, not regenerated uniformly from a nominal 30 fps. One duplicate sample timestamp (`14066000` µs) was adjusted to `14066001` µs:

```python
if last_pts is not None and pts <= last_pts:
    pts = last_pts + 1
```

This is a minimal monotonicity correction, **not** a general timeline-repair algorithm. Color metadata, HDR, rotation, subtitles, chapters, extra audio tracks, and other side data are not fully preserved.

<a id="route-b"></a>
## 6. Route B: USB Android decoding (fallback)

Requirements: ARM64 Android phone with USB debugging authorized, plus ADB, Python/PyAV, FFmpeg, and ffprobe on the computer. Root was used when **extracting** the original libraries, but the already-extracted decoder was successfully executed as an ordinary `adb shell` user. The script does not invoke `su` or modify the Kuaishou application.

```bash
adb devices -l
python transcode.py --serial "DEVICE_SERIAL" \
  "/absolute/path/input.mp4" "/absolute/path/output.mp4"

# If adb is not on PATH
python transcode.py --adb "/absolute/path/adb" --serial "DEVICE_SERIAL" \
  "/absolute/path/input.mp4" "/absolute/path/output.mp4"
```

Android-side working directory: `/data/local/tmp/kvc-probe`. It contains `phone_decode`, `libffmpeg.so`, `libc++_shared.so`, `input.mp4`, and `decode.log`. The script does not automatically delete these files; reusing the directory overwrites them. **Do not run concurrent USB jobs using that same directory.**

The phone emits a custom binary record stream, **not** MP4 or FLV:

```text
frame 0: signed little-endian int64 PTS + Y plane + U plane + V plane
frame 1: signed little-endian int64 PTS + Y plane + U plane + V plane
...
```

For the sample, timestamps are in microseconds, each packed 8-bit YUV420P frame is 1,382,400 bytes, and each record is 1,382,408 bytes. Diagnostic stderr is redirected to `decode.log` so it cannot corrupt binary stdout. This USB protocol is **different** from Route C's big-endian `KVCP0001` protocol.

<a id="route-c"></a>
## 7. Route C: Streaming transcoding with per-frame PTS

Added November 4, 2026. Implemented in `xin.chunming.KvcProbe_ffmpeg`. The original `KvcProbe.java` and `transcode_unidbg.py` retain their previous behavior; the old Python entry point does not automatically use Route C.

### Set up and run

Requires Java 17, Maven, native FFmpeg/ffprobe, Python 3.9+, and matching ARM64 libraries in `lib/`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-pts.txt

./run_pts.sh input.mp4 output.mp4
```

`run_pts.sh` compiles the Java project and uses `.venv/bin/python`. It refuses to overwrite an existing output. With no arguments, the original implementation defaults to a developer-specific Downloads input path and creates a timestamped `output_pts_*.mp4` in the project directory; **pass both paths explicitly on other machines**.

Optional timestamp audit:

```bash
KVC_PTS_AUDIT=/tmp/kvc-pts.csv ./run_pts.sh input.mp4 output.mp4
KVC_PYTHON=/absolute/path/to/venv/bin/python ./run_pts.sh input.mp4 output.mp4
```

The optional CSV contains `frame,original_pts,output_pts,time_base`, not pixel data. It is an audit log, **not** the source of FFmpeg timestamps, and will not overwrite an existing CSV.

### Run in IntelliJ IDEA

Run `xin.chunming.KvcProbe_ffmpeg`, set the **working directory to the project root**, and supply `input.mp4 output.mp4` as program arguments. If using another working directory, specify VM options:

```text
-Dkvc.python=/absolute/path/to/.venv/bin/python
-Dkvc.bridge=/absolute/path/to/pts_bridge.py
-Dkvc.libdir=/absolute/path/to/lib
-Dkvc.rootdir=/absolute/path/to/work/kvc-root
```

Optional:

```text
-Dkvc.ffmpeg=/opt/homebrew/bin/ffmpeg
-Dkvc.ffprobe=/opt/homebrew/bin/ffprobe
-Dkvc.pts.audit=/tmp/kvc-pts.csv
```

`kvc.python` must point to an executable, not a shell command with arguments.

### Timestamp pipeline and validation

1. After `avcodec_receive_frame`, Java reads the 64-bit PTS at `AVFrame + 144` for this library's ABI.
2. It reads dimensions/pixel format, starts Python on the first frame, and **still sends that first frame**.
3. Java sends PTS, payload length, and Y/U/V planes row by row, removing stride padding.
4. Python uses native ffprobe to obtain the input's **stream 0 time base**. `1/1000000` means one tick is one microsecond, but this must not be assumed for every file.
5. PyAV creates rawvideo AVPackets with `pts = dts = frame_pts`, sets their time base, and muxes them into NUT. Rawvideo has no B-frame reorder; x264 later produces its own encoded DTS.
6. Native FFmpeg uses `-fps_mode:v passthrough -enc_time_base:v demux` so it does not rebuild a fixed 30 fps timeline.

Nominal frame rate is used for stream description and final-frame duration estimation, **not** to replace intermediate frame timestamps.

| Input PTS condition | Behavior |
|---|---|
| Strictly increasing | Preserve unchanged |
| Equal to previous PTS | Preserve frame; advance output by the minimum tick necessary |
| Truly decreasing | Fail; do not silently sort or force constant frame rate |
| `AV_NOPTS_VALUE` | Fail rather than invent a timestamp |
| Negative video PTS | Reject in current version; a future fix would need a coordinated audio/video shift |

For the sample, frames 423 and 424 both had PTS `14066000`; frame 424 became `14066001` (+1 µs), and the change was logged.

### Audio synchronization and error handling

Native FFmpeg uses `-copyts` to keep the video and source audio on a shared timeline, and `-map 1:a:0? -c:a copy` to optionally copy the first audio stream. It does **not** use `-shortest`. Some source audio codecs cannot be copied directly into MP4 and would need transcoding. An `unknown codec kvc7` warning while probing the original input does not by itself mean failure: FFmpeg only takes its audio; the video comes from NUT.

### KVCP0001 wire format

All integers are **big-endian**:

```text
16-byte stream header:
  ASCII "KVCP0001" (8 bytes) + uint32 width + uint32 height
For each frame:
  int64 PTS + uint32 payload_size (12-byte header)
  tightly packed YUV420P payload
12-byte completion record:
  int64 frame_count + uint32 zero
Then close stdin.
```

The completion record distinguishes clean EOF from a truncated stream. Missing bytes, a missing completion record, or mismatched frame count are errors. Java reports `SUCCESS` only after Python and FFmpeg exit successfully. Partial MP4 files may remain after failures.

Route C is **not** zero-copy and does not implement network RPC. It still assumes this ARM64 library's ABI, stream index 0, even dimensions, 8-bit YUV420P, and a single video track plus the first optional audio track. Encoding uses native CPU libx264.

<a id="decode-only"></a>
## 8. Decode only: inspect raw YUV

This path decodes without running PyAV encoding or producing an MP4 with audio. It is useful for inspecting the first frame, verifying raw pixels, and exploring the native interface.

```bash
mkdir -p work
java -Xmx2g \
  -Dkvc.libdir="$PWD/lib" \
  -Dkvc.rootdir="$PWD/work/root" \
  -cp "unidbg/classes:unidbg/deps/*" \
  KvcProbe \
  "/absolute/path/input.mp4" \
  "$PWD/work/first.yuv" \
  1 \
  "$PWD/work/first-pts.txt"
```

Arguments are: input video, output YUV path, maximum frames (`1` = first frame; `0` = all), output PTS text path. **Direct Java execution can overwrite YUV/PTS outputs** and has no Python wrapper's 300-second timeout. The example explicitly sets library and root paths to avoid developer-specific defaults.

Convert the first frame to PNG:

```bash
ffmpeg -n -f rawvideo -pixel_format yuv420p -video_size 1280x720 \
  -i work/first.yuv -frames:v 1 work/first.png
```

Inspect raw YUV with ffprobe:

```bash
ffprobe -f rawvideo -pixel_format yuv420p \
  -video_size 1280x720 -framerate 30 work/first.yuv
```

Raw YUV has **no header**: it contains no dimensions, pixel format, frame rate, PTS, or audio. An error such as `Picture size 0x0 is invalid` means the missing interpretation parameters must be supplied. The `-framerate 30` above is a **manual assumption**, not information discovered in the file. Use the separate PTS text for the original timeline. For 1280×720 YUV420P, one frame is exactly **1,382,400 bytes**.

---

# Part III — Architecture

<a id="decode-internals"></a>
## 9. How the decoder works inside unidbg

### Java-side workflow

1. Create a 64-bit Android emulator; register Dynarmic first and Unicorn2 as fallback. Dynarmic was actually used.
2. Set `AndroidResolver(23)` and enable unidbg thread-dispatch compatibility.
3. Map emulated `/input.mp4` to the host input file.
4. Load `libc++_shared.so` and then `libffmpeg.so`.
5. Call `avformat_open_input`; inspect `codecpar` for stream index 0.
6. Find decoder `libkvc30dec` with `avcodec_find_decoder_by_name`.
7. Allocate a codec context, copy parameters, configure threading, open the decoder.
8. Read compressed AVPackets; call `avcodec_send_packet` and `avcodec_receive_frame`.
9. Copy valid pixel bytes from each Y/U/V plane row, omitting stride padding; save PTS.
10. Flush buffered frames at EOF by sending an empty packet.

No `JNI_OnLoad`, Kuaishou login environment, or app-specific Java business classes are required. This calls exported **native FFmpeg APIs**, not the app's Java playback interface.

```c
av_opt_set_int(ctx, "threads", 1, 0);
av_opt_set(ctx, "kvc30_params", ":kvc30DecodeThreads=1", 1);
```

Both calls returned zero in testing; that does not prove the library never creates threads internally.

### Pointers and emulated memory

```java
call("avcodec_send_packet", ptr(ctx), ptr(pkt));
call("avcodec_receive_frame", ptr(ctx), ptr(fr));
```

The native signatures are equivalent to:

```c
avcodec_send_packet(AVCodecContext *ctx, const AVPacket *pkt);
avcodec_receive_frame(AVCodecContext *ctx, AVFrame *frame);
```

Both arguments are pointers in **unidbg's emulated address space**, not JVM object addresses or ordinary macOS pointers. `AVPacket` contains metadata (`data`, `size`, `pts`, `dts`, etc.) and a pointer to compressed bytes. The decoded `AVFrame` points to Y/U/V pixel planes. The library itself handles demuxing through `av_read_frame` and manages packet allocations.

A Java `byte[]` cannot simply be passed as a native pointer. If you want to supply compressed packets manually, allocate the packet and buffer **inside the emulated environment**, preferably using library APIs such as `av_packet_alloc` and `av_new_packet`, and follow the API's ownership/reference-counting rules. A complete MP4 is **not** an AVPacket: to decode from in-memory MP4 bytes you still need a demuxer, for example through custom AVIO callbacks.

The Java code calls the FFmpeg send/receive interface; it does **not** directly invoke `kvc30dec_decode`. The library dispatches to its internal KVC implementation.

### Exported API functions explicitly called

| Phase | Functions |
|---|---|
| Logging | `av_log_set_level` |
| Container | `avformat_open_input`, `av_read_frame` |
| Decoder discovery and setup | `avcodec_find_decoder_by_name`, `avcodec_alloc_context3`, `avcodec_parameters_to_context`, `avcodec_open2` |
| Options | `av_opt_set_int`, `av_opt_set` |
| Packet/frame allocation | `av_packet_alloc`, `av_frame_alloc` |
| Decode | `avcodec_send_packet`, `avcodec_receive_frame` |
| Release references | `av_packet_unref`, `av_frame_unref` |

These are **15 distinct exported functions**, not 15 total calls. The send/receive functions may be called many times per packet or frame, and flushing is needed at EOF.

### How `kvLC` reaches the decoder

`kvc7` identifies the codec in MP4; `kvLC` identifies codec configuration. Its spelling and capitalization matter. It is **not** evidence of any connection to the VLC media player. Conceptually, the flow is:

```text
MP4 (kvc7 + kvLC + compressed samples)
 → avformat_open_input()
 → AVStream.codecpar (codec_id, dimensions, extradata)
 → avcodec_parameters_to_context()
 → avcodec_open2()
 → avcodec_send_packet() / avcodec_receive_frame()
```

The public FFmpeg API copies stream parameters and `extradata` into the codec context. However, the precise private `kvLC` byte layout, whether it is transformed on the way to `extradata`, and the exact stage at which the KVC implementation parses it **have not been established by tracing**. `kvLC` serves a similar conceptual purpose to H.264 `avcC` or HEVC `hvcC`, without implying the same internal structure.

<a id="data-transport"></a>
## 10. Moving decoded data: memory, pipes, shared memory, and RPC

This chapter describes architecture choices; **shared memory and RPC were discussed, not implemented or benchmarked**. Route A writes a full YUV intermediate file; Route C implements the streaming pipe approach.

The tested compressed video is roughly 5.5 MB, but its 1084 decoded 1280×720 YUV420P frames total about 1.5 GB. That is expected: compressed samples and uncompressed pixels are different representations.

```text
Y = 1280 × 720 = 921,600 bytes
U =  640 × 360 = 230,400 bytes
V =  640 × 360 = 230,400 bytes
Total per frame = 1,382,400 bytes
Total 1084 frames = 1,498,521,600 bytes
```

**Total decoded bytes are not the same as simultaneous RAM usage.** A sequential pipeline can reuse a bounded buffer. For example, ten packed frames occupy about 13.8 MB of pixel storage, but unidbg, JVM, native backends, decoder reference frames, OS pipes, x264 lookahead, and encoder buffers consume additional memory.

| Strategy | Advantage | Trade-off |
|---|---|---|
| Write complete YUV to disk | Easy inspection/retry | Large temporary files; separate decode and encode stages |
| Keep complete YUV in RAM | Avoid explicit YUV disk file | Memory grows with video length; possible GC/swap overhead |
| Bounded streaming pipe | Limited queued frames; overlapping decode/encode | Needs PTS protocol, backpressure, error propagation, process lifecycle handling |

The Android decoder and host encoder are independent:

```text
KVC → Android libffmpeg.so inside Java/unidbg
    → raw pixels + timestamps
    → native macOS FFmpeg (software or compatible hardware encoder)
    → MP4
```

Sending decoded pixels to native FFmpeg does **not** make KVC decoding hardware-accelerated. Native FFmpeg may support VideoToolbox for the *encoding* half, but this sample's VideoToolbox performance was not tested.

Java reads emulated pixel memory through unidbg, e.g.:

```java
byte[] row = data.getByteArray((long) y * stride, pw);
```

Route A writes the resulting bytes to a YUV file. Route C sends them through a binary process pipe and a Python adapter. Emulated pointers cannot be passed directly as native pointers to another process.

A pipe is an OS byte channel; it does not preserve logical frame boundaries unless the application protocol does. A full pipe causes the producer to wait for the consumer (**backpressure**), which can naturally limit queued frames. But deadlocks are possible if, for example, Java blocks writing stdin while FFmpeg blocks because Java is not draining stderr. Logs, cancellation, and failure propagation must be handled carefully.

Raw YUV has no PTS, resolution, audio, or color metadata. Declaring `-framerate 30` invents a constant-rate timeline and may break synchronization for variable-frame-rate inputs. Route C instead transfers PTS with each frame and uses NUT as a timestamp-aware intermediate stream. A custom `PTS + YUV` byte stream is **not** valid FFmpeg `rawvideo` input without an adapter.

Pipes and shared memory can both avoid large temporary files, but they differ: a pipe transports an ordered byte stream with built-in flow control; shared memory exposes a jointly mapped buffer and requires explicit synchronization, ownership, and lifetime management. RPC describes remote-style method invocation, not a requirement for moving local pixels. For this sequential local transcoder, the pipe is the simpler proven choice.

<a id="pts-deep-dive"></a>
## 11. Streaming internals: Java, Python, NUT, and per-frame PTS

The core design separates **decoding**, **timestamp-aware packetization**, and **encoding**:

```text
libffmpeg.so (Android ARM64) → Java/unidbg
  → KVCP0001 (YUV420P + original PTS)
  → pts_bridge.py (PyAV rawvideo packets, NUT mux)
  → native ffmpeg (H.264 encoding, original audio copy)
```

The bridge reads exact record lengths, validates dimensions/payloads, and handles monotonicity and end-of-stream checks. It can buffer adjacent frames to determine packet durations without holding the entire movie. Source stream time base is obtained with ffprobe. For rawvideo packets, PTS and DTS are identical before x264's own reordering. The NUT container carries the rawvideo description and timestamps to native FFmpeg; the `.nut` data is streamed through a pipe, not saved as a full intermediate file.

PTS is a **timestamp expressed in ticks of a time base**, not necessarily milliseconds or microseconds. With time base `1/1000000`, `PTS=14066000` represents 14.066 seconds; another file may use a different rational time base. Duplicate timestamps are corrected minimally; truly backward, missing, or negative timestamps are rejected under the current policy. The optional audit CSV is for inspection, not part of the muxer's timestamp input.

The custom `KVCP0001` protocol is **not** the same as the USB decoder's little-endian eight-byte PTS prefix. Its 16-byte magic/dimension header, 12-byte frame headers, packed YUV payloads, and completion record are described in [section 7](#route-c). The explicit completion record protects against treating an unexpectedly closed pipe as successful EOF. The pipeline must check both Python and FFmpeg exit statuses before declaring success.

NUT is useful here because it can transport a rawvideo stream with a declared pixel format, dimensions, time base, and packet timestamps. Plain rawvideo cannot do that. This is not a claim that arbitrary NUT streams can be concatenated byte-for-byte or that NUT eliminates all timestamp validation.

---

# Part IV — Reverse-engineering notes and verification

<a id="abi-notes"></a>
## 12. ABI, symbols, and original libraries

The project relies on the exact ABI of the supplied Android `libffmpeg.so`, **not** on an assumption that all FFmpeg builds have identical internal structure layouts. In particular, the Java decoder reads selected fields by offsets, including the sample-specific `AVFrame + 144` PTS location. Different library versions, build configurations, or ABIs may invalidate these offsets.

The observed codec name is `libkvc30dec`; `kvc7` is the MP4 codec tag, and `kvLC` is the configuration-box tag. They are different identifiers. `symbols.txt` records library hashes, dependencies, and exported symbols; `encoders.txt` records actually enumerated encoders. The ability to **decode** this KVC7 sample does not establish that a KVC **encoder** is available or that the proprietary algorithm has been recovered as portable source code.

Treat these notes as observations of the supplied binaries. Verify offsets, symbol availability, architecture, and dynamic dependencies again before substituting any `.so`.

<a id="verification"></a>
## 13. Validation and test results

The supplied KVC7 sample was decoded end-to-end and converted to an H.264 MP4 on the tested Apple Silicon setup. The sample has **1084 frames**, **1280×720**, 8-bit YUV420P output, and time base **1/1000000**. One pair of duplicate timestamps was observed and minimally corrected. The USB and original local unidbg routes were tested, and the streaming PTS route passed sample validation on November 4, 2026.

The repository includes `validation.json` and, in the initial distribution notes, additional unidbg verification records. The `test_pts_bridge.py` integration test exercises the bridge without requiring a KVC native library. Check output properties with tools such as:

```bash
ffprobe -v error -show_streams -show_format output.mp4
ffprobe -v error -select_streams v:0 -show_frames \
  -show_entries frame=pts,pkt_duration_time,best_effort_timestamp_time \
  -of csv output.mp4
```

A successful `avcodec_open2` return value alone is **not** end-to-end verification. Check decoded frame counts, expected raw pixel size, exit codes, output streams, and timestamp behavior. The source README's observations apply to the tested sample, not to untested KVC variants.

---

# Part V — Development and support

<a id="build"></a>
## 14. Building and modifying

The project is a Maven/Java unidbg application plus Python orchestration and bridging scripts. For Route C, the supplied `run_pts.sh` compiles Java automatically. You can also build from the repository root with Maven:

```bash
mvn compile
```

For the verified configuration, use Java 17 and the project-provided Maven dependencies. `KvcProbe.java` implements the original decode-to-file route; `KvcProbe_ffmpeg.java` implements streaming; `pts_bridge.py` handles framing, PTS, NUT muxing, and native FFmpeg invocation. `transcode_unidbg.py` handles Route A's PyAV encoding, and `transcode.py` handles USB orchestration.

If changing supported resolution, pixel format, time base, or codec/library version, review **all** matching assumptions: demuxed stream index, ABI offsets, AVFrame layout, YUV plane strides, byte counts, timestamps, and encoder input settings. Simply removing a 1280×720 guard does not make other formats safe.

Route A's `libx264` quality settings live in Python source (`stream.options`), rather than exposed CLI options. Route C uses the native FFmpeg encoding command. When editing the binary protocol, update both its Java writer and Python reader and rerun `test_pts_bridge.py`.

<a id="ffmpeg-integration"></a>
## 15. Integrating with your own FFmpeg

This toolkit is **not** a native FFmpeg KVC decoder plugin or an upstream patch. The practical integration boundary is the **decoded pixel stream plus timing information**. Route C already feeds the system FFmpeg via NUT, so native FFmpeg does not need to recognize KVC7.

Potential extensions include changing the downstream encoder, adapting color/metadata propagation, adding a custom AVIO input path, or writing a more direct native integration. Those are development possibilities, **not verified features**. Hardware encoding may be explored where supported; it does not accelerate the emulated KVC decoder itself.

<a id="faq"></a>
## 16. FAQ

**Why does stock FFmpeg report an unknown `kvc7` codec?** It has no decoder for this proprietary codec tag. This toolkit uses the extracted Android decoder instead.

**Can I load Android `libffmpeg.so` directly on macOS?** No. ARM64 instruction compatibility alone does not make Android ELF shared objects macOS-compatible.

**Is the KVC algorithm implemented in Java or C here?** No. Java and the Android C wrapper invoke the original binary's exported APIs.

**Do I need a rooted phone?** Not for local unidbg Routes A/C. Root was used to obtain the original library; the USB runtime was verified with ordinary `adb shell` privileges after extraction.

**Why is the decoded YUV much larger than the input?** It is uncompressed 8-bit YUV420P. One 1280×720 frame occupies 1,382,400 bytes.

**Why does ffprobe say `Picture size 0x0 is invalid` for `.yuv`?** Rawvideo does not store dimensions or pixel format. Supply them explicitly.

**Why not just pipe YUV directly to FFmpeg?** Raw YUV does not carry per-frame PTS. Route C adds a timestamp-aware protocol and NUT bridge.

**Does `rate=30` mean original PTS are discarded?** No. The relevant code explicitly supplies per-frame timestamps; nominal rate and frame PTS serve different roles.

**Can I use any resolution, 10-bit source, or KVC video?** Not established. The current prototype is constrained by the tested ABI and sample format.

**Does the tool preserve every MP4 track and metadata field?** No. It primarily preserves video pixels/timing and copies the first audio track where possible.

**Can I treat `decoder open=0` as a successful conversion?** No. Confirm final frame count, encoding, muxing, and process exit statuses.

<a id="limitations"></a>
## 17. Known limitations and future improvements

- Research-only prototype; **not designed for mass decoding, transcoding, or scraping**.
- Verified on a single KVC7 sample with a matching set of original ARM64 libraries; not a universal KVC implementation.
- No demonstrated portability to Intel macOS, Linux, Windows, or arbitrary unidbg/PyAV versions.
- Fixed assumptions about stream index 0, frame dimensions, 8-bit YUV420P, and internal library ABI/offsets.
- Route A writes a large intermediate YUV file and has a documented Python-script bug; Route C avoids full YUV/NUT files but still copies data between emulated memory and processes.
- Duplicate PTS are minimally adjusted; backward/missing/negative PTS are not automatically repaired.
- Only the first optional audio track is copied. No general preservation of multiple audio tracks, subtitles, chapters, color metadata, HDR, rotation, or side data.
- H.264 output uses lossy encoding; no claim of bit-exact round-trip quality.
- No integrated native KVC decoder for upstream FFmpeg, no demonstrated KVC encoder, no network RPC or shared-memory transport, and no verified hardware acceleration of KVC decoding.
- Changing libraries or formats requires fresh reverse-engineering and validation, not just bypassing checks.

<a id="license"></a>
## 18. Sources, licenses, and acknowledgments

### Provenance and licensing

- Upstream unidbg: [zhkl0228/unidbg](https://github.com/zhkl0228/unidbg).
- Source commit used: `e0d88a900ae9d197c325af8d6a5875ee9958b724`.
- The local build removed unrelated source packages, documentation, signing, and release plugins, without modifying emulator execution code.
- unidbg's Apache 2.0 license is in `unidbg/LICENSE-unidbg`; third-party JARs retain their own license information.
- Android binaries under `lib/` originated from a user-supplied device and have **different provenance and licensing** from unidbg. Their inclusion does **not** make them Apache-2.0-licensed and does **not** constitute possession of portable KVC source code.
- The original video sample is not bundled. The toolkit includes wrappers, runtime components, and verification artifacts for reproducibility and further study.

### References

These explain general media APIs and formats; **they are not specifications for proprietary KVC internals**.

- [FFmpeg command-line documentation](https://ffmpeg.org/ffmpeg.html): `copyts`, `fps_mode`, `enc_time_base`.
- [FFmpeg formats documentation](https://ffmpeg.org/ffmpeg-formats.html): rawvideo, NUT, MP4.
- [FFmpeg NUT documentation](https://ffmpeg.org/nut.html): NUT container and media types.
- [PyAV time documentation](https://pyav.org/docs/stable/api/time.html): timestamps and rational time bases. This page may describe an older release; tested behavior refers to PyAV 15.1.0.
- [PyAV container API](https://pyav.org/docs/stable/api/container.html): creating streams and muxing.

### Project source

- [`KvcProbe_ffmpeg.java`](src/main/java/xin/chunming/KvcProbe_ffmpeg.java)
- [`pts_bridge.py`](pts_bridge.py)
- [`test_pts_bridge.py`](test_pts_bridge.py)
- [`run_pts.sh`](run_pts.sh)

### Acknowledgments

Thanks to ChatGPT and the [unidbg](https://github.com/zhkl0228/unidbg) project.
