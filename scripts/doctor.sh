#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FAILURES=0

pass() { echo "[ok] $1"; }
fail() { echo "[fail] $1"; FAILURES=$((FAILURES + 1)); }

check_cmd() {
  local cmd="$1"
  local label="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "$label"
  else
    fail "$label"
  fi
}

check_cmd node "Node.js is installed"
check_cmd npm "npm is installed"
check_cmd python3 "python3 is installed"
check_cmd ffmpeg "ffmpeg is installed"
check_cmd ffprobe "ffprobe is installed"

if [ -x ".venv/bin/python3" ]; then
  pass ".venv exists"
else
  fail ".venv missing (run npm run setup:mac)"
fi

if [ -d "node_modules/electron" ]; then
  pass "Node dependencies are installed"
else
  fail "Node dependencies missing (run npm install)"
fi

if [ -x ".venv/bin/python3" ]; then
  if .venv/bin/python3 - <<'PY' >/dev/null 2>&1
import importlib
for pkg in ["PySide6", "nemo", "torch", "torchaudio"]:
    importlib.import_module(pkg)
PY
  then
    pass "Python dependencies import correctly"
  else
    fail "Python dependencies are incomplete (run .venv/bin/python3 -m pip install -r requirements.txt)"
  fi
fi

if [ "$FAILURES" -gt 0 ]; then
  echo
  echo "Doctor found $FAILURES issue(s)."
  exit 1
fi

echo
echo "Environment looks good."
