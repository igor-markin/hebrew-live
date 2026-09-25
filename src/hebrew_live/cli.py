"""Offline streaming captions. Network access exists only in `setup`."""
import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import hashlib
import importlib
import importlib.metadata
import json
import logging
import os
import platform
from pathlib import Path
import queue
import re
import sys
import threading
import time
import traceback

from .paths import data_root

ROOT = data_root()
# A wheel does not have run.sh to scope Hugging Face's transfer metadata.
# Keep its default with the rest of the app while respecting an explicit shell
# override. Source launches export the same variable before Python starts.
os.environ.setdefault('HF_HOME',str(ROOT/'cache/huggingface'))
SPEC = json.loads(Path(__file__).with_name('models.json').read_text())

from .session import Log, Session, LibraryHandler
from .stream import Settings, Boundary, AudioBlock

TOPICS = {
    'none': '',
    'news': 'A news report about current events.',
    'interview': 'An interview: questions and answers about experiences and opinions.',
    'parents': 'A parent-teacher meeting about school or kindergarten.',
    'courier': 'A conversation with a delivery courier about a parcel.',
    'health': 'A conversation with an Israeli health fund about appointments, referrals and coverage.',
}


RETIRED_MANIFEST_ASSETS={'translation_7b'}
RETIRED_MODEL_DIRS={'translation-7b'}


def model_download_keys():
    return ['asr','asr_multilingual','translation','vad']


def desktop_model_download_keys():
    """Return the fast desktop components prepared after first launch."""
    return ['fast_asr','translation','vad']


def preference_folder(models):
    if os.environ.get('HEBREW_LIVE_DESKTOP_MANAGED') == '1':
        return data_root()/'.local-settings'
    return models.parent/'.local-settings'


def print_model_info():
    print('Separate third-party assets (not covered by the Hebrew Live CLI code license):')
    for key in model_download_keys():
        spec=SPEC[key]
        print(f"- {key}: {spec.get('repo') or spec.get('url')}")
        print(f"  terms/evidence: {spec['terms_url']}")
        print(f"  review note: {spec['terms_note']}")


def print_language_info():
    """Print model-card capabilities separately from the qualified product scope."""
    from .languages import target_languages
    print('Qualified live source language: Hebrew (he)')
    print('Default target language: English (en)')
    print('Interface languages: English (en), Russian (ru), Hebrew (he)')
    values=target_languages()
    print(f'MiLMMT targets ({len(values)}):')
    print('  '+', '.join(f'{item.english_name} ({item.code})' for item in values))
    print(f'Overall product registry: {len(values)+1} languages including the qualified Hebrew source.')
    print('The optional multilingual Whisper checkpoint has 99 language tokens upstream; this product does not qualify arbitrary-language live input.')


def print_installed_storage(models=None, log_dir=None, uninstall=False):
    """Describe effective paths without treating explicit overrides as owned."""
    root=ROOT.expanduser().resolve()
    default_models=root/'models';default_logs=root/'logs'
    models=(models or default_models).expanduser().resolve()
    logs=(log_dir or default_logs).expanduser().resolve()
    preferences=models.parent/'.local-settings'
    models_overridden=models!=default_models
    logs_overridden=logs!=default_logs
    print(f'Managed data root: {root}')
    print(f'  models: {models}')
    if models_overridden:
        print('    explicit --models override; this path is not assumed to be app-owned and is excluded from root deletion')
    print(f'  recordings and session logs: {logs}')
    if logs_overridden:
        print('    explicit --log-dir override; this path is not assumed to be app-owned and is excluded from root deletion')
    print(f'  preferences: {preferences}')
    if models_overridden:
        print('    follows the --models parent; review it separately and do not infer ownership from this preview')
    hf_home=Path(os.environ['HF_HOME']).expanduser().resolve()
    print(f'  Hugging Face cache: {hf_home}')
    if hf_home != root/'cache/huggingface':
        print('    explicit HF_HOME override; this path is not assumed to be app-owned and is excluded from the deletion plan')
    print(f'Python environment: {sys.prefix}')
    print(f'Command path: {Path(sys.argv[0]).expanduser().resolve()}')
    print('Compatible --asr-model, --translation-model, and --vad-model paths are external user data and are never included in managed deletion.')
    if uninstall:
        print('')
        print('Dry run only; nothing was deleted.')
        print('Quit Hebrew Live CLI and review each listed app-owned path. Move the root to Trash only if it is dedicated to this app and contains no custom data you need.')
        if models_overridden or logs_overridden:
            print('The explicit --models/--log-dir paths above are outside the assumed root-owned deletion scope. Review them separately; the preview does not authorize deleting them.')
        print("If installed with 'uv tool install', run 'uv tool uninstall hebrew-live-cli'.")
        print("Otherwise run 'python -m pip uninstall hebrew-live-cli' from the Python environment shown above, or remove that environment if it exists only for this app.")
        print('Do not remove a shared uv or Python installation. External BYO models and unrelated files inside a custom root remain outside the deletion plan and require separate review.')


def require_supported_platform(require_metal=True):
    """Fail before model download/load when the qualified Apple runtime is absent."""
    system=platform.system();machine=platform.machine()
    if system!='Darwin':
        raise RuntimeError(f'Runtime requires macOS on Apple Silicon; detected {system}/{machine}. Linux, Windows, and Docker are unsupported')
    if machine!='arm64':
        hint=' Reopen a native terminal without Rosetta.' if machine=='x86_64' else ''
        raise RuntimeError(f'Runtime requires native Apple Silicon arm64; detected {machine}.{hint}')
    if not require_metal:return
    try:
        mx=importlib.import_module('mlx.core')
        if not mx.metal.is_available():raise RuntimeError('Metal backend is unavailable')
        mx.set_default_device(mx.gpu)
        value=mx.array([0],dtype=mx.int32);mx.eval(value)
    except Exception as exc:
        raise RuntimeError('MLX cannot access an Apple Metal device. Use a native arm64 macOS terminal; no CPU/CUDA fallback is supported') from exc


