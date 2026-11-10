"""무료 구글 번역(웹 번역기와 같은 엔드포인트)으로 영어 → 한국어."""
import json
import time

import requests

URL = "https://translate.googleapis.com/translate_a/single"
MAX_CHARS = 1800


class TranslateError(RuntimeError):
    pass


def _call(text, sl="en", tl="ko", session=None, retries=4):
    s = session or requests
    last = None
    for attempt in range(retries):
        try:
            r = s.get(URL, params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "dj": "1", "q": text},
                      timeout=20,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if r.status_code == 200:
                data = r.json()
                return "".join(seg.get("trans", "") for seg in data.get("sentences", []))
            last = f"HTTP {r.status_code}"
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise TranslateError("번역 서버 응답 실패: " + str(last))


def translate_many(texts, sl="en", tl="ko", progress=None):
    """문단 목록을 몇 개씩 묶어서 번역 (요청 횟수를 줄여 차단 방지). 순서·개수 그대로 돌려줌."""
    out = [None] * len(texts)
    sess = requests.Session()
    batches, cur, size = [], [], 0
    for i, t in enumerate(texts):
        t = t.replace("\n", " ").strip()
        if cur and size + len(t) + 1 > MAX_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append((i, t))
        size += len(t) + 1
    if cur:
        batches.append(cur)
    done = 0
    for b in batches:
        joined = "\n".join(t for _, t in b)
        res = _call(joined, sl, tl, sess).split("\n")
        if len(res) == len(b):
            for (i, _), r in zip(b, res):
                out[i] = r.strip()
        else:  # 줄 수가 어긋나면 하나씩 다시
            for i, t in b:
                out[i] = _call(t, sl, tl, sess).strip()
        done += len(b)
        if progress:
            progress(done / max(1, len(texts)))
    return out
