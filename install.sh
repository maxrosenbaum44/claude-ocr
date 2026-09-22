#!/usr/bin/env bash
# claude-ocr installer (macOS / Linux). Run: bash install.sh
# Idempotent. Needs python3 (3.10+). Tesseract via Homebrew if available.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="$root/.venv"
py="$venv/bin/python"

command -v python3 >/dev/null || { echo "python3 not found. macOS: brew install python@3.12"; exit 1; }
[ -x "$py" ] || python3 -m venv "$venv"
"$py" -m pip install --upgrade pip -q
"$py" -m pip install -r "$root/requirements.txt" -q

if ! command -v tesseract >/dev/null; then
  if command -v brew >/dev/null; then brew install tesseract; else echo "install tesseract (apt install tesseract-ocr) for the fast engine"; fi
fi

mkdir -p "$HOME/.claude/skills"
rm -rf "$HOME/.claude/skills/ocr"
ln -s "$root/skill" "$HOME/.claude/skills/ocr"

"$py" -c "import pymupdf, rapidocr_onnxruntime; print('python deps ok')"
echo "Installed. In any Claude Code session: /ocr <file-or-url>"
