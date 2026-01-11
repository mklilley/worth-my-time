#!/usr/bin/env bash
set -euo pipefail

echo "Installing optional dependencies for wmt."
echo

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  echo "No virtualenv detected (VIRTUAL_ENV is empty)."
  echo
  echo "Run:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e ."
  echo
  echo "Then rerun:"
  echo "  scripts/install_deps.sh"
  exit 1
fi

python3 -m pip install --upgrade pip
python3 -m pip install yt-dlp

echo
echo "Next:"
echo "yt-dlp installed (optional YouTube fallback + richer metadata)."
