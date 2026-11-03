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
/**
*  demo 输出原始yuv
* */
public class KvcProbe {
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
//        final File input = new File(args[0]);
        final File input = new File("/Users/fuchunming/Downloads/input.mp4");
       // int limit = args.length > 2 ? Integer.parseInt(args[2]) : 1;  //limit=1 只解一贞 limit=0 完整
        int limit =0;


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
        try (OutputStream out = new BufferedOutputStream(new FileOutputStream(args.length > 1 ? args[1] : "work/unidbg-first.yuv"));
             PrintWriter times = new PrintWriter(args.length > 3 ? args[3] : "work/unidbg-pts.txt")) {
            while (limit == 0 || count < limit) {
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
                   // if (w != 1280 || h != 720 || pix != 0) throw new RuntimeException("Unexpected frame");




                    if (w <= 0 || h <= 0 || pix != 0) {
                        throw new RuntimeException(
                                "Unsupported frame: " + w + "x" + h + ", pix_fmt=" + pix
                        );
                    }

                    if (count == 0) {
                        System.out.println(
                                "Output: " + w + "x" + h
                                        + ", yuv420p, pts_time_base must follow input stream"
                        );
                    }







                    times.println(ptr(fr).getLong(144));
                    for (int plane = 0; plane < 3; plane++) {
                        Pointer data = ptr(fr).getPointer(plane * 8);
                        int stride = ptr(fr).getInt(64 + plane * 4), pw = plane == 0 ? w : (w + 1) / 2, ph = plane == 0 ? h : (h + 1) / 2;
                        for (int y = 0; y < ph; y++) out.write(data.getByteArray((long) y * stride, pw));
                    }
                    count++;
                    call("av_frame_unref", ptr(fr));
                    if (count % 100 == 0) System.out.println("frames=" + count);
                    if (limit > 0 && count >= limit) break;
                }
                if (r < 0 && r != -11 && r != -541478725) throw new RuntimeException("receive=" + r);
                if (drain) break;
            }
        }
        System.out.println("SUCCESS frames=" + count + " seconds=" + (System.nanoTime() - started) / 1e9);
        e.close();
    }
}
