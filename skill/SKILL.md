---
name: ocr
description: Turn any PDF, scanned document, image, or PDF URL into clean Markdown that Claude can read. Use whenever the user hands over a PDF or image (course readings, scans, screenshots of text, contracts, statements, slide decks) or asks to OCR, extract, read, or summarize one. Auto-picks the fastest engine (text layer -> Tesseract -> RapidOCR) and flags pages Claude should read with its own vision.
---

# /ocr - PDF and image to Markdown

## Run it

```bash
"$OCR_PY" "$OCR_SCRIPT" <file-or-url> [--pages 1-5] [--engine auto|text|tesseract|rapid] [--images] [--out DIR]
```

Resolve the two paths once per session:

- Windows: `OCR_PY=$HOME/claude-ocr/.venv/Scripts/python.exe`
- macOS/Linux: `OCR_PY=$HOME/claude-ocr/.venv/bin/python`
- `OCR_SCRIPT=$HOME/claude-ocr/skill/scripts/ocr.py`

If `$HOME/claude-ocr` is missing, tell the user to run the install script from
https://github.com/maxrosenbaum44/claude-ocr (one command, ~2 min, free).

## Then

1. Read the JSON summary the script prints. `markdown` is the output path.
2. Read the Markdown file. It has `<!-- page N -->` markers.
3. If `thin_pages` is non-empty, PNGs for those pages are under `pages/`.
   Read each PNG with the Read tool and transcribe what the engine missed.
   Claude's vision is the best OCR available; use it for handwriting, stamps,
   rotated tables, and anything the engine mangled.
4. Answer the user's actual question from the text. Cite page numbers.

## Engine choice

- `auto` (default): PDFs with a real text layer skip OCR entirely (<1 s).
  Scans go to Tesseract (~1 s/page, good on clean scans).
- `--engine rapid`: RapidOCR, ~20-30 s/page on CPU. Use for phone photos,
  skewed or low-contrast scans, or when Tesseract output is garbage.
- `--images`: write a PNG for every page. Use when layout matters (tables,
  multi-column) and you want to eyeball pages yourself.
- Use `--pages` for long documents. Do the pages the question needs, not all 300.

## Canvas and other login-walled PDFs

The script can only fetch public URLs. For Canvas, open the file in the
browser tool, fetch the PDF bytes from the DocViewer session
(`/1/sessions/<jwt>/file/file.pdf` on canvadocs.instructure.com) or click
Download, save it locally, then run the script on the local path.

## Do not

- Do not paste 40 pages of Markdown back to the user. Answer the question.
- Do not run `rapid` on a whole textbook without `--pages`.
