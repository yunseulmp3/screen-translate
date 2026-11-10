"""형이 실제로 쓰는 흐름 재현: 프로그램 창에서 '녹화 시작' 버튼 클릭 → 창 내려감 → 뷰어가 페이지 넘김 → F9로 종료."""
import os, sys, subprocess, ctypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app
src = sys.argv[1]
app.set_dpi_aware()
a = app.App()
a.v_beep.set(False)
res = {}
def fake_pipeline(paths, session, filter_chrome):
    res["paths"] = len(paths)
    a.root.after(200, a.root.destroy)
a.run_pipeline = fake_pipeline
u = ctypes.windll.user32
viewer = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "show_pages.py"), src, "6.0"])
def start():
    a.root.deiconify(); a.root.focus_force(); a.root.update()
    res["fg_before"] = u.GetForegroundWindow() == a.own_hwnd
    a.toggle()  # = 버튼 클릭
    res["fg_after_iconify"] = u.GetForegroundWindow() == a.own_hwnd
    res["iconic"] = bool(u.IsIconic(a.own_hwnd))
def stop():
    a.toggle()  # = F9
    res["stats"] = dict(a.recorder.stats) if a.recorder else None
a.root.after(3000, start)  # 뷰어가 1페이지를 띄운 뒤 '녹화 시작' 클릭
def stop2():
    rec = a.recorder
    a.toggle()
    res["stats"] = rec.stats
a.root.after(14500, stop2)  # 넘김(6~12.5초) 끝난 뒤 F9
a.root.mainloop()
if viewer: viewer.wait(timeout=20)
msg = f"gui flow: {res}"
print(msg)
os.makedirs("ci-results", exist_ok=True)
open("ci-results/gui_record.txt", "w", encoding="utf-8").write(msg)
sys.exit(0 if res.get("paths") == 3 else 1)
