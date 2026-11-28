"""build_report.py - turns report.md into report.html and report.pdf (A4, 11-point text).

Run from anywhere with the project's Python:    python report/build_report.py

- report.html is one file with the figures inside it.
- report.pdf is printed from that file by Chrome or Chromium without a window. If no such browser is found, open
  report.html in any browser and print it to PDF (A4, no headers and footers).
- The script then prints on which page each section starts, so the 6-page limit of sections 1 to 7 can be checked.

AI disclosure: drafted with Claude (Anthropic) on 28 Nov 2026; log in AI_USE.md.
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
from pathlib import Path

import mistune          # installed with jupyterlab (requirements.txt)

HERE = Path(__file__).resolve().parent
SRC, HTML, PDF = HERE / "report.md", HERE / "report.html", HERE / "report.pdf"

CSS = """
@page { size: A4; margin: 18mm 19mm 17mm 19mm; @bottom-center { content: counter(page); font-size: 9pt; color: #555; } }
html { font-family: "Liberation Sans", Arial, Helvetica, sans-serif; font-size: 11pt; line-height: 1.27; color: #111; }
body { margin: 0; }
h1 { font-size: 15.5pt; line-height: 1.2; margin: 0 0 4pt 0; }
h2 { font-size: 12.5pt; margin: 10pt 0 3pt 0; break-after: avoid; }
p { margin: 0 0 5.5pt 0; text-align: left; }
p:has(+ table), p:has(+ figure) { break-after: avoid; }   /* a table title or a lead-in line stays with what it introduces */
ul, ol { margin: 0 0 5.5pt 0; padding-left: 16pt; }
li { margin: 0 0 1.5pt 0; }
code { font-family: "Liberation Mono", "DejaVu Sans Mono", monospace; font-size: 9.2pt; }
table { border-collapse: collapse; margin: 3pt 0 7pt 0; font-size: 9.3pt; line-height: 1.2; width: 100%; break-inside: avoid; }
th, td { border-bottom: 0.5pt solid #bbb; padding: 2pt 5pt 2pt 0; text-align: left; vertical-align: top; }
th { border-bottom: 0.9pt solid #333; font-weight: 600; }
td { white-space: nowrap; }
td:first-child { white-space: normal; }
figure { margin: 4pt 0 6pt 0; break-inside: avoid; text-align: center; }
figure img { width: 100%; max-width: 145mm; }
figcaption { font-size: 9.3pt; color: #333; text-align: left; margin-top: 1pt; }
hr { border: 0; break-after: page; margin: 0; }
h1.appendix { font-size: 13pt; }
a { color: inherit; text-decoration: none; }
"""


def embed(match: re.Match) -> str:
    """<img src="../figures/x.png" alt="caption"> -> a figure with the picture inside the file and a caption."""
    alt, src = match.group("alt"), match.group("src")
    data = base64.b64encode((HERE / src).resolve().read_bytes()).decode()
    return f'<figure><img src="data:image/png;base64,{data}" alt="{alt}"><figcaption>{alt}</figcaption></figure>'


def build_html() -> str:
    md = mistune.create_markdown(plugins=["table"], escape=False)
    body = md(SRC.read_text(encoding="utf-8"))
    body = re.sub(r'<p><img src="(?P<src>[^"]+)" alt="(?P<alt>[^"]*)"\s*/?></p>', embed, body)
    assert "<img src=\"../" not in body, "a figure was not embedded"
    body = body.replace("<h1>Technical appendix", '<h1 class="appendix">Technical appendix')
    title = re.search(r"<h1>(.*?)</h1>", body).group(1)
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{CSS}</style></head><body>\n{body}\n</body></html>\n")


def browser() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return name
    return None


def page_starts() -> None:
    if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
        return
    info = subprocess.run(["pdfinfo", str(PDF)], capture_output=True, text=True).stdout
    pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
    print(f"report.pdf: {pages} pages")
    seen: set[str] = set()
    last_main = None
    for p in range(1, pages + 1):
        text = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", str(PDF), "-"],
                              capture_output=True, text=True).stdout
        for line in text.splitlines():
            m = re.match(r"\s*(\d)\. (Abstract|Problem|Data curation|Methods|Results|Discussion|Reproducibility|References)", line)
            if m and m.group(2) not in seen:
                seen.add(m.group(2))
                print(f"  page {p}: {line.strip()}")
                if m.group(2) == "References":
                    last_main = p
            if "Technical appendix" in line and "appendix" not in seen:
                seen.add("appendix")
                print(f"  page {p}: {line.strip()}")
    if last_main:
        print(f"sections 1 to 7 end on page {last_main} (the limit is 6)")


def main() -> None:
    HTML.write_text(build_html(), encoding="utf-8")
    print(f"written {HTML.name} ({HTML.stat().st_size / 1024:.0f} KB)")
    exe = browser()
    if exe is None:
        print("no Chrome or Chromium found: open report.html in a browser and print it to PDF (A4)")
        return
    subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={PDF}", HTML.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"written {PDF.name} ({PDF.stat().st_size / 1024:.0f} KB)")
    page_starts()


if __name__ == "__main__":
    main()
