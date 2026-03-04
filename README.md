# mmmmhh (Electron + Python)

Desktop video editor that trims long silences and exports a YouTube-ready MP4 with captions.

## Features
- Silence-only cutting with pause-size control.
- Handle padding around cuts to avoid clipped syllables.
- Optional transcript export to `.txt`.
- Captions generated from Parakeet timestamps.
- Editable caption rows before export.
- Sidecar `.srt` and burned-in captions in output MP4 (fallback to subtitle track when needed).
- Supports `.mp4`, `.mov`, and `.m4v` inputs.

## Tech stack
- Electron UI (`main.js`, `renderer/`)
- Python processing pipeline (`pipeline.py`, `electron_bridge.py`)
- `ffmpeg` / `ffprobe` for media processing
- NVIDIA NeMo Parakeet model for transcription/timing

## Prerequisites (macOS)
- macOS
- Homebrew
- Node.js 20+
- Python 3.10+
- `ffmpeg` and `ffprobe` on PATH

Install Homebrew dependencies if needed:

```bash
brew install ffmpeg
```

## Getting Started

### Option A: Download from GitHub Releases (easiest)
1. Go to GitHub Releases and download the latest macOS artifact (`.dmg` or `.zip`).
2. Launch the app.
3. If your machine is missing Python deps, run setup once in this repo:

```bash
npm run setup:mac
```

Notes:
- Current release builds package the Electron shell, but still rely on local Python + `ffmpeg`.
- First transcription can take longer because NeMo model assets may download on first use.

### Option B: Run from source (developer flow)

```bash
git clone <repo-url>
cd mmmmhh
npm run setup:mac
npm start
```

## One-command setup

`npm run setup:mac` runs `scripts/bootstrap_mac.sh`, which:
- Installs `ffmpeg` via Homebrew if missing.
- Creates `.venv` if needed.
- Installs Python dependencies from `requirements.txt`.
- Installs Node dependencies with `npm install`.

## Run commands
- `npm start`: launch Electron app.
- `npm run doctor`: verify local runtime dependencies and imports.
- `npm run dist`: build unsigned macOS artifacts into `dist/`.

## Environment overrides
Electron resolves Python in this order:
1. `PYTHON_BIN` env var (if set)
2. `.venv/bin/python3` in repo root
3. `python3` on PATH

Example:

```bash
PYTHON_BIN=/opt/homebrew/bin/python3 npm start
```

## How it works
1. Extract mono 16 kHz audio via `ffmpeg`.
2. Transcribe audio with Parakeet (NeMo) for word timing.
3. Detect silence using `ffmpeg silencedetect`.
4. Trim only excess silence above your keep-pause threshold.
5. Export stitched MP4 with captions/transcript options.

## Usage
1. Choose input video.
2. Choose output `.mp4` path.
3. Optional: adjust transcript `.txt` path.
4. Tune pacing controls.
5. Optional: generate/edit caption rows.
6. Click **Process**.

## Settings
- Pacing preset:
  - `Natural`: keeps more breathing room.
  - `Balanced` (default): short-form social pacing without sounding choppy.
  - `Aggressive`: tighter cuts for faster cadence.
- Keep pauses up to: amount of silence retained per detected pause; anything longer is trimmed.
- Handle size: adds padding around each cut segment.
- Audio fade: short fade-in/out at each stitch to smooth abrupt audio changes.
- Micro-gap merge: gaps under 120 ms between nearby cuts are removed to avoid jittery pacing.
- Save transcript: writes a `.txt` transcript next to output by default.
- Burn captions + write SRT: enabled by default.
- Caption editor: lets you adjust caption text per timestamped segment.

## Preset values
- Natural:
  - Silence threshold: `-40 dB`
  - Minimum silence to edit: `350 ms`
  - Keep pauses up to: `260 ms`
  - Handle size: `140 ms`
  - Audio fade: `70 ms`
  - Micro-gap merge: `80 ms`
- Balanced (default):
  - Silence threshold: `-38 dB`
  - Minimum silence to edit: `280 ms`
  - Keep pauses up to: `200 ms`
  - Handle size: `120 ms`
  - Audio fade: `60 ms`
  - Micro-gap merge: `120 ms`
- Aggressive:
  - Silence threshold: `-35 dB`
  - Minimum silence to edit: `200 ms`
  - Keep pauses up to: `140 ms`
  - Handle size: `100 ms`
  - Audio fade: `50 ms`
  - Micro-gap merge: `150 ms`

## Release pipeline (GitHub Actions)
This repo includes `.github/workflows/release-electron.yml`.

- Trigger: push a tag matching `v*` (for example `v0.2.0`).
- Runner: `macos-latest`.
- Build: `npm run dist` (Electron macOS `dmg` + `zip`).
- Publish: artifacts uploaded to the matching GitHub Release.

## Troubleshooting
- `ffmpeg` not found: run `brew install ffmpeg`.
- Python import errors: run `npm run setup:mac`.
- Verify environment: run `npm run doctor`.
- Slow first run: initial NeMo model load/download can take time.
- macOS app blocked on first open: right-click app -> `Open` once to bypass Gatekeeper for unsigned builds.

## Project layout
- `main.js`: Electron main process and Python bridge process management.
- `preload.js`: secure IPC bridge for renderer.
- `renderer/`: frontend UI.
- `electron_bridge.py`: JSON IPC adapter between Electron and Python pipeline.
- `pipeline.py`: transcription, silence detection, and export logic.
- `scripts/bootstrap_mac.sh`: local setup helper.
- `scripts/doctor.sh`: environment diagnostics.

## Contributing
Issues and pull requests are welcome. Include repro steps and sample media when possible.
