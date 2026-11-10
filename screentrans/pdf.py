"""번역 결과를 PDF로 만든다. 원본 화면 1장 = PDF 1구역(새 쪽에서 시작)."""
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer)

from .layout import BULLET_RE

_WINF = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_USERF = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
_FONT_CANDIDATES = [
    # (보통, 굵게) — 윈도우 기본 '맑은 고딕'이 1순위
    (os.path.join(_WINF, "malgun.ttf"), os.path.join(_WINF, "malgunbd.ttf")),
    (os.path.join(_WINF, "NanumGothic.ttf"), os.path.join(_WINF, "NanumGothicBold.ttf")),
    (os.path.join(_USERF, "NanumGothic.ttf"), os.path.join(_USERF, "NanumGothicBold.ttf")),
    ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
]


def _register_fonts(extra=None):
    cands = ([extra] if extra else []) + _FONT_CANDIDATES
    for reg, bold in cands:
        if reg and os.path.exists(reg):
            pdfmetrics.registerFont(TTFont("KR", reg))
            pdfmetrics.registerFont(TTFont("KR-B", bold if bold and os.path.exists(bold) else reg))
            return "KR", "KR-B"
    raise RuntimeError("한글 글꼴(맑은 고딕)을 찾지 못했어요.")


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(doc._kr_font, 8)
    canvas.setFillColor(colors.HexColor("#9a9a9a"))
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"{doc.page}")
    canvas.drawString(18 * mm, 10 * mm, doc._kr_title)
    canvas.restoreState()


def build_pdf(path, pages, title="화면 번역", show_original=True, images=None, font=None):
    """pages: 페이지별 Para 목록(각 Para에 .text, .translated, .kind)
    images: 페이지별 캡처 이미지 경로(넣고 싶을 때만)"""
    f, fb = _register_fonts(font)
    ko = ParagraphStyle("ko", fontName=f, fontSize=11, leading=18, textColor=colors.HexColor("#1b1b1b"),
                        wordWrap="CJK", spaceAfter=1)
    ko_h = ParagraphStyle("ko_h", parent=ko, fontName=fb, fontSize=15, leading=22, spaceBefore=4)
    ko_b = ParagraphStyle("ko_b", parent=ko, leftIndent=12, bulletIndent=2)
    en = ParagraphStyle("en", fontName=f, fontSize=8, leading=11.5, textColor=colors.HexColor("#8a8a8a"),
                        wordWrap="LTR")
    en_b = ParagraphStyle("en_b", parent=en, leftIndent=12)
    tag = ParagraphStyle("tag", fontName=f, fontSize=8, leading=10, textColor=colors.HexColor("#b0b0b0"),
                         spaceAfter=8)

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm, title=title)
    doc._kr_font, doc._kr_title = f, title
    flow = []
    n = len(pages)
    for i, paras in enumerate(pages):
        if i:
            flow.append(PageBreak())
        flow.append(Paragraph(escape(f"원본 화면 {i + 1} / {n}"), tag))
        if images and i < len(images) and images[i]:
            img = Image(images[i])
            maxw, maxh = A4[0] - 36 * mm, 95 * mm
            sc = min(maxw / img.imageWidth, maxh / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * sc, img.imageHeight * sc
            flow += [img, Spacer(1, 6)]
        if not paras:
            flow.append(Paragraph("(이 화면에서 글자를 찾지 못했어요)", en))
        for p in paras:
            k = (p.translated or p.text).strip()
            o = p.text.strip()
            block = []
            if p.kind == "h":
                block.append(Paragraph(escape(k), ko_h))
            elif p.kind == "b":
                numbered = bool(BULLET_RE.match(o))
                block.append(Paragraph(escape(k), ko_b, bulletText=None if numbered else "•"))
            else:
                block.append(Paragraph(escape(k), ko))
            if show_original and o and o != k:
                block.append(Paragraph(escape(o), en_b if p.kind == "b" else en))
            block.append(Spacer(1, 9 if p.kind != "b" else 5))
            flow.append(KeepTogether(block))
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return path


def build_text(path, pages):
    """같은 내용을 메모장에서 볼 수 있는 텍스트로도 저장."""
    n = len(pages)
    with open(path, "w", encoding="utf-8-sig") as fp:
        for i, paras in enumerate(pages):
            fp.write(f"===== 원본 화면 {i + 1} / {n} =====\n\n")
            for p in paras:
                fp.write((p.translated or p.text).strip() + "\n")
                fp.write("  └ " + p.text.strip() + "\n\n")
    return path
