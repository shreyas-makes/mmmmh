import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float


def run_pipeline(params, log):
    input_path = Path(params["input_path"]).expanduser()
    output_path = Path(params["output_path"]).expanduser()

    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    log("Extracting audio...")
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav_path),
            ],
            log,
        )

        log("Transcribing with Parakeet TDT...")
        words, has_timestamps = transcribe_with_parakeet(str(wav_path), log)

    log("Detecting silences...")
    silence_segments = detect_silences(
        str(input_path), params["silence_db"], params["min_silence"], log
    )

    duration = get_duration(str(input_path), log)
    if not has_timestamps:
        words = assign_word_timestamps(words, silence_segments, duration, log)

    log("Detecting filler words...")
    filler_segments = detect_fillers(words, params["filler_words"], log)

    log("Merging cut ranges...")
    cut_segments = build_cut_segments(
        filler_segments,
        silence_segments,
        handle_ms=params["handle_ms"],
        breath_ms=params.get("breath_ms", 0),
        duration=duration,
    )

    keep_segments = invert_segments(cut_segments, duration)
    if not keep_segments:
        raise RuntimeError("No keepable segments detected. Try lower aggressiveness.")

    log("Exporting with ffmpeg...")
    export_video(
        str(input_path),
        str(output_path),
        keep_segments,
        log,
        audio_fade_ms=params.get("audio_fade_ms", 40),
    )

    if params.get("save_transcript") and params.get("transcript_path"):
        log("Writing transcript...")
        write_transcript(words, keep_segments, params["transcript_path"], log)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "duration": duration,
        "cut_segments": len(cut_segments),
        "keep_segments": len(keep_segments),
    }


def run_cmd(cmd, log):
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.stdout:
        log(process.stdout.strip())
    if process.stderr:
        log(process.stderr.strip())
    if process.returncode != 0:
        raise RuntimeError(f"Command failed: {shlex.join(cmd)}")


def get_duration(path, log):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        log(process.stderr.strip())
        raise RuntimeError("Failed to read duration via ffprobe")
    return float(process.stdout.strip())


def transcribe_with_parakeet(audio_path, log):
    # Limit native thread stacks in BLAS/NumPy to avoid recursion crashes on macOS.
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    try:
        from nemo.collections.asr.models import EncDecRNNTBPEModel
    except Exception as exc:
        raise RuntimeError(
            "Failed to import NeMo ASR. Install nemo_toolkit to use Parakeet TDT."
        ) from exc

    model = EncDecRNNTBPEModel.from_pretrained(model_name="nvidia/parakeet-tdt-0.6b-v3")
    model.eval()
    try:
        model.change_decoding_strategy({"timestamps": True})
    except Exception:
        pass

    hypotheses = model.transcribe(
        [audio_path],
        return_hypotheses=True,
        timestamps=True,
        batch_size=1,
    )

    if not hypotheses:
        raise RuntimeError("Parakeet transcription returned no hypotheses.")

    hyp = hypotheses[0]
    words = []

    if hasattr(hyp, "words"):
        for item in hyp.words:
            parsed = parse_timestamp_item(item)
            if parsed:
                words.append(parsed)
    else:
        word_items = extract_timestamp_items(hyp, ["word", "words"])
        if word_items:
            words.extend(parse_timestamp_items(word_items))
        elif isinstance(hyp, dict) and "words" in hyp:
            words.extend(parse_timestamp_items(hyp["words"]))

    words = [w for w in words if w.get("word") and w.get("start") is not None]

    if not words:
        char_items = extract_timestamp_items(hyp, ["char", "chars"])
        if char_items:
            words = words_from_chars(char_items)

    if not words:
        segments = extract_timestamp_items(hyp, ["segment", "segments"])
        if segments:
            words = words_from_segments(segments, log)

    if words:
        return words, True

    plain_words = extract_plain_words(hyp)
    if plain_words:
        words = [{"word": w} for w in plain_words]
        log("No word timestamps found. Will approximate using silence detection.")
        return words, False

    describe_timestamp_debug(hyp, log)
    raise RuntimeError(
        "No word timestamps found in Parakeet output. Check NeMo version or model support."
    )


