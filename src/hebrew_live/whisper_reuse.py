"""Reuse only the current Whisper decode window for word alignment.

Version/file qualification fails closed to upstream. Never share token KV caches,
change mel length, catch inference errors, or retain audio across transcriptions.
"""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import importlib
import importlib.metadata
from pathlib import Path
import threading
from unittest.mock import patch

_LOCK = threading.RLock()
_OWNER = None
_HASHES = {
 'transcribe.py':'21f015e0d56c5e6194d07d86d772730940fff52d8f06d55838ae92ebccc24fbb',
 'decoding.py':'fae5828b2d80760e6dbcd5a51d7704769dca67cad5d559085d0a08d40964e616',
 'timing.py':'2736c2bf19f2ebbaa521dae9deb3748c6b5d5f319af729f4078dc2b0769822cd',
 'whisper.py':'1ccfd1ff754ef6c0bfda3436dfa09e00e0d2e4295c5d75e151570e5eca626154',
}

@lru_cache(maxsize=1)
def compatible():
    try:
        dist=importlib.metadata.distribution('mlx-whisper')
        return dist.version=='0.4.3' and all(
            hashlib.sha256(Path(dist.locate_file('mlx_whisper/'+name)).read_bytes()).hexdigest()==digest
            for name,digest in _HASHES.items())
    except (OSError,importlib.metadata.PackageNotFoundError):
        return False

@contextmanager
def _alignment_context(Whisper,trans,event=None):
    global _OWNER
    owner=threading.get_ident()
    with _LOCK:
        if _OWNER==owner:
            raise RuntimeError('Nested Whisper reuse is not supported')
        _OWNER=owner
        state={};counts={'reuses':0,'fallbacks':0}
        decode0=Whisper.decode;add0=trans.add_word_timestamps;forward0=Whisper.forward_with_cross_qk
        def decode(model,mel,*a,**kw):
            if threading.get_ident()!=owner:return decode0(model,mel,*a,**kw)
            state.clear()
            result=decode0(model,mel,*a,**kw)
            features=getattr(result,'audio_features',None)
            if features is not None and getattr(mel,'ndim',None)==2:
                state.update(model=model,mel=mel,features=features)
            return result
        def add(*a,**kw):
            if threading.get_ident()!=owner:return add0(*a,**kw)
            try:
                model=kw.get('model');mel=kw.get('mel');features=state.get('features')
                valid=(not a and model is not None and model is state.get('model')
                       and mel is state.get('mel') and features is not None
                       and features.shape==(model.dims.n_audio_ctx,model.dims.n_audio_state)
                       and features.dtype==mel.dtype)
                if not valid:
                    counts['fallbacks']+=1
                    return add0(*a,**kw)
                def forward(current,actual,tokens):
                    if threading.get_ident()!=owner or current is not model or actual.shape!=(1,*mel.shape):
                        return forward0(current,actual,tokens)
                    logits,_,qk=current.decoder(tokens,features[None,:])
                    counts['reuses']+=1
                    return logits,qk
                with patch.object(Whisper,'forward_with_cross_qk',forward):return add0(**kw)
            finally:
                state.clear()
        try:
            with patch.object(Whisper,'decode',decode),patch.object(trans,'add_word_timestamps',add):
                yield counts
        finally:
            state.clear();_OWNER=None
            if event:event('whisper_encoder_reuse',**counts)

@contextmanager
def reuse_alignment(enabled=True,event=None):
    if not enabled:
        yield
        return
    if not compatible():
        if event:event('whisper_encoder_reuse_disabled',reason='unsupported library version or source')
        yield
        return
    trans=importlib.import_module('mlx_whisper.transcribe')
    model=importlib.import_module('mlx_whisper.whisper')
    with _alignment_context(model.Whisper,trans,event):yield
