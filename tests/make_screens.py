# synthetic "document viewer" screenshots for testing
from PIL import Image, ImageDraw, ImageFont
import textwrap, sys
W,H=1920,1032
SANS="/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
SANSB="/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
SERIF="/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
import glob
def _f(lin, win):
    c = glob.glob("/usr/share/fonts/**/" + lin, recursive=True) + glob.glob("C:/Windows/Fonts/" + win)
    return c[0]
SANS=_f("LiberationSans-Regular.ttf","arial.ttf")
SANSB=_f("LiberationSans-Bold.ttf","arialbd.ttf")
SERIF=_f("LiberationSerif-Regular.ttf","times.ttf")
pages=[
 [("h","Chapter 1. Setting Up Your Vocal Chain"),
  ("p","Before you start recording, make sure your audio interface is connected and recognized by the operating system. A stable connection prevents dropouts and clicks during long sessions."),
  ("p","The input gain should be set so that your loudest phrases peak around -10 dBFS. This leaves enough headroom for unexpected shouts or laughter while keeping the noise floor low."),
  ("b","Use a pop filter about two inches from the capsule."),
  ("b","Keep a consistent distance from the microphone."),
  ("b","Monitor with closed-back headphones to avoid bleed."),
 ],
 [("h","Chapter 2. Routing to OBS"),
  ("p","Hardware loopback lets you send the processed signal from your DAW back into the interface, where OBS can pick it up as a normal input device. This avoids virtual cables and keeps latency predictable."),
  ("p","In REAPER, create a dedicated output bus for the stream mix. Route the vocal track, music player, and notification sounds to this bus, then assign the bus to the loopback channels of your interface."),
  ("p","Finally, open OBS and add the loopback channel as a new audio input capture source. Check the meters while speaking: if the level is too hot, lower the bus fader rather than the input gain."),
 ],
 [("h","Troubleshooting"),
  ("p","If you hear your own voice twice, the direct monitoring and the software monitoring are both active. Turn one of them off so that only a single path reaches your headphones."),
  ("p","Crackling or robotic artifacts usually mean the buffer size is too small for your CPU. Increase the buffer to 256 samples and test again before changing any other settings."),
 ],
]
def render(i,pg,n):
    im=Image.new("RGB",(W,H),(56,56,60)); d=ImageDraw.Draw(im)
    ui=ImageFont.truetype(SANS,15)
    d.rectangle([0,0,W,36],fill=(36,36,40))
    d.text((12,9),"File   Edit   View   Window   Help",font=ui,fill=(220,220,220))
    d.text((W-260,9),f"Page {i+1} of {n}    100%",font=ui,fill=(220,220,220))
    d.rectangle([0,36,220,H],fill=(44,44,48))
    for k in range(n): d.text((20,60+k*30),f"Thumbnail {k+1}",font=ui,fill=(200,200,200))
    px0,py0,px1=560,60,1500
    d.rectangle([px0,py0,px1,H],fill=(255,255,255))
    x=px0+70; y=py0+60; maxw=px1-px0-140
    f=ImageFont.truetype(SERIF,22); fb=ImageFont.truetype(SANSB,30)
    def wrap(t,font,w):
        words=t.split(); lines=[]; cur=""
        for wd in words:
            tt=(cur+" "+wd).strip()
            if d.textlength(tt,font=font)<=w: cur=tt
            else: lines.append(cur); cur=wd
        lines.append(cur); return lines
    for kind,t in pg:
        if kind=="h":
            d.text((x,y),t,font=fb,fill=(20,20,20)); y+=62
        elif kind=="p":
            for ln in wrap(t,f,maxw): d.text((x,y),ln,font=f,fill=(30,30,30)); y+=32
            y+=22
        else:
            d.text((x+10,y),"•",font=f,fill=(30,30,30))
            for ln in wrap(t,f,maxw-40): d.text((x+40,y),ln,font=f,fill=(30,30,30)); y+=32
            y+=8
    d.text((px0+(px1-px0)//2-10,H-40),str(i+1),font=f,fill=(120,120,120))
    return im
if __name__=="__main__":
    import os; out = sys.argv[1] if len(sys.argv) > 1 else "test"; os.makedirs(out, exist_ok=True)
    for i,p in enumerate(pages): render(i,p,len(pages)).save(os.path.join(out, f"screen{i+1}.png"))