def extract_timestamp_items(hyp, keys):
    for attr_name in ("timestamps", "timestep"):
        value = getattr(hyp, attr_name, None)
        items = extract_from_container(value, keys)
        if items:
            return items
    if isinstance(hyp, dict):
        items = extract_from_container(hyp, keys)
        if items:
            return items
    return None


def extract_from_container(container, keys):
    if container is None:
        return None
    if isinstance(container, dict):
        for key in keys:
            items = container.get(key)
            if items:
                return items
    if hasattr(container, "get"):
        for key in keys:
            items = container.get(key)
            if items:
                return items
    if isinstance(container, list):
        if container and isinstance(container[0], (dict, list, tuple)):
            return container
    return None


def parse_timestamp_items(items):
    parsed = []
    for item in items:
        parsed_item = parse_timestamp_item(item)
        if parsed_item:
            parsed.append(parsed_item)
    return parsed


def parse_timestamp_item(item):
    if item is None or isinstance(item, str):
        return None
    if isinstance(item, dict):
        word = item.get("word") or item.get("text")
        start = item.get("start")
        end = item.get("end") or start
        if word and start is not None:
            return {"word": word, "start": start, "end": end}
        return None
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        word, start, end = item[0], item[1], item[2]
        if isinstance(word, str) and start is not None:
            return {"word": word, "start": start, "end": end}
    if hasattr(item, "word") and hasattr(item, "start"):
        return {"word": item.word, "start": item.start, "end": getattr(item, "end", None)}
    return None


def describe_timestamp_debug(hyp, log):
    for attr_name in ("timestamps", "timestep"):
        value = getattr(hyp, attr_name, None)
        if value is None:
            continue
        if isinstance(value, dict):
            keys = ", ".join(value.keys())
            log(f"Parakeet {attr_name} keys: {keys}")
        else:
            log(f"Parakeet {attr_name} type: {type(value)}")


def extract_plain_words(hyp):
    if hasattr(hyp, "words") and isinstance(hyp.words, list):
        if hyp.words and isinstance(hyp.words[0], str):
            return [w for w in hyp.words if isinstance(w, str)]
    if isinstance(hyp, dict) and "text" in hyp:
        text = hyp.get("text") or ""
        return [w for w in re.split(r"\\s+", text.strip()) if w]
    if hasattr(hyp, "text") and isinstance(hyp.text, str):
        return [w for w in re.split(r"\\s+", hyp.text.strip()) if w]
    return []


def assign_word_timestamps(words, silence_segments, duration, log):
    if not words:
        return words

    silences = merge_segments(silence_segments, handle_ms=0, duration=duration)
    speech_segments = invert_segments(silences, duration)
    if not speech_segments:
        speech_segments = [Segment(start=0.0, end=duration)]

    total_words = len(words)
    total_speech = sum(max(0.0, seg.end - seg.start) for seg in speech_segments)
    if total_speech <= 0:
        total_speech = duration or 1.0

    remaining = total_words
    allocations = []
    for idx, seg in enumerate(speech_segments):
        if idx == len(speech_segments) - 1:
            count = remaining
        else:
            ratio = max(0.0, seg.end - seg.start) / total_speech
            count = int(round(ratio * total_words))
            count = max(1, count) if remaining > 0 else 0
            count = min(count, remaining)
        allocations.append(count)
        remaining -= count

    # Fix rounding drift.
    for idx, count in enumerate(allocations):
        if remaining == 0:
            break
        if count > 0:
            allocations[idx] += 1
            remaining -= 1

    assigned = []
    word_index = 0
    for seg, count in zip(speech_segments, allocations):
        if count <= 0:
            continue
        seg_len = max(0.01, seg.end - seg.start)
        per_word = seg_len / count
        for i in range(count):
            if word_index >= total_words:
                break
            start = seg.start + i * per_word
            end = seg.start + (i + 1) * per_word
            assigned.append(
                {"word": words[word_index]["word"], "start": start, "end": end}
            )
            word_index += 1

    if word_index < total_words:
        # Fallback if we ran out of segments.
        fallback_start = speech_segments[-1].start
        fallback_end = speech_segments[-1].end
        seg_len = max(0.01, fallback_end - fallback_start)
        per_word = seg_len / max(total_words - word_index, 1)
        for i in range(word_index, total_words):
            idx = i - word_index
            start = fallback_start + idx * per_word
            end = fallback_start + (idx + 1) * per_word
            assigned.append({"word": words[i]["word"], "start": start, "end": end})

    log("Word timestamps approximated from speech segments.")
    return assigned


