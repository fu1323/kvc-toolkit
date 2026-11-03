typedef unsigned long size_t;
extern int dprintf(int,const char*,...);
#define printf(...) dprintf(2,__VA_ARGS__)
extern void exit(int); extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*); extern char *dlerror(void); extern void *fopen(const char*,const char*); extern size_t fwrite(const void*,size_t,size_t,void*); extern int fclose(void*);
#define API(ret,n,args) ret (*n)args=dlsym(lib,#n); if(!n){printf("missing %s\n",#n);exit(2);}
int main(void){
void *lib=dlopen("/data/local/tmp/kvc-probe/libffmpeg.so",2);if(!lib){printf("dlopen: %s\n",dlerror());return 1;}
API(int,avformat_open_input,(void**,const char*,void*,void*));
API(int,avformat_find_stream_info,(void*,void*));
API(void*,avcodec_find_decoder_by_name,(const char*));
API(void*,avcodec_alloc_context3,(void*));
API(int,avcodec_parameters_to_context,(void*,void*));
API(int,avcodec_open2,(void*,void*,void*));
API(void*,av_packet_alloc,(void)); API(void*,av_frame_alloc,(void));
API(int,av_read_frame,(void*,void*)); API(void,av_packet_unref,(void*));
API(int,avcodec_send_packet,(void*,void*)); API(int,avcodec_receive_frame,(void*,void*));
API(void,av_frame_unref,(void*)); API(const char*,av_get_pix_fmt_name,(int));
API(void,av_log_set_level,(int)); av_log_set_level(24);
void *fmt=0;int r=avformat_open_input(&fmt,"/data/local/tmp/kvc-probe/input.mp4",0,0);printf("open %d\n",r);if(r<0)return 2;
void **streams=*(void***)((char*)fmt+48);void *par=*(void**)((char*)streams[0]+192);printf("codec type=%d id=%x\n",*(int*)par,*(int*)((char*)par+4));
void *dec=avcodec_find_decoder_by_name("libkvc30dec");printf("decoder %p\n",dec);if(!dec)return 3;
void *ctx=avcodec_alloc_context3(dec);r=avcodec_parameters_to_context(ctx,par);if(r<0)return 4;
r=avcodec_open2(ctx,dec,0);printf("decoder open %d\n",r);if(r<0)return 5;
void *pkt=av_packet_alloc(),*fr=av_frame_alloc(),*out=fopen("/proc/self/fd/1","wb");if(!out)return 6;
int count=0,draining=0;
while(1){
if(!draining){r=av_read_frame(fmt,pkt);if(r<0)draining=1;else if(*(int*)((char*)pkt+36)!=0){av_packet_unref(pkt);continue;}}
r=avcodec_send_packet(ctx,draining?0:pkt);if(!draining)av_packet_unref(pkt);if(r<0){printf("send error %d\n",r);return 7;}
while((r=avcodec_receive_frame(ctx,fr))>=0){
unsigned char **data=fr;int *ls=(int*)((char*)fr+64);int w=*(int*)((char*)fr+112),h=*(int*)((char*)fr+116),pix=*(int*)((char*)fr+124);
if(!count)printf("FRAME %dx%d fmt=%d %s strides=%d,%d,%d\n",w,h,pix,av_get_pix_fmt_name(pix),ls[0],ls[1],ls[2]);

if(pix!=0){printf("unsupported output pixel format\n");return 8;}
long long pts=*(long long*)((char*)fr+144);
if(fwrite(&pts,8,1,out)!=1)return 9;
for(int p=0;p<3;p++){int pw=p?(w+1)/2:w,ph=p?(h+1)/2:h;for(int y=0;y<ph;y++)if(fwrite(data[p]+y*ls[p],1,pw,out)!=(size_t)pw)return 9;}
count++;av_frame_unref(fr);
}
if(r!=-11 && r!=-541478725){printf("receive error %d\n",r);return 10;}if(draining)break;
}
fclose(out);printf("DONE frames=%d\n",count);return 0;
}
void _start(void){exit(main());}
