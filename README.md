# claude-ocr

A `/ocr` skill for Claude Code. Turns PDFs, scans, images, and PDF URLs into clean Markdown, then lets Claude read the tricky pages itself.

Free, local, no API keys, no model downloads, nothing to maintain.

Engines, cheapest first:

| Engine | When | Speed (CPU) |
|---|---|---|
| PyMuPDF text layer | PDF already has text | instant |
| Tesseract 5 | scans, default | ~1 s/page |
| RapidOCR (PaddleOCR on onnxruntime) | photos, skew, low contrast; `--engine rapid` | ~20-30 s/page |
| Claude vision | pages flagged thin are rendered to PNG for Claude to read | n/a |

## Install

Windows:
```powershell
git clone https://github.com/maxrosenbaum44/claude-ocr $HOME\claude-ocr
powershell -ExecutionPolicy Bypass -File $HOME\claude-ocr\install.ps1
```

macOS / Linux:
```bash
git clone https://github.com/maxrosenbaum44/claude-ocr ~/claude-ocr
bash ~/claude-ocr/install.sh
```

## Use

In any Claude Code session: `/ocr path/to/file.pdf`, `/ocr https://.../paper.pdf`, or just hand Claude a PDF and ask a question. Options: `--pages 3-10`, `--engine rapid`, `--images`.

Direct CLI:
```bash
.venv/Scripts/python skill/scripts/ocr.py file.pdf --pages 1-5
```

## Update

`git -C ~/claude-ocr pull`. Re-run the install script only if `requirements.txt` changed.

## Why not Marker / Surya / docTR?

Tried. They are better on layout but need PyTorch, ~1.5 GB of models hosted by the vendor (older pins already fail to download), and on Windows some of their unsigned DLLs are blocked by Smart App Control. Not worth the upkeep when Claude can read the hard pages itself.