def words_from_chars(char_items):
    words = []
    current = []
    start = None
    end = None
    for item in char_items:
        if isinstance(item, str):
            continue
        char = item.get("char") or item.get("text") or ""
        if not char.strip():
            if current:
                words.append({"word": "".join(current), "start": start, "end": end})
                current = []
                start = None
                end = None
            continue
        if start is None:
            start = item.get("start")
        end = item.get("end") or item.get("start")
        current.append(char)

    if current:
        words.append({"word": "".join(current), "start": start, "end": end})
    return words


def words_from_segments(segments, log):
    words = []
    for segment in segments:
        if isinstance(segment, str):
            continue
        text = segment.get("text") or segment.get("word") or ""
        start = segment.get("start")
        end = segment.get("end")
        if start is None or end is None:
            continue
        tokens = [t for t in re.split(r"\s+", text.strip()) if t]
        if not tokens:
            continue
        segment_len = max(0.0, float(end) - float(start))
        per_word = segment_len / max(len(tokens), 1)
        for idx, token in enumerate(tokens):
            word_start = float(start) + idx * per_word
            word_end = float(start) + (idx + 1) * per_word
            words.append({"word": token, "start": word_start, "end": word_end})

    if words:
        log("Word timestamps approximated from segment timings.")
    return words


def detect_fillers(words, filler_words, log):
    fillers = {normalize_word(w) for w in filler_words}
    segments = []
    for item in words:
        normalized = normalize_word(item["word"])
        if normalized in fillers:
            start = float(item["start"])
            end = float(item.get("end") or start + 0.12)
            segments.append(Segment(start=start, end=end))
    log(f"Detected {len(segments)} filler segments.")
    return segments


def normalize_word(word):
    return re.sub(r"[^a-z0-9]+", "", word.lower())


def detect_silences(path, silence_db, min_silence, log):
    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-af",
        f"silencedetect=n={silence_db}dB:d={min_silence}",
        "-f",
        "null",
        "-",
    ]
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        log(process.stderr.strip())
        raise RuntimeError("ffmpeg silencedetect failed")

    silence_starts = []
    segments = []
    for line in process.stderr.splitlines():
        line = line.strip()
        if "silence_start" in line:
            value = float(line.split("silence_start:")[-1].strip())
            silence_starts.append(value)
        elif "silence_end" in line:
            end_part = line.split("silence_end:")[-1]
            end_value = float(end_part.split("|")[0].strip())
            start_value = silence_starts.pop(0) if silence_starts else None
            if start_value is not None:
                segments.append(Segment(start=start_value, end=end_value))

    log(f"Detected {len(segments)} silence segments.")
    return segments


def merge_segments(segments, handle_ms, duration):
    handle = handle_ms / 1000.0
    adjusted = []
    for segment in segments:
        start = max(0.0, segment.start - handle)
        end = min(duration, segment.end + handle)
        if end > start:
            adjusted.append(Segment(start=start, end=end))

    if not adjusted:
        return []

    adjusted.sort(key=lambda s: s.start)
    merged = [adjusted[0]]
    for segment in adjusted[1:]:
        last = merged[-1]
        if segment.start <= last.end:
            merged[-1] = Segment(start=last.start, end=max(last.end, segment.end))
        else:
            merged.append(segment)
    return merged


