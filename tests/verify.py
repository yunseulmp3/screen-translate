"""CI 검사: 결과 폴더의 result.json / txt / pdf 확인 + PDF 첫 장을 PNG로 렌더."""
import json, os, re, sys
ok = True
os.makedirs("ci-results", exist_ok=True)
report = []
for out, want_pages in zip(sys.argv[1::2], sys.argv[2::2]):
    want_pages = int(want_pages)
    if os.path.exists(os.path.join(out, "error.txt")):
        report.append(f"[{out}] ERROR\n" + open(os.path.join(out, "error.txt"), encoding="utf-8").read()); ok = False; continue
    r = json.load(open(os.path.join(out, "result.json"), encoding="utf-8"))
    txt = open(r["txt"], encoding="utf-8-sig").read()
    hangul = len(re.findall(r"[가-힣]", txt))
    report.append(f"[{out}] pages={r['pages']} (want {want_pages}) paragraphs={r['paragraphs']} hangul={hangul} warning={r['warning']} backend={r.get('backend')}")
    report.append(txt)
    if r["pages"] != want_pages or r["warning"] or hangul < 100 or not os.path.getsize(r["pdf"]):
        ok = False
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(r["pdf"])
        for i in range(min(2, len(pdf))):
            pdf[i].render(scale=1.2).to_pil().save(os.path.join("ci-results", f"{os.path.basename(out)}_p{i+1}.png"))
    except Exception as e:
        report.append("render fail: " + repr(e))

open(os.path.join("ci-results", "report.txt"), "w", encoding="utf-8").write(("PASS" if ok else "FAIL") + "\n\n" + "\n".join(report))
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
