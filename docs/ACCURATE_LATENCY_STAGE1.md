# Accurate-mode latency experiment, 2026-09-25

This stage keeps the same ivrit.ai Whisper Turbo and MiLMMT models and the same
single inference child. It adds timing events and a transient translation draft
as complete words arrive. The draft is never written to the archive or revision
history; a completed translation replaces it. Failure or cancellation clears it.
The UI currently polls the local state every 200 ms, so not every short-lived
preview will be rendered.

`scripts/diagnose_latency.py` summarizes a private diagnostics JSONL file
without printing speech. It reports queue wait and audio age at ASR start,
ASR processing time, accumulated ASR input versus unique audio, MT requests and
skips, time to first MT token and visible draft, and audio lag of completed
translations. The draft lead is the time between its first backend event and
completion of the same MT job; it is not a browser paint measurement.

## Local comparison

A saved 67.7-second WAV was replayed at 1× with prepared models and no network
request. About 43.5 seconds of its audio were accepted for the seven completed
groups. Each configuration ran once. Final source text, final translation, and
group boundaries matched exactly across these runs; this is only a check on
this recording. No user speech is included in this report.

| Configuration | ASR jobs | Repeated ASR audio | ASR queue wait p50 / p95 | First completed translation audio lag p50 / p95 | Draft lead before MT completion p50 / p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Aligned drafts (default) | 19 | 2.39× | 0.860 / 5.845 s | 4.044 / 7.800 s | 0.546 / 2.421 s |
| Drafts without word alignment | 44 | 4.97× | 0.054 / 0.921 s | 1.055 / 1.507 s | 0.183 / 0.471 s |
| Drafts without word alignment, experimental 2 s refresh spacing | 29 | 3.42× | 0.608 / 2.919 s | 3.259 / 5.405 s | 0.225 / 1.713 s |

The refresh-spacing rule skipped **zero** translations in the third run;
the existing superseded-refresh rule already discarded 5, 8, and 11 outdated
refreshes respectively. The new spacing rule was removed. System conditions
and the number of ASR jobs varied substantially, so the one-run latency
difference does not prove that removing word alignment caused it. Alternating
aligned and text-only calls on a fixed 4.5-second excerpt gave medians of about
0.748 and 0.706 seconds, with the same transcript. This small difference is not
enough to enable text-only drafts by default. The option remains available for
further controlled testing as `HEBREW_LIVE_TEXT_ONLY_DRAFT=1`.

All three replays ended with zero unprocessed-audio events. A local Browser
check showed the previous translation, the transient draft, and the completed
translation in sequence; opening revision history after completion showed only
the previous durable version. This verifies presentation behavior, not the
latency of Electron on another Mac.

The single worker still serializes ASR and MT. These changes can show useful
text sooner and expose queue growth, but they cannot guarantee bounded waiting
during dense speech. Separating model workers requires a separate comparison
of throughput, memory, heat, and final-translation latency.

## Packaged smoke check

The unsigned Apple Silicon DMG built after this change is 1,177,124,521 bytes
(SHA-256 `d806368a99f34c5685779a04abb930deda097506815eca6ec7e1a93e1c938be3`),
below the 1.8 GiB local target. Its mounted image verified successfully. The
app was copied from the DMG to a temporary folder; its bundled model directory
contains GigaAM-He ONNX and Silero ONNX, with no MiLMMT or Whisper weights.
The extracted Python engine ran a 15-second real-audio excerpt with prepared
external models, an empty managed-model directory, offline model resolution,
and no repository `.venv`. It emitted two transient previews and two completed
translation groups with no unprocessed-audio event. This is an engine check;
the full Electron shell and installation on another Mac were not exercised in
this stage.

Run the timing summary on a private log with:

```sh
python scripts/diagnose_latency.py /path/to/001-he-ru.diagnostics.jsonl
```
