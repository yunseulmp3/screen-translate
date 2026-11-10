"""실제 윈도우 화면 녹화 테스트: 전체화면 창에 페이지 1→2→1(되돌아감)→3을 띄우고 Recorder로 녹화."""
import os, sys, time, shutil, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tkinter as tk
from PIL import Image, ImageTk
import app

src = sys.argv[1]
app.set_dpi_aware()
mons = app.list_monitors()
print("monitors:", mons)
mon = mons[0]
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
W, H = mon["full"]["width"], mon["full"]["height"]
root.geometry(f"{W}x{H}+{mon['full']['left']}+{mon['full']['top']}")
imgs = [ImageTk.PhotoImage(Image.open(os.path.join(src, f"screen{i}.png")).resize((W, H))) for i in (1, 2, 3)]
lbl = tk.Label(root, image=imgs[0], bd=0)
lbl.pack(fill="both", expand=True)
cap = os.path.abspath("ci-results/live_captures")
shutil.rmtree(cap, ignore_errors=True); os.makedirs(cap)
counts = []
rec = app.Recorder(mon["work"], cap, on_page=lambda n: counts.append(n))
seq = [(0, 0.5), (1, 2.0), (0, 2.0), (2, 2.0)]


def show(k=0):
    if k == 0:
        rec.start()
    if k < len(seq):
        lbl.configure(image=imgs[seq[k][0]])
        root.after(int(seq[k][1] * 1000) + (1500 if k == 0 else 0), lambda: show(k + 1))
    else:
        paths = rec.stop()
        root.destroy()
        msg = f"live pages={len(paths)} err={rec.error}"
        print(msg)
        open("ci-results/live.txt", "w", encoding="utf-8").write(msg)
        sys.exit(0 if len(paths) == 3 else 1)


root.after(500, show)
root.mainloop()
