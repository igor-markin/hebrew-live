# Recognising only the tail of a growing group

The app re-decodes the whole open group every second although its finished sentences are
already frozen on screen. Here the frozen sentences are handed to Whisper as a forced decoder
`prefix`, so it writes only what follows them. Same audio, same model, no new dependency.
In the app since 2026-11-18; `HEBREW_LIVE_TAIL_ONLY=0` restores whole-group decodes.

Outputs hold speech text and stay outside the repository
(`~/Library/Caches/hebrew-live-refs/tail-only-out/`).

```sh
.venv/bin/python experiments/tail-only/prefix_probe.py OUT.json --set d1 --step 20 --limit 400   # windows cover each recording
.venv/bin/python experiments/tail-only/prefix_probe.py OUT.json --set d1 --step 20 --mixed       # adds the app's variant and the pause checks
.venv/bin/python experiments/tail-only/prefix_probe.py OUT.json --set d1 --step 20 --score
.venv/bin/python experiments/tail-only/noise_check.py
```

For each 20 s window: A = decode of the first 14 s (its finished sentences that are followed
by more speech are the frozen part), B = decode of all 20 s, P = decode of all 20 s continued
from the frozen part. Three variants:

- `timestamps`: every decode with timestamp tokens, as the app decoded before;
- `plain`: every decode with `without_timestamps=True`;
- `mixed`: A and B with timestamps, P without. **This is what the app does.**

## Results, 2026-11-18, MacBook Air M5

ivrit.ai eval-d1 (interviews, 247 windows, 10 039 reference words) and eval-whatsapp (186
windows, 8 594 words). WER is high for every variant because 20 s windows cut words at their
edges and the last partial window of a recording is dropped; only differences between
variants mean something. "Shown today" is frozen sentences plus the rest of a whole decode.

| eval-d1 | timestamps | plain | mixed |
| --- | --- | --- | --- |
| windows with a frozen part | 202 | 194 | 202 |
| tail identical to the tail of the whole decode | 85 % | 98 % | 85 % |
| tail came back empty although speech followed | 1 | 0 | 0 |
| errors: shown today | 949 | 932 | 949 |
| errors: frozen sentences + continued decode | 970 | 931 | 941 |

| eval-whatsapp | timestamps | plain | mixed |
| --- | --- | --- | --- |
| windows with a frozen part | 115 | 95 | 115 |
| tail identical to the tail of the whole decode | 66 % | 94 % | 60 % |
| errors: shown today | 1598 | 1564 | 1598 |
| errors: frozen sentences + continued decode | 1598 | 1569 | 1586 |

Time, 120 separate windows of eval-d1 with an idle CPU: whole decode 0.774 s with timestamps,
continued 0.550 s; plain 0.672 s and 0.502 s. Paired saving per decode 0.20-0.24 s in every run.

Why not `timestamps`: the forced text sits before the first timestamp token, which the model
never saw in training; on eval-d1 it added 21 errors and once returned nothing.

Why not `plain` for whole decodes, although it is 13 % faster with the same WER:

- `noise_check.py`, eleven 60 s signals without speech (silence, hiss, hum, clicks): 4 words
  with timestamps, 41 without. Noise that passes the speech detector would become text.
- On conversational speech it writes fewer sentence ends (95 instead of 115 windows had a
  finished sentence), so less would freeze.

Checks of the continued decode (`--mixed`):

- A pause after the speech (the same audio and frozen text, with and without 2 s of pink noise
  at -50 dBFS after it): the text changed in 26 of 202 windows on eval-d1 (9 words added, 2
  lost) and in 11 of 115 on eval-whatsapp (6 added, 2 lost). A whole decode with timestamps
  added 7 words on 241 windows and 3 on 165 under the same pause.
- Worst case, the forced text already holds everything that was said and only noise follows:
  the continued decode wrote 70 words in 56 of 241 windows (eval-d1) and 69 in 48 of 165
  (eval-whatsapp). The app cannot reach this state: the last sentence of a recognition is
  never frozen until the group closes, so speech always follows the forced text.

## The owner's vocabulary as a recognition prompt

`vocabulary_check.py` decodes the same windows again with a prompt of 29 clinic terms that the
recordings do not use (165 tokens, a comma list that ends with a period). Word errors:

| | no prompt | with the prompt |
| --- | --- | --- |
| eval-d1, whole decodes | 947 | 1184 |
| eval-d1, frozen sentences + continued decode | 941 | 986 |
| eval-whatsapp, whole decodes | 1585 | 1889 |
| eval-whatsapp, frozen sentences + continued decode | 1586 | 1595 |

A short list is no safer: the first 5 terms alone (24 tokens) gave 1337 errors on eval-d1 whole
decodes.

Vocabulary words written although not said: 2 and 1, so the harm is lost speech, not inserted
terms. Without the final period it is far worse: Whisper takes the speech for more of the
list (429 of 735 words lost on 20 windows, 3 with the period). The recognition prompt is
therefore off by default (`HEBREW_LIVE_VOCABULARY_ASR=1`); translation still gets the
entries that occur in the phrase.

## The live pipeline, 2026-11-18

The first phone call through the app (an automated menu, 107 s, taken over USB) continued no
decode at all: the pipeline talks to the engine through `RemoteEngine`, which had no
`can_continue`. Fixed; the recording replayed through `he-ru benchmark` both ways:

| | whole-group decodes | tail-only |
| --- | --- | --- |
| recognitions (continued) | 65 (0) | 64 (16) |
| rejected as a loop | 6 | 0 |
| recognition time, fitted | 0.62 s + 37 ms per second of audio | 0.74 s + 21 ms per second |
| recognition time in total | 62.0 s | 59.4 s |
| translation, p50 / p90 | 1.11 / 3.20 s | 1.29 / 3.29 s |
| text behind the audio, p50 / p90 / max | 2.6 / 8.3 / 11.2 s | 3.1 / 7.3 / 11.0 s |

The gain here is 4 %, not the 27 % of the window probe: a menu voice rarely ends a sentence, so
only four freezes happened, and a recognition costs about 0.65 s whatever the audio length.
The final text differs in 17 of 195 words, mostly in favour of tail-only (fewer misheard
words, no stray fragment).
One recording, one run each: the lag columns are within run-to-run noise.

Not measured: heat, whether a prompt helps recognition of the terms themselves.
