#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="$ROOT_DIR/scripts/com.wmt.plist.template"

CONFIG_DIR="$HOME/.config/wmt"
CONFIG_PATH="$CONFIG_DIR/config.yaml"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.wmt.plist"

STDOUT_LOG="$HOME/Library/Logs/wmt.launchd.log"
STDERR_LOG="$HOME/Library/Logs/wmt.launchd.err.log"

mkdir -p "$CONFIG_DIR" "$LAUNCH_AGENTS_DIR" "$HOME/Library/Logs"

WMT_BIN=""
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/wmt" ]]; then
  WMT_BIN="$VIRTUAL_ENV/bin/wmt"
elif [[ -x "$ROOT_DIR/.venv/bin/wmt" ]]; then
  WMT_BIN="$ROOT_DIR/.venv/bin/wmt"
elif command -v wmt >/dev/null 2>&1; then
  WMT_BIN="$(command -v wmt)"
fi

if [[ -z "$WMT_BIN" ]]; then
  echo "Could not find the 'wmt' executable."
  echo
  echo "Install it first, for example:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e ."
  echo
  echo "Then rerun:"
  echo "  scripts/install_launchd.sh"
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  cp "$ROOT_DIR/config.yaml" "$CONFIG_PATH"
  echo "Copied default config to: $CONFIG_PATH"
else
  echo "Config exists: $CONFIG_PATH"
fi

sed \
  -e "s|__CONFIG_PATH__|$CONFIG_PATH|g" \
  -e "s|__WORKDIR__|$ROOT_DIR|g" \
  -e "s|__WMT_BIN__|$WMT_BIN|g" \
  -e "s|__STDOUT_LOG__|$STDOUT_LOG|g" \
  -e "s|__STDERR_LOG__|$STDERR_LOG|g" \
  "$TEMPLATE_PATH" > "$PLIST_PATH"

echo "Wrote launchd plist: $PLIST_PATH"

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM" "$PLIST_PATH" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST_PATH"
launchctl enable "gui/$UID_NUM/com.wmt" || true

echo "Installed and started com.wmt"
echo "Logs: $STDOUT_LOG (stdout), $STDERR_LOG (stderr), plus worth_my_time.log from config"
