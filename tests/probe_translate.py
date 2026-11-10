"""번역 경로별 동작 점검 (CI용)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
from screentrans import translate as T
s = requests.Session(); s.headers["User-Agent"] = T.UA
texts = ["Hello, how are you?", "Increase the buffer to 256 samples and test again."]
lines = []
for name, fn in T.BACKENDS:
    try:
        lines.append(f"{name}: OK {fn(s, texts, 'en', 'ko')}")
    except Exception as e:
        lines.append(f"{name}: FAIL {e!r}")
# 여러 문단 한 번에 보냈을 때 원문 그대로 돌아오는 게 있는지
sys.path.insert(0, "tests")
from make_screens import pages
paras = [t for pg in pages for k, t in pg]
for name, fn in T.BACKENDS[:2]:
    try:
        res = fn(s, paras, "en", "ko")
        same = [i for i, (a, b) in enumerate(zip(paras, res)) if T._untranslated(a, b)]
        lines.append(f"{name} x{len(paras)} ({sum(map(len, paras))}자): 원문그대로={same}")
    except Exception as e:
        lines.append(f"{name} x{len(paras)}: FAIL {e!r}")
os.makedirs("ci-results", exist_ok=True)
open("ci-results/probe.txt", "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
