# Small bilingual translation experiment

On 2026-09-24, we compared two local Hebrew-to-English models followed by
[`Helsinki-NLP/opus-mt_tiny_eng-rus`](https://huggingface.co/Helsinki-NLP/opus-mt_tiny_eng-rus)
for English-to-Russian translation. This is an experiment, not a release model
selection. No conversation text or model weights are stored in this repository.

| Hebrew → English | Source and runtime | Weight file | License shown on model card |
| --- | --- | ---: | --- |
| [`tiedeman/opus-mt-he-en`](https://huggingface.co/tiedeman/opus-mt-he-en) | Older OPUS Marian model, PyTorch float32 | 154 MB | Apache-2.0 |
| [`WindyTranslate/translate-windy-hplt-he-en`](https://huggingface.co/WindyTranslate/translate-windy-hplt-he-en) | INT8 CTranslate2 conversion of the [HPLT v2 Hebrew-English model](https://huggingface.co/HPLT/translate-he-en-v2.0-hplt_opus), trained on HPLT v2 and OPUS data | 79 MB | CC-BY-4.0 |

The English-to-Russian PyTorch weight file is 50.7 MB. A local INT8
CTranslate2 conversion of that same model uses a 17.6 MB weight file; its
complete converted directory is about 22 MB. The HPLT base model is from
2025; the derived quantized repository was updated later. A recent repository
update does not establish that its underlying training data or architecture is
new. The derived model's card reports a small fine-tune and a FLORES-200 score,
but also says it has no human evaluation on conversation.

## Local measurement

The same 66 recognized Hebrew segments from one recorded conversation were
sent through both pipelines on this Mac. Both used two CPU threads, beam size
4, and sentence splitting at punctuation. The local test environment used
CTranslate2 4.8.2, Transformers 5.16.1, and PyTorch 2.14.0. Measurements cover
**model inference after text is available**; they exclude speech recognition,
queues, process startup, rendering, and time until a user sees the result. Russian output
followed the English output sequentially.

| Pipeline | English median / p95 | Russian total median / p95 | Peak test-process RSS |
| --- | ---: | ---: | ---: |
| Older OPUS → tiny English-Russian | 0.157 / 0.433 s | 0.197 / 0.526 s | 1,000 MB |
| HPLT INT8 → tiny English-Russian | 0.065 / 0.182 s | 0.102 / 0.282 s | 614 MB |
| HPLT INT8 → tiny English-Russian INT8 | 0.067 / 0.185 s | 0.083 / 0.224 s | 273 MB |

This comparison changes both the Hebrew model and inference runtime. The
speed and memory difference cannot be attributed to model age alone. In a
separate run of the HPLT pipeline, four CPU threads were slightly slower on
these short inputs than two (Russian median 0.114 s vs 0.102 s); one thread
was also slightly slower (0.112 s).

The INT8 English-to-Russian conversion changed 13 of 66 outputs compared with
the float32 version; none became empty. Most changes were small, but proper
names sometimes gained an unknown-token marker. The conversion alone is not
evidence of equivalent translation quality.

## End-to-end engine replay

The 421.2-second WAV was also replayed in real time through the app's normal
VAD, fast ONNX Hebrew recognizer, draft scheduler, engine process, publication
queue, and local browser UI. We ran the two translators sequentially on this
Mac with the **same** ASR and VAD models. Both runs produced 70 groups, 66 with
a translation; the final recognized Hebrew source was identical in those 66
groups. Safari displayed live revisions on the local browser page and the
completed result in the modern frontend. The measurements below come from
`live_publication.audio_lag`: time from the end of a processed audio fragment
to the first translated publication in the backend. The modern UI polls every
200 ms, so these are not measured pixel-display times or delays from the start
of a spoken phrase.

| Translation engine | First translated publication median / p95 / max | MT median / p95 | ASR queue median / p95 |
| --- | ---: | ---: | ---: |
| HPLT INT8 → tiny English-Russian INT8 | 0.178 / 0.237 / 0.330 s | 0.080 / 0.170 s | 0.000 / 0.001 s |
| Current MiLMMT | 0.485 / 0.637 / 0.804 s | 0.523 / 0.989 s | 0.000 / 0.469 s |

The app first collects 1.5 seconds of a new fragment before attempting ASR.
Measured from the **start of the selected audio fragment**, the first
translated publication had a median of 1.643 s for the bridge and 1.966 s for
MiLMMT, before the browser's next poll. This accumulation period is now the
largest part of first-preview latency.

No engine errors or capture discontinuities occurred. Each run had one MT
repetition rejection and four groups without an accepted final translation.
The bridge worker used no Metal allocation and had about 1.17 GB resident
memory in one `ps` sample; MiLMMT reported 2.24 GB peak Metal allocation and
about 1.23 GB resident memory in one `ps` sample. These memory readings are
different accounting measures and must not be added together. The 844 MB fast
ASR model dominates CPU resident memory in both configurations.

We also replayed the same 75-second landlord excerpt twice with MiLMMT,
changing only the first-ASR-snapshot threshold from 1.5 to 1.0 seconds. Ten
groups translated in each run and their final recognized Hebrew and final
translation matched exactly. Median first publication from fragment start
fell from 1.976 to 1.431 seconds. Early 1.0-second snapshots contained less
speech and sometimes changed a short instruction into a different phrase.
This small sample supports keeping 1.5 seconds as the default. The source
runtime accepts a local timing preference, but the current Electron interface
does not expose this control.

## Quality and decision

Splitting multi-sentence utterances restored several clauses that either
model dropped when given the whole utterance. It also reduced the worst
observed HPLT inference time in the 24-segment sample. The newer pipeline
mistook a proper noun for a similar-sounding common noun. Both models also
made an overly specific guess about a generic greeting. These wording errors
are tolerable for a fast, provisional preview. The
quality gate should instead focus on lost questions or changed actionable
facts such as dates, amounts, rental terms, and commitments. The two-step
pipeline can lose details during English-to-Russian translation. Its
outputs were reviewed against the recognized Hebrew and the existing app's
Russian output; the latter is **not ground truth**.

The integrated replay found a blocking quality problem. With identical Hebrew
recognition, the bridge omitted the possible rent increase in one long turn
and failed to convey that the price had remained the same for three years in
another. MiLMMT preserved those facts, although the recognizer's mistaken
word for "rent" still caused a wrong noun in both translations. Splitting long
Hebrew turns at conjunctions recovered some omitted clauses in a focused
trial, but also caused a question about staying another year to disappear from
the Russian output. That heuristic is not safe to enable globally.

The bridge therefore remains an **opt-in local experiment**, not the public
default. The CLI accepts both `--preview-he-en-model` and
`--preview-en-ru-model` for `listen` and `benchmark`, with fast Hebrew ASR and
`he-en` or `he-ru` only. The converted weights are not in this repository or
the Electron bundle. No independent background correction path exists yet;
revised ASR snapshots use the same single worker. A public switch requires a
quality check against human reference translations for consequential facts,
plus packaging, attribution, and a measured screen-display delay.

The local comparison script is
[`scripts/compare_hebrew_translation_bridge.py`](../scripts/compare_hebrew_translation_bridge.py).
It accepts local model paths and writes the detailed, private translation report
only outside the repository.
