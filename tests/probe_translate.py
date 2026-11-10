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
os.makedirs("ci-results", exist_ok=True)
open("ci-results/probe.txt", "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
