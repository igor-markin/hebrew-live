"""One translator at a time for the Hy-MT2 vs MiLMMT comparison.

MiLMMT goes through the app's own prompt (`hebrew_live.translation.prompt`), stop tokens
(`configure`), token budget (`mt_generate.max_tokens_for`), token loop (`mt_generate.generate`)
and repetition guard (`cli.translation_loop`): what `Engine.translate` does, without speculation.
Hy-MT2 goes through the same loop, budget and guard, with the prompt from the model card
(`tencent/Hy-MT2-1.8B` @ 9a341cd, English prompt for non-Chinese pairs, no system prompt) and the
chat template shipped with the weights. Nothing in `src/` is changed.

Modes: `greedy` (as the app runs), `rp` (greedy + repetition penalty 1.05 over the whole context,
as Hugging Face applies it), `rec` (the card's recommended sampling: temperature 0.7, top_p 0.6,
top_k 20, repetition penalty 1.05; seeded per sentence).
"""
import os
import sys
import time
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
APP_MODELS = Path.home() / 'Library' / 'Application Support' / 'Hebrew Live CLI' / 'models'
DEVTEST = REFS / 'flores200-devtest' / 'flores200_dataset'
MODELS = {
    'milmmt': APP_MODELS / 'milmmt-4b-4bit',
    'hy4': REFS / 'hy-mt2-1.8b-4bit',
    'hy8': REFS / 'hy-mt2-1.8b-8bit',
    'hybf16': REFS / 'hy-mt2-1.8b-bf16',  # unquantized MLX conversion, upper bound of the family at 1.8B
}
NAMES = {'en': 'English', 'ru': 'Russian', 'he': 'Hebrew'}
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
sys.path.insert(0, str(ROOT / 'src'))

HY_DEFAULT = ('Translate the following text into {target}. Note that you should only output the translated '
              'result without any additional explanation:\n\n{text}')
HY_TERMS = ('Reference the following translations:\n{terms}\n\nTranslate the following text into {target}. '
            'Note that you must ONLY output the translated result without any additional explanation:\n\n{text}')
HY_BACKGROUND = ('[Background Information]\n{background}\n\nPlease translate the following text into {target}, '
                 'taking the provided background information into consideration.\n\n[Source Text]\n{text}')


def flores(seed=20261011, n=300):
    """FLORES-200 devtest lines and the seeded sample `flores_mt.py` uses."""
    import random
    codes = {'he': 'heb_Hebr', 'en': 'eng_Latn', 'ru': 'rus_Cyrl'}
    lines = {lang: (DEVTEST / 'devtest' / f'{code}.devtest').read_text(encoding='utf-8').splitlines() for lang, code in codes.items()}
    urls = [row.split('\t')[0] for row in (DEVTEST / 'metadata_devtest.tsv').read_text(encoding='utf-8').splitlines()[1:]]
    indexes = sorted(random.Random(seed).sample(range(len(lines['he'])), n))
    return lines, urls, indexes


