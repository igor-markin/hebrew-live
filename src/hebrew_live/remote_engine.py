"""Spawned MLX engine process with bounded parent-owned lifecycle."""
from __future__ import annotations

import multiprocessing
import logging
import os
import threading
import time
import traceback


STARTUP_TIMEOUT = 180.0
SHUTDOWN_GRACE = 120.0
CANCEL_GRACE = 3.0
JOIN_GRACE = 2.0
TRANSPORT_TIMEOUT = 5.0


class RemoteEngineError(RuntimeError):
    pass


class RemoteEngineInterrupted(RemoteEngineError):
    pass


class _ChildLog:
    def __init__(self, send):
        self.send = send

    def event(self, event, **data):
        self.send(("event", event, data))

    def error(self, exc):
        self.send(("event", "engine_error", {
            "type": type(exc).__name__,
            "stack": [dict(file=os.path.basename(frame.filename), line=frame.lineno,
                           function=frame.name) for frame in traceback.extract_tb(exc.__traceback__)],
        }))


def _engine_process(receive, send, config, engine_factory=None):
    """Own every native model object; communicate only serializable values."""
    engine = None;handler = None
    try:
        # Spawn starts a fresh interpreter and therefore does not inherit the
        # parent's privacy-filtering logging handler. Install the same sanitizer
        # before importing or constructing native/model libraries.
        from .session import LibraryHandler
        log = _ChildLog(send.send)
        handler = LibraryHandler(log)
        logging.getLogger().addHandler(handler)
        if engine_factory is None:
            from .cli import Engine
            engine_factory = Engine
        engine = engine_factory(config["folder"], log, config["language"],
                                backend=config["backend"], asr_path=config["asr_path"],
                                translation_path=config["translation_path"])
        engine.direction = config["direction"]
        engine.topic = config["topic"]
        engine.warmup()
        send.send(("ready", {
            key: getattr(engine, key, None) for key in
            ("backend", "translation_size", "asr_path", "custom_models")
        }))
        while True:
            request_id, method, state, args, kwargs = receive.recv()
            for key, value in state.items():
                setattr(engine, key, value)
            if method == "close":
                engine.close()
                engine = None
                send.send(("done", request_id, None, {}))
                return
            try:
                if method == "translate":
                    for item in engine.translate(*args, **kwargs):
                        send.send(("yield", request_id, item, {}))
                    value = None
                else:
                    value = getattr(engine, method)(*args, **kwargs)
                snapshot = {key: getattr(engine, key, None) for key in (
                    "backend", "translation_size", "asr_path", "custom_models",
                    "recognition_status", "recognition_issue", "recognition_words",
                    "raw_recognition", "translation_context",
                )}
                try:
                    snapshot["peak_memory"] = engine.mx.get_peak_memory()
                except Exception:
                    snapshot["peak_memory"] = 0
                send.send(("done", request_id, value, snapshot))
            except BaseException as exc:
                send.send(("failed", request_id, type(exc).__name__, str(exc),
                           traceback.format_exc(limit=12)))
    except BaseException as exc:
        try:
            send.send(("fatal", type(exc).__name__, str(exc), traceback.format_exc(limit=12)))
        except BaseException:
            pass
    finally:
        if engine is not None:
            try:
                engine.close()
            except BaseException:
                pass
        if handler is not None:
            logging.getLogger().removeHandler(handler)
            handler.close()
        receive.close();send.close()


class _Memory:
    def __init__(self, owner):
        self.owner = owner

    def get_peak_memory(self):
        return self.owner._peak_memory


