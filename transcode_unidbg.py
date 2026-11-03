#!/usr/bin/env python3
"""Mac ARM64 KVC7 sample converter using unidbg, no Android device required."""
import argparse,json,os,subprocess,tempfile,time
from fractions import Fraction
from pathlib import Path
import av

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--java',default='java');a=p.parse_args()
    root=Path(__file__).resolve().parent
    if a.output.exists():raise SystemExit('Output already exists; choose a new path.')
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_tag_string,width,height,time_base,nb_frames','-of','json',str(a.input)]))['streams'][0]
    if (info['codec_tag_string'],info['width'],info['height'],info['time_base'])!=('kvc7',1280,720,'1/1000000'):
        raise SystemExit('Verified prototype requires kvc7, 1280x720, time_base=1/1000000.')
    started=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='kvc-unidbg-') as temp:
        temp=Path(temp);raw=temp/'frames.yuv';pts=temp/'pts.txt';video=temp/'video.mp4'
        cp=os.pathsep.join(map(str,[root/'unidbg/classes',root/'unidbg/deps/*']))
        subprocess.run([a.java,'-Xmx2g',f'-Dkvc.libdir={root/"lib"}',f'-Dkvc.rootdir={temp/"root"}','-cp',cp,'KvcProbe',str(a.input.resolve()),str(raw), '0',str(pts)],check=True,stdin=subprocess.DEVNULL,timeout=300)
        timestamps=[int(v) for v in pts.read_text().splitlines()]
        expected=int(info.get('nb_frames',len(timestamps)))
        if not timestamps or len(timestamps)!=expected or raw.stat().st_size!=len(timestamps)*1280*720*3//2:
            raise RuntimeError('Frame count/size verification failed')
        output=av.open(str(video),'w');stream=output.add_stream('libx264',rate=30)
        stream.width=1280;stream.height=720;stream.pix_fmt='yuv420p'
        stream.time_base=stream.codec_context.time_base=Fraction(1,1000000)
        stream.options={'crf':'18','preset':'fast'}
        last=None;adjusted=0
        try:
            with raw.open('rb') as src:
                for ts in timestamps:
                    if last is not None and ts<=last:ts=last+1;adjusted+=1
                    last=ts;frame=av.VideoFrame(1280,720,'yuv420p');frame.pts=ts;frame.time_base=Fraction(1,1000000)
                    for plane in frame.planes:
                        buf=src.read(plane.buffer_size)
                        if len(buf)!=plane.buffer_size:raise RuntimeError('Truncated frame')
                        plane.update(buf)
                    for packet in stream.encode(frame):output.mux(packet)
                for packet in stream.encode():output.mux(packet)
        finally:output.close()
        subprocess.run(['ffmpeg','-v','error','-n','-i',str(video),'-i',str(a.input),'-map','0:v:0','-map','1:a:0?','-c','copy','-movflags','+faststart',str(a.output)],check=True)
    print(f'Completed {len(timestamps)} frames, {adjusted} timestamp adjustments, {time.monotonic()-started:.2f}s total: {a.output}')
if __name__=='__main__':main()
