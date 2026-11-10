"""OCR 결과(줄 조각)를 '사람이 읽는 문단'으로 다시 묶는 모듈.

번역 품질은 문장이 중간에 잘리지 않는 게 제일 중요해서,
화면상의 줄바꿈을 지우고 문단 단위로 이어 붙인다.
"""
import re
from dataclasses import dataclass, field
from statistics import median

BULLET_RE = re.compile(r"^\s*([•·▪●◦■□▶►](?=\s*\S)|[\-–—*](?=\s)|\(?\d{1,2}[.)](?=\s)|\(?[a-zA-Z][.)](?=\s))\s*")
URL_RE = re.compile(r"(https?://|www\.)\S+|\b\S+\.(com|net|org|io|kr)(/\S*)?\b", re.I)
SENT_END_RE = re.compile(r"[.!?:;。\"'”’)]\s*$")


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


@dataclass
class Line(Box):
    pass


@dataclass
class Para:
    lines: list = field(default_factory=list)
    kind: str = "p"  # p(본문) / h(제목) / b(글머리표)
    text: str = ""
    translated: str = ""

    @property
    def x0(self):
        return min(l.x0 for l in self.lines)

    @property
    def x1(self):
        return max(l.x1 for l in self.lines)

    @property
    def y0(self):
        return min(l.y0 for l in self.lines)

    @property
    def y1(self):
        return max(l.y1 for l in self.lines)

    @property
    def h(self):
        return median(l.h for l in self.lines)


def boxes_from_ocr(result, min_score=0.5, offset=(0, 0)):
    out = []
    if result is None or result.boxes is None:
        return out
    ox, oy = offset
    for quad, txt, sc in zip(result.boxes, result.txts, result.scores):
        if not txt or float(sc) < min_score:
            continue
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        out.append(Box(min(xs) + ox, min(ys) + oy, max(xs) + ox, max(ys) + oy, txt.strip()))
    return out


def merge_into_lines(boxes):
    """같은 높이에 붙어 있는 조각을 한 줄로 합친다. (멀리 떨어진 건 다른 단/메뉴로 보고 분리)"""
    lines = []
    for b in sorted(boxes, key=lambda b: (b.cy, b.x0)):
        best = None
        for ln in lines:
            ov = min(ln.y1, b.y1) - max(ln.y0, b.y0)
            if ov < 0.6 * min(ln.h, b.h):
                continue
            gap = b.x0 - ln.x1
            if -0.3 * b.h <= gap <= 1.2 * max(ln.h, b.h):
                best = ln
                break
        if best:
            best.text = best.text + " " + b.text
            best.x1 = max(best.x1, b.x1)
            best.y0 = min(best.y0, b.y0)
            best.y1 = max(best.y1, b.y1)
        else:
            lines.append(Line(b.x0, b.y0, b.x1, b.y1, b.text))
    return lines


def _starts_bullet(text):
    return bool(BULLET_RE.match(text))


def group_paragraphs(lines):
    lines = sorted(lines, key=lambda l: (l.y0, l.x0))
    paras = []
    for ln in lines:
        target = None
        for p in reversed(paras[-6:]):
            last = p.lines[-1]
            ph = p.h
            # 세로 간격
            gap = ln.y0 - last.y1
            if len(p.lines) >= 2:
                inner = median(b.y0 - a.y1 for a, b in zip(p.lines, p.lines[1:]))
                max_gap = inner + 0.35 * ph
            else:
                max_gap = 0.5 * ph
            if not (-0.3 * ph <= gap <= max_gap):
                continue
            # 글자 크기가 비슷해야 함 (제목/본문 분리)
            if not (0.82 <= ln.h / ph <= 1.22):
                continue
            # 가로로 겹쳐야 함 (다른 단 X)
            if ln.x1 < p.x0 or ln.x0 > p.x1:
                continue
            # 왼쪽 시작점이 크게 다르면 다른 문단
            if abs(ln.x0 - last.x0) > 2.5 * ph and ln.x0 < p.x0 - 0.5 * ph:
                continue
            if _starts_bullet(ln.text):
                break  # 글머리표는 항상 새 문단
            # 앞 줄이 문장 끝 + 오른쪽이 많이 비어 있으면 문단 끝
            if SENT_END_RE.search(last.text) and last.x1 < p.x1 - 3 * ph:
                break
            # 글머리표 항목: 앞 줄이 문장으로 끝나고 이번 줄이 대문자로 시작하면 다음 항목 (기호를 OCR이 놓친 경우)
            if _starts_bullet(p.lines[0].text) and re.search(r"[.!?:]\s*$", last.text) and ln.text[:1].isupper():
                break
            target = p
            break
        if target is None:
            target = Para()
            paras.append(target)
        target.lines.append(ln)
    return paras


def _largest_gap(ivs, min_gap):
    ivs = sorted(ivs)
    cur_end = ivs[0][1]
    best = None
    for st, en in ivs[1:]:
        g = st - cur_end
        if g > min_gap and (best is None or g > best[0]):
            best = (g, (cur_end + st) / 2)
        cur_end = max(cur_end, en)
    return best


