#!/usr/bin/env python
"""
ocr.py - turn a PDF, image, or URL into clean Markdown for Claude.

Engines, cheapest that works first:
  text      PDF already has a text layer -> PyMuPDF extraction (< 1 s).
  tesseract scanned / image PDF -> render pages, Tesseract 5 (~1 s/page). Default for scans.
  rapid     RapidOCR (PaddleOCR models on onnxruntime). Slower (~20-30 s/page CPU)
            but better on photos, skew, low contrast, mixed scripts. Opt in with --engine rapid.
Pages that still come out thin are rendered to PNG so Claude can read them
with its own vision, which beats every engine above on hard pages.

Usage:
  ocr.py INPUT [--out DIR] [--pages 1-5] [--engine auto|text|tesseract|rapid]
               [--images] [--dpi 200]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

MIN_CHARS_PER_PAGE = 200  # below this a page is "thin" and gets flagged
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
]


def log(msg: str) -> None:
    print(f"[ocr] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- input ----
def fetch(src: str, workdir: Path) -> Path:
    if re.match(r"^https?://", src):
        name = re.sub(r"[^\w.-]", "_", src.split("?")[0].rsplit("/", 1)[-1]) or "download"
        dst = workdir / name
        log(f"downloading {src}")
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
        # Trust the bytes, not the URL (arxiv.org/pdf/1706.03762v7 has no extension).
        head = dst.read_bytes()[:12]
        sniffed = (
            ".pdf" if head.startswith(b"%PDF") else
            ".png" if head.startswith(b"\x89PNG") else
            ".jpg" if head.startswith(b"\xff\xd8") else
            ".webp" if head[8:12] == b"WEBP" else
            ".tif" if head[:4] in (b"II*\x00", b"MM\x00*") else None
        )
        if sniffed and dst.suffix.lower() != sniffed:
            fixed = dst.with_name(dst.name.replace(".", "_") + sniffed)
            dst.rename(fixed)
            dst = fixed
        return dst
    p = Path(src).expanduser().resolve()
    if not p.exists():
        sys.exit(f"[ocr] not found: {p}")
    return p


def to_pdf(path: Path, workdir: Path) -> Path:
    """Images become a one-page PDF so every engine sees the same input."""
    if path.suffix.lower() == ".pdf":
        return path
    if path.suffix.lower() in IMAGE_EXT:
        import pymupdf

        doc = pymupdf.open()
        img = pymupdf.open(path)
        rect = img[0].rect
        page = doc.new_page(width=rect.width, height=rect.height)
        page.insert_image(rect, filename=str(path))
        out = workdir / (path.stem + ".pdf")
        doc.save(out)
        return out
    sys.exit(f"[ocr] unsupported file type: {path.suffix}")


def parse_pages(spec: str | None, n: int) -> list[int]:
    """'1-3,7' -> [0,1,2,6] (0-based, clipped)."""
    if not spec:
        return list(range(n))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [i for i in out if 0 <= i < n]


# -------------------------------------------------------------- engines ----
def engine_text(pdf: Path, pages: list[int]) -> list[str]:
    import pymupdf

    doc = pymupdf.open(pdf)
    return [doc[i].get_text("text") for i in pages]


def has_text_layer(pdf: Path, pages: list[int]) -> bool:
    texts = engine_text(pdf, pages)
    good = sum(1 for t in texts if len(t.strip()) >= MIN_CHARS_PER_PAGE)
    return good >= max(1, int(0.6 * len(pages)))


def render_pages(pdf: Path, pages: list[int], dpi: int, outdir: Path) -> list[Path]:
    import pymupdf

    outdir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    paths = []
    for i in pages:
        p = outdir / f"page-{i + 1:03d}.png"
        doc[i].get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    return paths


def find_tesseract() -> str | None:
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for c in TESSERACT_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def engine_tesseract(pdf: Path, pages: list[int], dpi: int, workdir: Path) -> list[str]:
    exe = find_tesseract()
    if not exe:
        raise RuntimeError("tesseract not installed (winget UB-Mannheim.TesseractOCR / brew install tesseract)")
    pngs = render_pages(pdf, pages, dpi, workdir / "tess")
    out = []
    for png in pngs:
        r = subprocess.run(
            [exe, str(png), "stdout", "--psm", "3"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        out.append(r.stdout)
    return out


def _lines_from_boxes(results) -> str:
    """RapidOCR gives (box, text, score) per snippet. Group into lines by
    vertical center, then order left to right, so columns read sanely."""
    items = []
    for box, text, _score in results or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append(((min(ys) + max(ys)) / 2, min(xs), max(ys) - min(ys), text))
    items.sort()
    lines, cur, cur_y = [], [], None
    for yc, x0, h, text in items:
        if cur_y is None or abs(yc - cur_y) <= max(6, 0.5 * h):
            cur.append((x0, text))
            cur_y = yc if cur_y is None else (cur_y + yc) / 2
        else:
            lines.append(" ".join(t for _, t in sorted(cur)))
            cur, cur_y = [(x0, text)], yc
    if cur:
        lines.append(" ".join(t for _, t in sorted(cur)))
    return "\n".join(lines)


def engine_rapid(pdf: Path, pages: list[int], dpi: int, workdir: Path) -> list[str]:
    from rapidocr_onnxruntime import RapidOCR

    eng = RapidOCR()
    pngs = render_pages(pdf, pages, dpi, workdir / "rapid")
    out = []
    for k, png in enumerate(pngs, 1):
        t0 = time.time()
        res, _ = eng(str(png))
        out.append(_lines_from_boxes(res))
        log(f"rapid page {k}/{len(pngs)} {time.time() - t0:.0f}s")
    return out


# ----------------------------------------------------------------- main ----
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="PDF, image, or http(s) URL")
    ap.add_argument("--out", help="output directory (default: <input dir>/<stem>_ocr)")
    ap.add_argument("--pages", help="1-based page spec, e.g. 1-5,9")
    ap.add_argument("--engine", default="auto", choices=["auto", "text", "tesseract", "rapid"])
    ap.add_argument("--images", action="store_true", help="also write page PNGs for every page")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="ocr_"))
    src = fetch(a.input, work)
    pdf = to_pdf(src, work)
    outdir = Path(a.out) if a.out else src.parent / f"{src.stem}_ocr"
    outdir.mkdir(parents=True, exist_ok=True)

    import pymupdf

    n = len(pymupdf.open(pdf))
    pages = parse_pages(a.pages, n)
    if not pages:
        sys.exit("[ocr] page spec matched nothing")

    engine = a.engine
    if engine == "auto":
        engine = "text" if has_text_layer(pdf, pages) else "tesseract"
    log(f"{src.name}: {n} pages, using {len(pages)}, engine={engine}")

    t0 = time.time()
    texts: list[str] = []
    try:
        if engine == "text":
            texts = engine_text(pdf, pages)
        elif engine == "tesseract":
            texts = engine_tesseract(pdf, pages, a.dpi, work)
        else:
            texts = engine_rapid(pdf, pages, a.dpi, work)
    except Exception as e:  # missing binary, blocked DLL, bad image...
        log(f"{engine} failed ({type(e).__name__}: {str(e).strip()[:200]})")
        fallback = "rapid" if engine == "tesseract" else "tesseract"
        log(f"falling back to {fallback}")
        engine = fallback
        texts = engine_rapid(pdf, pages, a.dpi, work) if fallback == "rapid" else engine_tesseract(pdf, pages, a.dpi, work)
    secs = time.time() - t0

    # per-page assembly + thin-page detection
    md_parts, thin = [], []
    for k, t in enumerate(texts):
        pno = pages[k] + 1
        if len(t.strip()) < MIN_CHARS_PER_PAGE:
            thin.append(pno)
        md_parts.append(f"\n\n<!-- page {pno} -->\n\n" + t.strip())
    md_path = outdir / f"{src.stem}.md"
    md_path.write_text(f"# {src.name}\n" + "".join(md_parts).strip() + "\n", encoding="utf-8")

    png_pages = pages if a.images else [p - 1 for p in thin]
    pngs = render_pages(pdf, png_pages, min(a.dpi, 150), outdir / "pages") if png_pages else []

    print(json.dumps({
        "input": str(src),
        "markdown": str(md_path),
        "engine": engine,
        "pages_total": n,
        "pages_done": len(pages),
        "seconds": round(secs, 1),
        "chars": sum(len(t) for t in texts),
        "thin_pages": thin,
        "page_images": [str(p) for p in pngs],
    }, indent=2))
    if thin:
        log(f"{len(thin)} thin page(s) {thin}: PNGs under {outdir / 'pages'} - read them with the Read tool.")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