def setup(folder):
    import urllib.request
    from huggingface_hub import snapshot_download
    from .model_store import atomic_json, file_digest, preparation_lock
    with preparation_lock(folder):
        keys=model_download_keys()[:-1]
        print_model_info()
        print('Starting explicit model download…')
        for key in keys:
            spec = SPEC[key]
            snapshot_download(spec['repo'], revision=spec['revision'], local_dir=folder/spec.get('folder',key),
                              allow_patterns=['*.json','*.safetensors','*.npz','*.model','*.tiktoken','*.txt','*.jinja','README.md','LICENSE*','NOTICE*'])
        data = urllib.request.urlopen(SPEC['vad']['url'], timeout=60).read()
        if hashlib.sha256(data).hexdigest()!=SPEC['vad']['sha256']:
            raise RuntimeError('Downloaded VAD checksum does not match the pinned inventory')
        (folder/'silero.onnx').write_bytes(data)
        manifest = dict(schema_version=2,assets=model_download_keys(),spec=SPEC,
            files={str(p.relative_to(folder)):file_digest(p)
            for p in folder.rglob('*') if p.is_file() and '.cache' not in p.parts
            and p.name not in ('manifest.json','.model-prepare.lock') and not p.name.endswith('.part')
            and not (set(p.relative_to(folder).parts)&RETIRED_MODEL_DIRS)})
        atomic_json(folder/'manifest.json', manifest)
    print('Models downloaded and pinned. Run: he-ru doctor')


IDENTITY_FIELDS=('repo','revision','folder','url','sha256')
LEGACY_ASSETS=('asr','translation','vad')


def asset_identity(spec,key):
    if not isinstance(spec,dict) or not isinstance(spec.get(key),dict):
        raise ValueError('Invalid model manifest specification')
    value=spec[key]
    return {name:value[name] for name in IDENTITY_FIELDS if name in value}


def core_spec(spec):
    """Exact legacy manifest identity; new manifests use every declared asset."""
    result={}
    for key in LEGACY_ASSETS:
        identity=asset_identity(spec,key);identity.pop('sha256',None);result[key]=identity
    return result


def manifest_assets(manifest):
    """Validate schema/identity and return (declared assets, legacy format)."""
    if not isinstance(manifest,dict):raise ValueError('Invalid model manifest')
    spec=manifest.get('spec')
    if manifest.get('schema_version')==2:
        assets=manifest.get('assets')
        known=set(SPEC)|RETIRED_MANIFEST_ASSETS|{'fast_asr'}
        if (not isinstance(assets,list) or not assets or len(assets)!=len(set(assets))
                or any(not isinstance(key,str) or key not in known for key in assets)):
            raise ValueError('Invalid model manifest assets')
        # Schema v2 supports both the original CLI setup (four assets) and the
        # desktop setup (translation and VAD with ASR bundled into the app).
        # Whisper ASR remains a valid optional CLI or explicit desktop asset.
        required={'translation','vad'}
        if not required.issubset(assets):raise ValueError('Model manifest omits required setup assets')
        for key in set(assets)&set(SPEC):
            if asset_identity(spec,key)!=asset_identity(SPEC,key):
                raise ValueError('Model manifest asset revision changed')
        return set(assets)&set(SPEC),False
    if 'schema_version' in manifest:raise ValueError('Unsupported model manifest schema')
    if core_spec(spec)!=core_spec(SPEC):raise ValueError('Legacy model revisions changed')
    return set(LEGACY_ASSETS),True


def required_model_files(asset):
    folder=SPEC.get(asset,{}).get('folder',asset)
    if asset in ('asr','asr_multilingual'):
        return ({f'{folder}/config.json',f'{folder}/weights.safetensors'},())
    if asset=='translation':
        return ({f'{folder}/config.json',f'{folder}/model.safetensors'},
                (f'{folder}/tokenizer.json',f'{folder}/tokenizer.model'))
    if asset=='vad':return ({'silero.onnx'},())
    raise ValueError('Unknown model asset')


def verify(folder,required_assets=()):
    try:manifest=json.loads((folder/'manifest.json').read_text())
    except (OSError,ValueError,TypeError) as exc:raise RuntimeError('Model manifest is missing or unreadable; run setup') from exc
    try:declared,legacy=manifest_assets(manifest)
    except (KeyError,TypeError,ValueError) as exc:raise RuntimeError('Model revisions changed or manifest is invalid; run setup') from exc
    files=manifest.get('files')
    if not isinstance(files,dict) or not files:raise RuntimeError('Model manifest has no verified files; run setup')
    required=set(required_assets)
    if not required.issubset(SPEC):raise RuntimeError('Unknown required model asset')
    if not required.issubset(declared):raise RuntimeError('Selected model is absent from the setup manifest; run setup')
    coverage=declared
    names=set(files)
    if 'fast_asr' in manifest.get('assets', ()):
        from .fast_asr import MODEL_FILES
        pinned=json.loads(Path(__file__).with_name('fast_asr_manifest.json').read_text())['files']
        if any(files.get('fast-asr/'+name)!=pinned[name]['sha256'] for name in MODEL_FILES):
            raise RuntimeError('Fast ASR manifest does not match the pinned export; run setup')
    for asset in coverage:
        exact,alternatives=required_model_files(asset)
        if not exact.issubset(names):raise RuntimeError(f'Model manifest omits critical {asset} files; run setup')
        if alternatives and not any(name in names for name in alternatives):
            raise RuntimeError(f'Model manifest omits critical {asset} files; run setup')
    for name, digest in manifest['files'].items():
        if not isinstance(name,str):raise RuntimeError('Model manifest is invalid; run setup')
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('Model manifest is invalid; run setup')
        if relative.parts and relative.parts[0] in RETIRED_MODEL_DIRS:continue
        if not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise RuntimeError('Model manifest is invalid; run setup')
        p=folder/relative
        from .model_store import file_digest
        if not p.is_file() or file_digest(p)!=digest:
            raise RuntimeError('Model integrity check failed; run setup')


