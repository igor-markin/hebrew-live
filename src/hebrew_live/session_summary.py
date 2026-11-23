"""summary.json of a session: how fast speech reached the screen and how much the screen moved.

Built from the diagnostics of every part, so it also works on an old session folder:
`python -m hebrew_live.session_summary SESSION_DIR`. Numbers only, no speech text.

- screen: what the window reported drawing (`ui_render`). `screen_lag` is the engine's audio lag at
  publication plus publication-to-drawn time: seconds from the end of the audio a version was made
  from to that version on screen. Hebrew and translation are counted separately.
- backend: the same from the engine's own events, for sessions without a window (benchmark, replay).
- rewrites: a finished sentence (any sentence followed by another) that the next version no longer
  starts with; erased words are words of the previous version missing at the same place.
"""
import json
import re
import sys
from pathlib import Path

SENTENCE = re.compile(r'[^.!?…]+(?:[.!?…]+["»”)]*\s*|$)')
FILE = 'summary.json'


def sentences(text):
    return [s.strip() for s in SENTENCE.findall(text.strip()) if s.strip()]


def _bare(word):
    return word.rstrip('.,!?…:;"\'»«()–-')


def erased_words(before, after):
    """Words of `before` missing at the same place in `after`. Punctuation that follows a word
    (a draft's trailing "...") and a last word that only grew do not count."""
    a, b = [_bare(w) for w in before.split()], [_bare(w) for w in after.split()]
    kept = 0
    while kept < len(a) and kept < len(b) and a[kept] == b[kept]:
        kept += 1
    if kept == len(a) - 1 and kept < len(b) and b[kept].startswith(a[kept]):
        kept += 1
    return len(a) - kept


