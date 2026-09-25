"""Installed model choices and an ordered worker command."""
from dataclasses import dataclass
ASR={
 'fast':('GigaAM-He · быстрый черновик · ONNX CPU','fast-asr'),
 'turbo':('ivrit.ai Whisper Turbo · MLX','asr'),
 'multilingual':('Whisper Turbo · многоязычный · MLX','asr-multilingual'),
}
TRANSLATION={'milmmt':('MiLMMT 4B · 4-bit MLX','milmmt-4b-4bit')}
def validate(values,folder=None):
 if not isinstance(values,dict) or set(values)!={'asr','translation'} or not isinstance(values['asr'],str) or not isinstance(values['translation'],str) or values['asr'] not in ASR or values['translation'] not in TRANSLATION:raise ValueError('Unknown model selection')
 if folder is not None:
  for table,key in [(ASR,'asr'),(TRANSLATION,'translation')]:
   if key=='asr' and values[key]=='fast':
    from .fast_asr import model_at
    model_at(folder)
   elif not (folder/table[values[key]][1]).is_dir():raise ValueError('Model not installed')
 return dict(values)
@dataclass(frozen=True)
class ModelChange:
 selection: dict
