"""Qualified post-decode rejection, scoped to one preliminary transcription."""
from contextlib import contextmanager
import importlib
import threading
from unittest.mock import patch


class RepeatedDecode(Exception):
    def __init__(self, text, tokens):
        self.text = text
        self.tokens = list(tokens)
        super().__init__('early repeated recognition')


@contextmanager
def reject_repeated_decode(enabled, event):
    if not enabled:
        yield
        return
    from .whisper_reuse import compatible, _LOCK
    if not compatible():
        event('whisper_early_reject_disabled', reason='unsupported library version or source')
        yield
        return

    from .cli import repetition_loop
    Whisper = importlib.import_module('mlx_whisper.whisper').Whisper
    owner = threading.get_ident()
    with _LOCK:
        original = Whisper.decode

        def decode(model, *args, **kwargs):
            result = original(model, *args, **kwargs)
            if threading.get_ident() == owner and repetition_loop(result.text):
                raise RepeatedDecode(result.text, result.tokens)
            return result

        # The caller nests reuse inside this context. Both contexts unwind before
        # Engine catches our sentinel; native inference failures remain errors.
        with patch.object(Whisper, 'decode', decode):
            yield
