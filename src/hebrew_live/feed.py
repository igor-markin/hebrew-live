"""Ordered phrase worker; only the qualified reading mode is supported."""
import re
import threading
import time
from dataclasses import dataclass

@dataclass(frozen=True)
class RetryRequest:
    fragment: object
    original_group: str

def lexical(text):
    return re.findall(r'\w+',text.casefold(),flags=re.UNICODE)

def changed(source,target,final_source,final_target):
    return lexical(source)!=lexical(final_source) or lexical(target)!=lexical(final_target)

def inference(inbox, engine, updates, stop, errors, log, cancel=None):
    cancel = cancel or threading.Event()
    f = None
    from .phrase_inference import PhraseProcessor
    from .stream import Boundary
    from .retranslation import RetranslationProcessor
    phrases=PhraseProcessor(engine,updates,log,cancel)
    draft=RetranslationProcessor(engine,updates,log,cancel)
    draft.catchup_inbox=inbox
    phrases.deadline_barrier=getattr(inbox,"deadline_blocked",lambda:False)
    age_scheduler=getattr(engine,'phrase_scheduler','batch')=='age'
    try:
        while not cancel.is_set():
            phrases.service_deadlines()
            if phrases.jobs and (not age_scheduler or not inbox.asr_due_before_translation(phrases.jobs[0].ready_at)):
                phrases.translate_next();continue
            f = inbox.get(deadline_at=phrases.next_deadline()) if phrases.budgets else inbox.get()
            if f is getattr(inbox,"TIMEOUT",False):
                phrases.service_deadlines();continue
            if f is None:
                phrases.flush('eof');draft.flush('eof');break
            if isinstance(f,Boundary):
                phrases.flush(f.reason);draft.flush(f.reason);continue
            if isinstance(f,RetryRequest):
                # A retry is an explicit, isolated model job. It gets a new
                # visible group and durable records while the original failed
                # group and the live processor state remain untouched.
                retry=RetranslationProcessor(engine,updates,log,cancel)
                retry.counter=draft.counter;retry.export_counter=draft.export_counter;retry.mt_counter=draft.mt_counter
                try:
                    retry.process(f.fragment)
                    updates.put(('retry_done',0,f.original_group))
                except Exception as exc:
                    # If ASR succeeded but MT failed, close the retry group as
                    # unavailable instead of leaving a source-only open card.
                    # The original failed group is still preserved separately.
                    try:retry.finish('retry',valid=False)
                    except Exception:pass
                    try:log.event('fragment_retry_failed',group=f.original_group,error=type(exc).__name__)
                    except Exception:pass
                    updates.put(('retry_failed',0,dict(group=f.original_group,error='Повторная обработка не удалась.')))
                finally:
                    # A failed retry can still publish an unavailable group and
                    # durable records. Keep every ID source monotonic so later
                    # retries and ordinary speech cannot reuse those identities.
                    draft.counter=max(draft.counter,retry.counter)
                    draft.export_counter=max(draft.export_counter,retry.export_counter)
                    draft.mt_counter=max(draft.mt_counter,retry.mt_counter)
                continue
            from .model_selection import ModelChange
            if isinstance(f,ModelChange):
                if cancel.is_set():break
                phrases.flush('models');draft.flush('models')
                engine.switch_models(f.selection)
                updates.put(('models_ready',0,f.selection))
                f=None
                continue
            if f.settings is None or f.settings.mode!='phrases':
                raise ValueError('Only phrases mode is supported')
            now=time.monotonic()
            log.event('asr_job_start',segment=f.id,
                      queue_wait=max(0.,now-getattr(f,'queued_at',now)),
                      capture_age=max(0.,now-f.end))
            if f.settings.publication in ('revisable','draft'):
                draft.process(f)
            else:
                phrases.process(f,defer=age_scheduler)
    except Exception as exc:
        if f is not None and hasattr(log,'note_unprocessed_fragment'):
            log.note_unprocessed_fragment(getattr(f,'fragment',f),'inference_interrupted')
        errors.put(exc);stop.set()
        try:log.error(exc)
        except Exception:pass
    finally:
        updates.put(('done',0,''))
