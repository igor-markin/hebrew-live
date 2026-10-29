"""Replay a recorded session's ASR texts through the draft pipeline with the real translator.

    PYTHONPATH=src .venv/bin/python experiments/stable-sentences/replay.py SESSION_DIR OUT.jsonl \
        [--until 1440] [--models DIR]

ASR is not run: every `live_asr` event of the recording returns its recorded text and
status, so both variants see identical speech. Set HEBREW_LIVE_FREEZE_SENTENCES=0 for the
whole-group baseline. Writes every screen update (`live_publication`, `live_stream`) and
`mt_generation` timings as JSON lines. Loads only the translation model (about 2.5 GB).
"""
import argparse, json, os, queue, sys, threading, time
from pathlib import Path
from types import SimpleNamespace

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
import numpy as np
from mlx_lm import load
from mlx_lm.sample_utils import make_sampler

from hebrew_live import mt_generate
from hebrew_live.cli import Fragment
from hebrew_live.retranslation import RetranslationProcessor
from hebrew_live.stream import Settings
from hebrew_live.translation import configure, prompt

DEFAULT_MODELS = Path.home() / 'Library/Application Support/Hebrew Live CLI/models'


class Engine:
    backend = 'turbo'; asr_path = translation_size = None; accepts_hint = False
    recognition_issue = None

    def __init__(self, folder, out):
        self.model, self.tokenizer = load(str(folder))
        configure(self.tokenizer, 'milmmt')
        self.translation_context = []; self.event = None; self.out = out

    def recognize(self, audio, *args, **kwargs):
        self.recognition_status = self.event['status']
        return self.event['source'] if self.event['status'] == 'accepted' else ''

    def translate(self, text, hint=''):
        ids = prompt(self.tokenizer, 'milmmt', text, self.direction, self.topic, self.translation_context)
        limit = mt_generate.max_tokens_for(len(self.tokenizer.encode(text, add_special_tokens=False)))
        began = time.monotonic(); stats = {}
        for piece, reason in mt_generate.generate(self.model, self.tokenizer, ids, max_tokens=limit,
                                                  sampler=make_sampler(temp=0), stats=stats):
            yield piece, reason
        self.out.write(json.dumps(dict(kind='mt_generation', seconds=time.monotonic() - began,
                                       prompt_tokens=len(ids), context=list(self.translation_context),
                                       source=text), ensure_ascii=False) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('session'); p.add_argument('out'); p.add_argument('--until', type=float, default=1440.)
    p.add_argument('--models', type=Path, default=DEFAULT_MODELS)
    a = p.parse_args()
    events = [d for d in map(json.loads, next(Path(a.session).glob('*.diagnostics.jsonl')).open())
              if d['event'] == 'live_asr' and d['start'] <= a.until]
    out = open(a.out, 'w')
    engine = Engine(a.models / 'milmmt-4b-4bit', out)
    updates = queue.Queue()
    log = SimpleNamespace(event=lambda name, **values: None)
    processor = RetranslationProcessor(engine, updates, log, threading.Event(), async_mt=False)
    settings = Settings(publication='draft', direction='he-ru')
    began = time.monotonic()
    for index, event in enumerate(events):
        start, end = round(event['start'] * 16000), round(event['end'] * 16000)
        closing = event.get('closing')
        engine.event = event
        processor.process(Fragment(event['fragment'], event['revision'], np.zeros(end - start, np.float32),
                                   0., 0., bool(closing), settings, end / 16000, 0.,
                                   closing or ''))
        while not updates.empty():
            kind, sid, value = updates.get()
            if kind in ('live_publication', 'live_stream'):
                out.write(json.dumps(dict(kind=kind, segment=sid, at=event['end'], **value), ensure_ascii=False) + '\n')
        if index % 100 == 0:
            print(f'{index}/{len(events)} {time.monotonic() - began:.0f}s', file=sys.stderr, flush=True)
    processor.flush()
    while not updates.empty():
        kind, sid, value = updates.get()
        if kind in ('live_publication', 'live_stream'):
            out.write(json.dumps(dict(kind=kind, segment=sid, at=None, **value), ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
