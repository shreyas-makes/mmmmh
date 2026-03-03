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


@dataclass
class CaptionSegment:
    start: float
    end: float
    text: str


def run_pipeline(params, log):
    input_path = Path(params["input_path"]).expanduser()
    output_path = ensure_path_suffix(Path(params["output_path"]).expanduser(), ".mp4").resolve()
    if not str(params["output_path"]).lower().endswith(".mp4"):
        log(f"Output path missing .mp4 extension. Using: {output_path}")
    captions_enabled = params.get("captions_enabled", True)
    caption_srt_path = str(
        Path(params.get("caption_srt_path") or output_path.with_suffix(".srt")).expanduser().resolve()
    )
    caption_segments_override = normalize_caption_override(
        params.get("caption_segments_override")
    )

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
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
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

    pause_floor_ms = resolve_pause_floor_ms(params.get("pause_floor_ms"))
    log(f"Keeping up to {pause_floor_ms} ms per silence.")

    log("Merging cut ranges...")
    cut_segments = build_cut_segments(
        silence_segments,
        handle_ms=params["handle_ms"],
        pause_floor_ms=pause_floor_ms,
        duration=duration,
    )

    keep_segments = invert_segments(cut_segments, duration)
    if not keep_segments:
        raise RuntimeError("No keepable segments detected. Try lower aggressiveness.")

    caption_segments = []
    if captions_enabled:
        if caption_segments_override:
            caption_segments = caption_segments_override
            log(f"Using {len(caption_segments)} user-edited caption segments.")
        else:
            words_on_output = remap_words_to_output_timeline(words, keep_segments)
            caption_segments = build_caption_segments(words_on_output)
            if not caption_segments:
                raise RuntimeError("No caption segments generated from edited output.")
        write_srt(caption_segments, caption_srt_path, log)

    log("Exporting with ffmpeg...")
    if captions_enabled:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_video_path = str(Path(tmpdir) / "video_no_captions.mp4")
            export_video(
                str(input_path),
                temp_video_path,
                keep_segments,
                log,
                audio_fade_ms=params.get("audio_fade_ms", 40),
            )
            burn_subtitles_into_mp4(temp_video_path, caption_srt_path, str(output_path), log)
    else:
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
        "captions_enabled": captions_enabled,
        "captions_segments_count": len(caption_segments),
        "captions_srt_path": str(Path(caption_srt_path).expanduser()) if captions_enabled else "",
        "captions_embedded": captions_enabled,
    }


def ensure_path_suffix(path, suffix):
    if path.suffix.lower() == suffix.lower():
        return path
    return path.with_suffix(suffix)


