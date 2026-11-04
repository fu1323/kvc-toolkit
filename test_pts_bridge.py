"""Small integration checks. Requires PyAV, ffmpeg and ffprobe, but no KVC library."""
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from fractions import Fraction

import pts_bridge as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=size=16x16:rate=30:duration=0.2', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=0.2',
                        '-c:v', 'libx264', '-c:a', 'aac', '-video_track_timescale', '1000000',
                        '-output_ts_offset', '5', str(self.source)], check=True)

    def wire(self, pts, complete=True):
        pixels = bytes([80]) * 256 + bytes([128]) * 128
        data = bytearray(struct.pack('>8sII', bridge.MAGIC, 16, 16))
        for p in pts:
            data.extend(struct.pack('>qI', p, len(pixels)))
            data.extend(pixels)
        if complete:
            data.extend(struct.pack('>qI', len(pts), 0))
        return io.BytesIO(data)

    def probe(self, file, args):
        return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', *args,
                                                  '-of', 'json', str(file)]))

    def test_vfr_duplicate_and_nonzero_audio_timeline(self):
        out = self.root / 'result.mp4'
        bridge.transcode(self.wire([5000000, 5033333, 5033333, 5100000]), self.source, out)
        frames = self.probe(out, ['-select_streams', 'v:0', '-show_frames',
                                 '-show_entries', 'frame=pts'])['frames']
        self.assertEqual([int(f['pts']) for f in frames], [5000000, 5033333, 5033334, 5100000])
        args = ['-select_streams', 'a:0', '-show_packets', '-show_data_hash', 'sha256',
                '-show_entries', 'packet=pts,dts,duration,data_hash']
        self.assertEqual(self.probe(self.source, args)['packets'], self.probe(out, args)['packets'])

    def test_non_microsecond_timebase(self):
        source = self.root / '90k.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.source), '-map', '0:v:0',
                        '-c', 'copy', '-video_track_timescale', '90000', str(source)], check=True)
        out = self.root / '90k-out.mp4'
        bridge.transcode(self.wire([0, 3000, 7500, 9000]), source, out)
        result = self.probe(out, ['-select_streams', 'v:0', '-show_streams', '-show_frames',
                                 '-show_entries', 'stream=time_base:frame=pts'])
        tb = Fraction(result['streams'][0]['time_base'])
        self.assertEqual([int(f['pts']) * tb for f in result['frames']],
                         [Fraction(p, 90000) for p in [0, 3000, 7500, 9000]])

    def test_truncated_stream_is_not_success(self):
        with self.assertRaises(EOFError):
            bridge.transcode(self.wire([5000000], complete=False), self.source, self.root / 'bad.mp4')

    def test_backwards_pts_rejected(self):
        with self.assertRaisesRegex(ValueError, 'backwards'):
            bridge.transcode(self.wire([5000000, 4999999]), self.source, self.root / 'bad.mp4')

    def test_existing_output_unchanged(self):
        out = self.root / 'exists.mp4'
        out.write_bytes(b'keep me')
        with self.assertRaises(FileExistsError):
            bridge.transcode(self.wire([5000000]), self.source, out)
        self.assertEqual(out.read_bytes(), b'keep me')


if __name__ == '__main__':
    unittest.main()