def validate_custom_models(models,asr=None,translation=None,vad=None,asr_backend='turbo'):
    """Validate supported local model layouts without treating them as setup assets."""
    managed=models.resolve()
    values={}
    for name,value,kind in (('ASR',asr,'directory'),('translation',translation,'directory'),('VAD',vad,'file')):
        if value is None:continue
        path=value.expanduser().resolve()
        if path==managed or path.is_relative_to(managed):
            raise ValueError(f'Custom {name} path must be outside the setup-managed models directory')
        if kind=='directory' and not path.is_dir():raise ValueError(f'Custom {name} model directory does not exist')
        if kind=='file' and not path.is_file():raise ValueError(f'Custom {name} model file does not exist')
        values[name.lower()]=path
    if asr is not None:
        if asr_backend=='fast':
            from .fast_asr import model_at
            model_at(models,values['asr'])
        elif not (values['asr']/'config.json').is_file() or not (values['asr']/'weights.safetensors').is_file():
            raise ValueError('Custom ASR model must be an MLX Whisper directory with config.json and weights.safetensors')
    if translation is not None:
        path=values['translation']
        has_tokenizer=(path/'tokenizer.json').is_file() or (path/'tokenizer.model').is_file()
        if not (path/'config.json').is_file() or not has_tokenizer or not any(path.glob('*.safetensors')):
            raise ValueError('Custom translation model must be an MLX-LM directory with config, tokenizer, and safetensors files')
    if vad is not None and values['vad'].suffix.lower()!='.onnx':
        raise ValueError('Custom VAD model must be a Silero-compatible ONNX file')
    return values


