# Snappy Cut (Parakeet TDT)

Mac GUI that removes silences and filler words from videos, then exports a YouTube-ready H.264 + AAC edit.

## Features
- Silence detection with adjustable aggressiveness.
- Filler-word cutting from Parakeet TDT transcripts.
- Handle padding around cuts to avoid clipped syllables.
- Optional transcript export to `.txt`.
- Captions generated with Parakeet and aligned to the edited timeline.
- Editable caption segment UI before export.
- Caption output as sidecar `.srt` and embedded MP4 subtitle track.
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
3. (Optional) Keep or change the transcript `.txt` path.
4. Adjust aggressiveness and handle size.
5. Edit filler words if needed.
6. (Optional) Generate/refresh captions, then edit caption text rows.
7. Click Process.

## Settings
- Aggressiveness: higher removes more silence (shorter minimum pause length, less negative threshold).
- Handle size: adds padding around each cut segment.
- Pause floor: keeps a minimum amount of conversational pause so cuts do not sound choppy.
- Audio fade: short fade-in/out at each stitch to smooth abrupt audio changes.
- Save transcript: writes a `.txt` transcript next to the output by default.
- Filler words: comma-separated list matched case-insensitively.
- Enable captions: on by default; writes `.srt` and embeds subtitles into MP4.
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