class Translator:
    def __init__(self, name, mode='greedy', seed=1):
        import mlx.core as mx
        from mlx_lm import load
        self.mx, self.name, self.mode, self.seed = mx, name, mode, seed
        began = time.perf_counter()
        self.model, self.tokenizer = load(str(MODELS[name]))
        if name == 'milmmt':
            from hebrew_live.translation import configure
            configure(self.tokenizer, 'milmmt')
        self.load_seconds = time.perf_counter() - began

    # prompts -------------------------------------------------------------------------------
    def ids(self, text, direction, pairs=(), terms=(), background=(), style='prefix'):
        """Token ids of the request. `pairs`: (source, translation) of the sentences before `text`;
        `style` says how Hy-MT2 gets them: `prefix` (as the app does for MiLMMT: both sides open
        with them and the model continues its own translation), `turns` (earlier chat turns),
        `background` (the card's background template, Hebrew only). `terms`: (source, target)."""
        source, target = (NAMES[c] for c in direction.split('-'))
        if self.name == 'milmmt':
            from hebrew_live.translation import prompt
            ids = prompt(self.tokenizer, 'milmmt', text, direction, pairs=pairs)
            if terms:  # no documented format for MiLMMT: a plain instruction line before the request
                head = 'Use these translations of names and terms:\n' + '\n'.join(f'{s} = {t}' for s, t in terms) + '\n'
                ids = self.tokenizer.encode(head, add_special_tokens=False) + ids
            return ids
        tok = self.tokenizer
        user = lambda t: HY_DEFAULT.format(target=target, text=t)
        if terms:
            user = lambda t: HY_TERMS.format(target=target, text=t, terms='\n'.join(f'{s} translates to {d}' for s, d in terms))
        if pairs and style == 'turns':
            messages = []
            for src, done in pairs:
                messages += [{'role': 'user', 'content': user(src)}, {'role': 'assistant', 'content': done}]
            return tok.apply_chat_template(messages + [{'role': 'user', 'content': user(text)}], add_generation_prompt=True)
        if pairs and style == 'background':
            content = HY_BACKGROUND.format(target=target, text=text, background=' '.join(p[0] for p in pairs))
            return tok.apply_chat_template([{'role': 'user', 'content': content}], add_generation_prompt=True)
        if pairs:  # prefix
            before = ' '.join(p[0] for p in pairs)
            done = ' '.join(p[1] for p in pairs)
            ids = tok.apply_chat_template([{'role': 'user', 'content': user(f'{before} {text}')}], add_generation_prompt=True)
            return ids + tok.encode(done + ' ', add_special_tokens=False)
        return tok.apply_chat_template([{'role': 'user', 'content': user(text)}], add_generation_prompt=True)

    # generation ----------------------------------------------------------------------------
    def _sampler(self):
        from mlx_lm.sample_utils import make_logits_processors, make_sampler
        from mlx_lm.generate import generate_step
        if self.mode == 'greedy':
            return make_sampler(temp=0), None
        processors = make_logits_processors(repetition_penalty=1.05, repetition_context_size=4096)
        step = partial(generate_step, logits_processors=processors)
        if self.mode == 'rp':
            return make_sampler(temp=0), step
        return make_sampler(temp=0.7, top_p=0.6, top_k=20), step

    def translate(self, text, direction, key=0, **prompt_args):
        from hebrew_live import mt_generate
        from hebrew_live.cli import translation_loop
        ids = self.ids(text, direction, **prompt_args)
        max_tokens = mt_generate.max_tokens_for(len(self.tokenizer.encode(text, add_special_tokens=False)))
        sampler, step = self._sampler()
        if self.mode == 'rec':
            self.mx.random.seed(self.seed * 100003 + key)
        stats = {}
        generated, reason, first = '', None, None
        began = time.perf_counter()
        for piece, reason in mt_generate.generate(self.model, self.tokenizer, ids, max_tokens=max_tokens,
                                                  sampler=sampler, stats=stats, step=step):
            if piece and first is None:
                first = time.perf_counter() - began
            if translation_loop(generated + piece, text):
                reason = 'repetition'
                break
            generated += piece
        total = time.perf_counter() - began
        return dict(text=generated.strip(), first=first, total=total, tokens=stats.get('tokens'),
                    first_token=stats.get('first_token_seconds'), prompt_tokens=len(ids), reason=reason)

    def peak_gb(self):
        return self.mx.get_peak_memory() / 1e9


def memory_state():
    """(pressure level, free percent) as `experiments/nn-audit-2026-10/gated.py` reads them."""
    sys.path.insert(0, str(ROOT / 'experiments' / 'nn-audit-2026-10'))
    from gated import memory
    return memory()


def require_memory():
    level, free = memory_state()
    if level != 1 or free is None or free < 40:
        sys.exit(f'memory not quiet: pressure level {level}, free {free} %; not starting')
    return level, free