def build_cut_segments(filler_segments, silence_segments, handle_ms, breath_ms, duration):
    filler_cuts = merge_segments(filler_segments, handle_ms=handle_ms, duration=duration)
    silence_cuts = []
    merged_silences = merge_segments(silence_segments, handle_ms=handle_ms, duration=duration)
    breath = max(0.0, breath_ms / 1000.0)

    for segment in merged_silences:
        if breath <= 0.0:
            silence_cuts.append(segment)
            continue
        seg_len = segment.end - segment.start
        if seg_len <= breath:
            continue
        keep_start = segment.start + (seg_len - breath) / 2.0
        keep_end = keep_start + breath
        left = Segment(start=segment.start, end=keep_start)
        right = Segment(start=keep_end, end=segment.end)
        if left.end > left.start:
            silence_cuts.append(left)
        if right.end > right.start:
            silence_cuts.append(right)

    return merge_segments(filler_cuts + silence_cuts, handle_ms=0, duration=duration)


def invert_segments(cut_segments, duration):
    if not cut_segments:
        return [Segment(start=0.0, end=duration)]

    keep = []
    cursor = 0.0
    for segment in cut_segments:
        if segment.start > cursor:
            keep.append(Segment(start=cursor, end=segment.start))
        cursor = max(cursor, segment.end)

    if cursor < duration:
        keep.append(Segment(start=cursor, end=duration))
    return keep


def export_video(input_path, output_path, keep_segments, log, audio_fade_ms=40):
    video_filters = []
    audio_filters = []
    concat_inputs = []
    fade_sec = max(0.0, audio_fade_ms / 1000.0)

    for idx, segment in enumerate(keep_segments):
        seg_duration = max(0.0, segment.end - segment.start)
        video_filters.append(
            f"[0:v]trim=start={segment.start}:end={segment.end},setpts=PTS-STARTPTS[v{idx}]"
        )
        audio_chain = (
            f"[0:a]atrim=start={segment.start}:end={segment.end},asetpts=PTS-STARTPTS"
        )
        if fade_sec > 0.0 and seg_duration > 0.0:
            effective_fade = min(fade_sec, seg_duration / 2.0)
            if effective_fade > 0.0:
                fade_out_start = max(0.0, seg_duration - effective_fade)
                audio_chain += (
                    f",afade=t=in:st=0:d={effective_fade:.3f}"
                    f",afade=t=out:st={fade_out_start:.3f}:d={effective_fade:.3f}"
                )
        audio_chain += f"[a{idx}]"
        audio_filters.append(audio_chain)
        concat_inputs.append(f"[v{idx}][a{idx}]")

    filter_complex = ";".join(video_filters + audio_filters)
    filter_complex += ";" + "".join(concat_inputs)
    filter_complex += f"concat=n={len(keep_segments)}:v=1:a=1[outv][outa]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        output_path,
    ]

    run_cmd(cmd, log)


def write_transcript(words, keep_segments, transcript_path, log):
    tokens = []
    segment_index = 0
    for item in words:
        word = str(item.get("word", "")).strip()
        if not word:
            continue
        start = item.get("start")
        if start is not None:
            while segment_index < len(keep_segments) and start >= keep_segments[segment_index].end:
                segment_index += 1
            if segment_index >= len(keep_segments):
                break
            if start < keep_segments[segment_index].start:
                continue
        if tokens and word in {".", ",", "!", "?", ":", ";"}:
            tokens[-1] += word
        else:
            tokens.append(word)
    text = " ".join(tokens).strip()
    path = Path(transcript_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    log(f"Transcript saved to {path}")
