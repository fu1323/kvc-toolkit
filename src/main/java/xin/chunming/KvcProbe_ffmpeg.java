package xin.chunming;

import com.github.unidbg.*;
import com.github.unidbg.Module;
import com.github.unidbg.arm.backend.*;
import com.github.unidbg.linux.android.*;
import com.github.unidbg.linux.file.SimpleFileIO;
import com.github.unidbg.file.FileResult;
import com.github.unidbg.pointer.UnidbgPointer;
import com.github.unidbg.memory.MemoryBlock;
import com.sun.jna.Pointer;

import java.io.*;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * unidbg -> PTS/YUV 管道 -> Python/PyAV NUT 封装 -> 本机 FFmpeg。
 * 原始 YUV 不落盘；PTS 从当前解码帧读取。
 *
 *
 */

public class KvcProbe_ffmpeg {
    static AndroidEmulator e;
    static Module lib;

    static long call(String n, Object... args) {
        return lib.findSymbolByName(n).call(e, args).longValue();
    }

    static UnidbgPointer ptr(long a) {
        return UnidbgPointer.pointer(e, a);
    }

    static void check(String label, long r) {
        System.out.println(label + "=" + r);
        if (r < 0 && (int) r < 0) throw new RuntimeException(label + ": " + r);
    }

    public static void main(String[] args) throws Exception {
        if (args.length > 2) {
            throw new IllegalArgumentException("Usage: KvcProbe_ffmpeg [input.mp4] [output.mp4]");
        }
        final File input = new File(args.length > 0 ? args[0] : "/Users/fuchunming/Downloads/input.mp4");
        final File output = new File(args.length > 1 ? args[1] : "output_pts_" + System.currentTimeMillis() + ".mp4");
        if (!input.isFile()) throw new FileNotFoundException(input.toString());
        if (output.exists()) throw new IOException("Refusing to overwrite " + output);

        e = AndroidEmulatorBuilder.for64Bit().setProcessName("kvc-probe").setRootDir(new File(System.getProperty("kvc.rootdir", "work/kvc-root")))
                .addBackendFactory(new DynarmicFactory(true)).addBackendFactory(new Unicorn2Factory(true)).build();
        e.getMemory().setLibraryResolver(new AndroidResolver(23));
        e.getSyscallHandler().setEnableThreadDispatcher(true);
        e.getSyscallHandler().addIOResolver((em, path, flags) -> path.equals("/input.mp4") ? FileResult.success(new SimpleFileIO(flags, input, path)) : null);
        e.getMemory().load(new File(System.getProperty("kvc.libdir", "lib"), "libc++_shared.so"), true);
        lib = e.getMemory().load(new File(System.getProperty("kvc.libdir", "lib"), "libffmpeg.so"), true);
        System.out.println("LOADED " + lib.name + " backend=" + e.getBackend().getClass());
        call("av_log_set_level", 24);
        MemoryBlock handle = e.getMemory().malloc(8, true);
        handle.getPointer().setLong(0, 0);
        check("open", (int) call("avformat_open_input", handle.getPointer(), "/input.mp4", 0, 0));
        Pointer fmt = handle.getPointer().getPointer(0), stream = fmt.getPointer(48).getPointer(0), par = stream.getPointer(192);
        System.out.println("codec=" + Integer.toHexString(par.getInt(4)));
        long dec = call("avcodec_find_decoder_by_name", "libkvc30dec");
        if (dec == 0) throw new RuntimeException("no decoder");
        long ctx = call("avcodec_alloc_context3", ptr(dec));
        check("parameters", (int) call("avcodec_parameters_to_context", ptr(ctx), par));
        System.out.println("threads option=" + (int) call("av_opt_set_int", ptr(ctx), "threads", 1L, 0));
        System.out.println("kvc option=" + (int) call("av_opt_set", ptr(ctx), "kvc30_params", ":kvc30DecodeThreads=1", 1));
        check("decoder open", (int) call("avcodec_open2", ptr(ctx), ptr(dec), 0));
        long pkt = call("av_packet_alloc"), fr = call("av_frame_alloc");
        int count = 0;
        boolean drain = false;
        long started = System.nanoTime();

        // 首帧解出后，才确定尺寸并启动 FFmpeg。
        try (FfmpegPipe pipe = new FfmpegPipe(input, output)) {
            while (true) {
                if (!drain) {
                    int r = (int) call("av_read_frame", fmt, ptr(pkt));
                    if (r == -541478725) drain = true;
                    else if (r < 0) throw new RuntimeException("read=" + r);
                    else if (ptr(pkt).getInt(36) != 0) {
                        call("av_packet_unref", ptr(pkt));
                        continue;
                    }
                }
                int r = (int) call("avcodec_send_packet", ptr(ctx), drain ? null : ptr(pkt));
                if (!drain) call("av_packet_unref", ptr(pkt));
                if (r < 0) throw new RuntimeException("send=" + r);
                while ((r = (int) call("avcodec_receive_frame", ptr(ctx), ptr(fr))) >= 0) {
                    int w = ptr(fr).getInt(112), h = ptr(fr).getInt(116), pix = ptr(fr).getInt(124);

                    if (w <= 0 || h <= 0 || pix != 0) {
                        throw new RuntimeException(
                                "Unsupported frame: " + w + "x" + h + ", pix_fmt=" + pix
                        );
                    }

                    if (count == 0) {
                        System.out.println(
                                "Output: " + w + "x" + h
                                        + ", yuv420p; bridge reads source stream time_base"
                        );
                    }

                    long pts = ptr(fr).getLong(144); // 此 ARM64 库的 AVFrame.pts 偏移
                    if (pts == Long.MIN_VALUE) throw new IOException("Decoded frame has no PTS");
                    pipe.writeFrame(fr, w, h, pts);
                    count++;
                    call("av_frame_unref", ptr(fr));
                    if (count % 100 == 0) System.out.println("frames=" + count);
                }
                if (r < 0 && r != -11 && r != -541478725) throw new RuntimeException("receive=" + r);
                if (drain) break;
            }
            pipe.finish(count);
        } finally {
            e.close();
        }
        System.out.println("SUCCESS frames=" + count + " seconds=" + (System.nanoTime() - started) / 1e9);
    }