def preview_captions(params, log):
    input_path = Path(params["input_path"]).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    log("Extracting audio for caption preview...")
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-map",
                "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav_path),
            ],
            log,
        )
        log("Transcribing with Parakeet TDT for caption preview...")
        words, has_timestamps = transcribe_with_parakeet(str(wav_path), log)

    log("Detecting silences for caption preview...")
    silence_segments = detect_silences(
        str(input_path), params["silence_db"], params["min_silence"], log
    )
    duration = get_duration(str(input_path), log)
    if not has_timestamps:
        words = assign_word_timestamps(words, silence_segments, duration, log)

    pause_floor_ms = resolve_pause_floor_ms(params.get("pause_floor_ms"))
    log(f"Pause keep setting for preview: {pause_floor_ms} ms")
    cut_segments = build_cut_segments(
        silence_segments,
        handle_ms=params["handle_ms"],
        pause_floor_ms=pause_floor_ms,
        duration=duration,
    )
    keep_segments = invert_segments(cut_segments, duration)
    words_on_output = remap_words_to_output_timeline(words, keep_segments)
    caption_segments = build_caption_segments(words_on_output)
    if not caption_segments:
        raise RuntimeError("No caption segments were generated in preview.")

    return {
        "segments": [caption_segment_to_dict(seg) for seg in caption_segments],
        "segments_count": len(caption_segments),
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
    timestamp_scale = infer_timestamp_scale(hyp)
    words = []

    if hasattr(hyp, "words"):
        words.extend(parse_timestamp_items(hyp.words, timestamp_scale=timestamp_scale))

    word_items = extract_timestamp_items(hyp, ["word", "words"])
    if word_items:
        words.extend(parse_timestamp_items(word_items, timestamp_scale=timestamp_scale))
    elif isinstance(hyp, dict) and "words" in hyp:
        words.extend(parse_timestamp_items(hyp["words"], timestamp_scale=timestamp_scale))

    words = [w for w in words if w.get("word") and w.get("start") is not None]
    words = dedupe_word_timestamps(words)

    if not words:
        char_items = extract_timestamp_items(hyp, ["char", "chars"])
        if char_items:
            words = words_from_chars(char_items, timestamp_scale=timestamp_scale)

    if not words:
        segments = extract_timestamp_items(hyp, ["segment", "segments"])
        if segments:
            words = words_from_segments(segments, log, timestamp_scale=timestamp_scale)

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
    for attr_name in ("timestamps", "timestamp", "timestep"):
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


def parse_timestamp_items(items, timestamp_scale=1.0):
    parsed = []
    if not isinstance(items, (list, tuple)):
        return parsed
    for item in items:
        parsed_item = parse_timestamp_item(item, timestamp_scale=timestamp_scale)
        if parsed_item:
            parsed.append(parsed_item)
    return parsed


def parse_timestamp_item(item, timestamp_scale=1.0):
    if item is None or isinstance(item, str):
        return None
    if isinstance(item, dict):
        word = item.get("word") or item.get("text") or item.get("token")
        start, start_key = first_present(
            item, ["start", "start_time", "startTime", "start_offset", "offset"]
        )
        end, end_key = first_present(item, ["end", "end_time", "endTime", "end_offset"])
        if word and start is not None:
            start_value = normalize_timestamp_value(start, start_key, timestamp_scale)
            end_value = normalize_timestamp_value(
                end if end is not None else start,
                end_key if end_key is not None else start_key,
                timestamp_scale,
            )
            if start_value is None:
                return None
            if end_value is None or end_value < start_value:
                end_value = start_value
            return {"word": str(word), "start": start_value, "end": end_value}
        return None
    if isinstance(item, (list, tuple)) and len(item) >= 3:
        word, start, end = item[0], item[1], item[2]
        if isinstance(word, str) and start is not None:
            start_value = normalize_timestamp_value(start, "start", timestamp_scale)
            end_value = normalize_timestamp_value(
                end if end is not None else start, "end", timestamp_scale
            )
            if start_value is None:
                return None
            if end_value is None or end_value < start_value:
                end_value = start_value
            return {"word": word, "start": start_value, "end": end_value}
    if hasattr(item, "word"):
        start, start_key = first_attr_present(
            item, ["start", "start_time", "startTime", "start_offset", "offset"]
        )
        end, end_key = first_attr_present(item, ["end", "end_time", "endTime", "end_offset"])
        if start is not None:
            start_value = normalize_timestamp_value(start, start_key, timestamp_scale)
            end_value = normalize_timestamp_value(
                end if end is not None else start,
                end_key if end_key is not None else start_key,
                timestamp_scale,
            )
            if start_value is None:
                return None
            if end_value is None or end_value < start_value:
                end_value = start_value
            return {"word": str(item.word), "start": start_value, "end": end_value}
    return None


def infer_timestamp_scale(hyp):
    candidates = []
    for container in (
        hyp,
        getattr(hyp, "timestamps", None),
        getattr(hyp, "timestamp", None),
        getattr(hyp, "timestep", None),
    ):
        if container is None:
            continue
        for key in ("timestep_duration", "time_stride", "frame_duration", "window_stride"):
            value = None
            if isinstance(container, dict):
                value = container.get(key)
            elif hasattr(container, "get"):
                value = container.get(key)
            else:
                value = getattr(container, key, None)
            if value is not None:
                numeric = safe_float(value)
                if numeric and numeric > 0:
                    candidates.append(numeric)
    return candidates[0] if candidates else 1.0


def safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_present(mapping, keys):
    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key), key
    return None, None


def first_attr_present(obj, keys):
    for key in keys:
        value = getattr(obj, key, None)
        if value is not None:
            return value, key
    return None, None


def normalize_timestamp_value(value, source_key, timestamp_scale):
    numeric = safe_float(value)
    if numeric is None:
        return None
    key = source_key or ""
    if "offset" in key and timestamp_scale > 0:
        return numeric * timestamp_scale
    return numeric


