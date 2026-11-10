"""영어 → 한국어 번역 (무료). 구글 번역을 먼저 쓰고, 막히면 자동으로 다른 길로 넘어간다.

순서: 구글(gtx) → 구글(크롬 사전 확장 경로) → 마이크로소프트(엣지 내장 번역) → 구글 모바일 페이지
한 번 막힌 길은 이번 작업 동안 다시 쓰지 않음.
"""
import html
import re
import time

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_CHARS = 1800

last_backend = None  # 마지막으로 성공한 번역 경로 이름(로그·테스트용)


class TranslateError(RuntimeError):
    pass


class _Blocked(Exception):
    pass


def _check(r):
    if r.status_code != 200:
        raise _Blocked(f"HTTP {r.status_code}")


# ── 각 번역 경로: 문자열 목록을 받아 같은 개수의 번역 목록을 돌려줌 ──

def _gtx_one(sess, text, sl, tl):
    r = sess.get("https://translate.googleapis.com/translate_a/single",
                 params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "dj": "1", "q": text}, timeout=20)
    _check(r)
    return "".join(s.get("trans", "") for s in r.json().get("sentences", []))


def _google_gtx(sess, texts, sl, tl):
    # 여러 문단을 줄바꿈으로 묶어 한 번에 → 줄 수가 어긋나면 하나씩
    res = _gtx_one(sess, "\n".join(texts), sl, tl).split("\n")
    if len(res) == len(texts):
        return res
    return [_gtx_one(sess, t, sl, tl) for t in texts]


def _google_dict(sess, texts, sl, tl):
    r = sess.get("https://clients5.google.com/translate_a/t",
                 params=[("client", "dict-chrome-ex"), ("sl", sl), ("tl", tl)] + [("q", t) for t in texts], timeout=20)
    _check(r)
    data = r.json()
    if len(texts) == 1 and isinstance(data, list) and data and isinstance(data[0], str):
        data = [data[0]]
    out = []
    for d in data:
        while isinstance(d, list):
            d = d[0] if d else ""
        out.append(str(d))
    if len(out) != len(texts):
        raise _Blocked("응답 개수 불일치")
    return out


_edge_token = {"v": None, "t": 0}


def _edge(sess, texts, sl, tl):
    if not _edge_token["v"] or time.time() - _edge_token["t"] > 500:
        r = sess.get("https://edge.microsoft.com/translate/auth", timeout=15)
        _check(r)
        _edge_token.update(v=r.text.strip(), t=time.time())
    r = sess.post("https://api-edge.cognitive.microsofttranslator.com/translate",
                  params={"from": sl, "to": tl, "api-version": "3.0"},
                  headers={"Authorization": "Bearer " + _edge_token["v"], "Content-Type": "application/json"},
                  json=[{"Text": t} for t in texts], timeout=30)
    if r.status_code == 401:
        _edge_token["v"] = None
    _check(r)
    return [d["translations"][0]["text"] for d in r.json()]


_RESULT_RE = re.compile(r'<div class="result-container">(.*?)</div>', re.S)


def _google_mobile(sess, texts, sl, tl):
    out = []
    for t in texts:
        r = sess.get("https://translate.google.com/m", params={"sl": sl, "tl": tl, "q": t, "hl": "ko"}, timeout=20)
        _check(r)
        m = _RESULT_RE.search(r.text)
        if not m:
            raise _Blocked("결과 없음")
        out.append(html.unescape(m.group(1)))
    return out


BACKENDS = [("google", _google_gtx), ("google-dict", _google_dict), ("microsoft", _edge), ("google-mobile", _google_mobile)]


def _with_retry(fn, sess, texts, sl, tl, tries=2):
    last = None
    for i in range(tries):
        try:
            res = fn(sess, texts, sl, tl)
            if len(res) != len(texts):
                raise _Blocked("응답 개수 불일치")
            return res
        except (_Blocked, requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
            last = e
            time.sleep(1.0 + i)
    raise _Blocked(str(last))


def _untranslated(src, res):
    """번역 결과가 원문 그대로 돌아온 경우 (일부 경로는 길이 제한을 넘으면 원문을 그대로 돌려줌)"""
    return bool(re.search(r"[A-Za-z]{3}", src)) and \
        re.sub(r"\W+", "", (res or "").lower()) == re.sub(r"\W+", "", src.lower())


def translate_many(texts, sl="en", tl="ko", progress=None, backends=None):
    """문단 목록을 몇 개씩 묶어서 번역. 순서·개수 그대로 돌려줌."""
    global last_backend
    texts = [t.replace("\n", " ").strip() for t in texts]
    out = [""] * len(texts)
    batches, cur, size = [], [], 0
    for i, t in enumerate(texts):
        if cur and (size + len(t) + 1 > MAX_CHARS or len(cur) >= 25):
            batches.append(cur)
            cur, size = [], 0
        cur.append(i)
        size += len(t) + 1
    if cur:
        batches.append(cur)

    alive = list(backends or BACKENDS)
    errors = []
    sess = requests.Session()
    sess.headers["User-Agent"] = UA

    def run(chunk, start=0):
        """살아있는 경로로 번역. 반환 (결과, 사용한 경로 인덱스)"""
        global last_backend
        k = start
        while k < len(alive):
            name, fn = alive[k]
            try:
                res = _with_retry(fn, sess, chunk, sl, tl)
                last_backend = name
                return res, k
            except _Blocked as e:
                errors.append(f"{name}: {e}")
                if start == 0:
                    alive.pop(k)  # 막힌 길은 버리고 다음 길로
                else:
                    k += 1
        raise TranslateError(" / ".join(errors) or "번역 경로 없음")

    done = 0
    for b in batches:
        res, _ = run([texts[i] for i in b])
        for i, r in zip(b, res):
            out[i] = r.strip()
        done += len(b)
        if progress:
            progress(done / max(1, len(texts)))

    # 원문 그대로 돌아온 문단은 하나씩 다시 (그래도 안 되면 다음 경로로)
    for i, t in enumerate(texts):
        if not _untranslated(t, out[i]):
            continue
        k = 0
        while k < len(alive):
            try:
                r, used = run([t], start=k)
            except TranslateError:
                break
            if not _untranslated(t, r[0]):
                out[i] = r[0].strip()
                break
            k = used + 1
    return out
