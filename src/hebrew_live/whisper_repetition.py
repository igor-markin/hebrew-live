"""Qualified rejection of runaway Whisper decodes, scoped to one transcription."""
from contextlib import contextmanager
import importlib
import threading
from unittest.mock import patch

CHECK_EVERY = 4  # greedy steps between text checks


class RepeatedDecode(Exception):
    def __init__(self, text, tokens):
        self.text = text
        self.tokens = list(tokens)
        super().__init__('early repeated recognition')


@contextmanager
def reject_repeated_decode(enabled, event, stop_in_loop=False):
    """Reject loops after decoding; with `stop_in_loop`, also while decoding.

    The in-loop check only uses the part of `repetition_loop` that cannot be
    undone by more tokens, so a stopped decode would have been rejected anyway.
    """
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
            if not stop_in_loop:
                yield
                return
            decoding = importlib.import_module('mlx_whisper.decoding')
            DecodingTask, GreedyDecoder = decoding.DecodingTask, decoding.GreedyDecoder
            main_loop = DecodingTask._main_loop

            def _main_loop(task, *args, **kwargs):
                decoder = task.decoder
                if threading.get_ident() != owner or not isinstance(decoder, GreedyDecoder):
                    return main_loop(task, *args, **kwargs)
                update, eot, tokenizer, steps = decoder.update, decoder.eot, task.tokenizer, [0]

                def checked(tokens, logits, sum_logprobs):
                    # `tokens` is the previous step, already queued on the GPU: reading
                    # it does not stall the step being built.
                    steps[0] += 1
                    if steps[0] % CHECK_EVERY == 0:
                        ids = [t for t in tokens[0].tolist() if t < eot]
                        text = tokenizer.decode(ids)
                        if repetition_loop(text, partial=True):
                            raise RepeatedDecode(text.strip(), ids)
                    return update(tokens, logits, sum_logprobs)

                decoder.update = checked
                try:
                    return main_loop(task, *args, **kwargs)
                finally:
                    del decoder.update

            with patch.object(DecodingTask, '_main_loop', _main_loop):
                yield