def _xy_cut(items, depth=0):
    """여러 단(컬럼) 배치도 읽는 순서대로 정렬.
    넓은 세로 틈(단 나눔)이 있으면 먼저 좌우로, 아니면 위아래로 재귀 분할."""
    if len(items) <= 1 or depth > 16:
        return sorted(items, key=lambda p: (p.y0, p.x0))
    hs = median(p.h for p in items)
    for axis, min_gap in (("x", 1.5 * hs), ("y", 0.4 * hs), ("x", 0.8 * hs)):
        if axis == "x":
            best = _largest_gap([(p.x0, p.x1) for p in items], min_gap)
            if best:
                a = [p for p in items if p.x1 <= best[1]]
                b = [p for p in items if p.x1 > best[1]]
        else:
            best = _largest_gap([(p.y0, p.y1) for p in items], min_gap)
            if best:
                a = [p for p in items if p.y1 <= best[1]]
                b = [p for p in items if p.y1 > best[1]]
        if best and a and b:
            return _xy_cut(a, depth + 1) + _xy_cut(b, depth + 1)
    return sorted(items, key=lambda p: (p.y0, p.x0))


def join_lines(lines):
    out = ""
    for ln in lines:
        t = ln.text.strip()
        if not out:
            out = t
        elif re.search(r"[A-Za-z]-$", out) and t[:1].islower():
            out = out[:-1] + t  # exam- / ple → example
        else:
            out = out + " " + t
    return re.sub(r"\s+", " ", out).strip()


def finalize(paras):
    if not paras:
        return []
    body_h = median(l.h for p in paras for l in p.lines)
    for p in paras:
        p.text = join_lines(p.lines)
        m = BULLET_RE.match(p.text)
        if m:
            p.kind = "b"
            if not re.search(r"[0-9A-Za-z]", m.group(1)):
                p.text = p.text[m.end():].strip()  # 기호 글머리표는 PDF에서 다시 붙임
        elif p.h >= 1.2 * body_h and len(p.lines) <= 3:
            p.kind = "h"
        elif p.h >= 1.1 * body_h and len(p.lines) == 1 and len(p.text) < 60 and not SENT_END_RE.search(p.text):
            p.kind = "h"  # 조금 큰 한 줄짜리 소제목
    # OCR이 글머리표 기호(•)를 놓친 줄: 바로 위 글머리표 항목의 글자 시작 위치와 같으면 글머리표로
    by_y = sorted(paras, key=lambda p: p.y0)
    for a, b in zip(by_y, by_y[1:]):
        if a.kind == "b" and b.kind == "p" and len(b.lines) <= 3 and \
                a.x0 + 0.3 * a.h <= b.x0 <= a.x0 + 2.5 * a.h and b.y0 - a.y1 < 1.5 * a.h:
            b.kind = "b"
    return _xy_cut(paras)


def paragraphs_from_boxes(boxes):
    return finalize(group_paragraphs(merge_into_lines(boxes)))


# ───────── 여러 페이지에 걸친 화면 잡동사니(메뉴/툴바/썸네일) 걸러내기 ─────────

def _norm(t):
    return re.sub(r"\W+", "", t.lower())


def remove_screen_chrome(pages_lines, frame_h):
    """pages_lines: 페이지별 Line 목록. 화면 UI로 보이는 줄을 제거해서 돌려준다.

    1) 모든 페이지(3장 이상이면 60% 이상)에서 같은 위치·같은 글자로 반복되는 줄 → 프로그램 메뉴/고정 머리글
    2) 화면 맨 위/아래 띠에 있는 짧은 줄 (예: 'Page 3 of 10  100%') → 뷰어 상태 표시
    3) 숫자/기호만 있는 줄 (쪽번호)
    """
    n = len(pages_lines)
    need = n if n <= 2 else max(2, int(round(0.6 * n)))
    keyed = [{(_norm(l.text), round((l.x0 + l.x1) / 24), round(l.cy / 12)) for l in lines}
             for lines in pages_lines]
    out = []
    for lines in pages_lines:
        repeated = set()
        if n >= 2:
            for idx, l in enumerate(lines):
                nt = _norm(l.text)
                k = (nt, round((l.x0 + l.x1) / 24), round(l.cy / 12))
                hits = sum(1 for ks in keyed
                           if any(kk[0] == k[0] and abs(kk[1] - k[1]) <= 1 and abs(kk[2] - k[2]) <= 1 for kk in ks))
                if nt and hits >= need:
                    repeated.add(idx)
            # 안전장치: 반복 줄이 페이지 글자의 절반 이상이면 '같은 문서를 두 번 찍은 것'으로 보고 지우지 않음
            total = sum(len(l.text) for l in lines) or 1
            if sum(len(lines[i].text) for i in repeated) > 0.5 * total:
                repeated = set()
        keep = []
        for idx, l in enumerate(lines):
            if idx in repeated:
                continue  # 매 화면 같은 자리에 반복 → 프로그램 메뉴/고정 머리글
            if not re.search(r"[A-Za-z]", l.text):
                continue  # 숫자·기호만 → 쪽번호 등
            if l.cy < 0.045 * frame_h:
                continue  # 창 제목줄/메뉴줄
            if l.cy < 0.09 * frame_h and (len(l.text) < 40 or URL_RE.search(l.text)):
                continue  # 브라우저 탭·주소창, 툴바
            if len(l.text) < 30 and l.cy > 0.965 * frame_h:
                continue  # 아래쪽 상태 표시줄
            keep.append(l)
        out.append(keep)
    return out


def dedupe_overlap(pages_paras):
    """스크롤로 넘긴 경우 이전 페이지와 겹치는 문단을 뺀다."""
    prev = set()
    for paras in pages_paras:
        cur = {_norm(p.text) for p in paras}
        paras[:] = [p for p in paras if _norm(p.text) not in prev or len(_norm(p.text)) < 4]
        prev = cur
    return pages_paras