def dedupe_word_timestamps(words):
    deduped = []
    seen = set()
    for item in words:
        key = (
            str(item.get("word", "")).strip().lower(),
            round(float(item.get("start", 0.0)), 4),
            round(float(item.get("end", 0.0)), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def describe_timestamp_debug(hyp, log):
    for attr_name in ("timestamps", "timestamp", "timestep"):
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


def remap_words_to_output_timeline(words, keep_segments):
    remapped = []
    for item in words:
        raw_word = str(item.get("word", "")).strip()
        start = item.get("start")
        if not raw_word or start is None:
            continue

        end = item.get("end")
        start_out = map_time_to_output_timeline(float(start), keep_segments)
        if start_out is None:
            continue

        end_in = float(end) if end is not None else float(start) + 0.12
        end_out = map_time_to_output_timeline(end_in, keep_segments)
        if end_out is None or end_out <= start_out:
            end_out = start_out + 0.12

        remapped.append({"word": raw_word, "start": start_out, "end": end_out})
    return remapped


def map_time_to_output_timeline(value, keep_segments):
    elapsed = 0.0
    for segment in keep_segments:
        if value < segment.start:
            return None
        if segment.start <= value <= segment.end:
            return elapsed + (value - segment.start)
        elapsed += segment.end - segment.start
    return None


def build_caption_segments(
    words,
    max_chars=42,
    max_duration=3.5,
    punctuation_split_min_chars=18,
    gap_threshold=0.35,
):
    if not words:
        return []

    segments = []
    current = []
    current_start = None
    last_end = None

    for item in words:
        word = str(item["word"]).strip()
        start = float(item["start"])
        end = float(item.get("end") or start + 0.12)
        if not word:
            continue

        if not current:
            current = [item]
            current_start = start
            last_end = end
            continue

        gap = max(0.0, start - (last_end or start))
        candidate = current + [item]
        candidate_text = join_tokens([str(x["word"]).strip() for x in candidate]).strip()
        candidate_duration = max(0.0, end - float(current_start))

        if (
            gap > gap_threshold
            or len(candidate_text) > max_chars
            or candidate_duration > max_duration
        ):
            segments.append(
                CaptionSegment(
                    start=float(current_start),
                    end=float(last_end or current_start),
                    text=join_tokens([str(x["word"]).strip() for x in current]).strip(),
                )
            )
            current = [item]
            current_start = start
            last_end = end
            continue

        current.append(item)
        last_end = end
        current_text = join_tokens([str(x["word"]).strip() for x in current]).strip()
        if (
            ends_with_sentence_punctuation(word)
            and len(current_text) >= punctuation_split_min_chars
        ):
            segments.append(
                CaptionSegment(
                    start=float(current_start),
                    end=float(last_end),
                    text=current_text,
                )
            )
            current = []
            current_start = None
            last_end = None

    if current:
        segments.append(
            CaptionSegment(
                start=float(current_start or 0.0),
                end=float(last_end or (current_start or 0.0) + 0.12),
                text=join_tokens([str(x["word"]).strip() for x in current]).strip(),
            )
        )

    normalized = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        start = max(0.0, float(segment.start))
        end = max(start + 0.05, float(segment.end))
        normalized.append(CaptionSegment(start=start, end=end, text=text))
    return normalized


def ends_with_sentence_punctuation(word):
    return bool(re.search(r"[.!?]$", word))


def normalize_caption_override(segments):
    if not isinstance(segments, list):
        return []

    normalized = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        start = segment.get("start")
        end = segment.get("end")
        if not text or start is None or end is None:
            continue
        start_value = max(0.0, float(start))
        end_value = max(start_value + 0.05, float(end))
        normalized.append(CaptionSegment(start=start_value, end=end_value, text=text))
    return normalized


def caption_segment_to_dict(segment):
    return {"start": segment.start, "end": segment.end, "text": segment.text}


def words_from_chars(char_items, timestamp_scale=1.0):
    words = []
    current = []
    start = None
    end = None
    for item in char_items:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            continue
        char = item.get("char") or item.get("text") or item.get("token") or ""
        if not char.strip():
            if current:
                words.append({"word": "".join(current), "start": start, "end": end})
                current = []
                start = None
                end = None
            continue
        if start is None:
            start_raw, start_key = first_present(
                item, ["start", "start_time", "startTime", "start_offset", "offset"]
            )
            start = normalize_timestamp_value(start_raw, start_key, timestamp_scale)
        end_raw, end_key = first_present(item, ["end", "end_time", "endTime", "end_offset"])
        if end_raw is None:
            end_raw, end_key = first_present(
                item, ["start", "start_time", "startTime", "start_offset", "offset"]
            )
        end = normalize_timestamp_value(end_raw, end_key, timestamp_scale)
        current.append(char)

    if current:
        words.append({"word": "".join(current), "start": start, "end": end})
    return words


def words_from_segments(segments, log, timestamp_scale=1.0):
    words = []
    for segment in segments:
        if isinstance(segment, str):
            continue
        if not isinstance(segment, dict):
            continue
        text = segment.get("text") or segment.get("word") or ""
        start, start_key = first_present(
            segment, ["start", "start_time", "startTime", "start_offset", "offset"]
        )
        end, end_key = first_present(segment, ["end", "end_time", "endTime", "end_offset"])
        start = normalize_timestamp_value(start, start_key, timestamp_scale)
        end = normalize_timestamp_value(end, end_key, timestamp_scale)
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


def detect_silences(path, silence_db, min_silence, log):
    cmd = [
        "ffmpeg",
        "-i",
        path,
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
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


def build_cut_segments(silence_segments, handle_ms, pause_floor_ms, duration):
    silence_cuts = []
    merged_silences = merge_segments(silence_segments, handle_ms=handle_ms, duration=duration)
    pause_floor_ms = resolve_pause_floor_ms(pause_floor_ms)
    pause_floor = max(0.0, pause_floor_ms / 1000.0)

    for segment in merged_silences:
        if pause_floor <= 0.0:
            silence_cuts.append(segment)
            continue
        seg_len = segment.end - segment.start
        if seg_len <= pause_floor:
            continue
        keep_start = segment.start + (seg_len - pause_floor) / 2.0
        keep_end = keep_start + pause_floor
        left = Segment(start=segment.start, end=keep_start)
        right = Segment(start=keep_end, end=segment.end)
        if left.end > left.start:
            silence_cuts.append(left)
        if right.end > right.start:
            silence_cuts.append(right)

    return merge_segments(silence_cuts, handle_ms=0, duration=duration)


def resolve_pause_floor_ms(pause_floor_ms):
    if pause_floor_ms is None:
        return 180
    return int(pause_floor_ms)


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


def format_srt_time(seconds):
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    secs = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_srt(segments, srt_path, log):
    path = Path(srt_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for idx, segment in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(
            f"{format_srt_time(segment.start)} --> {format_srt_time(segment.end)}"
        )
        lines.append(segment.text)
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    log(f"Captions saved to {path}")


def mux_subtitles_into_mp4(video_path, srt_path, output_path, log):
    Path(output_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        srt_path,
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=eng",
        "-disposition:s:0",
        "default",
        output_path,
    ]
    run_cmd(cmd, log)


def burn_subtitles_into_mp4(video_path, srt_path, output_path, log):
    Path(output_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    if not ffmpeg_supports_subtitles_filter():
        log("ffmpeg 'subtitles' filter unavailable (missing libass). Falling back to embedded subtitle track.")
        mux_subtitles_into_mp4(video_path, srt_path, output_path, log)
        return
    subtitle_path = escape_subtitles_filter_path(str(Path(srt_path).expanduser()))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-vf",
        f"subtitles={subtitle_path}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "-f",
        "mp4",
        output_path,
    ]
    try:
        run_cmd(cmd, log)
    except RuntimeError as exc:
        log(
            f"Hard-burn captions failed ({exc}). Falling back to embedded subtitle track."
        )
        mux_subtitles_into_mp4(video_path, srt_path, output_path, log)


def ffmpeg_supports_subtitles_filter():
    process = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    )
    output = (process.stdout or "") + "\n" + (process.stderr or "")
    return bool(re.search(r"^\s*T\.\S*\s+subtitles\s", output, re.MULTILINE))


def escape_subtitles_filter_path(path):
    # Escape characters significant to ffmpeg filter argument parsing.
    return (
        path.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


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


def join_tokens(tokens):
    merged = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if merged and token in {".", ",", "!", "?", ":", ";"}:
            merged[-1] += token
        else:
            merged.append(token)
    return " ".join(merged)
