"""원본 모양 그대로 번역 PDF.

캡처 화면에서 문서 부분만 잘라 → 영어 글자 줄만 주변 배경색으로 지우고 →
같은 자리에 한국어를 (원래 글자 크기에 맞춰) 다시 써 넣는다.
사진·도형·표 선 같은 나머지 픽셀은 원본 그대로 남는다.
사진 위에 얹힌 글자(배경이 고르지 않은 곳)는 지우면 사진이 망가지므로 원본 그대로 둔다.
"""
import cv2
import numpy as np
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .layout import BULLET_RE
from .pdf import _register_fonts

PAGE_W = 595.0  # A4 가로폭(pt)에 맞춤, 세로는 원본 비율


# ───────── 색 분석 ─────────

def _ring(rgb, box, gap=2, width=4):
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    X0, Y0 = max(0, x0 - gap - width), max(0, y0 - gap - width)
    X1, Y1 = min(w, x1 + gap + width), min(h, y1 + gap + width)
    reg = rgb[Y0:Y1, X0:X1].reshape(-1, 3) if Y1 > Y0 and X1 > X0 else np.zeros((0, 3))
    if reg.size == 0:
        return np.zeros((0, 3), np.uint8)
    yy, xx = np.mgrid[Y0:Y1, X0:X1]
    inner = (xx >= x0 - gap) & (xx < x1 + gap) & (yy >= y0 - gap) & (yy < y1 + gap)
    return reg[~inner.reshape(-1)]


def _flat(ring, frac=0.85, tol=9):
    if len(ring) < 10:
        return False, None
    med = np.median(ring, axis=0)
    dev = np.abs(ring.astype(int) - med).max(axis=1)
    return bool(np.mean(dev < tol) >= frac), tuple(int(v) for v in med)


def classify_bg(rgb, box, page_bg):
    """글자 줄 뒤 배경 판단. 반환 (배경색, 지워도 되는지)
    - 문서 바탕색 위 → 지움
    - 단색 상자(강조 박스 등) 위 → 지움
    - 사진/그라데이션 위 → 원본 유지"""
    ring = _ring(rgb, box)
    if len(ring) < 10:
        return (255, 255, 255), False
    pb = np.array(page_bg)
    near = np.abs(ring.astype(int) - pb).max(axis=1) < 20
    if near.mean() >= 0.5:
        return tuple(int(v) for v in np.median(ring[near], axis=0)), True
    ok1, med1 = _flat(ring)
    if ok1:
        ok2, med2 = _flat(_ring(rgb, box, gap=10, width=8), frac=0.8)
        if ok2 and max(abs(a - b) for a, b in zip(med1, med2)) < 12:
            return med1, True
    return tuple(int(v) for v in np.median(ring, axis=0)), False


def page_background(rgb, paras):
    meds = []
    for p in paras:
        ring = _ring(rgb, (p.x0, p.y0, p.x1, p.y1))
        if len(ring):
            meds.append(np.median(ring, axis=0))
    if not meds:
        return (255, 255, 255)
    meds = np.array(meds)
    # 가장 많은 문단이 공유하는 색(최빈값 근처)
    best = max(meds, key=lambda m: int((np.abs(meds - m).max(axis=1) < 20).sum()))
    return tuple(int(v) for v in best)


def background_of(rgb, box):
    ring = _ring(rgb, box)
    ok, med = _flat(ring, frac=0.6, tol=24)
    return (med or (255, 255, 255)), ok


def text_color_of(rgb, box, bg):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    reg = rgb[max(0, y0):y1, max(0, x0):x1].reshape(-1, 3).astype(int)
    if reg.size:
        d = np.abs(reg - np.array(bg)).max(axis=1)
        ink = reg[d > 0.55 * d.max()] if d.max() > 60 else reg[:0]
        if len(ink) > 5:
            return tuple(int(v) for v in np.median(ink, axis=0))
    lum = 0.3 * bg[0] + 0.59 * bg[1] + 0.11 * bg[2]
    return (20, 20, 20) if lum > 128 else (235, 235, 235)


# ───────── 문서 영역 찾기 ─────────

