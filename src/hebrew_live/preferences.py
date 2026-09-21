"""Local preferences; atomic writes never overwrite a good file partially."""
import json,os,tempfile,threading
from pathlib import Path
from .tuning import validate as timing_validate,as_dict
from .model_selection import validate as model_validate
_LOCK=threading.RLock()
RETIRED_TRANSLATION_NOTICE='The saved retired translation-model choice is no longer supported; this session uses the installed MiLMMT model. No model files were deleted.'
def read(folder):
 path=Path(folder)/'preferences.json'
 if not path.exists():return {}
 data=json.loads(path.read_text())
 if not isinstance(data,dict):raise ValueError('Invalid preferences')
 if data.get('schema_version',1) not in (1,2,3):raise ValueError('Unsupported preferences schema')
 result={}
 if 'timing' in data:result['timing']=as_dict(timing_validate(data['timing']))
 if 'mode' in data:
  if data['mode'] not in ('phrases','both','full','blocks','pauses'):raise ValueError('Invalid translation mode')
  result['mode']='phrases'  # Migrate retired profiles in memory; do not rewrite on read.
 if 'publication' in data:
  if data['publication'] not in ('phrases','revisable','draft'):raise ValueError('Invalid publication mode')
  result['publication']='draft'
 if 'models' in data:
  models=data['models']
  if isinstance(models,dict) and models.get('translation')=='7b':
   models=dict(models,translation='milmmt')
   result['preference_notices']=[RETIRED_TRANSLATION_NOTICE]
  result['models']=model_validate(models)
 if 'target_language' in data:
  from .languages import LANGUAGES
  target=data['target_language']
  if target not in LANGUAGES or target=='he':raise ValueError('Invalid target language')
  result['target_language']=target
 if 'ui_locale' in data:
  if data['ui_locale'] not in ('en','ru','he'):raise ValueError('Invalid interface language')
  result['ui_locale']=data['ui_locale']
 result['draft_max_audio_seconds']=validate_draft_limit(data.get('draft_max_audio_seconds',20.0))
 result['draft_catchup_enabled']=validate_catchup(data.get('draft_catchup_enabled',False))
 return result
def save(folder,**values):
 with _LOCK:
  folder=Path(folder);folder.mkdir(exist_ok=True,mode=0o700)
  data=read(folder);data.pop('preference_notices',None);data.update(values);data['schema_version']=3
  if data.get('mode','phrases')!='phrases':raise ValueError('Invalid translation mode')
  if data.get('publication','draft') != 'draft':raise ValueError('Only draft publication is supported')
  if 'timing' in data:data['timing']=as_dict(timing_validate(data['timing']))
  if 'models' in data:data['models']=model_validate(data['models'])
  if 'target_language' in data:
   from .languages import LANGUAGES
   if data['target_language'] not in LANGUAGES or data['target_language']=='he':raise ValueError('Invalid target language')
  if 'ui_locale' in data and data['ui_locale'] not in ('en','ru','he'):raise ValueError('Invalid interface language')
  data['draft_max_audio_seconds']=validate_draft_limit(data.get('draft_max_audio_seconds',20.0))
  data['draft_catchup_enabled']=validate_catchup(data.get('draft_catchup_enabled',False))
  fd,name=tempfile.mkstemp(prefix='.preferences-',dir=folder)
  try:
   with os.fdopen(fd,'w') as file:
    json.dump(data,file,ensure_ascii=False,indent=2);file.flush();os.fsync(file.fileno())
   os.replace(name,folder/'preferences.json')
  finally:
   if os.path.exists(name):os.unlink(name)

def validate_draft_limit(value):
 import math
 if type(value) not in (int,float) or not math.isfinite(value) or not 1 <= value <= 30:
  raise ValueError('draft_max_audio_seconds must be a finite number from 1 to 30')
 return float(value)

def validate_catchup(value):
 if type(value) is not bool:raise ValueError('draft_catchup_enabled must be boolean')
 return value
