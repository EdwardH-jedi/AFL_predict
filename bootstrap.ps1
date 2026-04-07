# bootstrap.ps1 - AFL Predict one-shot setup for Windows (PowerShell)
# Usage: Right-click -> "Run with PowerShell"  OR  .\bootstrap.ps1
#
# What this does:
#   1. Creates an isolated virtual environment (.venv) in the project folder
#   2. Installs all dependencies INSIDE the venv (never touches global Python)
#   3. Copies .env.example -> .env if .env doesn't exist
#   4. Creates required storage directories
#
# open-webui is NOT affected because it uses a separate environment.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==> AFL Predict -- Windows Bootstrap" -ForegroundColor Cyan
Write-Host ""

# --- 1. Check Python ---
try {
    $pyver = & python --version 2>&1
    Write-Host "    Python: $pyver"
} catch {
    Write-Host "ERROR: python not found. Install Python 3.11 from python.org" -ForegroundColor Red
    exit 1
}

# --- 2. Create venv if it doesn't exist ---
if (-Not (Test-Path ".venv")) {
    Write-Host "==> Creating virtual environment (.venv)" -ForegroundColor Yellow
    python -m venv .venv
    Write-Host "    Done." -ForegroundColor Green
} else {
    Write-Host "==> Virtual environment already exists (.venv)" -ForegroundColor Green
}

# --- 3. Upgrade pip inside venv ---
Write-Host "==> Upgrading pip inside venv..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet

# --- 4. Install dependencies into venv ---
Write-Host "==> Installing dependencies (this may take a few minutes)..." -ForegroundColor Yellow
& .\.venv\Scripts\pip.exe install -r requirements-dev.txt

Write-Host ""
Write-Host "==> Dependencies installed." -ForegroundColor Green

# --- 5. Copy .env if missing ---
if (-Not (Test-Path ".env")) {
    Write-Host "==> Copying .env.example -> .env"
    Copy-Item ".env.example" ".env"
    Write-Host "    *** Open .env and fill in ODDS_API_KEY etc. before running ***" -ForegroundColor Yellow
} else {
    Write-Host "==> .env already exists -- skipping copy."
}

# --- 6. Create storage directories ---
Write-Host "==> Creating storage directories..."
New-Item -ItemType Directory -Force -Path "storage\raw_snapshots" | Out-Null
New-Item -ItemType Directory -Force -Path "storage\model_artifacts" | Out-Null
New-Item -ItemType Directory -Force -Path "storage\daily_summaries" | Out-Null

# --- Done ---
Write-Host ""
Write-Host "==> Bootstrap complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "  1. Activate venv:     .\.venv\Scripts\Activate.ps1"
Write-Host "  2. Apply DB schema:   python -m alembic upgrade head"
Write-Host "  3. Start API:         uvicorn api.main:app --reload"
Write-Host "  4. Run tests:         pytest tests/ -v"
Write-Host ""
Write-Host "  open-webui is NOT affected (it uses its own environment)." -ForegroundColor Green
Write-Host ""
