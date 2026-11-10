"""화면번역 — 영어 화면을 녹화하듯 넘기면 한국어 번역 PDF로 만들어 주는 윈도우 프로그램.

사용: F9(또는 버튼)로 녹화 시작 → 문서를 한 장씩 넘김 → F9로 끝 → PDF 자동으로 열림
"""
import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback

IS_WIN = os.name == "nt"
APP_DIR_NAME = "ScreenTranslate"


# ───────────────────────── 경로 / 설정 / 로그 ─────────────────────────

def documents_dir():
    if IS_WIN:
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def output_root():
    return os.path.join(documents_dir(), "화면번역")


def appdata_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def log(msg):
    try:
        with open(os.path.join(appdata_dir(), "log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except Exception:
        pass


DEFAULTS = {"monitor": 0, "pick_region": False, "style": "layout", "beep": True}


def load_settings():
    try:
        with open(os.path.join(appdata_dir(), "settings.json"), encoding="utf-8") as f:
            s = json.load(f)
        return {**DEFAULTS, **s}
    except Exception:
        return dict(DEFAULTS)


def save_settings(s):
    try:
        with open(os.path.join(appdata_dir(), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def new_session_dir():
    d = os.path.join(output_root(), time.strftime("%Y-%m-%d_%H%M%S"))
    os.makedirs(os.path.join(d, "캡처"), exist_ok=True)
    return d


# ───────────────────────── 윈도우: 모니터 / 창 ─────────────────────────

def set_dpi_aware():
    if not IS_WIN:
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def list_monitors():
    """[{name, left, top, width, height}] — 작업표시줄을 뺀 '작업 영역' 기준."""
    import mss
    out = []
    with mss.mss() as sct:
        mons = sct.monitors[1:]
    for i, m in enumerate(mons):
        work = dict(left=m["left"], top=m["top"], width=m["width"], height=m["height"])
        primary = (m["left"] == 0 and m["top"] == 0)
        if IS_WIN:
            try:
                import ctypes
                from ctypes import wintypes

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
                u = ctypes.windll.user32
                u.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
                u.MonitorFromPoint.restype = wintypes.HMONITOR
                pt = wintypes.POINT(m["left"] + m["width"] // 2, m["top"] + m["height"] // 2)
                hmon = u.MonitorFromPoint(pt, 2)
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    r = mi.rcWork
                    work = dict(left=r.left, top=r.top, width=r.right - r.left, height=r.bottom - r.top)
                    primary = bool(mi.dwFlags & 1)
            except Exception as e:
                log("work area 실패: " + repr(e))
        name = f"모니터 {i + 1}{' (주 모니터)' if primary else ''} · {m['width']}×{m['height']}"
        out.append(dict(name=name, full=dict(m), work=work, primary=primary))
    out.sort(key=lambda x: (not x["primary"]))
    return out


def foreground_hwnd():
    if not IS_WIN:
        return None
    import ctypes
    return ctypes.windll.user32.GetForegroundWindow()


def own_window_on_screen(hwnd):
    """이 프로그램 창이 '내려가 있지 않고' 맨 앞에 있을 때만 True.
    (창을 내려도 윈도우가 그 창을 계속 '활성 창'으로 잡고 있는 경우가 있어서 최소화 여부를 같이 봐야 함)"""
    if not IS_WIN or not hwnd:
        return False
    import ctypes
    u = ctypes.windll.user32
    return u.GetForegroundWindow() == hwnd and not u.IsIconic(hwnd) and bool(u.IsWindowVisible(hwnd))


def beep(kind="page"):
    if not IS_WIN:
        return

    def _b():
        try:
            import winsound
            if kind == "start":
                winsound.Beep(880, 90); winsound.Beep(1320, 120)
            elif kind == "stop":
                winsound.Beep(1320, 90); winsound.Beep(880, 140)
            else:
                winsound.Beep(1500, 45)
        except Exception:
            pass
    threading.Thread(target=_b, daemon=True).start()


# ───────────────────────── 녹화(캡처) ─────────────────────────

class Recorder:
    """지정 영역을 0.25초마다 찍어서, 페이지가 바뀌고 멈춘 순간만 PNG로 저장."""

    def __init__(self, rect, cap_dir, on_page, own_hwnd=None, interval=0.25):
        from screentrans.pages import PageDetector
        self.rect = rect
        self.cap_dir = cap_dir
        self.paths = []
        self._on_page_cb = on_page
        self.own_hwnd = own_hwnd
        self.interval = interval
        self.det = PageDetector(self._on_page)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.error = None
        self.stats = {"grabbed": 0, "skipped_own": 0, "fg_own_minimized": 0}

    def _on_page(self, rgb, n):
        from screentrans.imageio import save_png
        p = os.path.join(self.cap_dir, f"page_{n:03d}.png")
        save_png(p, rgb)
        self.paths.append(p)
        self._on_page_cb(n)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()
        self.thread.join(timeout=5)
        log(f"녹화 통계: {self.stats}, 저장 {len(self.paths)}장")
        if not self.paths and self.det.last_frame is not None:
            try:  # 원인 확인용: 마지막으로 찍힌 화면을 남겨둠
                from screentrans.imageio import save_png
                save_png(os.path.join(os.path.dirname(self.cap_dir), "_마지막화면.png"), self.det.last_frame)
            except Exception:
                pass
        return self.paths

    def _run(self):
        import mss
        import numpy as np
        try:
            with mss.mss() as sct:
                while not self._stop.is_set():
                    t0 = time.monotonic()
                    if self.own_hwnd and foreground_hwnd() == self.own_hwnd and IS_WIN:
                        import ctypes
                        if ctypes.windll.user32.IsIconic(self.own_hwnd):
                            self.stats["fg_own_minimized"] += 1  # 예전 버그 상황(내려간 창이 활성으로 남음) 기록용
                    if own_window_on_screen(self.own_hwnd):
                        self.stats["skipped_own"] += 1
                        time.sleep(self.interval)  # 이 프로그램 창이 화면에 떠 있으면 찍지 않음
                        continue
                    shot = sct.grab(self.rect)
                    self.stats["grabbed"] += 1
                    rgb = np.asarray(shot)[:, :, 2::-1]  # BGRA → RGB
                    self.det.feed(rgb, t0)
                    time.sleep(max(0.0, self.interval - (time.monotonic() - t0)))
                self.det.flush()
        except Exception as e:
            self.error = e
            log("녹화 오류: " + traceback.format_exc())


# ───────────────────────── 영역 고르기(드래그) ─────────────────────────

def pick_region(root, mon_full):
    """모니터 위에 반투명 막을 씌우고 드래그로 영역 선택. Esc = 취소(None)."""
    import tkinter as tk
    result = {"rect": None}
    top = tk.Toplevel(root)
    top.overrideredirect(True)
    top.geometry(f"{mon_full['width']}x{mon_full['height']}+{mon_full['left']}+{mon_full['top']}")
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.35)
    cv = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)
    cv.create_text(mon_full["width"] // 2, 60, fill="white", font=("Malgun Gothic", 20, "bold"),
                   text="번역할 문서 부분을 드래그하세요   (Esc: 취소)")
    st = {}

    def down(e):
        st["x"], st["y"] = e.x, e.y
        st["r"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#ffd400", width=4)

    def move(e):
        if "r" in st:
            cv.coords(st["r"], st["x"], st["y"], e.x, e.y)

    def up(e):
        if "x" not in st:
            return
        x0, x1 = sorted((st["x"], e.x))
        y0, y1 = sorted((st["y"], e.y))
        if x1 - x0 > 40 and y1 - y0 > 40:
            result["rect"] = dict(left=mon_full["left"] + x0, top=mon_full["top"] + y0,
                                  width=x1 - x0, height=y1 - y0)
        top.destroy()

    cv.bind("<ButtonPress-1>", down)
    cv.bind("<B1-Motion>", move)
    cv.bind("<ButtonRelease-1>", up)
    top.bind("<Escape>", lambda e: top.destroy())
    top.focus_force()
    top.grab_set()
    root.wait_window(top)
    return result["rect"]


# ───────────────────────── 화면(GUI) ─────────────────────────

class App:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.s = load_settings()
        self.q = queue.Queue()
        self.recorder = None
        self.session = None
        self.busy = False
        self.last_dir = None

        self.root = root = tk.Tk()
        root.title("화면번역")
        root.resizable(False, False)
        try:
            root.iconbitmap(default=resource_path("icon.ico"))
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use("vista" if IS_WIN else "clam")
        except Exception:
            pass
        F = ("Malgun Gothic", 10)
        style.configure(".", font=F)
        style.configure("Big.TButton", font=("Malgun Gothic", 13, "bold"), padding=(10, 12))
        style.configure("Title.TLabel", font=("Malgun Gothic", 16, "bold"))
        style.configure("Sub.TLabel", foreground="#666")

        fr = ttk.Frame(root, padding=18)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="화면번역", style="Title.TLabel").pack(anchor="w")
        ttk.Label(fr, text="영어 화면을 넘기면서 녹화 → 한국어 번역 PDF", style="Sub.TLabel").pack(anchor="w", pady=(0, 12))

        self.monitors = list_monitors()
        row = ttk.Frame(fr)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text="녹화할 화면").pack(side="left")
        self.mon_var = tk.StringVar()
        self.mon_cb = ttk.Combobox(row, state="readonly", width=30, textvariable=self.mon_var,
                                   values=[m["name"] for m in self.monitors])
        idx = min(self.s.get("monitor", 0), max(0, len(self.monitors) - 1))
        if self.monitors:
            self.mon_cb.current(idx)
        self.mon_cb.pack(side="right")

        self.v_region = tk.BooleanVar(value=self.s["pick_region"])
        self.v_style = tk.StringVar(value=self.s.get("style", "layout"))
        self.v_beep = tk.BooleanVar(value=self.s["beep"])
        ttk.Label(fr, text="결과 PDF 모양").pack(anchor="w", pady=(6, 0))
        for val, txt in (("layout", "원본 모양 그대로 — 사진·배치 유지, 영어 자리에 한국어"),
                         ("text", "번역문만 정리 — 한국어 + 영어 원문 작게")):
            ttk.Radiobutton(fr, text=txt, value=val, variable=self.v_style, command=self._save).pack(anchor="w", padx=(10, 0))
        ttk.Label(fr, text="").pack()
        for var, txt in ((self.v_region, "시작할 때 번역할 부분만 드래그로 고르기"),
                         (self.v_beep, "한 장 저장될 때마다 '삑' 소리")):
            ttk.Checkbutton(fr, text=txt, variable=var, command=self._save).pack(anchor="w", pady=1)

        self.btn = ttk.Button(fr, text="●  녹화 시작   (F9)", style="Big.TButton", command=self.toggle)
        self.btn.pack(fill="x", pady=(14, 6))
        self.btn_file = ttk.Button(fr, text="녹화해 둔 영상 / 캡처 이미지로 만들기…", command=self.from_file)
        self.btn_file.pack(fill="x")

        self.pb = ttk.Progressbar(fr, mode="determinate", maximum=1000)
        self.pb.pack(fill="x", pady=(14, 4))
        self.status = tk.StringVar(value="대기 중 · F9를 누르면 녹화가 시작돼요")
        ttk.Label(fr, textvariable=self.status, wraplength=380).pack(anchor="w")
        self.btn_open = ttk.Button(fr, text="결과 폴더 열기", command=self.open_folder)
        self.btn_open.pack(anchor="e", pady=(10, 0))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.update_idletasks()
        try:
            self.own_hwnd = int(root.wm_frame(), 16)
        except Exception:
            self.own_hwnd = None
        self._setup_hotkey()
        root.after(100, self._poll)

    # ── 기타 ──
    def _save(self):
        self.s.update(monitor=self.mon_cb.current(), pick_region=self.v_region.get(),
                      style=self.v_style.get(), beep=self.v_beep.get())
        save_settings(self.s)

    def _setup_hotkey(self):
        try:
            import keyboard
            keyboard.add_hotkey("f9", lambda: self.q.put(("toggle",)))
            self.hotkey_ok = True
        except Exception as e:
            self.hotkey_ok = False
            log("단축키 등록 실패: " + repr(e))
            self.status.set("F9 단축키를 못 켰어요. 버튼으로 시작/종료해 주세요.")

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "toggle":
                    self.toggle()
                elif kind == "page":
                    n = msg[1]
                    self.root.title(f"● 녹화 중 · {n}장")
                    self.status.set(f"녹화 중… {n}장 저장됨  (끝내려면 F9)")
                    if self.v_beep.get():
                        beep("page")
                elif kind == "progress":
                    self.status.set(msg[1])
                    self.pb["value"] = int(msg[2] * 1000)
                elif kind == "done":
                    self._done(*msg[1:])
                elif kind == "error":
                    self._error(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def open_folder(self):
        d = self.last_dir or output_root()
        os.makedirs(d, exist_ok=True)
        if IS_WIN:
            os.startfile(d)

    def _set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        self.btn.configure(state=st)
        self.btn_file.configure(state=st)

    # ── 녹화 ──
    def toggle(self):
        if self.busy:
            return
        if self.recorder:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        self._save()
        if not self.monitors:
            self._error("모니터를 찾지 못했어요.")
            return
        mon = self.monitors[max(0, self.mon_cb.current())]
        rect = mon["work"]
        picked = False
        if self.v_region.get():
            r = pick_region(self.root, mon["full"])
            if not r:
                self.status.set("영역 고르기를 취소했어요.")
                return
            rect, picked = r, True
        self.session = new_session_dir()
        self.picked = picked
        self.root.iconify()
        self.root.update()
        time.sleep(0.4)  # 창이 내려가는 애니메이션이 찍히지 않게
        self.recorder = Recorder(rect, os.path.join(self.session, "캡처"),
                                 on_page=lambda n: self.q.put(("page", n)), own_hwnd=self.own_hwnd)
        self.recorder.start()
        beep("start")
        self.root.title("● 녹화 중 · 0장")
        self.btn.configure(text="■  녹화 끝내기   (F9)")
        self.status.set("녹화 중… 문서를 한 장씩 넘기세요. 넘긴 뒤 1초쯤 멈추면 저장돼요.")
        self.pb["value"] = 0
        log(f"녹화 시작 rect={rect}")

    def stop_recording(self):
        rec, self.recorder = self.recorder, None
        paths = rec.stop()
        beep("stop")
        self.root.title("화면번역")
        self.btn.configure(text="●  녹화 시작   (F9)")
        self.root.deiconify()
        self.root.lift()
        log(f"녹화 끝: {len(paths)}장")
        if rec.error:
            self._error(f"녹화 중 오류가 났어요: {rec.error}")
            return
        if not paths:
            st = rec.stats
            if st["grabbed"] == 0:
                self.status.set("화면을 한 장도 못 찍었어요. (프로그램 창이 계속 앞에 있었음) "
                                "(기록: %APPDATA%\\ScreenTranslate\\log.txt)")
            else:
                self.status.set(f"저장된 화면이 없어요. (찍은 프레임 {st['grabbed']}개) 넘긴 뒤 1초 정도 멈춰 주세요.")
            return
        self.run_pipeline(paths, self.session, filter_chrome=not self.picked)

    # ── 파일로 ──
    def from_file(self):
        from tkinter import filedialog
        files = filedialog.askopenfilenames(
            title="녹화 영상 또는 캡처 이미지 선택",
            filetypes=[("영상/이미지", "*.mp4 *.mkv *.mov *.avi *.webm *.flv *.png *.jpg *.jpeg *.bmp"),
                       ("모든 파일", "*.*")])
        if not files:
            return
        self._save()
        session = new_session_dir()
        vids = [f for f in files if os.path.splitext(f)[1].lower() in (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv")]
        imgs = [f for f in files if f not in vids]
        self._set_busy(True)

        def work():
            try:
                paths = list(imgs)
                for v in vids:
                    paths += extract_video(v, os.path.join(session, "캡처"),
                                           progress=lambda f: self.q.put(("progress", f"영상에서 페이지 찾는 중… {int(f*100)}%", 0.05 * f)),
                                           start_index=len(paths) + 1)
                self._pipeline_work(paths, session, filter_chrome=True)
            except Exception as e:
                log(traceback.format_exc())
                self.q.put(("error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    # ── 번역/PDF ──
    def run_pipeline(self, paths, session, filter_chrome):
        self._set_busy(True)
        threading.Thread(target=lambda: self._pipeline_work(paths, session, filter_chrome), daemon=True).start()

    def _pipeline_work(self, paths, session, filter_chrome):
        from screentrans import pipeline
        try:
            res = pipeline.process(paths, session, filter_chrome=filter_chrome, style=self.v_style.get(),
                                   progress=lambda m, f: self.q.put(("progress", m, f)))
            self.q.put(("done", res["pdf"], res.get("warning"), session, len(paths)))
        except Exception as e:
            log(traceback.format_exc())
            self.q.put(("error", str(e)))

    def _done(self, pdf, warning, session, n):
        self._set_busy(False)
        self.last_dir = session
        self.pb["value"] = 1000
        self.status.set(f"완료! 화면 {n}장 → {os.path.basename(pdf)}" + (f"\n⚠ {warning}" if warning else ""))
        log(f"완료 {pdf} warning={warning}")
        if IS_WIN:
            try:
                os.startfile(pdf)
            except Exception:
                pass

    def _error(self, msg):
        from tkinter import messagebox
        self._set_busy(False)
        self.status.set("오류: " + msg)
        messagebox.showerror("화면번역", msg)

    def on_close(self):
        if self.recorder:
            self.recorder.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def extract_video(path, cap_dir, progress=None, start_index=1):
    from screentrans.imageio import save_png, video_safe_path
    from screentrans.pages import pages_from_video
    os.makedirs(cap_dir, exist_ok=True)
    out = []

    def on_page(rgb, n):
        p = os.path.join(cap_dir, f"page_{start_index + n - 1:03d}.png")
        save_png(p, rgb)
        out.append(p)
    open_path, tmp = video_safe_path(path)
    try:
        pages_from_video(open_path, on_page, progress=progress)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return out


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


# ───────────────────────── 명령줄(자동 테스트용) ─────────────────────────

def cli(args):
    from screentrans import pipeline
    out = args.out or new_session_dir()
    os.makedirs(out, exist_ok=True)
    paths = list(args.images or [])
    if args.video:
        paths += extract_video(args.video, os.path.join(out, "캡처"), start_index=len(paths) + 1)
    res = pipeline.process(paths, out, filter_chrome=True, include_images=args.include_images, style=args.style)
    summary = {"pages": len(paths), "pdf": res["pdf"], "txt": res["txt"], "warning": res.get("warning"), "backend": res.get("backend"),
               "paragraphs": sum(len(p) for p in res["pages"])}
    with open(os.path.join(out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return 0


def main():
    set_dpi_aware()
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="*")
    ap.add_argument("--video")
    ap.add_argument("--out")
    ap.add_argument("--include-images", action="store_true")
    ap.add_argument("--style", default="layout", choices=["layout", "text"])
    args = ap.parse_args()
    if args.images or args.video:
        try:
            sys.exit(cli(args))
        except Exception:
            log(traceback.format_exc())
            if args.out:
                os.makedirs(args.out, exist_ok=True)
                with open(os.path.join(args.out, "error.txt"), "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            sys.exit(1)
    App().run()


if __name__ == "__main__":
    main()
