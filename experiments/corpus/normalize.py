"""Hebrew text normalisation for WER, following the ivrit.ai leaderboard evaluation.

The leaderboard (ivrit-ai/asr-training, evaluate_model.py) strips invisible bidi/zero-width
characters and niqqud, deletes ASCII quotes, then applies Whisper's `BasicTextNormalizer`
(lower-case, drop bracketed spans, turn marks/symbols/punctuation into spaces, collapse
whitespace) and scores words with jiwer. It does not fold final letters or spell out numbers
(the plan's wording suggests otherwise); `fold_finals=True` is available for diagnostics only.
"""
import re
import unicodedata

INVISIBLE = dict.fromkeys(map(ord, (
    "؜​‌‍‎‏‪‫‬‭‮"
    "⁦⁧⁨⁩﻿")))
FINAL_TO_REGULAR = str.maketrans('ךםןףץ', 'כמנפצ')


def _strip_niqqud(text):
    # Hebrew points and cantillation marks (non-spacing); maqaf/sof pasuq stay and become spaces.
    return ''.join(c for c in text if not ('֑' <= c <= 'ׇ' and unicodedata.category(c) == 'Mn'))


def _basic(text):
    text = text.lower()
    text = re.sub(r'[<\[][^>\]]*[>\]]', '', text)
    text = re.sub(r'\(([^)]+?)\)', '', text)
    text = ''.join(' ' if unicodedata.category(c)[0] in 'MSP' else c
                   for c in unicodedata.normalize('NFKC', text)).lower()
    return re.sub(r'\s+', ' ', text)


def normalize(text, fold_finals=False):
    text = _strip_niqqud(text.translate(INVISIBLE)).replace('"', '').replace("'", '')
    text = _basic(text).strip()
    return text.translate(FINAL_TO_REGULAR) if fold_finals else text