    private static final class FfmpegPipe implements AutoCloseable {
        private final File input;
        private final File output;
        private Process process;
        private DataOutputStream out;
        private int width;
        private int height;
        private boolean finished;

        FfmpegPipe(File input, File output) {
            this.input = input;
            this.output = output;
        }

        void writeFrame(long frame, int w, int h, long pts) throws IOException {
            if (process == null) {
                width = w;
                height = h;
                File bridge = new File(System.getProperty("kvc.bridge", "pts_bridge.py"));
                if (!bridge.isFile()) throw new FileNotFoundException("Missing Python bridge: " + bridge);
                String defaultPython = new File(".venv/bin/python").isFile() ? ".venv/bin/python" : "python3";
                List<String> command = new ArrayList<>();
                command.add(System.getProperty("kvc.python", defaultPython));
                command.add("-u");
                command.add(bridge.getAbsolutePath());
                command.add("--input");
                command.add(input.getAbsolutePath());
                command.add("--output");
                command.add(output.getAbsolutePath());
                command.add("--ffmpeg");
                command.add(System.getProperty("kvc.ffmpeg", "ffmpeg"));
                command.add("--ffprobe");
                command.add(System.getProperty("kvc.ffprobe", "ffprobe"));
                String audit = System.getProperty("kvc.pts.audit");
                if (audit != null && !audit.isEmpty()) {
                    command.add("--audit");
                    command.add(new File(audit).getAbsolutePath());
                }
                ProcessBuilder pb = new ProcessBuilder(command);
                pb.redirectError(ProcessBuilder.Redirect.INHERIT);
                pb.redirectOutput(ProcessBuilder.Redirect.INHERIT);
                process = pb.start();
                out = new DataOutputStream(new BufferedOutputStream(process.getOutputStream(), 1024 * 1024));
                // Protocol uses Java DataOutputStream's big-endian byte order.
                out.writeBytes("KVCP0001");
                out.writeInt(w);
                out.writeInt(h);
            } else if (w != width || h != height) {
                throw new IOException("Frame size changed: " + width + "x" + height + " -> " + w + "x" + h);
            }
            long bytes = (long) w * h + 2L * ((w + 1) / 2) * ((h + 1) / 2);
            if (bytes > Integer.MAX_VALUE) throw new IOException("Frame too large");
            out.writeLong(pts);
            out.writeInt((int) bytes);
            // 首帧启动桥接进程之后也会继续执行这里，不丢首帧。
            for (int plane = 0; plane < 3; plane++) {
                Pointer data = ptr(frame).getPointer(plane * 8);
                int stride = ptr(frame).getInt(64 + plane * 4);
                int pw = plane == 0 ? w : (w + 1) / 2;
                int ph = plane == 0 ? h : (h + 1) / 2;
                for (int y = 0; y < ph; y++) {
                    out.write(data.getByteArray((long) y * stride, pw));
                }
            }
        }

        void finish(long count) throws IOException, InterruptedException {
            if (process == null) throw new IOException("No video frame decoded");
            // 显式完成记录：区分正常结束与 Java 崩溃/解码中断。
            out.writeLong(count);
            out.writeInt(0);
            out.close();
            if (!process.waitFor(120, TimeUnit.SECONDS)) {
                throw new IOException("Timed out waiting for Python/FFmpeg to finish");
            }
            if (process.exitValue() != 0) {
                throw new IOException("PTS bridge exited with code " + process.exitValue());
            }
            finished = true;
        }

        @Override
        public void close() throws IOException, InterruptedException {
            if (process == null) return;
            if (!finished && process.isAlive()) process.destroy();
            try {
                if (out != null) out.close();
            } finally {
                if (process.isAlive() && !process.waitFor(5, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    process.waitFor();
                }
            }
        }
    }
}
