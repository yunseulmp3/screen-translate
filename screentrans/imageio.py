"""윈도우 한글 경로에서도 깨지지 않는 이미지 읽기/쓰기 (cv2.imread는 한글 경로에서 실패함)."""
import os
import shutil
import tempfile

import cv2
import numpy as np


def save_png(path, rgb):
    ok, buf = cv2.imencode(".png", rgb[:, :, ::-1])
    if not ok:
        raise RuntimeError("이미지 저장 실패")
    with open(path, "wb") as f:
        f.write(buf.tobytes())


def load_rgb(path):
    data = np.fromfile(path, dtype=np.uint8)
    bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError("이미지를 읽을 수 없어요: " + path)
    return bgr[:, :, ::-1].copy()


def video_safe_path(path):
    """영상 경로에 한글이 있으면 OpenCV가 못 여는 경우가 있어서, 짧은 경로나 임시 사본으로 바꿔준다.
    반환: (열 경로, 나중에 지울 임시파일 or None)"""
    try:
        path.encode("ascii")
        return path, None
    except UnicodeEncodeError:
        pass
    if os.name == "nt":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024):
                sp = buf.value
                sp.encode("ascii")
                return sp, None
        except Exception:
            pass
    ext = os.path.splitext(path)[1] or ".mp4"
    fd, tmp = tempfile.mkstemp(suffix=ext, prefix="st_video_")
    os.close(fd)
    shutil.copyfile(path, tmp)
    return tmp, tmp
