# 사진이 많은 정리 문서 흉내: 뷰어 화면 안에 흰 문서, 제목/본문/사진/캡션/사진 옆 글/글머리표
import glob, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


def _f(lin, win):
    c = glob.glob("/usr/share/fonts/**/" + lin, recursive=True) + glob.glob("C:/Windows/Fonts/" + win)
    return c[0]


SANS = _f("LiberationSans-Regular.ttf", "arial.ttf")
SANSB = _f("LiberationSans-Bold.ttf", "arialbd.ttf")
SANSI = _f("LiberationSans-Italic.ttf", "ariali.ttf")
W, H = 1920, 1032


def photo(w, h, seed, label=None):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([(xx / w * 180 + 40), (yy / h * 120 + 60), (255 - xx / w * 150)], -1)
    base += rng.normal(0, 12, base.shape)
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    for k in range(6):
        x, y, r = rng.integers(0, w), rng.integers(0, h), rng.integers(15, 60)
        d.ellipse([x - r, y - r, x + r, y + r], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    if label:
        d = ImageDraw.Draw(im)
        d.text((14, h - 34), label, font=ImageFont.truetype(SANSB, 18), fill=(255, 255, 255))
    return im


def wrap(d, t, font, w):
    words, lines, cur = t.split(), [], ""
    for wd in words:
        tt = (cur + " " + wd).strip()
        if d.textlength(tt, font=font) <= w:
            cur = tt
        else:
            lines.append(cur); cur = wd
    lines.append(cur)
    return lines


def chrome(i, n):
    im = Image.new("RGB", (W, H), (56, 56, 60))
    d = ImageDraw.Draw(im)
    ui = ImageFont.truetype(SANS, 15)
    d.rectangle([0, 0, W, 36], fill=(36, 36, 40))
    d.text((12, 9), "File   Edit   View   Insert   Help", font=ui, fill=(220, 220, 220))
    d.text((W - 260, 9), f"Page {i + 1} of {n}    100%", font=ui, fill=(220, 220, 220))
    px0, px1 = 520, 1400
    d.rectangle([px0, 56, px1, H], fill=(255, 255, 255))
    return im, d, px0, px1


def page1(n):
    im, d, px0, px1 = chrome(0, n)
    x, y, mw = px0 + 60, 100, px1 - px0 - 120
    fb, f, fi = ImageFont.truetype(SANSB, 30), ImageFont.truetype(SANS, 19), ImageFont.truetype(SANSI, 15)
    d.text((x, y), "My Home Studio Setup", font=fb, fill=(20, 20, 20)); y += 56
    for ln in wrap(d, "This page shows how my desk is arranged for recording and streaming. Every cable is labeled so that the setup can be restored quickly after moving.", f, mw):
        d.text((x, y), ln, font=f, fill=(30, 30, 30)); y += 27
    y += 18
    ph = photo(mw, 300, 1, label="DESK OVERVIEW")
    im.paste(ph, (x, y)); y += 300 + 8
    d.text((x, y), "Figure 1. The interface sits on the left, monitors in the center.", font=fi, fill=(110, 110, 110)); y += 36
    for ln in wrap(d, "The microphone arm is mounted on the right side so that it never blocks the screen. Keep the arm tight enough that it does not drift during long sessions.", f, mw):
        d.text((x, y), ln, font=f, fill=(30, 30, 30)); y += 27
    return im


def page2(n):
    im, d, px0, px1 = chrome(1, n)
    x, y, mw = px0 + 60, 100, px1 - px0 - 120
    fb, f, fi = ImageFont.truetype(SANSB, 26), ImageFont.truetype(SANS, 19), ImageFont.truetype(SANSI, 15)
    d.text((x, y), "Cable Routing", font=fb, fill=(20, 20, 20)); y += 52
    ph = photo(330, 250, 2)
    im.paste(ph, (x, y))
    tx, tw = x + 330 + 30, mw - 360
    yy = y
    for ln in wrap(d, "Power cables run along the back edge of the desk, while audio cables stay on the front side. Separating them reduces hum and makes troubleshooting much easier.", f, tw):
        d.text((tx, yy), ln, font=f, fill=(30, 30, 30)); yy += 27
    y += 250 + 8
    d.text((x, y), "Figure 2. Cable tray under the desk.", font=fi, fill=(110, 110, 110)); y += 40
    d.text((x, y), "Checklist", font=ImageFont.truetype(SANSB, 22), fill=(20, 20, 20)); y += 40
    for t in ["Label both ends of every cable.", "Use short patch cables between the interface and the preamp.",
              "Leave one spare input free for guests."]:
        d.text((x + 6, y), "•", font=f, fill=(30, 30, 30))
        d.text((x + 30, y), t, font=f, fill=(30, 30, 30)); y += 32
    y += 16
    ph = photo(mw, 230, 3)
    im.paste(ph, (x, y)); y += 230 + 8
    d.text((x, y), "Figure 3. Finished setup after routing.", font=fi, fill=(110, 110, 110))
    return im


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "test"
    os.makedirs(out, exist_ok=True)
    page1(2).save(os.path.join(out, "photo1.png"))
    page2(2).save(os.path.join(out, "photo2.png"))
