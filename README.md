# claude-ocr

A `/ocr` skill for Claude Code. Turns PDFs, scans, images, and PDF URLs into clean Markdown, then lets Claude read the tricky pages itself.

Free, local, no API keys. Engines: PyMuPDF text layer (instant) -> [Marker](https://github.com/datalab-to/marker) (layout-aware OCR, tables, math) -> Tesseract (fallback). Pages the engine handles poorly are rendered to PNG so Claude can transcribe them with vision.

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

First install downloads ~1.5 GB of Marker models. After that everything runs offline.

## Use

In any Claude Code session: `/ocr path/to/file.pdf` or `/ocr https://.../paper.pdf`, or just hand Claude a PDF and ask a question. Options: `--pages 3-10`, `--engine marker`, `--images`.

Direct CLI:
```bash
.venv/Scripts/python skill/scripts/ocr.py file.pdf --pages 1-5
```

## Update

`git -C ~/claude-ocr pull`. Re-run the install script only if `requirements.txt` changed.
