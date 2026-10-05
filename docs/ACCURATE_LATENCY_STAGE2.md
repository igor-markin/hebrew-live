# Accurate-mode pipeline experiment, 2026-09-25

The Accurate mode now has an opt-in `HEBREW_LIVE_SPLIT_WORKERS=1` experiment.
It puts ivrit.ai Whisper Turbo and MiLMMT in separate spawned processes and
lets ASR accept the next audio snapshot while an MT thread handles the earlier
text. The default remains the serial worker. Each job carries its frozen
direction and session part. The MT queue retains first and closing jobs,
replaces waiting obsolete refreshes, and has a fixed eight-job bound. A failed
MT worker marks its accepted ranges as unprocessed. Closing groups can complete
after ASR has started the next group. An older first translation cannot replace
a newer visible source version.

The browser sends a local-only acknowledgement after two animation frames when
a visible card contains a new translation preview. Diagnostics record the time
from backend preview emission to that acknowledgement. This is a check that the
preview reached rendered DOM, not a precise display scanout measurement. The
200 ms state polling interval still affects whether a brief preview is seen.

## Matched local comparison

The same saved 67.7-second WAV was replayed at 1×, three times per
configuration, using the same Whisper Turbo and MiLMMT files. Model resolution was offline and
source WAV saving was disabled for these temporary test sessions. No other
Hebrew Live app was running. Final source and target text, group ranges, and
the nine closed groups matched exactly in all six runs. Each run recorded zero
unprocessed-audio events. These checks cover this recording only.

| Run | ASR queue wait p95 | First completed translation lag p50 / p95 | Closed translation lag p50 / p95 | ASR/MT job overlap |
| --- | ---: | ---: | ---: | ---: |
| Serial 1 | 0.548 s | 1.103 / 2.056 s | 1.382 / 2.184 s | 0.001 s |
| Split 1 | 0.497 s | 1.038 / 2.677 s | 1.593 / 2.967 s | 9.550 s |
| Serial 2 | 0.557 s | 1.038 / 1.956 s | 1.357 / 2.292 s | 0.001 s |
| Split 2 | 0.527 s | 1.086 / 1.813 s | 1.718 / 4.349 s | 11.511 s |
| Serial 3 | 1.131 s | 1.191 / 2.434 s | 1.818 / 3.021 s | 0.001 s |
| Split 3 | 0.474 s | 1.000 / 2.562 s | 1.421 / 2.643 s | 6.851 s |

The workers genuinely overlapped. The p95 duration of MT generation was
0.992–1.169 s in serial runs and 1.416–1.674 s in split runs. Closed
translation p95 was worse in the first two split comparisons, but the third
split run was better than the third serial run. The third split run used the
final display policy: while its first translation is pending, the card keeps
the older source rather than briefly showing a newer source and then
reverting. None of its first translations was discarded. This variability
does not establish a repeatable latency improvement. Concurrent MLX work on
the same GPU is a plausible cause of the longer MT jobs, but these timings do
not directly attribute time to GPU contention. One short recording also does
not establish long-session thermal behavior. Split mode remains disabled by
default.

The serial worker reached 4,372,309,888 peak MLX bytes and 1,606,664,192
peak process RSS bytes in an additional full replay with RSS instrumentation.
In a split replay, the ASR worker reached 2,189,110,134 MLX bytes and
758,595,584 RSS bytes; the MT worker reached 2,308,310,708 MLX bytes and
1,524,432,896 RSS bytes. The sum of the two worker peaks is about 4.50 GB of
MLX allocations and 2.28 GB of RSS. Those peaks may occur at different times;
the sums are not a measured simultaneous process-tree peak. Do not add MLX
allocations to RSS to estimate physical RAM consumption.

A separate 20-second Browser replay produced two visible preview
acknowledgements, 18 and 93 ms after their backend preview events. The short
replay does not provide a useful p95 for the UI. It demonstrates that the
browser receives and renders some intermediate text before MT completion.

`scripts/diagnose_latency.py` reports these timing and memory fields without
printing speech. The full Electron shell, a second Mac, a long continuous
conversation, and a Core ML/Neural Engine Whisper implementation were not
tested here. The next accelerator experiment should compare the same model on
Core ML/ANE against the serial MLX baseline before changing the default.

## Test package

The local unsigned Apple Silicon DMG is 1,177,139,059 bytes (SHA-256
`7c25846c1ea82f4ba9b68b235977b32d8db8b0f4bd641bc8a40233b5b811c6de`),
below the 1.8 GiB target. `hdiutil verify` passed. Its embedded engine contains
GigaAM-He ONNX and Silero ONNX, but no MiLMMT or Whisper weights. The engine
was launched directly from the mounted final DMG with an isolated data root,
verified copies of the external models, no repository `.venv`, and offline
model resolution. A 20-second saved-audio excerpt produced three completed
groups and zero unprocessed-audio events. The full Electron shell was not
launched for this stage.