def stats(values):
    values = sorted(v for v in values if isinstance(v, (int, float)))
    if not values:
        return dict(count=0)
    n = len(values)
    return dict(count=n, p50=round(values[n // 2], 3), p95=round(values[min(n - 1, int(n * .95))], 3),
                max=round(values[-1], 3), mean=round(sum(values) / n, 3))


class Moves:
    """Rewrites of one text field across the versions of each group."""

    def __init__(self):
        self.last, self.complete = {}, set()
        self.versions = self.finished_checks = self.finished_rewritten = 0
        self.erased = self.versions_with_erasure = self.closed_changes = 0

    def add(self, group, text, complete=False):
        self.versions += 1
        old = self.last.get(group)
        if old is not None and old != text:
            if group in self.complete:
                self.closed_changes += 1
            prefix = ''
            normalized = re.sub(r'\s+', ' ', text)
            for sentence in sentences(old)[:-1]:
                self.finished_checks += 1
                prefix = (prefix + ' ' + sentence).strip()
                if not normalized.startswith(prefix):
                    self.finished_rewritten += 1
            lost = erased_words(old, text)
            self.erased += lost
            self.versions_with_erasure += bool(lost)
        if text:
            self.last[group] = text
        if complete:
            self.complete.add(group)

    def result(self):
        return dict(versions=self.versions, finished_sentence_checks=self.finished_checks,
                    finished_sentences_rewritten=self.finished_rewritten, erased_words=self.erased,
                    versions_with_erasure=self.versions_with_erasure, changes_after_closed=self.closed_changes)


def read_events(folder):
    events = []
    for path in sorted(Path(folder).glob('*.diagnostics.jsonl')):
        part = path.name.split('-', 1)[0]
        with path.open(encoding='utf8') as file:
            for line in file:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    event['_part'] = part
                    events.append(event)
    return events


def summarize(events):
    by = {}
    for event in events:
        by.setdefault(event.get('event'), []).append(event)
    get = lambda name: by.get(name, [])

    renders = get('ui_render')
    screen_he, screen_tr, first_he, first_tr = [], [], {}, {}
    screen_moves_he, screen_moves_tr = Moves(), Moves()
    for event in renders:
        key = (event['_part'], event.get('group'))
        lag = event.get('screen_lag')
        if event.get('source_changed') and event.get('source'):
            screen_he.append(lag)
            first_he.setdefault(key, lag)
        if event.get('translation_changed') and event.get('translation'):
            screen_tr.append(lag)
            first_tr.setdefault(key, lag)
        screen_moves_he.add(key, event.get('source', ''), event.get('complete'))
        screen_moves_tr.add(key, event.get('translation', ''), event.get('complete'))

    publications = get('live_publication')
    backend_moves_he, backend_moves_tr = Moves(), Moves()
    backend_he, backend_tr, seen = [], [], {}
    # The last open Hebrew of each group and what the closing version made of it.
    draft, final_change = {}, dict(groups=0, changed=0, erased_words=0, draft_words=0)
    # While a group is open the window shows its `live_source` Hebrew, not the publication's.
    live = set()
    for event in sorted(publications + get('live_source'), key=lambda e: e.get('elapsed', 0)):
        key = (event['_part'], event.get('segment'))
        if event.get('event') == 'live_source':
            if event.get('source'):
                live.add(key)
                backend_he.append(event.get('audio_lag'))
                backend_moves_he.add(key, event['source'])
                draft[key] = event['source']
            continue
        current = event.get('current') or {}
        source, translation = current.get('source', ''), current.get('translation', '')
        old_source, old_translation = seen.get(key, ('', ''))
        shown_live = key in live and event.get('stage') == 'open'
        if event.get('stage') == 'open' and source:
            if not shown_live:
                draft[key] = source
        elif key in draft and source:
            before = draft.pop(key)
            final_change['groups'] += 1
            final_change['draft_words'] += len(before.split())
            lost = erased_words(before, source)
            final_change['erased_words'] += lost
            final_change['changed'] += bool(lost)
        if source and source != old_source and not shown_live:
            backend_he.append(event.get('audio_lag'))
        if translation and translation != old_translation:
            backend_tr.append(event.get('audio_lag'))
        seen[key] = (source or old_source, translation or old_translation)
        closed = event.get('stage') in ('closed', 'technical', 'unavailable')
        if not shown_live:
            backend_moves_he.add(key, source, closed)
        backend_moves_tr.add(key, translation, closed)

    count = lambda name: len(get(name))
    memory = get('worker_memory')
    device = (get('device') or [{}])[-1]
    duration = max((event.get('elapsed', 0) for event in events), default=0)
    clicks = get('ui_click')
    return dict(
        schema_version=1,
        duration_seconds=round(duration, 3),
        input=device.get('input'),
        groups=len({(e['_part'], e.get('segment')) for e in publications}),
        screen=dict(
            reported=bool(renders), renders=len(renders),
            hebrew_lag=stats(screen_he), translation_lag=stats(screen_tr),
            first_hebrew_lag=stats(first_he.values()), first_translation_lag=stats(first_tr.values()),
            publish_to_screen=stats(e.get('publish_to_screen') for e in renders),
            hebrew_moves=screen_moves_he.result(), translation_moves=screen_moves_tr.result()),
        backend=dict(
            hebrew_lag=stats(backend_he), translation_lag=stats(backend_tr),
            first_preview_lag=stats(e.get('audio_lag') for e in get('mt_first_preview')),
            # A streaming draft writes a word a little after hearing it: the lag of its last
            # written word (also counts trailing silence, so an upper bound).
            hebrew_word_lag=stats(e['audio_lag'] + max(0., e['end'] - e['start'] - e['heard_until'])
                                  for e in get('live_source')
                                  if isinstance(e.get('heard_until'), (int, float)) and
                                  all(isinstance(e.get(k), (int, float)) for k in ('audio_lag', 'start', 'end'))),
            hebrew_moves=backend_moves_he.result(), translation_moves=backend_moves_tr.result(),
            closing_vs_last_draft=final_change,
            asr_seconds=stats(e.get('seconds') for e in get('live_asr')),
            whisper_seconds=stats(e.get('seconds') for e in get('live_asr') if not e.get('draft_engine')),
            whisper_total_seconds=round(sum(e.get('seconds') or 0 for e in get('live_asr')
                                            if not e.get('draft_engine')), 3),
            streaming_draft_seconds=stats(e.get('seconds') for e in get('live_asr') if e.get('draft_engine')),
            mt_seconds=stats(e.get('seconds') for e in get('mt_generation')),
            mt_first_token_seconds=stats(e.get('seconds') for e in get('mt_first_token')),
            sentences_frozen=count('sentences_frozen')),
        translation_runs=dict(
            requested=count('mt_requested'), finished=count('mt_finished'),
            interrupted=count('mt_interrupted'), discarded=count('mt_discarded'),
            cancelled=count('mt_cancel'), skipped_superseded=count('mt_skipped_superseded_refresh'),
            failed=sum(1 for e in get('live_mt') if e.get('issue'))),
        reader=dict(clicks=len(clicks), scrolls=count('ui_scroll'), keys=count('ui_key'),
                    follow_off=sum(1 for e in get('ui_follow') if e.get('following') is False),
                    hidden=sum(1 for e in get('ui_visibility') if e.get('visible') is False)),
        memory=dict(peak_mlx_bytes=max((e.get('peak_mlx') or 0 for e in memory), default=None) if memory else None,
                    peak_rss_bytes=max((e.get('peak_rss') or 0 for e in memory), default=None) if memory else None),
        errors=count('error'), number_mismatches=count('number_mismatch'),
    )


def write(folder):
    """Write FILE into the session folder; returns the summary. Never raises for a bad log."""
    folder = Path(folder)
    summary = summarize(read_events(folder))
    target = folder / FILE
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=1) + '\n', encoding='utf8')
    temporary.replace(target)
    return summary


if __name__ == '__main__':
    for argument in sys.argv[1:] or ['.']:
        print(json.dumps(write(argument), ensure_ascii=False, indent=1))
