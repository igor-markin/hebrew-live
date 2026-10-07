# NN audit scripts, 2026-10

Measurement scripts behind `docs/NN_IMPROVEMENT_PLAN.ru.md` (results in its Appendix A).
They are opt-in local experiments: nothing here is imported by the application, and the
Whisper patches in `whisper_patches.py` are measurement aids, not production code.

Prerequisites: the project `.venv`, prepared models in `./models` (`asr`, `milmmt-4b-4bit`),
and the local synthetic corpus `logs/asr-comparison-20260908` (12 clean Hebrew TTS clips with
reference texts; not part of the public export). Run everything from the repository root with
`.venv/bin/python experiments/nn-audit-2026-10/<script>.py`. Keep a single MLX job at a time; the
gated scripts skip rounds while CPU idle is below 62 % and report min/median over accepted rounds.

| Script | Question |
| --- | --- |
| `asr_cost_vs_length.py` | ASR snapshot cost vs audio length through `Engine.recognize` |
| `asr_breakdown.py` | mel / encoder / decoder / word-timestamp split of one call; fused-attention feature diff |
| `asr_ab_fused.py` | gated A/B: stock vs fused encoder attention |
| `asr_ab_fused_wts.py` | gated 2x2: fused attention x word timestamps |
| `asr_ab_context_floor.py` | gated A/B: encoder context floor 15 s / 20 s vs shipped |
| `asr_quality.py` | WER and transcript identity for fused / naive truncation / context floors |
| `asr_text_identity_wts.py` | is the text identical with word timestamps off? |
| `mt_cost_vs_length.py` | MiLMMT timing vs phrase length; `max_tokens=256` truncation probe (`probe` arg) |
| `mt_profile.py` | prefill / decode step / `stream_generate` overhead |
| `mt_wrapper_ab.py` | paired A/B: `stream_generate` vs `generate_step`, token identity |
| `mt_identity.py` | plan 1.1 identity: `mt_generate` (generate_step) vs stock `stream_generate`, yielded text and finish reasons, he-en/ru/my |
| `mt_speculate_ab.py` | plan 1.6: drafting from the previous translation vs plain greedy; text identity, paired time ratio, acceptance (`JOIN=n` makes longer phrases) |
| `mt_batch_cost.py` | plan 1.6 cost model: forward time of 1..32 tokens with a warm cache |
| `gpu_roofline.py`, `gpu_bandwidth.py` | matmul TFLOPS, attention kernel time, read bandwidth and decode ceiling |
| `load_model.py` | offered GPU load of the live schedule under continuous speech (model, not a measurement) |
| `milmmt_12.py`, `apple_translate.swift` | the 12 references through MiLMMT and Apple Translation side by side |
| `apple_probe.swift` | Hebrew support in Apple Translation and Apple Speech on this Mac |

Swift probes: `xcrun swiftc -parse-as-library -O -o <name> <name>.swift` (Command Line Tools with
the macOS 26+ SDK are enough). `timeout` is not installed on macOS; use
`perl -e 'alarm 240; exec @ARGV' ./apple_translate sentences.txt` to bound a run.