def document_area(rgb, paras, pad=10):
    """뷰어 화면 안의 '문서 종이' 부분(본문 배경과 같은 색으로 이어진 영역)을 찾는다."""
    h, w = rgb.shape[:2]
    if not paras:
        return (0, 0, w, h)
    bgs = [background_of(rgb, (p.x0, p.y0, p.x1, p.y1)) for p in paras]
    good = [b for b, u in bgs if u] or [b for b, _ in bgs]
    bg = np.median(np.array(good), axis=0)
    k = 4
    small = cv2.resize(rgb, (w // k, h // k), interpolation=cv2.INTER_AREA).astype(int)
    mask = (np.abs(small - bg).max(axis=2) < 22).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
    picked = set()
    for p in paras:
        for (px, py) in ((p.x0 - 6, p.y0 - 6), (p.x1 + 6, p.y1 + 6), (p.x0 - 6, p.y1 + 6)):
            sx, sy = int(px) // k, int(py) // k
            if 0 <= sx < w // k and 0 <= sy < h // k and lab[sy, sx] > 0:
                picked.add(int(lab[sy, sx]))
    x0, y0 = min(p.x0 for p in paras), min(p.y0 for p in paras)
    x1, y1 = max(p.x1 for p in paras), max(p.y1 for p in paras)
    for L in picked:
        sx, sy, sw, sh, _ = stats[L]
        x0, y0 = min(x0, sx * k), min(y0, sy * k)
        x1, y1 = max(x1, (sx + sw) * k), max(y1, (sy + sh) * k)
    return (max(0, int(x0) - pad), max(0, int(y0) - pad), min(w, int(x1) + pad), min(h, int(y1) + pad))


def union_area(areas):
    return (min(a[0] for a in areas), min(a[1] for a in areas), max(a[2] for a in areas), max(a[3] for a in areas))


# ───────── 한국어 줄바꿈/크기 맞추기 ─────────

def _wrap(text, font, fs, width):
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        t = (cur + " " + wd).strip()
        if stringWidth(t, font, fs) <= width or not cur:
            if stringWidth(t, font, fs) > width and not cur:
                # 한 단어가 너무 길면 글자 단위로 끊음
                piece = ""
                for ch in wd:
                    if stringWidth(piece + ch, font, fs) > width and piece:
                        lines.append(piece)
                        piece = ch
                    else:
                        piece += ch
                cur = piece
            else:
                cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def fit_text(text, font, box_w, box_h, line_h, pitch, max_w=None):
    """원래 줄 높이(line_h)에 맞는 글자 크기에서 시작해, 박스에 들어갈 때까지 조금씩 줄인다.
    반환: (글자크기, 줄간격, 줄 목록, 실제 폭)"""
    fs0 = line_h * 0.66
    ratio = (pitch / fs0) if pitch else 1.45
    ratio = min(max(ratio, 1.25), 2.2)
    width = box_w
    fs = fs0
    while True:
        lines = _wrap(text, font, fs, width)
        if len(lines) == 1 and max_w and stringWidth(lines[0], font, fs) > width:
            width = min(max_w, stringWidth(lines[0], font, fs) + 1)
            lines = _wrap(text, font, fs, width)
        need = (len(lines) - 1) * fs * ratio + line_h * 0.9
        if need <= box_h + 0.35 * line_h or fs <= fs0 * 0.6:
            return fs, fs * ratio, lines, width
        fs *= 0.94


# ───────── 페이지 그리기 ─────────

def ink_left(rgb, ln, bg):
    """OCR 상자는 여백이 조금 붙어 있어서, 실제 글자가 시작되는 x를 픽셀로 찾는다."""
    x0, y0, x1, y1 = [int(round(v)) for v in (ln.x0, ln.y0, ln.x1, ln.y1)]
    reg = rgb[max(0, y0):y1, max(0, x0):x1].astype(int)
    if reg.size == 0:
        return None
    cols = np.where((np.abs(reg - np.array(bg)).max(axis=2) > 60).any(axis=0))[0]
    return x0 + int(cols[0]) if len(cols) else None


def text_start_after_bullet(rgb, ln, bg):
    """글머리표가 있는 줄에서 '기호 다음 글자'가 시작되는 x를 픽셀로 찾는다 (원본 들여쓰기 그대로)."""
    x0, y0, x1, y1 = [int(round(v)) for v in (ln.x0, ln.y0, ln.x1, ln.y1)]
    reg = rgb[max(0, y0):y1, max(0, x0):x1].astype(int)
    if reg.size == 0:
        return None
    ink = (np.abs(reg - np.array(bg)).max(axis=2) > 60).any(axis=0)
    cols = np.where(ink)[0]
    if len(cols) == 0:
        return None
    i = cols[0]
    while i < len(ink) and ink[i]:
        i += 1  # 기호 덩어리 지나감
    gap_start = i
    while i < len(ink) and not ink[i]:
        i += 1  # 빈칸
    if i >= len(ink) or i - gap_start < 2:
        return None
    return x0 + i


def size_classes(paras):
    """OCR 줄 높이는 g·p 같은 아래로 내려가는 글자 유무로 들쭉날쭉함 →
    비슷한 높이(±15%)끼리 묶어서 같은 글자 크기로 통일 (같은 목록 항목끼리 크기가 달라지지 않게)"""
    hs = sorted((float(np.median([l.h for l in p.lines])), i) for i, p in enumerate(paras))
    ref = {}
    group = []
    for h, i in hs:
        if group and h > group[0][0] * 1.15:
            m = max(g[0] for g in group)
            for _, j in group:
                ref[j] = m
            group = []
        group.append((h, i))
    if group:
        m = max(g[0] for g in group)
        for _, j in group:
            ref[j] = m
    return ref


def render_page(c, rgb, paras, area, font, font_b):
    ax0, ay0, ax1, ay1 = area
    img = rgb[ay0:ay1, ax0:ax1].copy()
    ch, cw = img.shape[:2]
    s = PAGE_W / cw
    page_h = ch * s
    c.setPageSize((PAGE_W, page_h))

    page_bg = page_background(rgb, paras)
    plans = []
    for i, p in enumerate(paras):
        if not (p.translated or "").strip():
            continue
        if p.x1 < ax0 or p.x0 > ax1 or p.y1 < ay0 or p.y0 > ay1:
            continue
        cls = [classify_bg(rgb, (ln.x0, ln.y0, ln.x1, ln.y1), page_bg) for ln in p.lines]
        if not all(ok for _, ok in cls):
            continue  # 사진 위 글자 → 원본 유지
        bg0 = cls[0][0]
        color = text_color_of(rgb, (p.lines[0].x0, p.lines[0].y0, p.lines[0].x1, p.lines[0].y1), bg0)
        # 영어 줄 지우기 (줄마다 그 둘레 배경색으로)
        for ln, (lb, _) in zip(p.lines, cls):
            px, py = 0.12 * ln.h, 0.1 * ln.h
            X0, Y0 = int(ln.x0 - px - ax0), int(ln.y0 - py - ay0)
            X1, Y1 = int(np.ceil(ln.x1 + px - ax0)), int(np.ceil(ln.y1 + py - ay0))
            img[max(0, Y0):max(0, Y1), max(0, X0):max(0, X1)] = lb
        plans.append((p, color, bg0))

    c.drawImage(ImageReader(Image.fromarray(img)), 0, 0, width=PAGE_W, height=page_h)

    ref_h = size_classes([p for p, _, _ in plans])
    for idx, (p, color, bgc) in enumerate(plans):
        lines = p.lines
        line_h = ref_h.get(idx, float(np.median([l.h for l in lines])))
        pitch = float(np.median([b.y0 - a.y0 for a, b in zip(lines, lines[1:])])) if len(lines) > 1 else None
        f = font_b if p.kind == "h" else font
        x_ink = ink_left(rgb, lines[0], bgc) or p.x0
        x_text = x_ink
        bullet = False
        if p.kind == "b" and BULLET_RE.match(lines[0].text) and not BULLET_RE.match(p.text):
            bullet = True  # 원본 글머리표 기호도 같이 지워졌으니 다시 그림
            x_text = text_start_after_bullet(rgb, lines[0], bgc) or (x_ink + line_h * 0.95)
        box_w = p.x1 - x_text
        others_right = [q.x0 for q, _, _ in plans if q is not p and q.x0 > p.x1 and q.y0 < p.y1 and q.y1 > p.y0]
        max_w = (min(others_right) - 10 if others_right else ax1 - 12) - x_text
        fs, lead, out_lines, _ = fit_text(p.translated.strip(), f, box_w, p.y1 - p.y0, line_h, pitch,
                                          max_w=max_w if len(lines) == 1 else None)
        c.setFillColorRGB(*[v / 255 for v in color])
        top = p.y0 - ay0
        for k, t in enumerate(out_lines):
            base_img = top + line_h / 2 + fs * 0.36 + k * lead  # 줄 가운데에 글자 높이 맞춤
            y_pdf = page_h - base_img * s
            c.setFont(f, fs * s)
            c.drawString((x_text - ax0) * s, y_pdf, t)
            if bullet and k == 0:
                c.drawString((x_ink - ax0) * s, y_pdf, "•")
    c.showPage()


def build_layout_pdf(path, image_paths, pages, areas, title="화면 번역", font=None):
    """image_paths: 페이지별 캡처 이미지, pages: 페이지별 문단 목록, areas: 페이지별 자를 영역"""
    from .imageio import load_rgb
    f, fb = _register_fonts(font)
    c = canvas.Canvas(path, pageCompression=1)
    c.setTitle(title)
    for ip, paras, area in zip(image_paths, pages, areas):
        render_page(c, load_rgb(ip), paras, area, f, fb)
    c.save()
    return path
