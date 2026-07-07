#!/usr/bin/env bash
# One-shot dev setup: creates a virtualenv, installs deps, seeds .env.
# Run from the project root:  ./setup.sh
set -euo pipefail

PY=${PYTHON:-python3}

echo "==> Creating virtualenv in .venv"
"$PY" -m venv .venv

echo "==> Installing dependencies"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  echo "==> Seeding .env from .env.example (fill in your secrets)"
  cp .env.example .env
else
  echo "==> .env already exists, leaving it alone"
fi

echo
echo "Done. Next:"
echo "  1. Edit .env and add your TELEGRAM_TOKEN and OPENAI_API_KEY"
echo "  2. source .venv/bin/activate"
echo "  3. python bot.py"
