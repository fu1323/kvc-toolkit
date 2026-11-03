#!/usr/bin/env python3
"""Sample-specific KVC7 Android bridge; requires Python av, adb and ffmpeg."""
import argparse, json, struct, subprocess, tempfile
from fractions import Fraction
from pathlib import Path
import av

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input',type=Path);ap.add_argument('output',type=Path)
    ap.add_argument('--adb',default='adb');ap.add_argument('--serial')
    args=ap.parse_args();root=Path(__file__).resolve().parent
    if args.output.exists():raise SystemExit('Output already exists; choose a new path.')
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_tag_string,width,height,time_base,nb_frames','-of','json',str(args.input)]))['streams'][0]
    if (info['codec_tag_string'],info['width'],info['height'],info['time_base'])!=('kvc7',1280,720,'1/1000000'):
        raise SystemExit('This verified prototype requires kvc7, 1280x720, time_base=1/1000000.')
    adb=[args.adb]+(['-s',args.serial] if args.serial else [])
    def run(*a):subprocess.run(adb+list(a),check=True)
    remote='/data/local/tmp/kvc-probe'
    run('shell','mkdir','-p',remote)
    run('push',str(root/'phone_decode'),str(root/'lib/libffmpeg.so'),str(root/'lib/libc++_shared.so'),remote+'/')
    run('push',str(args.input),remote+'/input.mp4')
    run('shell','chmod','755',remote+'/phone_decode')
    with tempfile.TemporaryDirectory(prefix='kvc-') as td:
        video=Path(td)/'video.mp4'
        process=subprocess.Popen(adb+['exec-out',f"sh -c 'LD_LIBRARY_PATH={remote} {remote}/phone_decode 2>{remote}/decode.log'"],stdout=subprocess.PIPE)
        def readn(n):
            b=bytearray()
            while len(b)<n:
                chunk=process.stdout.read(n-len(b))
                if not chunk:break
                b.extend(chunk)
            return b
        output=av.open(str(video),'w');stream=output.add_stream('libx264',rate=30)
        stream.width=1280;stream.height=720;stream.pix_fmt='yuv420p'
        stream.time_base=stream.codec_context.time_base=Fraction(1,1000000)
        stream.options={'crf':'18','preset':'fast'}
        count=0;last_pts=None;adjusted=0
        try:
            while True:
                header=readn(8)
                if not header:break
                if len(header)!=8:raise RuntimeError('Truncated frame timestamp')
                frame=av.VideoFrame(1280,720,'yuv420p');frame.pts=struct.unpack('<q',header)[0]
                if last_pts is not None and frame.pts<=last_pts:
                    frame.pts=last_pts+1;adjusted+=1
                last_pts=frame.pts
                frame.time_base=Fraction(1,1000000)
                for plane in frame.planes:
                    data=readn(plane.buffer_size)
                    if len(data)!=plane.buffer_size:raise RuntimeError('Truncated frame')
                    plane.update(data)
                for packet in stream.encode(frame):output.mux(packet)
                count+=1
                if count%100==0:print(f'{count} frames',flush=True)
            for packet in stream.encode():output.mux(packet)
        finally:
            output.close();process.stdout.close()
        rc=process.wait()
        run('shell','cat',remote+'/decode.log')
        if rc or count==0:raise RuntimeError(f'Decoder failed: {rc}, {count} frames')
        if 'nb_frames' in info and count!=int(info['nb_frames']):raise RuntimeError(f'Frame count mismatch: {count} vs {info["nb_frames"]}')
        subprocess.run(['ffmpeg','-v','warning','-n','-i',str(video),'-i',str(args.input),'-map','0:v:0','-map','1:a:0?','-c','copy','-movflags','+faststart',str(args.output)],check=True)
        print(f'Completed {count} frames, adjusted {adjusted} repeated/non-increasing timestamps: {args.output}')
if __name__=='__main__':main()
