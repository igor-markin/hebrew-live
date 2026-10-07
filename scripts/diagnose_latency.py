"""Print timing-only summaries from private diagnostics without echoing speech."""

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path


def quantiles(values):
    values = sorted(value for value in values if isinstance(value, (int, float)) and math.isfinite(value))
    if not values:
        return {"count": 0, "p50": None, "p95": None, "max": None}
    def at(fraction):
        return round(values[min(len(values)-1, math.ceil(len(values)*fraction)-1)], 3)
    return {"count": len(values), "p50": at(.5), "p95": at(.95), "max": round(values[-1], 3)}


def union_seconds(events):
    ranges = sorted((event["start"], event["end"]) for event in events
                    if isinstance(event.get("start"), (int, float))
                    and isinstance(event.get("end"), (int, float))
                    and event["end"] > event["start"])
    if not ranges:
        return 0.
    total = 0.
    left, right = ranges[0]
    for start, end in ranges[1:]:
        if start <= right:
            right = max(right, end)
        else:
            total += right-left
            left, right = start, end
    return total+right-left


def erasure(previous, new):
    """Words of the visible text that must be deleted before the new version can be appended."""
    shared = 0
    for old, fresh in zip(previous, new):
        if old != fresh:
            break
        shared += 1
    return len(previous)-shared


def stability(versions):
    """versions: chronological [(seconds_from_group_start, translation_text)] of one group.

    Returns (first_visible_seconds, normalized_erasure, stable_word_seconds[]). Normalized
    erasure is deleted words over words of the final text; a word is stable from the first
    version after which it is never changed or removed again."""
    texts = [(moment, text.split()) for moment, text in versions if isinstance(text, str) and text.split()]
    if not texts:
        return None, None, []
    final = texts[-1][1]
    erased = sum(erasure(texts[i-1][1], texts[i][1]) for i in range(1, len(texts)))
    stable = []
    for position, word in enumerate(final):
        index = len(texts)-1
        while index > 0 and len(texts[index-1][1]) > position and texts[index-1][1][position] == word:
            index -= 1
        stable.append(texts[index][0])
    return texts[0][0], erased/len(final), stable


def audio_seconds_of(path, events):
    """Accepted audio duration from the session summary next to the log, else the last ASR end."""
    try:
        summary = json.loads((path.parent/"session.json").read_text(encoding="utf-8"))
        total = sum(item.get("duration", 0) for item in summary.get("accepted", {}).values())
        if total > 0:
            return total
    except (OSError, ValueError, AttributeError):
        pass
    ends = [event.get("end") for event in events["live_asr"] if isinstance(event.get("end"), (int, float))]
    return max(ends) if ends else None


