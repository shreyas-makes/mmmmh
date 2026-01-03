# Snappy Cut - Postmortem

## Overview
Goal: Build a one-stop macOS GUI that ingests an MP4/MOV, removes silences and lexical fillers using Parakeet TDT + ffmpeg, and exports H.264 + AAC.

Outcome: Working pipeline with robust timestamp handling and a fallback when Parakeet does not emit word timestamps.

## Timeline of Issues and Fixes

1) **Python binary missing (`python` not found)**
- **Symptom**: `zsh: command not found: python`.
- **Fix**: Switched to `python3` and installed Python 3.11 via Homebrew.

2) **Parakeet import failure (Python 3.13 + ml_dtypes error)**
- **Symptom**: `AttributeError: module 'ml_dtypes' has no attribute 'float4_e2m1fn'` when importing NeMo/ONNX.
- **Root cause**: Incompatible package versions with Python 3.13.
- **Fix**: Recreated the virtualenv with Python 3.11 and reinstalled requirements.

3) **Large model download stall**
- **Symptom**: Model download was slow (2.51 GB) and initially interrupted.
- **Fix**: Confirmed download step and allowed it to proceed later.

4) **GUI crash (SIGBUS / recursion stack overflow)**
- **Symptom**: `EXC_BAD_ACCESS (SIGBUS)` with stack overflow in OpenBLAS during torch import in background thread.
- **Root cause**: OpenBLAS spawning threads with deep recursion.
- **Fix**: Added BLAS/OMP thread limits before importing NeMo/torch in `transcribe_with_parakeet`:
  - `OPENBLAS_NUM_THREADS=1`
  - `OMP_NUM_THREADS=1`
  - `VECLIB_MAXIMUM_THREADS=1`
  - `NUMEXPR_NUM_THREADS=1`

5) **Parakeet output type mismatch**
- **Symptom**: `"str" object has no attribute "word"`.
- **Root cause**: `hyp.words` returned a list of strings rather than word objects.
- **Fix**: Guarded against string items and made timestamp parsing more defensive.

6) **Missing word timestamps**
- **Symptom**: `No word timestamps found in Parakeet output. Check NeMo version or model support.`
- **Root cause**: Parakeet returned only raw word strings, without timestamps in `timestamps` or `timestep`.
- **Fixes**:
  - Added multiple fallback parsers (dicts, tuples, objects, `timestep`).
  - Added debug logging for timestamp structures.
  - Final fallback: **approximate word timestamps** using speech segments inferred from silence detection.

## Final Working Behavior
- Parakeet provides transcription and words.
- If timestamps are missing, the pipeline estimates word timing by distributing words across non-silent segments.
- Filler removal and silence removal both work, and the output is encoded as H.264 + AAC.

## ASCII Visual of the Timestamp Problem
```
Wanted (ideal):
Audio timeline
|---word1---|--word2--|...|--wordN--|
    ^start/end timestamps for every word

But Parakeet gave:
words = ["I'm", "taking", "a", "video", ...]
timestamps = None
timestep   = None

So we had:
Audio timeline
|--speech--|  (silence)  |----speech----|
(no word timestamps)

Fallback fix:
1) Detect silence -> infer speech segments
2) Spread words across speech time

Result:
|w1|w2|w3|  (silence)  |w4|w5|w6|...
(approx timestamps from speech segments)
```

## Files Changed
- `app.py`: UI adjustments (MOV support).
- `pipeline.py`: Robust Parakeet parsing, BLAS thread limits, timestamp fallbacks.
- `README.md`: usage notes.
- `requirements.txt`: dependencies.

## Remaining Risks / Notes
- Word timestamps are approximated when Parakeet does not provide them; accuracy depends on silence detection quality.
- The model download is large and can take time on first run.
