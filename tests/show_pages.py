"""문서 뷰어 흉내: 전체화면(맨 위)에 페이지를 순서대로 띄움. 포커스는 가져가지 않음."""
import sys, time, tkinter as tk
from PIL import Image, ImageTk
src, delay0 = sys.argv[1], float(sys.argv[2])
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True)
W, H = root.winfo_screenwidth(), root.winfo_screenheight()
root.geometry(f"{W}x{H}+0+0")
imgs = [ImageTk.PhotoImage(Image.open(f"{src}/screen{i}.png").resize((W, H))) for i in (1, 2, 3)]
lbl = tk.Label(root, image=imgs[0], bd=0); lbl.pack(fill="both", expand=True)
seq = [(1, 2.0), (0, 2.0), (2, 2.5)]  # 2 → 1(되돌아감) → 3
def step(k=0):
    if k < len(seq):
        lbl.configure(image=imgs[seq[k][0]])
        root.after(int(seq[k][1] * 1000), lambda: step(k + 1))
    else:
        root.after(3000, root.destroy)
root.after(int(delay0 * 1000), step)
root.mainloop()
