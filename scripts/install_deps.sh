#!/usr/bin/env bash
set -euo pipefail

echo "Installing optional system dependencies for wmt."
echo

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew not found. Install Homebrew first, then rerun this script."
  exit 1
fi

brew install yt-dlp

echo
echo "Next:"
echo "1) Install the Python package in editable mode:"
echo "   python3 -m venv .venv && source .venv/bin/activate && pip install -e ."
