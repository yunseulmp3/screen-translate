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


def fit_text(text, font, box_w, fs0, lead_ratio, max_lines_h, max_w=None):
    """원래 글자 크기(fs0)에서 시작해, 원래 문단 높이 안에 들어갈 때까지 조금씩 줄인다.
    반환: (글자크기, 줄간격, 줄 목록)"""
    fs = fs0
    while True:
        width = box_w
        lines = _wrap(text, font, fs, width)
        if len(lines) > 1 and max_w and max_w > box_w:
            # 한 줄짜리 원문(제목 등)이 한국어로 길어지면 오른쪽 빈 공간까지 써서 한 줄 유지
            if stringWidth(text, font, fs) <= max_w:
                lines = [text]
        need = (len(lines) - 1) * fs * lead_ratio
        if need <= max_lines_h or fs <= fs0 * 0.6:
            return fs, fs * lead_ratio, lines
        fs *= 0.95


# ───────── 글자 픽셀 분석 ─────────

def line_metrics(rgb, ln, bg):
    """OCR 상자 안의 실제 글자 픽셀로: 시작 x, x높이(소문자 몸통 높이), 기준선 y, 굵기, 글머리표"""
    x0, y0, x1, y1 = [int(round(v)) for v in (ln.x0, ln.y0, ln.x1, ln.y1)]
    reg = rgb[max(0, y0):y1, max(0, x0):x1].astype(int)
    if reg.size == 0:
        return None
    ink = np.abs(reg - np.array(bg)).max(axis=2) > 60
    colany = ink.any(axis=0)
    cols = np.where(colany)[0]
    if len(cols) < 3:
        return None
    rc = ink.sum(axis=1)
    band = np.where(rc >= 0.4 * rc.max())[0]
    b0, b1 = int(band[0]), int(band[-1])
    xh = b1 - b0 + 1
    c0, c1 = int(cols[0]), int(cols[-1])
    density = ink[b0:b1 + 1, c0:c1 + 1].sum() / float(xh * (c1 - c0 + 1))
    m = {"x": x0 + c0, "xh": float(xh), "base": y0 + b1 + 1, "density": float(density), "bullet": None}
    # 첫 덩어리가 작고 꽉 찬 점/짧은 선 + 뒤에 빈칸 → 글머리표
    i = c0
    while i < len(colany) and colany[i]:
        i += 1
    j = i
    while j < len(colany) and not colany[j]:
        j += 1
    if j < len(colany) and (j - i) >= 0.25 * xh:
        blob = ink[:, c0:i]
        rows = np.where(blob.any(axis=1))[0]
        if len(rows):
            bh, bw = rows[-1] - rows[0] + 1, i - c0
            fill = blob[rows[0]:rows[-1] + 1].sum() / float(bh * bw)
            cy = (rows[0] + rows[-1]) / 2
            if bw <= 0.9 * xh and bh <= 0.9 * xh and fill > 0.55 and b0 - 1 <= cy <= b1 + 1:
                m["bullet"] = (x0 + c0, x0 + j, "–" if bw > 2 * bh else "•")
    return m


def size_classes(xhs):
    """x높이가 비슷한(±12%) 문단끼리 같은 글자 크기로 통일 → 같은 목록 항목끼리 크기가 들쭉날쭉하지 않게"""
    order = sorted(range(len(xhs)), key=lambda i: xhs[i])
    out = [None] * len(xhs)
    group = []
    for i in order + [None]:
        if i is None or (group and xhs[i] > xhs[group[0]] * 1.12):
            med = float(np.median([xhs[g] for g in group])) if group else 0
            for g in group:
                out[g] = med
            group = []
        if i is not None:
            group.append(i)
    return out


# ───────── 페이지 그리기 ─────────

