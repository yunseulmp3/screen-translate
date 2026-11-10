# 테스트 영상: 페이지1 → 넘김 애니메이션 → 페이지2 → 페이지1로 되돌아감(중복) → 페이지3, 깜빡이는 커서
import sys, os, shutil, tempfile, cv2, numpy as np
src=sys.argv[1:4]; out=sys.argv[4]
imgs=[cv2.imdecode(np.fromfile(p,dtype=np.uint8),cv2.IMREAD_COLOR) for p in src]  # 한글 경로 대응
H,W=imgs[0].shape[:2]; fps=30
tmp=os.path.join(tempfile.gettempdir(),"st_rec_tmp.mp4")
vw=cv2.VideoWriter(tmp,cv2.VideoWriter_fourcc(*"mp4v"),fps,(W,H))
def hold(img,sec):
    for k in range(int(sec*fps)):
        f=img.copy()
        if (k//15)%2==0: cv2.rectangle(f,(700,600),(702,622),(0,0,0),-1)  # caret
        vw.write(f)
def trans(a,b,sec=0.35):
    n=int(sec*fps)
    for k in range(n):
        t=(k+1)/n; off=int(W*t)
        f=np.empty_like(a); f[:, :W-off]=a[:, off:]; f[:, W-off:]=b[:, :off]; vw.write(f)
hold(imgs[0],1.5); trans(imgs[0],imgs[1]); hold(imgs[1],0.4)  # 너무 짧게 멈춤 → 그래도 다음에 다시 2초
hold(imgs[1],1.6); trans(imgs[1],imgs[0]); hold(imgs[0],1.2); trans(imgs[0],imgs[2]); hold(imgs[2],0.5)
vw.release()
shutil.move(tmp,out)
