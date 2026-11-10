# 어려운 화면: 작은 글씨 웹페이지 2단 + 다크모드
from PIL import Image, ImageDraw, ImageFont
import glob, sys
F=glob.glob("/usr/share/fonts/**/LiberationSans-Regular.ttf",recursive=True)+glob.glob("C:/Windows/Fonts/arial.ttf")
FB=glob.glob("/usr/share/fonts/**/LiberationSans-Bold.ttf",recursive=True)+glob.glob("C:/Windows/Fonts/arialbd.ttf")
def wrap(d,t,font,w):
    words=t.split(); lines=[]; cur=""
    for wd in words:
        tt=(cur+" "+wd).strip()
        if d.textlength(tt,font=font)<=w: cur=tt
        else: lines.append(cur); cur=wd
    lines.append(cur); return lines
A="Latency is the delay between the moment a sound enters the microphone and the moment it comes out of the speakers. For live streaming, anything under ten milliseconds feels instant to most performers, while delays above twenty milliseconds become distracting."
B="Sample rate and buffer size work together. A higher sample rate shortens each buffer in time, but it also increases the load on the processor. Most streamers are well served by 48 kHz with a buffer of 128 or 256 samples."
C="When in doubt, measure. Record a click through the full chain and compare the recorded waveform with the original to find the real round-trip latency of your setup."
D="Dark mode pages are harder to read for some recognition engines, because the text is light on a dark background. This test makes sure the program handles inverted colors without losing words."
E="If a paragraph continues onto the next screen, the program keeps both parts but removes any paragraph that was already captured on the previous screen."
def page(dark=False):
    W,H=1920,1032; bg=(30,30,32) if dark else (255,255,255); fg=(225,225,225) if dark else (25,25,25)
    im=Image.new("RGB",(W,H),bg); d=ImageDraw.Draw(im)
    f=ImageFont.truetype(F[0],15); fb=ImageFont.truetype(FB[0],24)
    d.rectangle([0,0,W,70],fill=(60,60,64)); d.text((20,25),"https://example.com/guide/latency      Search   Sign in",font=f,fill=(230,230,230))
    d.text((300,110),"Dark Mode and Scrolling" if dark else "Understanding Latency in Streaming Setups",font=fb,fill=fg)
    y0=170
    for col,txts in (((300,[D]),(1000,[E])) if dark else ((300,[A,C]),(1000,[B]))):
        y=y0
        for t in txts:
            for ln in wrap(d,t,f,600): d.text((col,y),ln,font=f,fill=fg); y+=22
            y+=16
    return im
page(False).save(sys.argv[1] if len(sys.argv)>1 else "/home/claude/work/test/hard1.png")
page(True).save(sys.argv[2] if len(sys.argv)>2 else "/home/claude/work/test/hard2.png")
