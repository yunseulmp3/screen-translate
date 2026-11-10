"""영어 글자 인식 (RapidOCR, 인터넷 없이 PC에서 바로 동작)."""
import logging
import threading

_engine = None
_lock = threading.Lock()


def get_engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR
            _engine = RapidOCR(params={"Global.log_level": "error"})
            logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        return _engine


def read_boxes(rgb, region=None):
    """rgb: HxWx3 이미지. region=(x0,y0,x1,y1)이면 그 부분만 읽음. 좌표는 원본 기준으로 돌려줌."""
    from .layout import boxes_from_ocr
    ox = oy = 0
    img = rgb
    if region:
        x0, y0, x1, y1 = [int(v) for v in region]
        img = rgb[y0:y1, x0:x1]
        ox, oy = x0, y0
    bgr = img[:, :, ::-1].copy()
    res = get_engine()(bgr)
    return boxes_from_ocr(res, offset=(ox, oy))
