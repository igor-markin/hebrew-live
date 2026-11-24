"""Installed model choices and an ordered worker command."""
from dataclasses import dataclass
# Speech is recognized by the streaming zipformer bundled with the app (streaming_asr); the
# Whisper choices of earlier releases ('turbo', 'fast', 'multilingual') now mean it.
ASR={'streaming':('ivrit.ai zipformer2 · streaming, bundled',None)}
LEGACY_ASR=('turbo','fast','multilingual')
TRANSLATION={'milmmt':('MiLMMT 4B · 4-bit MLX','milmmt-4b-4bit')}
def current_asr(value):
 return 'streaming' if value in LEGACY_ASR else value
def validate(values,folder=None):
 if isinstance(values,dict) and values.get('asr') in LEGACY_ASR:values=dict(values,asr='streaming')
 if not isinstance(values,dict) or set(values)!={'asr','translation'} or not isinstance(values['asr'],str) or not isinstance(values['translation'],str) or values['asr'] not in ASR or values['translation'] not in TRANSLATION:raise ValueError('Unknown model selection')
 if folder is not None:
  for table,key in [(ASR,'asr'),(TRANSLATION,'translation')]:
   name=table[values[key]][1]
   if name is not None and not (folder/name).is_dir():raise ValueError('Model not installed')
 return dict(values)
@dataclass(frozen=True)
class ModelChange:
 selection: dict
