# Snappy Cut (Parakeet TDT)

Mac GUI that trims long silences from videos and exports a YouTube-ready H.264 + AAC edit with baked-in captions.

## Features
- Silence-only cutting with a simple pause-size slider.
- Handle padding around cuts to avoid clipped syllables.
- Optional transcript export to `.txt`.
- Captions generated with Parakeet and aligned to the edited timeline.
- Editable caption segment UI before export.
- Caption output as sidecar `.srt` and burned into the output MP4 (fallback to embedded subtitle track if needed).
- Exports `.mp4` (H.264 + AAC) ready for upload.
- Supports `.mp4`, `.mov`, and `.m4v` inputs.

## How it works
1. Extract mono 16 kHz audio with `ffmpeg`.
2. Transcribe with Parakeet TDT (NeMo) for word timing.
3. Detect silence with `ffmpeg` `silencedetect`.
4. Cut only the excess part of silences above your selected pause size.
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
3. (Optional) Keep or change the transcript `.txt` path.
4. Set how much pause you want to keep.
5. Adjust handle size if needed.
6. (Optional) Generate/refresh captions, then edit caption text rows.
7. Click Process.

## Settings
- Keep pauses up to: the amount of silence retained per detected pause; anything longer is trimmed.
- Handle size: adds padding around each cut segment.
- Audio fade: short fade-in/out at each stitch to smooth abrupt audio changes.
- Save transcript: writes a `.txt` transcript next to the output by default.
- Enable captions: on by default; writes `.srt` and burns subtitles into MP4.
- Caption editor: lets you change caption text per timestamped segment.

## Project layout
- `app.py`: PySide6 GUI and parameter mapping.
- `pipeline.py`: audio extraction, transcription, detection, and export.
- `requirements.txt`: Python dependencies.

## Troubleshooting
- No word timestamps: update `nemo_toolkit` for Parakeet word timing support.
- Apple Silicon: install a CPU-compatible PyTorch build if CUDA is unavailable.

## Contributing
Issues and pull requests are welcome. Please include repro steps and sample media if possible.
