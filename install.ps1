# claude-ocr installer (Windows). Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Idempotent. Needs Python 3.10+ on PATH and git.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root ".venv"
$py = Join-Path $venv "Scripts\python.exe"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Installing via winget..."
    winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements --silent
    Write-Host "Reopen this terminal and re-run install.ps1 (winget does not refresh PATH)."
    exit 1
}

if (-not (Test-Path $py)) { python -m venv $venv }
& $py -m pip install --upgrade pip -q
& $py -m pip install -r (Join-Path $root "requirements.txt") -q

# Tesseract (signed installer, ~50 MB)
if (-not (Test-Path "C:\Program Files\Tesseract-OCR\tesseract.exe")) {
    winget install --id UB-Mannheim.TesseractOCR --source winget --accept-package-agreements --accept-source-agreements --silent | Out-Null
}

# Link the skill into Claude Code's user skills dir
$skills = Join-Path $HOME ".claude\skills"
New-Item -ItemType Directory -Force $skills | Out-Null
$link = Join-Path $skills "ocr"
if (Test-Path $link) { cmd /c rmdir "$link" | Out-Null }
cmd /c mklink /J "$link" "$(Join-Path $root 'skill')" | Out-Null

& $py -c "import pymupdf, rapidocr_onnxruntime; print('python deps ok')"
Write-Host "Installed. In any Claude Code session: /ocr <file-or-url>"