def render_page(c, rgb, paras, area, font, font_b):
    ax0, ay0, ax1, ay1 = area
    img = rgb[ay0:ay1, ax0:ax1].copy()
    ch, cw = img.shape[:2]
    s = PAGE_W / cw
    page_h = ch * s
    c.setPageSize((PAGE_W, page_h))

    page_bg = page_background(rgb, paras)
    plans = []
    for p in paras:
        if not (p.translated or "").strip():
            continue
        if p.x1 < ax0 or p.x0 > ax1 or p.y1 < ay0 or p.y0 > ay1:
            continue
        cls = [classify_bg(rgb, (ln.x0, ln.y0, ln.x1, ln.y1), page_bg) for ln in p.lines]
        if not all(ok for _, ok in cls):
            continue  # 사진 위 글자 → 원본 유지
        bg0 = cls[0][0]
        mets = [line_metrics(rgb, ln, lb) for ln, (lb, _) in zip(p.lines, cls)]
        if mets[0] is None:
            continue
        color = text_color_of(rgb, (p.lines[0].x0, p.lines[0].y0, p.lines[0].x1, p.lines[0].y1), bg0)
        # 영어 줄 지우기 (줄마다 그 둘레 배경색으로)
        for ln, (lb, _) in zip(p.lines, cls):
            px, py = 0.12 * ln.h, 0.1 * ln.h
            X0, Y0 = int(ln.x0 - px - ax0), int(ln.y0 - py - ay0)
            X1, Y1 = int(np.ceil(ln.x1 + px - ax0)), int(np.ceil(ln.y1 + py - ay0))
            img[max(0, Y0):max(0, Y1), max(0, X0):max(0, X1)] = lb
        plans.append({"p": p, "color": color, "mets": [m for m in mets if m]})

    c.drawImage(ImageReader(Image.fromarray(img)), 0, 0, width=PAGE_W, height=page_h)
    if not plans:
        c.showPage()
        return

    xhs = [float(np.median([m["xh"] for m in pl["mets"]])) for pl in plans]
    xh_ref = size_classes(xhs)
    dens = [float(np.median([m["density"] for m in pl["mets"]])) for pl in plans]
    dens_med = float(np.median(dens))

    for k, pl in enumerate(plans):
        p, m0, mets = pl["p"], pl["mets"][0], pl["mets"]
        bold = dens[k] >= 1.15 * dens_med or (p.kind == "h" and dens[k] >= 1.1 * dens_med)
        f = font_b if bold else font
        x_mark, x_text, mark = m0["x"], m0["x"], None
        if m0["bullet"]:
            x_mark, x_text, mark = m0["bullet"]
        elif p.kind == "b" and BULLET_RE.match(p.lines[0].text) and not BULLET_RE.match(p.text):
            mark, x_text = "•", m0["x"] + xh_ref[k] * 2.2
        fs0 = xh_ref[k] * 1.8  # 영어 소문자 몸통 높이 → 한국어 글자 크기
        bases = [m["base"] for m in mets]
        pitch = float(np.median(np.diff(bases))) if len(bases) > 1 else fs0 * 1.5
        lead_ratio = min(max(pitch / fs0, 1.2), 2.2)
        max_lines_h = (len(p.lines) - 1) * pitch + 0.45 * pitch
        others_right = [q["p"].x0 for q in plans if q["p"] is not p and q["p"].x0 > p.x1
                        and q["p"].y0 < p.y1 and q["p"].y1 > p.y0]
        right_limit = (min(others_right) - 10) if others_right else (ax1 - 12)
        fs, lead, out_lines = fit_text(p.translated.strip(), f, p.x1 - x_text + 2, fs0, lead_ratio, max_lines_h,
                                       max_w=(right_limit - x_text) if len(p.lines) == 1 else None)
        c.setFillColorRGB(*[v / 255 for v in pl["color"]])
        c.setFont(f, fs * s)
        for i, t in enumerate(out_lines):
            base = bases[0] + i * lead  # 원문 첫 줄 기준선에 맞춤
            y_pdf = page_h - (base - ay0) * s
            c.drawString((x_text - ax0) * s, y_pdf, t)
            if mark and i == 0:
                c.drawString((x_mark - ax0) * s, y_pdf, mark)
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