def minute_buckets(events, field, width=300., select=None):
    """Median of `field` per `width` seconds of session time; shows slowdown over a long run."""
    buckets = defaultdict(list)
    for event in events:
        moment, value = event.get("elapsed"), event.get(field)
        if (isinstance(moment, (int, float)) and isinstance(value, (int, float)) and
                (select is None or select(event))):
            buckets[int(moment//width)].append(value)
    return {str(int(index*width)): quantiles(values)["p50"] for index, values in sorted(buckets.items())}


def summarize(path):
    events = defaultdict(list)
    malformed = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if isinstance(event, dict) and isinstance(event.get("event"), str):
                events[event["event"]].append(event)
    def metric(event_name, field):
        return quantiles(event.get(field) for event in events[event_name])
    mode = next((event.get("asr") for event in events["effective_models"]), None)
    starts = events["asr_job_start"]
    asr = events["live_asr"]
    input_seconds = sum(event.get("input_seconds", 0) for event in asr)
    unique_seconds = union_seconds(asr)
    first_translations = {}
    final_translations = []
    for event in events["live_publication"]:
        current = event.get("current") or {}
        if not current.get("translation"):
            continue
        if event.get("segment") not in first_translations:
            first_translations[event.get("segment")] = event.get("audio_lag")
        if event.get("stage") in ("closed", "technical"):
            final_translations.append(event.get("audio_lag"))
    kinds = Counter(event.get("kind") for event in events["mt_requested"])
    def job_key(event):
        return (event.get("segment"), event.get("epoch"), event.get("job_id"), event.get("job_version"))
    first_previews = {job_key(event): event.get("elapsed") for event in events["mt_first_preview"]}
    preview_advances = [event["elapsed"]-first_previews[job_key(event)]
                        for event in events["mt_finished"]
                        if job_key(event) in first_previews and isinstance(event.get("elapsed"), (int, float))
                        and isinstance(first_previews[job_key(event)], (int, float))]
    waits = [event["queue_wait"] for event in starts if isinstance(event.get("queue_wait"), (int, float))]
    middle = len(waits)//2
    split_memory = events["split_engine_memory"][-1] if events["split_engine_memory"] else {}
    asr_ranges = [(event["elapsed"]-event["seconds"],event["elapsed"])
                  for event in asr if isinstance(event.get("elapsed"),(int,float))
                  and isinstance(event.get("seconds"),(int,float))]
    mt_starts = {job_key(event):event["elapsed"] for event in events["mt_started"]
                 if isinstance(event.get("elapsed"),(int,float))}
    mt_ranges = [(mt_starts[job_key(event)],event["elapsed"])
                 for event in events["mt_finished"] if job_key(event) in mt_starts
                 and isinstance(event.get("elapsed"),(int,float))]
    overlap=sum(max(0.,min(asr_end,mt_end)-max(asr_start,mt_start))
                for asr_start,asr_end in asr_ranges for mt_start,mt_end in mt_ranges)
    groups = defaultdict(list)
    for event in events["live_publication"]:
        current = event.get("current") or {}
        if current.get("translation") and isinstance(event.get("from_start"), (int, float)):
            groups[event.get("segment")].append((event["from_start"], current["translation"]))
    first_visible, erasures, stable_words = [], [], []
    for versions in groups.values():
        first, normalized, stable = stability(versions)
        if first is None:
            continue
        first_visible.append(first)
        erasures.append(normalized)
        stable_words.extend(stable)
    lost = sum(len(events[name]) for name in ("recognition_repetition", "recognition_early_repetition",
                                              "unrecognized_audio"))
    audio = audio_seconds_of(path, events)
    short_asr = lambda event: isinstance(event.get("input_seconds"), (int, float)) and 1 <= event["input_seconds"] <= 4
    memory = [value for name, field in (("worker_memory", "peak_mlx"), ("worker_memory", "peak_rss"),
                                        ("warmup_finished", "peak_memory"))
              for value in (event.get(field) for event in events[name]) if isinstance(value, (int, float))]
    generations = events["mt_generation"]
    proposed = sum(event.get("proposed", 0) for event in generations)
    accepted_drafts = sum(event.get("accepted_drafts", 0) for event in generations)
    return {
        "pipeline": next((event.get("mode") for event in events["inference_pipeline"]),"unknown"),
        "audio_seconds": round(audio, 1) if audio else None,
        "time_to_first_visible_draft_seconds": quantiles(first_visible),
        "normalized_erasure": quantiles(erasures),
        "stable_word_seconds": quantiles(stable_words),
        "lost_speech_events": lost,
        "lost_speech_per_10_minutes": round(lost/(audio/600), 2) if audio else None,
        "mlx_runtime": next((event for event in events["mlx_runtime"]), None) and {
            key: value for key, value in events["mlx_runtime"][0].items() if key not in ("event", "elapsed")},
        "asr_short_call_seconds_by_5_minutes": minute_buckets(asr, "seconds", select=short_asr),
        "mt_duration_seconds_by_5_minutes": minute_buckets(events["mt_finished"], "seconds"),
        "peak_memory_bytes": max(memory) if memory else None,
        "mt_interrupted": dict(Counter(event.get("reason") for event in events["mt_interrupted"])),
        "mt_prioritized": len(events["mt_prioritized"]),
        "mt_cancel": dict(Counter(event.get("outcome") for event in events["mt_cancel"])),
        "mt_cancel_seconds": metric("mt_cancel", "seconds"),
        "mt_length_truncated": sum(bool(event.get("truncated")) for event in events["mt_finished"]),
        "mt_generation_first_token_seconds": quantiles(event.get("first_token_seconds") for event in generations),
        "mt_generation_tokens": quantiles(event.get("tokens") for event in generations),
        "mt_speculative_acceptance": round(accepted_drafts/proposed, 3) if proposed else None,
        "asr_mode": mode,
        "diagnostics_incomplete_lines": malformed,
        "asr_queue_wait_seconds": metric("asr_job_start", "queue_wait"),
        "asr_capture_age_at_start_seconds": metric("asr_job_start", "capture_age"),
        "asr_queue_wait_first_half_seconds": quantiles(waits[:middle]),
        "asr_queue_wait_second_half_seconds": quantiles(waits[middle:]),
        "asr_duration_seconds": metric("live_asr", "seconds"),
        "asr_input_audio_seconds": round(input_seconds, 3),
        "asr_unique_audio_seconds": round(unique_seconds, 3),
        "asr_repeat_work_ratio": round(input_seconds/unique_seconds, 3) if unique_seconds else None,
        "asr_without_word_alignment": sum(event.get("word_alignment") is False for event in asr),
        "mt_requested_by_kind": dict(kinds),
        "mt_started": len(events["mt_started"]),
        "mt_cached": len(events["mt_cached"]),
        "mt_skipped_superseded_refresh": len(events["mt_skipped_superseded_refresh"]),
        "mt_first_token_seconds": metric("mt_first_token", "seconds"),
        "mt_first_visible_draft_audio_lag_seconds": metric("mt_first_preview", "audio_lag"),
        "draft_preview_before_completed_mt_seconds": quantiles(preview_advances),
        "mt_duration_seconds": metric("mt_finished", "seconds"),
        "asr_mt_overlap_seconds": round(overlap,3),
        "mt_pending_depth": metric("mt_queued","queue_depth"),
        "mlx_peak_bytes_by_worker": {key:split_memory[key] for key in ("asr_peak","mt_peak")
                                     if key in split_memory},
        "ui_preview_backend_to_dom_ack_seconds": metric("ui_preview_seen","backend_to_dom_ack"),
        "first_completed_translation_audio_lag_seconds": quantiles(first_translations.values()),
        "closed_translation_audio_lag_seconds": quantiles(final_translations),
        "unprocessed_audio_events": len(events["unprocessed_audio"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnostics", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.diagnostics], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
