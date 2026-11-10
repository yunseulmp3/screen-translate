"""캡처된 페이지 이미지들 → 글자 인식 → 문단 정리 → 번역 → PDF."""
import os
import time

from . import layout, ocr
from .imageio import load_rgb, save_png
from .pdf import build_pdf, build_text
from . import translate as _tr
from .translate import TranslateError, translate_many


def _crop_to_text(img_path, paras, out_path, margin=40):
    """PDF에 넣을 캡처 사진: 글자가 있는 부분만 잘라서 (빈 여백 제거)"""
    if not paras:
        return img_path
    rgb = load_rgb(img_path)
    h, w = rgb.shape[:2]
    x0 = max(0, int(min(p.x0 for p in paras)) - margin)
    y0 = max(0, int(min(p.y0 for p in paras)) - margin)
    x1 = min(w, int(max(p.x1 for p in paras)) + margin)
    y1 = min(h, int(max(p.y1 for p in paras)) + margin)
    save_png(out_path, rgb[y0:y1, x0:x1])
    return out_path


def process(image_paths, out_dir, filter_chrome=True, show_original=True, include_images=False,
            progress=None, translator=translate_many, title=None, style="layout"):
    """style: "layout" = 원본 모양 그대로(사진 포함, 영어 자리에 한국어) / "text" = 번역문만 정리
    반환: {"pdf", "txt", "pages", "warning", "backend"}"""
    def report(msg, frac):
        if progress:
            progress(msg, frac)

    n = len(image_paths)
    if n == 0:
        raise RuntimeError("저장된 화면이 없어요. 녹화 중에 화면을 1초 정도 멈춰 두면 한 장으로 저장돼요.")
    report("글자 인식 준비 중…", 0.0)
    ocr.get_engine()
    pages_lines, frame_h = [], 1
    for i, p in enumerate(image_paths):
        report(f"글자 읽는 중… ({i + 1}/{n})", 0.05 + 0.6 * i / n)
        rgb = load_rgb(p)
        frame_h = rgb.shape[0]
        boxes = ocr.read_boxes(rgb)
        pages_lines.append(layout.merge_into_lines(boxes))
    if filter_chrome:
        pages_lines = layout.remove_screen_chrome(pages_lines, frame_h)
    pages = [layout.finalize(layout.group_paragraphs(lines)) for lines in pages_lines]
    if style == "text":
        layout.dedupe_overlap(pages)  # 원본 모양 모드에선 화면을 그대로 살려야 하니 중복 제거 안 함

    flat = [p for paras in pages for p in paras]
    report(f"번역 중… (문단 {len(flat)}개)", 0.68)
    warning = None
    if flat:
        try:
            res = translator([p.text for p in flat],
                             progress=lambda f: report(f"번역 중… (문단 {len(flat)}개)", 0.68 + 0.25 * f))
            for p, t in zip(flat, res):
                p.translated = t or ""
        except TranslateError as e:
            warning = f"번역을 못 했어요(인터넷 연결 확인). 영어 원문만 PDF로 저장했어요. [{e}]"
    else:
        warning = "화면에서 영어 글자를 찾지 못했어요."

    report("PDF 만드는 중…", 0.95)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    pdf_path = os.path.join(out_dir, f"번역_{stamp}.pdf")
    txt_path = os.path.join(out_dir, f"번역_{stamp}.txt")
    if style == "layout":
        from .relayout import build_layout_pdf, document_area, union_area
        report("원본 모양으로 PDF 만드는 중…", 0.95)
        areas = []
        for ip, paras in zip(image_paths, pages):
            rgb = load_rgb(ip)
            areas.append(document_area(rgb, paras) if filter_chrome else (0, 0, rgb.shape[1], rgb.shape[0]))
        if filter_chrome and len(areas) > 1:
            areas = [union_area(areas)] * len(areas)  # 페이지마다 같은 크기로
        build_layout_pdf(pdf_path, image_paths, pages, areas,
                         title=title or f"화면 번역 · {time.strftime('%Y-%m-%d %H:%M')}")
        build_text(txt_path, pages)
        report("완료", 1.0)
        return {"pdf": pdf_path, "txt": txt_path, "pages": pages, "warning": warning, "backend": _tr.last_backend}

    images = None
    if include_images:
        images = [_crop_to_text(p, paras, os.path.join(out_dir, f"_crop_{i + 1:03d}.png"))
                  for i, (p, paras) in enumerate(zip(image_paths, pages))]
    build_pdf(pdf_path, pages, title=title or f"화면 번역 · {time.strftime('%Y-%m-%d %H:%M')}",
              show_original=show_original, images=images)
    for im in images or []:
        if im and os.path.basename(im).startswith("_crop_"):
            try:
                os.remove(im)
            except OSError:
                pass
    build_text(txt_path, pages)
    report("완료", 1.0)
    return {"pdf": pdf_path, "txt": txt_path, "pages": pages, "warning": warning, "backend": _tr.last_backend}
