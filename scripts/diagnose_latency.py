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
    return {
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