def bug_report(models):
    """Return a shareable metadata report without captions, audio, tokens or paths."""
    packages={}
    for name in ('hebrew-live-cli','mlx','mlx-whisper','mlx-lm','onnxruntime','sounddevice','soundfile','soxr'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    manifest_status={'present':False,'readable':False,'spec_matches':False,'file_count':0}
    manifest=models/'manifest.json'
    if manifest.is_file():
        manifest_status['present']=True
        try:
            value=json.loads(manifest.read_text())
            manifest_status.update(readable=True,
                                   file_count=len(value.get('files',{})) if isinstance(value.get('files'),dict) else 0)
            try:
                manifest_assets(value)
                manifest_status['spec_matches']=True
            except (KeyError,ValueError,TypeError):pass
        except (OSError,ValueError,TypeError):pass
    choices={
        'asr':{key:(models/folder).is_dir() for key,(_,folder) in __import__('hebrew_live.model_selection',fromlist=['ASR']).ASR.items()},
        'translation':{key:(models/folder).is_dir() for key,(_,folder) in __import__('hebrew_live.model_selection',fromlist=['TRANSLATION']).TRANSLATION.items()},
    }
    return {
        'schema_version':1,
        'privacy':'Contains environment metadata only; no audio, captions, logs, local paths, browser token, or preferences.',
        'system':{'macos':platform.mac_ver()[0] or None,'machine':platform.machine(),'python':platform.python_version()},
        'package_versions':packages,
        'model_inventory':{key:{'source':value.get('repo') or value.get('url'),'revision':value.get('revision')} for key,value in SPEC.items() if isinstance(value,dict)},
        'installed_model_choices':choices,
        'model_manifest':manifest_status,
        'custom_data_home':bool(os.environ.get('HEBREW_LIVE_HOME')),
    }

class VAD:
    def __init__(self, path):
        import numpy as np
        import onnxruntime as ort
        ort.disable_telemetry_events()
        opts=ort.SessionOptions();opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
        self.state=np.zeros((2,1,128),dtype=np.float32)
        self.context=np.zeros((1,64),dtype=np.float32)
    def reset(self):
        self.state.fill(0)
        self.context.fill(0)

    def __call__(self, frame):
        import numpy as np
        x=np.concatenate([self.context,frame.reshape(1,-1)],axis=1)
        out,self.state=self.session.run(None,{'input':x,'state':self.state,'sr':np.array(16000,dtype=np.int64)})
        self.context=x[:,-64:]
        return float(out[0][0])

def repetition_loop(text):
    """Reject runaway letter/phrase loops while preserving ordinary emphasis."""
    if re.search(r"([^\W\d_])\1{11,}",text,re.IGNORECASE):
        return True
    words=re.findall(r"\w+",text.lower())
    for size in range(3,min(16,len(words)//3)+1):
        for start in range(len(words)-size*3+1):
            if words[start:start+size]==words[start+size:start+size*2]==words[start+size*2:start+size*3]:
                return True
    return False


class Engine:
    def __init__(self, folder, log, language='he', backend='turbo',
                 asr_path=None, translation_path=None):
        self.encoder_reuse=True
        self.early_reject=os.environ.get('HEBREW_LIVE_EARLY_REJECT','1')!='0'
        self.backend=backend
        self.translation_size='milmmt'
        self.language=language
        self.direction="he-en"
        self.topic="none"
        import mlx.core as mx
        from mlx_lm import load
        from transformers.utils import logging as transformer_logging
        transformer_logging.disable_default_handler()
        transformer_logging.enable_propagation()
        self.mx=mx;self.log=log
        self.custom_models=asr_path is not None or translation_path is not None
        if backend=='fast':
            from .fast_asr import FastHebrewOnnx, model_at
            self.asr_path=str(model_at(folder,asr_path))
            self.asr=FastHebrewOnnx(Path(self.asr_path))
        else:
            import mlx_whisper
            self.asr=mlx_whisper
            self.asr_path=str(asr_path or folder/({'multilingual':'asr-multilingual'}.get(backend,'asr')))
        self.log.event('asr_early_reject_config',enabled=self.early_reject,
                       scope='phrases/preliminary/he-source/he/turbo')
        t=time.monotonic()
        from .model_selection import TRANSLATION, validate
        validate(dict(asr=backend,translation='milmmt'))
        if backend!='fast' and asr_path is None and not (folder/({'multilingual':'asr-multilingual'}.get(backend,'asr'))).is_dir():
            raise ValueError('Model not installed')
        if translation_path is None and not (folder/TRANSLATION['milmmt'][1]).is_dir():
            raise ValueError('Model not installed')
        self.model,self.tokenizer=load(str(translation_path or folder/TRANSLATION['milmmt'][1]))
        from .translation import configure
        configure(self.tokenizer,'milmmt')
        self.log.event('translation_loaded',seconds=time.monotonic()-t)
        self.models_folder=folder
        self.context=deque(maxlen=2)
    def close(self):
        """Release native model state before Python starts tearing down MLX locks."""
        import gc,importlib
        self.mx.synchronize()
        if self.backend!='fast':
            holder=importlib.import_module('mlx_whisper.transcribe').ModelHolder
            holder.model=None;holder.model_path=None
        self.asr=None
        self.model=None;self.tokenizer=None
        gc.collect();self.mx.synchronize();self.mx.clear_cache()

    def switch_models(self, selection):
        if self.custom_models:raise ValueError('Runtime model switching is disabled with custom local model paths')
        from .model_selection import validate
        import gc,importlib
        values=validate(selection,self.models_folder)
        if values['asr']=='fast' and not self.direction.startswith('he-'):
            raise ValueError('Fast Hebrew ASR supports Hebrew source audio only')
        direction,topic=self.direction,self.topic
        self.log.event('model_load_start',**values)
        self.mx.synchronize()
        if self.backend!='fast':
            holder=importlib.import_module('mlx_whisper.transcribe').ModelHolder
            holder.model=None;holder.model_path=None
        self.asr=None
        self.model=None;self.tokenizer=None
        gc.collect();self.mx.clear_cache()
        # Runs only in the inference worker, after all preceding final jobs.
        self.__init__(self.models_folder,self.log,self.language,values['asr'])
        self.direction,self.topic=direction,topic
        self.warmup()
        self.log.event('model_load_complete',**values)

    def recognize(self, audio, prefix=0, *, preliminary=False, mode=None, align_words=True):
        self.recognition_status='empty'
        self.recognition_issue=None
        self.raw_recognition=''
        self.recognition_words=[]
        from .languages import split_direction
        source_language, _ = split_direction(self.direction)
        early=(preliminary and mode=='phrases' and getattr(self,'early_reject',False)
               and getattr(self,'backend',None)=='turbo' and self.language=='he'
               and source_language=='he')
        word_timestamps = align_words or prefix > 0 or getattr(self,'backend','turbo')=='fast'
        if getattr(self,'backend','turbo')=='fast':
            result=self.asr.transcribe(audio)
        else:
            from .whisper_reuse import reuse_alignment
            from .whisper_repetition import reject_repeated_decode, RepeatedDecode
            try:
                with reject_repeated_decode(early,self.log.event):
                    with reuse_alignment(getattr(self,'encoder_reuse',False) and word_timestamps,self.log.event):
                        result=self.asr.transcribe(audio,path_or_hf_repo=self.asr_path,language=None if self.language=='auto' else self.language,task='transcribe',
                            temperature=0.0,word_timestamps=word_timestamps,condition_on_previous_text=False,verbose=None)
            except RepeatedDecode as exc:
                self.recognition_status='rejected';self.recognition_issue='early repeated recognition'
                self.recognition_words=[]
                self.raw_recognition=exc.text
                self.log.event('recognition_early_repetition',reason=self.recognition_issue,
                               raw_text=exc.text,tokens=exc.tokens)
                return ''
        self.log.event('recognition_quality',language=result.get('language'),segments=[{k:s.get(k) for k in ('avg_logprob','compression_ratio','no_speech_prob')} for s in result.get('segments',[])])
        words=([w for s in result.get('segments',[]) for w in s.get('words',[]) if (w['start']+w['end'])/2>=prefix]
               if word_timestamps else [])
        self.recognition_words=words
        text=(''.join(w['word'] for w in words) if word_timestamps else
              ''.join(s.get('text','') for s in result.get('segments',[]))).strip()
        self.raw_recognition=text
        from .script_filter import clearly_non_hebrew
        if self.language=='he' and source_language=='he' and clearly_non_hebrew(text):
            self.recognition_status='rejected';self.recognition_words=[]
            self.recognition_issue='non-Hebrew transcript'
            self.log.event('recognition_script_filtered',requested_language='he',reason=self.recognition_issue)
            return ''
        if self.language == 'ru' and len(re.findall(r'[א-ת]',text)) > len(re.findall(r'[А-Яа-яЁё]',text)):
            self.recognition_status='rejected';self.recognition_words=[]
            self.recognition_issue='ASR returned Hebrew instead of Russian'
            self.log.event('recognition_script_mismatch',requested_language='ru')
            return ''
        if repetition_loop(text):
            self.recognition_status='rejected';self.recognition_words=[]
            self.log.event('recognition_repetition');self.recognition_issue='repeated recognition';return ''
        self.recognition_status='accepted' if text else 'empty'
        return text
    def translate(self, text):
        from mlx_lm import stream_generate
        from mlx_lm.sample_utils import make_sampler
        from .translation import prompt
        ids=prompt(self.tokenizer,'milmmt',text,self.direction,self.topic,getattr(self,'translation_context',[]))
        generated=''
        for result in stream_generate(self.model,self.tokenizer,prompt=ids,max_tokens=256,sampler=make_sampler(temp=0)):
            candidate=generated+result.text
            if repetition_loop(candidate):
                yield '', 'repetition'
                return
            generated=candidate
            yield result.text, result.finish_reason
    def warmup(self):
        import numpy as np
        t=time.monotonic()
        silence=np.zeros(16000,dtype=np.float32)
        if self.backend=='fast':
            self.asr.transcribe(silence)
        else:
            self.asr.transcribe(silence,path_or_hf_repo=self.asr_path,language=self.language,
                               temperature=0.,word_timestamps=True,condition_on_previous_text=False,verbose=None)
        list(self.translate('שלום.'))
        self.log.event('warmup_finished',seconds=time.monotonic()-t,peak_memory=self.mx.get_peak_memory())

@dataclass
class Fragment:
    id: int
    revision: int
    audio: object
    prefix: float
    end: float
    final: bool
    settings: object = None
    offset: float = 0.
    quiet: float = 0.
    reason: str = ""

class Inbox:
    TIMEOUT=object()
    """Bounded final FIFO; only the newest provisional snapshot is retained."""
    def __init__(self,on_overload=None):
        self.condition=threading.Condition();self.finals=deque();self.preview=None;self.done=False;self.latest={}
        self.overloaded=False;self.on_overload=on_overload
    def put(self, f):
        with self.condition:
            f.queued_at=time.monotonic()
            self.latest[f.id]=f.revision
            if self.overloaded:
                if self.on_overload:self.on_overload(f)
                return False
            if f.final:
                if len(self.finals)>=4:
                    self.overloaded=True
                    self.preview=None
                    if self.on_overload:self.on_overload(f)
                    return False
                self.finals.append(f)
                if self.preview and self.preview.id<=f.id:self.preview=None
            else:self.preview=f
            self.condition.notify()
            return True
    def put_boundary(self, boundary):
        with self.condition:
            self.finals.append(boundary);self.condition.notify()

    def put_model_change(self, change):
        with self.condition:
            self.finals.append(change);self.condition.notify()

    def put_retry(self, request):
        with self.condition:
            self.finals.append(request);self.condition.notify()
    def superseded(self, f):
        with self.condition:
            return not f.final and any(getattr(item,'id',None)==f.id for item in self.finals)
    def finish(self):
        with self.condition:self.done=True;self.condition.notify_all()
    def pending_fragments(self):
        with self.condition:
            return [item.fragment if hasattr(item,'fragment') else item for item in self.finals
                    if hasattr(item,'fragment') or isinstance(item,Fragment)]
    def newer_audio_waiting(self, current):
        """Whether the next FIFO audio snapshot supersedes a draft refresh."""
        with self.condition:
            candidate=self.finals[0] if self.finals else self.preview
            return (isinstance(candidate,Fragment) and candidate.settings==current.settings and
                    (candidate.id>current.id or
                     candidate.id==current.id and candidate.revision>current.revision))
    def take_draft_catchup(self, current, group_start, group_end):
        """Take only the ordinary next item, atomically; never wait or skip FIFO."""
        with self.condition:
            if self.done:return None,'eof'
            if any(not isinstance(f,Fragment) for f in self.finals):return None,'barrier'
            f=self.finals[0] if self.finals else self.preview
            if f is None:return None,'no_snapshot'
            if f.settings!=current.settings or f.id!=current.id:return None,'other_context'
            end=round(f.offset*16000);start=end-len(f.audio)
            if f.revision<=current.revision or end<=group_end:return None,'not_newer'
            if start>group_end or end<=group_start:return None,'audio_gap'
            if end-group_start>=round(current.settings.draft_max_audio_seconds*16000):return None,'group_limit'
            if f.final and f.reason not in ('window','silence'):return None,'closing_barrier'
            if self.finals:self.finals.popleft()
            else:self.preview=None
            return f,'eligible'
    def asr_due_before_translation(self, ready_at):
        """Experiment policy: ASR wait/1s vs oldest ready MT wait/2s.

        Boundaries and model changes are barriers: drain old MT before taking
        them. No GPU concurrency or interruption in the middle of generation.
        """
        with self.condition:
            f=self.finals[0] if self.finals else self.preview
            if f is None or not hasattr(f,'audio'):return False
            now=time.monotonic()
            return max(0.,now-getattr(f,'queued_at',now)) >= max(0.,now-ready_at)/2

    def deadline_blocked(self):
        # Pending controls invalidate timer decisions, not accepted audio or MT.
        with self.condition:
            return self.done or any(not hasattr(f,'audio') for f in self.finals)

    def get(self,deadline_at=None):
        with self.condition:
            while not self.finals and self.preview is None and not self.done:
                remaining=None if deadline_at is None else deadline_at-time.monotonic()
                if remaining is not None and remaining<=0:return self.TIMEOUT
                self.condition.wait(remaining)
            if self.finals:return self.finals.popleft()
            f=self.preview;self.preview=None;return f


def segment(raw, inbox, vad, stop, log, errors):
    import numpy as np
    pending=np.empty(0,dtype=np.float32);history=deque(maxlen=6)
    frames=[];active=False;quiet=0;sid=0;rev=0;prefix=0.;last=0
    end=time.monotonic();offset=0.;settings=None;group_timing=None;group_mode='phrases'

    def publish(final, reason=""):
        nonlocal rev, last
        rev += 1
        audio = np.concatenate(frames)
        from dataclasses import replace
        frozen=replace(settings,timing=group_timing,mode=group_mode) if settings is not None else None
        accepted=inbox.put(Fragment(sid,rev,audio,prefix,end,final,frozen,offset,quiet*.032,reason))
        if accepted is False:
            stop.set()
            log.event('processing_overload',segment=sid,revision=rev,
                      start=max(0.,offset-len(audio)/16000+prefix),end=offset)
        last = len(frames)*.032
        log.event('fragment',segment=sid,revision=rev,seconds=len(audio)/16000,new_seconds=len(audio)/16000-prefix,context_seconds=prefix,final=final)

    def flush(reason="eof"):
        nonlocal frames, pending, end, offset
        # Preserve the sub-VAD-frame audio tail at pause/switch/EOF.
        if active and len(pending):
            frames.append(pending);end += len(pending)/16000;offset += len(pending)/16000
        if active and frames and sum(map(len,frames))/16000 > prefix:
            publish(True,reason)
        pending=np.empty(0,dtype=np.float32)

    try:
        while True:
            item=raw.get()
            if item is None:
                flush();break
            if isinstance(item, Boundary):
                flush(item.reason)
                inbox.put_boundary(item)
                frames=[];history.clear();active=False;quiet=0;prefix=0.;last=0
                settings=item.settings
                if item.reason=='models':
                    from .model_selection import ModelChange
                    inbox.put_model_change(ModelChange(dict(zip(('asr','translation'),settings.models))))
                if hasattr(vad,'reset'):vad.reset()
                continue
            if isinstance(item, AudioBlock):
                data,block_end,block_offset,settings=item.data,item.end,item.offset,item.settings
                if hasattr(log,'bind'):log.bind(settings.part)
            else:
                data,block_end=item;block_offset=offset+len(pending)/16000+len(data)/16000
            pending=np.concatenate([pending,data])
            while len(pending)>=512:
                frame=pending[:512];pending=pending[512:]
                end=block_end-len(pending)/16000;offset=block_offset-len(pending)/16000
                speech=vad(frame)>=.5
                if not active:
                    if not speech:history.append(frame);continue
                    active=True;frames=list(history);history.clear();sid+=1;rev=0;last=0;prefix=0
                    group_timing=getattr(settings,'timing',None)
                    group_mode=getattr(settings,'mode','phrases')
                    log.event('speech_start',segment=sid,timing=group_timing)
                frames.append(frame);quiet=0 if speech else quiet+1
                length=len(frames)*.032
                # Keep hesitations inside one revisable utterance. A short VAD pause
                # is not a sentence boundary, even after four seconds of speech.
                limit=10.
                final=quiet*.032>=(group_timing[4] if group_timing else 1.28) or length-prefix>=limit
                snapshot=group_timing[1] if group_timing else 1.
                first=group_timing[0] if group_timing else snapshot
                if final or (length-prefix>=first and length-last>=snapshot):publish(final,'silence' if quiet*.032>=(group_timing[4] if group_timing else 1.28) else 'window' if final else '')
                if final:
                    if quiet*.032 >= (group_timing[4] if group_timing else 1.28):
                        active=False;history.extend(frames[-6:]);frames=[];quiet=0
                    else:
                        # Retain acoustic context, but assign only NEW audio to the next group.
                        next_timing=getattr(settings,'timing',None)
                        next_limit=10. if group_mode=='phrases' else next_timing[3] if next_timing else (30 if group_mode=='pauses' else 10)
                        context_frames=max(16,int(min(8.,max(0.,30.-next_limit))/.032))
                        frames=frames[-context_frames:];prefix=len(frames)*.032;sid+=1;rev=0;last=prefix
                        group_timing=getattr(settings,'timing',None)
                        group_mode=getattr(settings,'mode','phrases')
                    # A technical window must keep the accumulated quiet time.
                    # Otherwise the later real silence either disappears entirely
                    # or receives an extra pause budget and leaves MT open.
    except Exception as exc:
        errors.put(exc);stop.set()
        try:log.error(exc)
        except Exception:pass
    finally:inbox.finish()


from .display import TranslationScreen, TerminalKeys


def run(args, log):
    from .runtime import run_session
    from .preferences import read as read_preferences
    if getattr(args,'publication',None) is None:
        args.publication=read_preferences(preference_folder(args.models)).get('publication','draft')
    ui=getattr(args,'ui','auto')
    if ui=='browser' or (ui=='auto' and args.command=='listen' and sys.stdout.isatty()):
        from .browser_ui import BrowserUI
        with BrowserUI(open_browser=not getattr(args,'no_open_browser',False),live=getattr(args,'publication',None) in ('revisable','draft')) as browser:
            from .model_selection import ASR,TRANSLATION
            asr_label=('Custom local ONNX Hebrew' if args.asr_backend=='fast' else 'Custom local MLX Whisper') if getattr(args,'asr_model',None) else ASR[args.asr_backend][0]
            translation_label=('Custom local MLX-LM' if getattr(args,'translation_model',None)
                               else TRANSLATION['milmmt'][0])
            browser.details(direction=args.direction,models={'Распознавание':asr_label,
                'Перевод':translation_label,'Проверка языка':'Фильтр письменности; без определения аудиоязыка'},
                topic=args.topic,session=str(log.path),
                save_raw_audio_locked=bool(getattr(args,'save_raw_audio_explicit',False)))
            current=log
            while True:
                browser.begin_session(current)
                try:
                    run_session(args,current,browser_ui=browser)
                except Exception as exc:
                    try:current.error(exc)
                    except Exception:pass
                    raise
                finally:
                    current.close()
                if not browser.wait_for_next_session(args.command=='listen' and getattr(current,'restart_safe',True)):break
                # run_session owns and closes each engine. A fresh session gets
                # fresh workers, PCM, IDs and log routing; no old queue is reused.
                previous=current
                models=getattr(args,'models',None)
                saved=read_preferences(preference_folder(models)) if models is not None else {}
                save_audio=(args.save_raw_audio if getattr(args,'save_raw_audio_explicit',False)
                            else saved.get('save_raw_audio',getattr(current,'save_audio',True)))
                current=Session(args.log_dir,args.direction,dict(log.metadata),save_audio=save_audio)
                for handler in logging.getLogger().handlers:
                    if isinstance(handler,LibraryHandler) and handler.log is previous:
                        handler.log=current
                current.event('start',command=args.command,restarted=True)
            return None
    return run_session(args, log)


def main():
    parser=argparse.ArgumentParser(description='Offline Hebrew live captions and local translation (Apple Silicon MLX/Metal only)')
    parser.add_argument('--models',type=Path,default=ROOT/'models')
    parser.add_argument('--log-dir',type=Path,default=ROOT/'logs')
    parser.add_argument('--debug-text',action='store_true',help='Legacy flag; listen/benchmark always save transcripts separately')
    sub=parser.add_subparsers(dest='command',required=True)
    setup_command=sub.add_parser('setup')
    setup_command.add_argument('--accept-model-terms',action='store_true',help='Acknowledge the separately linked model terms before download')
    model_info=sub.add_parser('model-info',help='Print pinned model sources and terms/evidence without downloading')
    sub.add_parser('languages',help='Print qualified product languages and pinned translation-model target lists')
    sub.add_parser('storage',help='Print installed-command storage paths without creating or deleting them')
    uninstall=sub.add_parser('uninstall',help='Preview complete installed-command removal without deleting anything')
    uninstall.add_argument('--dry-run',action='store_true',required=True)
    doctor=sub.add_parser('doctor');sub.add_parser('devices')
    report_command=sub.add_parser('report',help='Print a privacy-filtered bug-report metadata bundle')
    report_command.add_argument('--output',type=Path,help='Write JSON locally instead of printing it')
    listen=sub.add_parser('listen');listen.add_argument('--device',type=int)
    bench=sub.add_parser('benchmark');bench.add_argument('file',type=Path)
    for command in (doctor,listen,bench):
        command.add_argument('--asr-model',type=Path,help='Compatible local ASR directory outside the managed models folder (ONNX for fast, MLX Whisper otherwise)')
        command.add_argument('--translation-model',type=Path,help='Compatible local MLX-LM directory outside the managed models folder')
        command.add_argument('--vad-model',type=Path,help='Compatible local Silero VAD ONNX file outside the managed models folder')
    doctor.add_argument('--asr-backend',choices=('fast','turbo','multilingual'),default='turbo',help='Recognition contract for the selected ASR model')
    for command in (listen,bench):
        command.add_argument('--preview-he-en-model',type=Path,
                             help='Experimental local CTranslate2 Hebrew→English model')
        command.add_argument('--preview-en-ru-model',type=Path,
                             help='Experimental local CTranslate2 English→Russian model')
        command.add_argument('--publication',choices=('draft',),default=None)
        command.add_argument('--start-paused',action='store_true')
        command.add_argument('--no-open-browser',action='store_true')
        command.add_argument('--translation-mode',choices=('phrases',),default=None)
        command.add_argument('--asr-backend',choices=('fast','turbo','multilingual'),default='turbo')
        command.add_argument('--ui',choices=('auto','browser','terminal','plain'),default='auto')
        command.add_argument('--language',choices=('he','en','ru'),default=None)
        from .languages import target_languages
        directions=tuple(['he-'+item.code for item in target_languages()]+['ru-he'])
        command.add_argument('--direction',choices=directions,default='he-en')
        command.add_argument('--topic',choices=tuple(TOPICS),default='none')
        command.add_argument('--save-raw-audio',action=argparse.BooleanOptionalAction,default=None,
                             help='Persist source WAV files in the session archive (default: saved preference or enabled)')
    args=parser.parse_args();args.models=args.models.resolve();args.log_dir=args.log_dir.resolve()
    if args.command=='setup' and not args.accept_model_terms:
        parser.error('setup requires --accept-model-terms after you run model-info and review the linked terms')
    if args.command=='model-info':
        print_model_info()
        return 0
    if args.command=='languages':
        print_language_info()
        return 0
    if args.command in ('storage','uninstall'):
        print_installed_storage(args.models,args.log_dir,args.command=='uninstall')
        return 0
    if args.command=='report':
        rendered=json.dumps(bug_report(args.models),ensure_ascii=False,indent=2)+'\n'
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(rendered)
            print(f'Wrote privacy-filtered report: {args.output}')
        else:print(rendered,end='')
        return 0
    preview_requested=(args.command in ('listen','benchmark') and
                       bool(getattr(args,'preview_he_en_model',None) or
                            getattr(args,'preview_en_ru_model',None)))
    try:require_supported_platform(require_metal=args.command!='devices' and not preview_requested)
    except RuntimeError as exc:parser.error(str(exc))
    custom_models={}
    if args.command in ('doctor','listen','benchmark'):
        try:custom_models=validate_custom_models(args.models,args.asr_model,args.translation_model,args.vad_model,args.asr_backend)
        except ValueError as exc:parser.error(str(exc))
    if args.command in ('listen','benchmark'):
        preview_paths=(args.preview_he_en_model,args.preview_en_ru_model)
        if any(preview_paths) and not all(preview_paths):
            parser.error('Both --preview-he-en-model and --preview-en-ru-model are required')
        args.bridge_models=preview_paths if all(preview_paths) else None
        if args.bridge_models:
            if args.translation_model or args.asr_backend!='fast':
                parser.error('Bridge preview requires --asr-backend fast and no --translation-model')
            from .bridge_preview import validate_bridge_models
            try:args.bridge_models=validate_bridge_models(*args.bridge_models)
            except ValueError as exc:parser.error(str(exc))
        from .preferences import read as read_preferences
        saved_preferences=read_preferences(preference_folder(args.models))
        args.save_raw_audio_explicit=args.save_raw_audio is not None
        if args.save_raw_audio is None:args.save_raw_audio=saved_preferences.get('save_raw_audio',True)
        saved=saved_preferences.get('models',{})
        if saved and not custom_models:
            if not any(x=='--asr-backend' or x.startswith('--asr-backend=') for x in sys.argv):args.asr_backend=saved['asr']
        for notice in saved_preferences.get('preference_notices',()):print('Preference notice: '+notice,file=sys.stderr)
        if (saved_preferences.get('target_language') and
                not any(x=='--direction' or x.startswith('--direction=') for x in sys.argv)):
            from .languages import direction_for_target
            try:args.direction=direction_for_target(saved_preferences['target_language'])
            except ValueError as exc:parser.error(str(exc))
        from .languages import validate_direction
        try:validate_direction(args.direction)
        except ValueError as exc:parser.error(str(exc))
        if args.bridge_models and args.direction not in ('he-en','he-ru'):
            parser.error('Bridge preview supports --direction he-en or he-ru only')
        if args.asr_backend=='fast' and (args.language not in (None,'he') or not args.direction.startswith('he-')):
            parser.error('Fast Hebrew ASR supports Hebrew source audio only')
    active_models={'asr':dict(SPEC['asr']),'translation':dict(SPEC['translation'])}
    if getattr(args,'asr_backend','turbo')=='multilingual':
        active_models['asr']=dict(SPEC['asr_multilingual'])
    elif getattr(args,'asr_backend','turbo')=='fast':
        active_models['asr']=json.loads(Path(__file__).with_name('fast_asr_manifest.json').read_text())

    if custom_models.get('asr'):active_models['asr']={'source':'custom local ONNX' if args.asr_backend=='fast' else 'custom local MLX Whisper','contract':getattr(args,'asr_backend','turbo')}
    if custom_models.get('translation'):active_models['translation']={'source':'custom local MLX-LM','contract':'milmmt'}
    if getattr(args,'bridge_models',None):
        active_models['translation']={'source':'local HPLT Hebrew→English + tiny English→Russian',
                                      'contract':'bridge-preview-int8'}
    metadata=dict(asr_backend=getattr(args,'asr_backend','turbo'),models=active_models, python=sys.version,
                  code_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.iterdir() if p.suffix in ('.py','.html','.js','.css')},
                  versions={p:importlib.metadata.version(p) for p in ('mlx','mlx-whisper','mlx-lm','onnxruntime','sounddevice','soxr')})
    log = (Session(args.log_dir,args.direction,dict(metadata,topic=args.topic,language=args.language or args.direction[:2]),
                   save_audio=getattr(args,'save_raw_audio',True))
           if args.command in ('listen','benchmark') else Log(args.log_dir,args.debug_text))
    handler=LibraryHandler(log)
    logging.getLogger().addHandler(handler)
    logging.getLogger('transformers').propagate=True
    print(f'Session / diagnostics: {log.path}',file=sys.stderr)
    try:
        log.event('start',command=args.command,models=active_models,debug_text=args.debug_text,python=sys.version,
            versions={p:importlib.metadata.version(p) for p in ('mlx','mlx-whisper','mlx-lm','onnxruntime','sounddevice','soxr')})
        if args.command=='setup':setup(args.models)
        else:
            os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
            if args.command=='devices':
                import sounddevice as sd
                print(sd.query_devices())
            elif args.command=='doctor':
                required=set()
                if not custom_models.get('asr') and args.asr_backend!='fast':required.add('asr_multilingual' if args.asr_backend=='multilingual' else 'asr')
                if not custom_models.get('translation'):required.add('translation')
                if not custom_models.get('vad'):required.add('vad')
                if required:verify(args.models,required)
                engine=Engine(args.models,log,backend=args.asr_backend,asr_path=custom_models.get('asr'),
                              translation_path=custom_models.get('translation'))
                engine.warmup();vad=VAD(custom_models.get('vad',args.models/'silero.onnx'))
                import numpy as np
                log.event('vad_silence',probability=vad(np.zeros(512,dtype=np.float32)))
                print('Model loading, inference warmup and VAD passed. Microphone not opened.')
            else:run(args,log)
    except KeyboardInterrupt:
        try:log.event('interrupted_before_ready')
        except Exception:pass
        return 130
    except Exception as exc:
        try:log.error(exc)
        except Exception:pass
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
        print('See diagnostic log. Run in a normal macOS terminal if Metal is unavailable. No cloud fallback.',file=sys.stderr)
        return 1
    finally:
        logging.getLogger().removeHandler(handler);handler.close()
        try:log.close()
        except Exception as exc:
            print(f'Could not finalize session files: {type(exc).__name__}',file=sys.stderr)
            return 1
    return 0

if __name__=='__main__':sys.exit(main())
