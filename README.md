# Snappy Cut (Parakeet TDT)

Mac GUI that removes silences and filler words from videos, then exports a YouTube-ready H.264 + AAC edit.

## Features
- Silence detection with adjustable aggressiveness.
- Filler-word cutting from Parakeet TDT transcripts.
- Handle padding around cuts to avoid clipped syllables.
- Exports `.mp4` (H.264 + AAC) ready for upload.
- Supports `.mp4`, `.mov`, and `.m4v` inputs.

## How it works
1. Extract mono 16 kHz audio with `ffmpeg`.
2. Transcribe with Parakeet TDT (NeMo) for word timing.
3. Detect silence with `ffmpeg` `silencedetect`.
4. Merge filler + silence ranges, add handles, invert to keep ranges.
5. Concatenate keep ranges and export via `ffmpeg`.

## Requirements
- macOS
- Python 3.10+
- `ffmpeg` + `ffprobe` on PATH
- NVIDIA NeMo (Parakeet TDT model download)

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install ffmpeg if needed:
```bash
brew install ffmpeg
```

## Run
```bash
python app.py
```

## Usage
1. Choose the input video.
2. Pick an output `.mp4` path.
3. Adjust aggressiveness and handle size.
4. Edit filler words if needed.
5. Click Process.

## Settings
- Aggressiveness: higher removes more silence (shorter min silence, higher threshold).
- Handle size: adds padding around each cut segment.
- Filler words: comma-separated list matched case-insensitively.

## Project layout
- `app.py`: PySide6 GUI and parameter mapping.
- `pipeline.py`: audio extraction, transcription, detection, and export.
- `requirements.txt`: Python dependencies.

## Troubleshooting
- No word timestamps: update `nemo_toolkit` for Parakeet word timing support.
- Apple Silicon: install a CPU-compatible PyTorch build if CUDA is unavailable.

## Contributing
Issues and pull requests are welcome. Please include repro steps and sample media if possible.
