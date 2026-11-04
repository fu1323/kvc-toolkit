#!/usr/bin/env python3
"""KVCP0001 (Java big-endian records) -> rawvideo/NUT -> native ffmpeg.

Only bounded frame buffers are retained. No raw YUV or NUT files are created.
"""
import argparse
import json
import struct
import signal
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

try:
    import av
except ImportError:
    raise SystemExit("PyAV is missing. Run: python -m pip install -r requirements-pts.txt")

MAGIC = b'KVCP0001'
NO_PTS = -(1 << 63)


def read_exact(source, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = source.read(size - len(chunks))
        if not part:
            raise EOFError('Java stream truncated (missing frame bytes or completion record)')
        chunks.extend(part)
    return bytes(chunks)


def probe_input(path, ffprobe):
    result = subprocess.run([
        ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(path)
    ], capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout)['streams']
    video = next((s for s in streams if s['index'] == 0), None)
    if video is None or video['codec_type'] != 'video':
        raise ValueError('This decoder currently requires video at stream index 0')
    tb = Fraction(video['time_base'])
    if tb <= 0:
        raise ValueError('Invalid source video time_base')
    for key in ('r_frame_rate', 'avg_frame_rate'):
        try:
            rate = Fraction(video[key])
            if rate > 0:
                break
        except (KeyError, ValueError, ZeroDivisionError):
            pass
    else:
        raise ValueError('No valid nominal frame rate for final-frame duration')
    return video, tb, rate


def transcode(source, input_path, output_path, ffmpeg='ffmpeg', ffprobe='ffprobe', audit_path=None):
    input_path, output_path = Path(input_path).resolve(), Path(output_path).absolute()
    if output_path.exists():
        raise FileExistsError('Refusing to overwrite ' + str(output_path))
    if not output_path.parent.is_dir():
        raise ValueError('Output directory does not exist: ' + str(output_path.parent))
    metadata, tb, rate = probe_input(input_path, ffprobe)
    magic, width, height = struct.unpack('>8sII', read_exact(source, 16))
    if magic != MAGIC or not (0 < width <= 16384 and 0 < height <= 16384):
        raise ValueError('Invalid KVCP0001 stream header')
    if width % 2 or height % 2:
        raise ValueError('libx264 yuv420p output requires even width and height')
    frame_size = width * height + 2 * ((width + 1) // 2) * ((height + 1) // 2)
    # The decoder emits frame PTS in the original video stream time base.
    # Keep that timeline for BOTH inputs: no per-input start-at-zero adjustment.
    command = [ffmpeg, '-hide_banner', '-nostdin', '-n', '-copyts',
               '-f', 'nut', '-i', 'pipe:0', '-i', str(input_path),
               '-map', '0:v:0', '-map', '1:a:0?',
               '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
               '-fps_mode:v', 'passthrough', '-enc_time_base:v', 'demux',
               '-video_track_timescale', str(tb.denominator),
               '-c:a', 'copy', '-avoid_negative_ts', 'disabled',
               '-movflags', '+faststart']
    # Preserve declared source colour information through the rawvideo bridge.
    for key, option in [('color_range', '-color_range'), ('color_space', '-colorspace'),
                        ('color_transfer', '-color_trc'), ('color_primaries', '-color_primaries')]:
        value = metadata.get(key)
        if value and value not in ('unknown', 'unspecified'):
            command += [option, value]
    sar = metadata.get('sample_aspect_ratio', '1:1')
    if sar not in ('N/A', '0:1', '1:1'):
        a, b = map(int, sar.split(':'))
        if a > 0 and b > 0:
            command += ['-vf', 'setsar={}/{}'.format(a, b)]
    command.append(str(output_path))
    audit = open(audit_path, 'x', encoding='utf-8') if audit_path else None
    if audit:
        audit.write('frame,original_pts,output_pts,time_base\n')
    process = None
    container = None
    count = corrections = 0
    pending = None
    last_original = last_output = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        container = av.open(process.stdin, mode='w', format='nut',
                            options={'avoid_negative_ts': 'disabled', 'flush_packets': '1'})
        stream = container.add_stream('rawvideo', rate=rate)
        stream.width, stream.height, stream.pix_fmt = width, height, 'yuv420p'
        stream.time_base = tb
        stream.codec_context.time_base = tb
        container.start_encoding()
        print('PTS bridge: {}x{}, source time_base={}, NUT time_base={}'.format(
            width, height, tb, stream.time_base), file=sys.stderr)

        def mux(record, duration):
            pts, pixels = record
            packet = av.Packet(pixels)
            packet.stream = stream
            packet.pts = packet.dts = pts  # raw frames have no decode/display reordering
            packet.time_base = tb
            packet.duration = duration
            packet.is_keyframe = True
            container.mux(packet)  # PyAV rescales packet timestamps to stream.time_base.

        while True:
            original, size = struct.unpack('>qI', read_exact(source, 12))
            if size == 0:
                if original != count or count == 0:
                    raise ValueError('Invalid completion record/frame count')
                if source.read(1):
                    raise ValueError('Unexpected bytes after completion record')
                break
            if size != frame_size:
                raise ValueError('Frame byte count mismatch: {} != {}'.format(size, frame_size))
            if original == NO_PTS:
                raise ValueError('Missing AVFrame PTS; refusing to invent timestamps')
            if original < 0:
                raise ValueError('Negative video PTS requires a common audio/video timeline shift; unsupported here')
            if last_original is not None and original < last_original:
                raise ValueError('PTS moved backwards at frame {}'.format(count + 1))
            pts = original if last_output is None else max(original, last_output + 1)
            if pts != original:
                corrections += 1
                print('PTS correction: frame {}: {} -> {} (time_base={})'.format(
                    count + 1, original, pts, tb), file=sys.stderr)
            pixels = read_exact(source, size)
            if pending is not None:
                mux(pending, pts - pending[0])
            pending = (pts, pixels)
            count += 1
            if audit:
                audit.write('{},{},{},{}\n'.format(count, original, pts, tb))
            last_original, last_output = original, pts
        # Use source track end when available, otherwise the nominal frame duration.
        duration = max(1, round(1 / rate / tb))
        if 'duration_ts' in metadata and 'start_pts' in metadata:
            remaining = int(metadata['start_pts']) + int(metadata['duration_ts']) - pending[0]
            if remaining > 0:
                duration = remaining
        mux(pending, duration)
        container.close()
        container = None
        process.stdin.close()
        result = process.wait(timeout=120)
        if result:
            raise RuntimeError('Native FFmpeg exited with code {}'.format(result))
        print('PTS bridge SUCCESS: frames={}, corrections={}, output={}'.format(
            count, corrections, output_path), file=sys.stderr)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if container is not None:
            try:
                container.close()
            except Exception:
                pass
        if process is not None and process.stdin:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        if audit:
            audit.close()


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Bridge terminated')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--ffprobe', default='ffprobe')
    parser.add_argument('--audit', help='Optional small CSV of PTS, opened without overwriting')
    args = parser.parse_args()
    try:
        transcode(sys.stdin.buffer, args.input, args.output, args.ffmpeg, args.ffprobe, args.audit)
    except (Exception, KeyboardInterrupt) as error:
        print('PTS bridge FAILED: {}: {}'.format(type(error).__name__, error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
