"""녹화 프레임에서 '페이지가 넘어가서 멈춘 순간'만 골라내는 모듈."""
import cv2
import numpy as np


def _small_gray(frame, width=480):
    h, w = frame.shape[:2]
    scale = width / float(w)
    small = cv2.resize(frame, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)


def changed_fraction(a, b, level=28):
    """두 축소 흑백 이미지에서 눈에 띄게 바뀐 픽셀 비율."""
    if a.shape != b.shape:
        return 1.0
    return float(np.count_nonzero(cv2.absdiff(a, b) > level)) / a.size


class PageDetector:
    """프레임을 계속 넣어주면, 화면이 바뀐 뒤 settle초 동안 멈춰 있을 때 새 페이지로 확정한다.

    - 커서 깜빡임·시계 같은 작은 변화(move_thresh 미만)는 무시
    - 이전에 저장한 페이지와 거의 같으면(뒤로 넘겼다 다시 온 경우) 중복으로 보고 건너뜀
    """

    def __init__(self, on_page, settle=0.7, move_thresh=0.0015, page_thresh=0.006, dup_thresh=0.003):
        self.on_page = on_page
        self.settle = settle
        self.move_thresh = move_thresh
        self.page_thresh = page_thresh
        self.dup_thresh = dup_thresh
        self.prev = None
        self.last_frame = None
        self.stable_since = None
        self.committed = False
        self.saved = []  # 저장된 페이지들의 축소본

    def feed(self, frame, t):
        small = _small_gray(frame)
        if self.prev is None or changed_fraction(self.prev, small) > self.move_thresh:
            self.stable_since = t
            self.committed = False
        self.prev = small
        self.last_frame = frame
        if self.committed or t - self.stable_since < self.settle:
            return
        self._commit(frame, small)

    def flush(self):
        """녹화 종료 시: 마지막 화면이 아직 확정 전이면 저장."""
        if self.last_frame is not None and not self.committed:
            self._commit(self.last_frame, self.prev)

    def _commit(self, frame, small):
        self.committed = True
        if self.saved and changed_fraction(self.saved[-1], small) < self.page_thresh:
            return  # 직전 페이지와 같음
        if any(changed_fraction(s, small) < self.dup_thresh for s in self.saved):
            return  # 예전에 이미 저장한 페이지 (뒤로 넘겼다 온 경우)
        self.saved.append(small)
        self.on_page(frame.copy(), len(self.saved))

    @property
    def count(self):
        return len(self.saved)


def pages_from_video(path, on_page, fps=4.0, progress=None, stop_flag=None):
    """녹화 영상 파일에서 페이지를 뽑는다. 반환: 페이지 수"""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError("영상 파일을 열 수 없어요: " + path)
    vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if vfps <= 0 or vfps > 240:
        vfps = 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(vfps / fps)))
    det = PageDetector(on_page)
    i = 0
    while True:
        if stop_flag is not None and stop_flag():
            break
        if not cap.grab():
            break
        if i % step == 0:
            ok, bgr = cap.retrieve()
            if not ok:
                break
            det.feed(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), i / vfps)
            if progress and total:
                progress(min(1.0, i / total))
        i += 1
    det.flush()
    cap.release()
    return det.count