class RemoteEngine:
    """Parent proxy. Durable session state and processors never leave the parent."""
    def __init__(self, folder, log, language="he", backend="turbo", asr_path=None,
                 translation_path=None, direction="he-en", topic="none", stop=None,
                 cancel=None, startup_timeout=STARTUP_TIMEOUT,
                 shutdown_grace=SHUTDOWN_GRACE, cancel_grace=CANCEL_GRACE,
                 engine_factory=None,worker_target=_engine_process):
        self.log = log
        self.language = language;self.direction = direction;self.topic = topic
        self.translation_context = []
        self.recognition_status = "empty";self.recognition_issue = None
        self.recognition_words = [];self.raw_recognition = ""
        self.recognition_guard_due = False
        self.phrase_scheduler = "batch"
        self._peak_memory = 0;self.mx = _Memory(self)
        self._stop = stop or threading.Event();self._cancel = cancel or threading.Event()
        self._shutdown_grace = shutdown_grace;self._cancel_grace = cancel_grace
        self._shutdown_started = None;self._request_id = 0;self._closed = False
        self._rpc_lock=threading.Lock()
        context = multiprocessing.get_context("spawn")
        child_receive, parent_send = context.Pipe(duplex=False)
        parent_receive, child_send = context.Pipe(duplex=False)
        self._send = parent_send;self._receive = parent_receive
        config = dict(folder=folder, language=language, backend=backend,
                      asr_path=asr_path, translation_path=translation_path,
                      direction=direction, topic=topic)
        self._process = context.Process(target=worker_target,
            args=(child_receive, child_send, config, engine_factory), name="mlx-inference")
        try:
            self._process.start();child_receive.close();child_send.close()
            message = self._receive_until(None, startup_timeout, allow_shutdown=False)
            if message[0] != "ready":
                raise RemoteEngineError(self._format_failure(message, "MLX engine startup failed"))
            for key, value in message[1].items():setattr(self, key, value)
        except BaseException:
            self._abort_process();self._close_resources();raise

    def _format_failure(self, message, prefix):
        if message and message[0] == "fatal":
            return f"{prefix}: {message[1]}: {message[2]}"
        if message and message[0] == "failed":
            return f"{prefix}: {message[2]}: {message[3]}"
        return prefix

    def _receive_until(self, request_id, timeout, allow_shutdown=True):
        deadline = time.monotonic()+timeout
        while True:
            if allow_shutdown and (self._cancel.is_set() or self._stop.is_set()):
                if self._shutdown_started is None:self._shutdown_started=time.monotonic()
                grace=self._cancel_grace if self._cancel.is_set() else self._shutdown_grace
                deadline=min(deadline,self._shutdown_started+grace)
            remaining=deadline-time.monotonic()
            if remaining<=0:
                self._abort_process()
                raise RemoteEngineInterrupted("Native inference exceeded the shutdown deadline")
            if self._receive.poll(min(.1,remaining)):
                try:message=self._receive.recv()
                except EOFError:
                    message=("fatal","ChildExit","MLX engine pipe closed","")
                if message[0]=="event":
                    try:self.log.event(message[1],**message[2])
                    except Exception:pass
                    continue
                if message[0]=="fatal":
                    self._abort_process()
                    raise RemoteEngineError(self._format_failure(message,"MLX engine process failed"))
                if request_id is None or (len(message)>1 and message[1]==request_id):return message
            if not self._process.is_alive():
                self._abort_process()
                raise RemoteEngineError("MLX engine process exited unexpectedly")

    def _bounded_send(self, payload, timeout, allow_shutdown=True):
        finished=threading.Event();failure=[]
        def send():
            try:self._send.send(payload)
            except BaseException as exc:failure.append(exc)
            finally:finished.set()
        sender=threading.Thread(target=send,name='mlx-ipc-send',daemon=True);sender.start()
        deadline=time.monotonic()+min(timeout,TRANSPORT_TIMEOUT)
        while not finished.wait(.05):
            if allow_shutdown and (self._cancel.is_set() or self._stop.is_set()):
                if self._shutdown_started is None:self._shutdown_started=time.monotonic()
                grace=self._cancel_grace if self._cancel.is_set() else self._shutdown_grace
                deadline=min(deadline,self._shutdown_started+grace)
            if not self._process.is_alive() or time.monotonic()>=deadline:
                self._abort_process();sender.join(.2)
                raise RemoteEngineInterrupted('MLX engine request transport exceeded the shutdown deadline')
        if failure:
            self._abort_process();raise RemoteEngineError('MLX engine request pipe failed') from failure[0]

    def _state(self):
        return {key:getattr(self,key) for key in (
            "language","direction","topic","translation_context","recognition_guard_due")}

    def _request_locked(self, method, *args, timeout=24*60*60, **kwargs):
        if self._closed:raise RemoteEngineInterrupted("MLX engine is closed")
        self._request_id+=1;request_id=self._request_id
        self._bounded_send((request_id,method,self._state(),args,kwargs),timeout)
        return request_id,self._receive_until(request_id,timeout)

    def _apply(self, snapshot):
        for key,value in snapshot.items():
            if key=="peak_memory":self._peak_memory=value
            else:setattr(self,key,value)

    def recognize(self, *args, **kwargs):
        with self._rpc_lock:
            _,message=self._request_locked("recognize",*args,**kwargs)
            if message[0]=="failed":raise RemoteEngineError(self._format_failure(message,"Recognition failed"))
            self._apply(message[3]);return message[2]

    def translate(self, *args, **kwargs):
        self._rpc_lock.acquire()
        request_id=None;complete=False
        try:
            request_id,message=self._request_locked("translate",*args,**kwargs)
            while True:
                if message[0]=="yield":
                    yield message[2]
                    message=self._receive_until(request_id,24*60*60)
                    continue
                if message[0]=="failed":
                    complete=True
                    raise RemoteEngineError(self._format_failure(message,"Translation failed"))
                self._apply(message[3]);complete=True;return
        finally:
            if request_id is not None and not complete and self._process.is_alive():
                # A caller may stop consuming a streaming generation. Drain its
                # messages while holding the RPC lock so none can be attributed
                # to the next session part/request. Endless native generation is
                # escalated to process termination by this bounded wait.
                try:
                    deadline=time.monotonic()+self._cancel_grace
                    terminal_drained=False
                    while time.monotonic()<deadline:
                        message=self._receive_until(request_id,max(.01,deadline-time.monotonic()))
                        if message[0] in ('done','failed'):
                            terminal_drained=True;break
                    if not terminal_drained:self._abort_process()
                except Exception:
                    self._abort_process()
            self._rpc_lock.release()

    def switch_models(self, selection):
        with self._rpc_lock:
            _,message=self._request_locked("switch_models",selection,timeout=STARTUP_TIMEOUT)
            if message[0]=="failed":raise RemoteEngineError(self._format_failure(message,"Model switch failed"))
            self._apply(message[3])

    def warmup(self):
        # Warmup is completed before the child reports ready.
        return None

    def _abort_process(self):
        process=getattr(self,"_process",None)
        if process is None:return
        if process.is_alive():process.terminate();process.join(JOIN_GRACE)
        if process.is_alive():process.kill();process.join(JOIN_GRACE)

    def interrupt(self):
        self._cancel.set();self._abort_process()

    def _close_resources(self):
        for connection in (getattr(self,'_send',None),getattr(self,'_receive',None)):
            if connection is not None:
                try:connection.close()
                except OSError:pass
        process=getattr(self,'_process',None)
        if process is not None and not process.is_alive():
            try:process.close()
            except (ValueError,OSError):pass

    def close(self):
        if self._closed:return
        self._closed=True
        process=self._process
        acquired=self._rpc_lock.acquire(timeout=JOIN_GRACE)
        try:
            if not acquired:
                self._abort_process()
            elif process.is_alive():
                try:
                    self._request_id+=1;request_id=self._request_id
                    self._bounded_send((request_id,"close",{},(),{}),JOIN_GRACE,allow_shutdown=False)
                    self._receive_until(request_id,JOIN_GRACE,allow_shutdown=False)
                except Exception:self._abort_process()
        finally:
            if acquired:self._rpc_lock.release()
        if process.is_alive():self._abort_process()
        self._close_resources()

    @property
    def alive(self):
        return not self._closed and self._process.is_alive()
