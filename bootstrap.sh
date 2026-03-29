#!/usr/bin/env bash
# bootstrap.sh — One-shot local dev setup
set -euo pipefail

echo "==> AFL Predict — bootstrap"

# 1. Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "    Python: $python_version"

# 2. Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "==> Creating virtual environment (.venv)"
    python3 -m venv .venv
fi

# 3. Activate venv
# shellcheck disable=SC1091
source .venv/bin/activate

# 4. Install dependencies
echo "==> Installing dependencies"
pip install --upgrade pip -q
pip install -r requirements-dev.txt -q

# 5. Copy .env if missing
if [ ! -f ".env" ]; then
    echo "==> Copying .env.example → .env"
    cp .env.example .env
    echo "    *** Update .env with your real values before running ***"
fi

# 6. Create storage directories
echo "==> Creating storage directories"
mkdir -p storage/raw_snapshots storage/model_artifacts

echo ""
echo "==> Bootstrap complete."
echo "    Activate your venv: source .venv/bin/activate"
echo "    Start API:          make serve"
echo "    Run pipeline:       make pipeline"
echo "    Run tests:          make test"
