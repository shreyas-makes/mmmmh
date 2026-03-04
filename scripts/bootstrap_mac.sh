#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[error] Missing required command: $cmd"
    return 1
  fi
}

echo "[info] Verifying required tools..."
require_cmd python3
require_cmd node
require_cmd npm

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "[info] Installing ffmpeg via Homebrew..."
    brew install ffmpeg
  else
    echo "[error] ffmpeg/ffprobe not found and Homebrew is not installed."
    echo "[error] Install Homebrew, then run: brew install ffmpeg"
    exit 1
  fi
fi

if [ ! -d ".venv" ]; then
  echo "[info] Creating Python virtual environment (.venv)..."
  python3 -m venv .venv
else
  echo "[info] Reusing existing .venv"
fi

echo "[info] Installing Python dependencies..."
"$ROOT_DIR/.venv/bin/python3" -m pip install --upgrade pip
"$ROOT_DIR/.venv/bin/python3" -m pip install -r requirements.txt

echo "[info] Installing Node dependencies..."
npm install

echo

echo "[done] Setup complete."
echo "[next] Run: npm start"
