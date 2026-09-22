#!/usr/bin/env python
"""
ocr.py - turn a PDF, image, or URL into clean Markdown for Claude.

Strategy (fast to slow, cheapest that works):
  1. text   : PDF already has a text layer -> PyMuPDF extraction (< 1 s).
  2. marker : scanned / image PDF -> Marker (Surya layout + OCR), best quality.
  3. tesseract: Marker unavailable -> render pages, run Tesseract CLI.
Pages that still come out thin are flagged so Claude can read the PNGs
directly with its own vision.

Usage:
  ocr.py INPUT [--out DIR] [--pages 1-5] [--engine auto|text|marker|tesseract]
               [--images] [--dpi 150] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
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


def log(msg: str) -> None:
    print(f"[ocr] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- input ----
def fetch(src: str, workdir: Path) -> Path:
    if re.match(r"^https?://", src):
        name = re.sub(r"[^\w.-]", "_", src.split("?")[0].rsplit("/", 1)[-1]) or "download"
        if not Path(name).suffix:
            name += ".pdf"
        dst = workdir / name
        log(f"downloading {src}")
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
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
        import fitz  # PyMuPDF

        doc = fitz.open()
        img = fitz.open(path)
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
    import fitz

    doc = fitz.open(pdf)
    return [doc[i].get_text("text") for i in pages]


def has_text_layer(pdf: Path, pages: list[int]) -> bool:
    texts = engine_text(pdf, pages)
    good = sum(1 for t in texts if len(t.strip()) >= MIN_CHARS_PER_PAGE)
    return good >= max(1, int(0.6 * len(pages)))


def engine_marker(pdf: Path, pages: list[int], force_ocr: bool) -> list[str]:
    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    cfg = {
        "output_format": "markdown",
        "page_range": ",".join(str(i) for i in pages),
        "force_ocr": force_ocr,
        "paginate_output": True,
        "disable_image_extraction": True,
    }
    parser = ConfigParser(cfg)
    log("loading Marker models (first run downloads ~1.5 GB, later runs ~20 s)")
    t0 = time.time()
    converter = PdfConverter(
        config=parser.generate_config_dict(),
        artifact_dict=create_model_dict(),
        processor_list=parser.get_processors(),
        renderer=parser.get_renderer(),
    )
    log(f"models ready in {time.time() - t0:.0f}s, converting {len(pages)} page(s)")
    rendered = converter(str(pdf))
    text, _, _ = text_from_rendered(rendered)
    # paginate_output separates pages with a form-feed + page marker line
    chunks = re.split(r"\n*-{3,}\s*\n*\{\d+\}-{3,}\n*|\f", text)
    chunks = [c for c in chunks if c.strip()]
    if len(chunks) != len(pages):
        return [text]  # fall back to one blob rather than misalign
    return chunks


def render_pages(pdf: Path, pages: list[int], dpi: int, outdir: Path) -> list[Path]:
    import fitz

    outdir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf)
    paths = []
    for i in pages:
        p = outdir / f"page-{i + 1:03d}.png"
        doc[i].get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    return paths


def engine_tesseract(pdf: Path, pages: list[int], dpi: int, workdir: Path) -> list[str]:
    exe = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not Path(exe).exists():
        sys.exit("[ocr] neither Marker nor Tesseract is available; run install script")
    pngs = render_pages(pdf, pages, dpi, workdir / "tess")
    out = []
    for png in pngs:
        r = subprocess.run([exe, str(png), "stdout", "--psm", "3"], capture_output=True, text=True)
        out.append(r.stdout)
    return out


# ----------------------------------------------------------------- main ----
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="PDF, image, or http(s) URL")
    ap.add_argument("--out", help="output directory (default: <input dir>/<stem>_ocr)")
    ap.add_argument("--pages", help="1-based page spec, e.g. 1-5,9")
    ap.add_argument("--engine", default="auto", choices=["auto", "text", "marker", "tesseract"])
    ap.add_argument("--images", action="store_true", help="also write page PNGs for every page")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--json", action="store_true", help="print machine-readable summary only")
    a = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="ocr_"))
    src = fetch(a.input, work)
    pdf = to_pdf(src, work)
    outdir = Path(a.out) if a.out else src.parent / f"{src.stem}_ocr"
    outdir.mkdir(parents=True, exist_ok=True)

    import fitz

    n = len(fitz.open(pdf))
    pages = parse_pages(a.pages, n)
    if not pages:
        sys.exit("[ocr] page spec matched nothing")

    engine = a.engine
    if engine == "auto":
        engine = "text" if has_text_layer(pdf, pages) else "marker"
    log(f"{src.name}: {n} pages, using {len(pages)}, engine={engine}")

    t0 = time.time()
    texts: list[str]
    if engine == "text":
        texts = engine_text(pdf, pages)
    elif engine == "marker":
        try:
            texts = engine_marker(pdf, pages, force_ocr=not has_text_layer(pdf, pages))
        except ImportError as e:
            log(f"Marker not importable ({e}); falling back to Tesseract")
            engine = "tesseract"
            texts = engine_tesseract(pdf, pages, a.dpi, work)
    else:
        texts = engine_tesseract(pdf, pages, a.dpi, work)
    secs = time.time() - t0

    # per-page assembly + thin-page detection
    md_parts, thin = [], []
    aligned = len(texts) == len(pages)
    for k, t in enumerate(texts):
        pno = pages[k] + 1 if aligned else None
        if aligned and len(t.strip()) < MIN_CHARS_PER_PAGE:
            thin.append(pno)
        header = f"\n\n<!-- page {pno} -->\n\n" if aligned else "\n\n"
        md_parts.append(header + t.strip())
    md_path = outdir / f"{src.stem}.md"
    md_path.write_text(f"# {src.name}\n" + "".join(md_parts).strip() + "\n", encoding="utf-8")

    png_pages = pages if a.images else [p - 1 for p in thin]
    pngs = render_pages(pdf, png_pages, a.dpi, outdir / "pages") if png_pages else []

    summary = {
        "input": str(src),
        "markdown": str(md_path),
        "engine": engine,
        "pages_total": n,
        "pages_done": len(pages),
        "seconds": round(secs, 1),
        "chars": sum(len(t) for t in texts),
        "thin_pages": thin,
        "page_images": [str(p) for p in pngs],
    }
    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        print(json.dumps(summary, indent=2))
        if thin:
            print(
                f"\n[ocr] {len(thin)} thin page(s) {thin}: PNGs written under {outdir / 'pages'} - "
                "read them with the Read tool to fill gaps.",
                file=sys.stderr,
            )
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
