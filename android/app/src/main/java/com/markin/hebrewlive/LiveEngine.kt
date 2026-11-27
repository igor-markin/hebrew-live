package com.markin.hebrewlive

import android.annotation.SuppressLint
import android.content.res.AssetManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecordingConfiguration
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import android.util.Log
import com.k2fsa.sherpa.onnx.EndpointConfig
import com.k2fsa.sherpa.onnx.EndpointRule
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig
import org.json.JSONObject
import java.io.File
import java.util.concurrent.LinkedBlockingDeque
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** One phrase: Hebrew from the streaming recognizer, Russian from MiLMMT. */
class Segment(val id: Int, val startedMs: Long) {
    @Volatile var hebrew: String = ""
    @Volatile var russian: String = ""
    @Volatile var final: Boolean = false          // recognizer closed the phrase
    @Volatile var translated: Boolean = false     // final translation finished
    @Volatile var draftFor: String = ""           // Hebrew the visible Russian belongs to
    @Volatile var endedMs: Long = 0
    @Volatile var translatedMs: Long = 0
    @Volatile var stats: MtStats? = null
    /** Where the phrase is in the session WAV, seconds. */
    @Volatile var startAudioS: Double = 0.0
    @Volatile var endAudioS: Double = 0.0
    @Volatile var drafts: Int = 0
    /** Clauses of one recognizer utterance share a group and one card on screen. */
    @Volatile var group: Int = 0
    /** Input it was heard on; context never crosses from the microphone to a call. */
    @Volatile var source: String = ""
    /** The final translation ended on its own (not cut by a stop or the budget). */
    @Volatile var complete: Boolean = false
}

/**
 * Microphone -> sherpa-onnx zipformer2 (ivrit.ai, CPU) -> phrases -> MiLMMT (llama.cpp, CPU).
 * The recognizer's own endpoint rules close a phrase; a closed phrase is translated with the
 * previous phrase as context, an open one gets a draft translation when it has grown.
 */
class LiveEngine(
    private val assets: AssetManager,
    private val audioManager: AudioManager,
    private val callAudio: CallAudio?,
    private val sessionsDir: File,
    private val listener: Listener,
) {
    interface Listener {
        fun onSegment(segment: Segment)
        fun onStatus(text: String)
    }

    private val recognizer: OnlineRecognizer by lazy { OnlineRecognizer(assets, recognizerConfig()) }
    private var translator: Translator? = null
    private val ids = AtomicInteger()
    val segments = mutableListOf<Segment>()

    @Volatile private var recording = false
    private var audioThread: Thread? = null
    private var worker: Thread? = null
    private val finals = LinkedBlockingDeque<Segment>()
    @Volatile private var draft: Segment? = null
    @Volatile private var draftRequestedMs = 0L
    /** What the model is doing now: "draft", "final" or null. */
    @Volatile private var running: String? = null
    private val wake = Object()

    /** Loudness of the last 100 ms, dBFS (-90 = silence). */
    @Volatile var levelDb = -90.0
    /** Android silences the current input (another app took the microphone, or a call started). */
    @Volatile var silenced = false
    /** What is being listened to now: the microphone or the call. */
    @Volatile var source = ""

    // Recognizer cost: seconds of compute per second of audio.
    @Volatile var asrAudioSeconds = 0.0
    @Volatile var asrComputeSeconds = 0.0
    private var log: java.io.Writer? = null
    private var wav: WavWriter? = null

    fun attachTranslator(t: Translator?) {
        translator = t
        Trace.event("translator", "model" to t?.modelName, "threads" to t?.threads)
        ensureWorker()
    }

    val isRecording: Boolean get() = recording

    fun warmUpRecognizer(): Long {
        val t0 = SystemClock.elapsedRealtime()
        recognizer.hashCode()
        return SystemClock.elapsedRealtime() - t0
    }

    @SuppressLint("MissingPermission")
    fun start() {
        if (recording) return
        recording = true
        sessionsDir.mkdirs()
        val name = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.US).format(java.util.Date())
        log = File(sessionsDir, "$name.jsonl").bufferedWriter()
        wav = WavWriter(File(sessionsDir, "$name.wav"), RATE)
        sessionName = name
        Trace.event("session_start", "session" to name, "wav" to "$name.wav",
            "model" to translator?.modelName, "threads" to translator?.threads,
            "audio_mode" to audioManager.mode, "shizuku" to callAudio?.state()?.name,
            "config" to mapOf(
                "rate" to RATE, "draft_step_words" to DRAFT_STEP_WORDS, "asr_threads" to 2,
                "clause_min_words" to CLAUSE_MIN_WORDS, "clause_force_words" to CLAUSE_FORCE_WORDS,
                "endpoint_rule1" to "after 8 s, silence 0.3 s", "endpoint_rule2" to "silence 0.8 s after speech",
                "endpoint_rule3" to "phrase 20 s", "context_gap_s" to 20,
            ))
        Trace.system("session_start")
        ensureWorker()
        audioThread = Thread({ audioLoop() }, "asr").apply { start() }
    }

    fun stop() {
        recording = false
        audioThread?.join(3000)
        audioThread = null
        Trace.event("session_stop", "session" to sessionName, "audio_s" to samplesTotal.toDouble() / RATE,
            "asr_rtf" to if (asrAudioSeconds > 0) asrComputeSeconds / asrAudioSeconds else null,
            "phrases" to synchronized(segments) { segments.size })
        wav?.close()
        wav = null
    }

    fun clear() {
        synchronized(segments) { segments.clear() }
    }

    private fun recognizerConfig() = OnlineRecognizerConfig(
        featConfig = FeatureConfig(sampleRate = RATE, featureDim = 80, dither = 0f),
        modelConfig = OnlineModelConfig(
            transducer = OnlineTransducerModelConfig(
                encoder = "asr/encoder.int8.onnx",
                decoder = "asr/decoder.int8.onnx",
                joiner = "asr/joiner.int8.onnx",
            ),
            tokens = "asr/tokens.txt",
            numThreads = 2,
            modelType = "zipformer2",
            provider = "cpu",
        ),
        endpointConfig = EndpointConfig(
            // An automatic voice reads long sentences with short pauses: after 8 s a pause of 0.3 s closes the phrase
            // (replayed on a recorded call: splits between clauses, no cut words; 0.3 s after 6 s cut a word).
            rule1 = EndpointRule(true, 0.3f, 8f),
            // A pause of 0.8 s after speech closes the phrase; 20 s is the longest phrase, as the desktop's draft limit.
            rule2 = EndpointRule(true, 0.8f, 0f),
            rule3 = EndpointRule(false, 0f, 20f),
        ),
        enableEndpoint = true,
        decodingMethod = "greedy_search",
    )

    private fun inCall() = audioManager.mode == AudioManager.MODE_IN_CALL

    private fun openMic(): AudioInput? = MicInput(audioManager).takeIf { it.ok } ?: run {
        listener.onStatus("Микрофон недоступен")
        null
    }

    /** During a phone call Android silences the microphone of ordinary apps: switch to call audio via Shizuku and back. */
    private fun switchIfNeeded(input: AudioInput, now: Long): AudioInput {
        if (now - lastSwitchCheck < 1000) return input
        lastSwitchCheck = now
        val calls = callAudio
        if (input is MicInput && inCall()) {
            if (calls == null || calls.state() != CallAudio.State.READY) {
                if (!warnedNoShizuku) {
                    warnedNoShizuku = true
                    traceInput(input, "call without Shizuku")
                    listener.onStatus("⚠ Идёт звонок: Android заглушил микрофон. Для звука звонка нужен Shizuku с разрешением для Hebrew Live.")
                }
                return input
            }
            if (now - lastCallAttempt < 10_000) return input
            lastCallAttempt = now
            val call = calls.open()
            if (call == null) {
                traceInput(input, "call audio failed", calls.lastError)
                listener.onStatus("⚠ Идёт звонок, а звук звонка не открылся: ${calls.lastError}")
                return input
            }
            input.close()
            traceInput(call, "call started")
            listener.onStatus("Звонок: слушаю ${call.label}")
            return call
        }
        if (input is CallStream && !inCall()) {
            input.close()
            warnedNoShizuku = false
            val mic = openMic() ?: return input
            traceInput(mic, "call ended")
            listener.onStatus("Звонок закончился, слушаю микрофон")
            return mic
        }
        return input
    }

    private var sessionName = ""
    /** Samples written to the session WAV so far: the audio clock of every event. */
    @Volatile private var samplesTotal = 0L
    private val audioS: Double get() = samplesTotal.toDouble() / RATE

    private fun traceInput(input: AudioInput, reason: String, error: String? = null) {
        Trace.event("input", "source" to input.label, "reason" to reason, "audio_s" to audioS,
            "audio_mode" to audioManager.mode, "shizuku" to callAudio?.state()?.name,
            "silenced" to input.silenced, "error" to error)
    }

    private var lastSwitchCheck = 0L
    private var lastCallAttempt = 0L
    private var warnedNoShizuku = false

    private fun audioLoop() {
        lastSwitchCheck = 0L
        lastCallAttempt = 0L
        warnedNoShizuku = false
        samplesTotal = 0L
        var input: AudioInput = openMic() ?: run {
            recording = false
            return
        }
        val stream = recognizer.createStream("")
        val chunk = ShortArray(RATE / 10)
        current = null
        committed = 0
        prevTail = ""
        group = 0
        var wasSilenced = false
        listener.onStatus("Слушаю ${input.label}")
        traceInput(input, "start")
        // Per-second audio summary for the journal.
        var secSamples = 0
        var secEnergy = 0.0
        var secPeakDb = -90.0
        var secCompute = 0.0
        var lastSystem = SystemClock.elapsedRealtime()
        try {
            while (recording) {
                input = switchIfNeeded(input, SystemClock.elapsedRealtime())
                val n = input.read(chunk)
                if (n < 0) {
                    // The call stream ended (the shell process stopped): back to the microphone.
                    input.close()
                    Trace.event("input_ended", "source" to input.label, "audio_s" to audioS)
                    input = openMic() ?: break
                    traceInput(input, "call stream ended")
                    listener.onStatus("Звук звонка прервался, слушаю микрофон")
                    continue
                }
                silenced = input.silenced
                if (silenced != wasSilenced) {
                    wasSilenced = silenced
                    Trace.event("silenced", "value" to silenced, "source" to input.label, "audio_s" to audioS, "audio_mode" to audioManager.mode)
                    if (input is MicInput && !inCall()) listener.onStatus(
                        if (silenced) "⚠ Микрофон забрало другое приложение. Распознавание слышит тишину."
                        else "Слушаю ${input.label}"
                    )
                }
                if (n == 0) continue
                wav?.write(chunk, n)
                samplesTotal += n
                val samples = FloatArray(n) { chunk[it] / 32768f }
                var energy = 0.0
                for (v in samples) energy += v * v
                levelDb = 10 * Math.log10(energy / n + 1e-9)
                secSamples += n
                secEnergy += energy
                secPeakDb = maxOf(secPeakDb, levelDb)
                source = input.label
                val t0 = System.nanoTime()
                stream.acceptWaveform(samples, RATE)
                while (recognizer.isReady(stream)) recognizer.decode(stream)
                val text = recognizer.getResult(stream).text.trim()
                val endpoint = recognizer.isEndpoint(stream)
                val compute = (System.nanoTime() - t0) / 1e9
                asrComputeSeconds += compute
                asrAudioSeconds += n.toDouble() / RATE
                secCompute += compute
                if (secSamples >= RATE) {
                    Trace.event("audio", "audio_s" to audioS, "source" to input.label,
                        "mean_db" to 10 * Math.log10(secEnergy / secSamples + 1e-9), "peak_db" to secPeakDb,
                        "asr_rtf" to secCompute * RATE / secSamples, "silenced" to silenced)
                    secSamples = 0
                    secEnergy = 0.0
                    secPeakDb = -90.0
                    secCompute = 0.0
                }
                val nowMs = SystemClock.elapsedRealtime()
                if (nowMs - lastSystem >= 5000) {
                    lastSystem = nowMs
                    Trace.system("listening")
                }

                onText(text, input.label, n)
                if (endpoint) {
                    endUtterance(text, "endpoint")
                    recognizer.reset(stream)
                }
            }
            stream.inputFinished()
            while (recognizer.isReady(stream)) recognizer.decode(stream)
            endUtterance(recognizer.getResult(stream).text.trim(), "pause pressed")
        } finally {
            input.close()
            silenced = false
            levelDb = -90.0
            source = ""
            stream.release()
            listener.onStatus("Пауза")
        }
    }

    // ---------- one utterance of the recognizer, cut into clauses ----------
    // The recognizer's text grows until an endpoint. Translating the whole of a 15-20 s sentence again
    // at its end took 10-15 s and rewrote the screen many times. So a clause that has stopped changing
    // is closed as its own phrase as soon as the next word starts: it is translated once, with the
    // previous clause as context, and the open tail stays short.

    private var current: Segment? = null
    private var lastDraftWords = 0
    /** Characters of the recognizer's text already given to closed clauses. */
    private var committed = 0
    /** The open tail at the previous update: a clause is cut only where it did not change. */
    private var prevTail = ""
    /** The utterance the clauses belong to; the screen shows one card per utterance. */
    private var group = 0

    private fun tailStart(text: String): Int {
        val base = minOf(committed, text.length)
        return base + (text.length - base - text.substring(base).trimStart().length)
    }

    private fun onText(text: String, source: String, n: Int) {
        var start = tailStart(text)
        var tail = text.substring(start)
        if (tail.isEmpty() || tail == current?.hebrew) return
        val cut = clauseCut(tail, prevTail)
        if (cut > 0) {
            val seg = openSegment(source, n)
            seg.hebrew = tail.substring(0, cut).trim()
            Trace.event("asr_partial", "seg" to seg.id, "audio_s" to audioS, "he" to seg.hebrew, "clause" to true)
            close(seg, "clause")
            current = null
            committed = start + cut
            start = tailStart(text)
            tail = text.substring(start)
            if (tail.isEmpty()) {
                prevTail = ""
                return
            }
        }
        prevTail = tail
        val seg = openSegment(source, n)
        seg.hebrew = tail
        Trace.event("asr_partial", "seg" to seg.id, "audio_s" to audioS, "he" to tail)
        listener.onSegment(seg)
        val words = tail.split(' ').size
        if (words >= lastDraftWords + DRAFT_STEP_WORDS) {
            lastDraftWords = words
            requestDraft(seg)
        }
    }

    private fun openSegment(source: String, n: Int): Segment = current ?: Segment(ids.incrementAndGet(), SystemClock.elapsedRealtime()).also {
        current = it
        lastDraftWords = 0
        if (group == 0) group = it.id
        it.group = group
        it.startAudioS = audioS - n.toDouble() / RATE
        it.source = source
        synchronized(segments) { segments.add(it) }
    }

    /** The recognizer closed the utterance: the open tail becomes the last clause. */
    private fun endUtterance(text: String, reason: String) {
        val tail = text.substring(tailStart(text)).trim()
        val seg = current
        if (seg != null) {
            if (tail.isNotEmpty()) seg.hebrew = tail
            close(seg, reason)
        } else if (tail.isNotEmpty() && group != 0) {
            Trace.event("asr_tail_dropped", "he" to tail)
        }
        current = null
        committed = 0
        prevTail = ""
        group = 0
    }

    /**
     * Where a clause can be closed in the open tail, or 0. Only words that were already there at the
     * previous update count (the recognizer updates about every 1.3 s, and its last word may be cut).
     * Among them: the last punctuation with at least [CLAUSE_MIN_WORDS] words before it; or, in a long
     * run without punctuation, all of them once there are [CLAUSE_FORCE_WORDS].
     */
    private fun clauseCut(tail: String, prev: String): Int {
        val words = Regex("\\S+").findAll(tail).toList()
        val before = prev.split(' ').filter { it.isNotEmpty() }
        var stable = 0
        while (stable < words.size && stable < before.size && words[stable].value == before[stable]) stable++
        stable = minOf(stable, before.size - 1, words.size - 1)
        if (stable < CLAUSE_MIN_WORDS) return 0
        for (i in stable - 1 downTo CLAUSE_MIN_WORDS - 1) {
            if (words[i].value.last() in ",.?!;:") return words[i].range.last + 1
        }
        if (stable >= CLAUSE_FORCE_WORDS) return words[stable - 1].range.last + 1
        return 0
    }

    private fun close(seg: Segment, reason: String) {
        seg.final = true
        seg.endedMs = SystemClock.elapsedRealtime()
        seg.endAudioS = audioS
        Trace.event("asr_final", "seg" to seg.id, "reason" to reason, "he" to seg.hebrew,
            "start_audio_s" to seg.startAudioS, "end_audio_s" to seg.endAudioS,
            "speech_ms" to seg.endedMs - seg.startedMs, "queue" to finals.size,
            "mt_running" to running)
        listener.onSegment(seg)
        if (translator == null) {
            writeLog(seg)
            return
        }
        finals.add(seg)
        // A running draft yields to the closed phrase; a running final translation is never cut.
        if (running == "draft") translator?.cancel()
        synchronized(wake) { wake.notifyAll() }
    }

    private fun requestDraft(seg: Segment) {
        if (translator == null) return
        draft = seg
        draftRequestedMs = SystemClock.elapsedRealtime()
        synchronized(wake) { wake.notifyAll() }
    }

    private fun ensureWorker() {
        if (worker?.isAlive == true) return
        worker = Thread({ workerLoop() }, "mt").apply {
            isDaemon = true
            start()
        }
    }

    private fun workerLoop() {
        while (true) {
            val t = translator
            // Without a model the closed phrases wait in the queue; they are not dropped.
            val seg = if (t != null) finals.poll(0, TimeUnit.MILLISECONDS) else null
            if (t == null || (seg == null && draft == null)) {
                synchronized(wake) { wake.wait(500) }
                continue
            }
            try {
                running = if (seg != null) "final" else "draft"
                if (seg != null) translateFinal(t, seg) else translateDraft(t)
            } catch (e: Throwable) {
                Log.e(TAG, "translation failed", e)
                Trace.error("mt_error", e)
                listener.onStatus("Ошибка перевода: ${e.message}")
            } finally {
                running = null
            }
        }
    }

    private fun translateDraft(t: Translator) {
        val seg = draft ?: return
        draft = null
        if (seg.final) return
        val source = seg.hebrew
        val pairs = contextFor(seg)
        val startMs = SystemClock.elapsedRealtime()
        val waitMs = startMs - draftRequestedMs
        seg.drafts++
        val out = t.translate(source, pairs) { partial ->
            if (seg.final || finals.isNotEmpty()) return@translate false
            seg.russian = partial
            seg.draftFor = source
            listener.onSegment(seg)
            true
        }
        val shown = !seg.final && finals.isEmpty() && out.isNotEmpty()
        if (shown) {
            seg.russian = out
            seg.draftFor = source
            listener.onSegment(seg)
        }
        traceMt(t, "draft", seg, source, pairs, out, waitMs, shown)
    }

    private fun translateFinal(t: Translator, seg: Segment) {
        val source = seg.hebrew
        val pairs = contextFor(seg)
        val waitMs = SystemClock.elapsedRealtime() - seg.endedMs
        val out = t.translate(source, pairs) { partial ->
            seg.russian = partial
            seg.draftFor = source
            listener.onSegment(seg)
            true
        }
        seg.russian = out
        seg.draftFor = source
        seg.translated = true
        seg.translatedMs = SystemClock.elapsedRealtime()
        seg.stats = t.lastStats
        seg.complete = t.lastStats.complete && out.isNotEmpty()
        listener.onSegment(seg)
        writeLog(seg)
        traceMt(t, "final", seg, source, pairs, out, waitMs, true)
    }

    /** One line per model call: the exact prompt, what came out, why it stopped and every timing. */
    private fun traceMt(t: Translator, kind: String, seg: Segment, source: String, pairs: List<Pair<String, String>>,
                        out: String, waitMs: Long, shown: Boolean) {
        val s = t.lastStats
        Trace.event("mt", "kind" to kind, "seg" to seg.id, "he" to source, "ru" to out,
            "shown" to shown, "stop" to s.stop, "context_pairs" to pairs.size,
            "prompt" to t.lastPrompt, "budget" to t.lastBudget, "reused_tokens" to s.reusedTokens, "threads" to t.threads, "model" to t.modelName,
            "wait_ms" to waitMs, "prompt_tokens" to s.promptTokens, "prompt_ms" to s.promptMs,
            "tokens" to s.tokens, "gen_ms" to s.genMs, "first_token_ms" to s.firstTokenMs,
            "tok_per_s" to s.tokensPerSecond,
            "after_phrase_end_ms" to if (seg.final && seg.endedMs > 0) SystemClock.elapsedRealtime() - seg.endedMs else null,
            "queue" to finals.size, "draft_no" to seg.drafts)
    }

    /** The previous translated phrase, if it ended within 20 s, as in the desktop's pairs. */
    private fun contextFor(seg: Segment): List<Pair<String, String>> {
        val previous = synchronized(segments) {
            val i = segments.indexOf(seg)
            if (i > 0) segments[i - 1] else null
        } ?: return emptyList()
        // A cut or empty translation would make the model finish the previous sentence inside this one.
        if (!previous.translated || !previous.complete || previous.russian.isEmpty()) return emptyList()
        if (previous.source != seg.source) return emptyList()
        if (seg.startedMs - previous.endedMs > 20_000) return emptyList()
        return listOf(previous.hebrew to previous.russian)
    }

    private fun writeLog(seg: Segment) {
        val s = seg.stats
        val line = JSONObject().apply {
            put("id", seg.id)
            put("he", seg.hebrew)
            put("ru", seg.russian)
            put("speech_ms", seg.endedMs - seg.startedMs)
            put("mt_after_end_ms", if (seg.translatedMs > 0) seg.translatedMs - seg.endedMs else JSONObject.NULL)
            if (s != null) {
                put("prompt_tokens", s.promptTokens)
                put("prompt_ms", s.promptMs)
                put("tokens", s.tokens)
                put("gen_ms", s.genMs)
                put("first_token_ms", s.firstTokenMs)
                put("tok_per_s", s.tokensPerSecond)
            }
            put("asr_rtf", if (asrAudioSeconds > 0) asrComputeSeconds / asrAudioSeconds else JSONObject.NULL)
        }
        synchronized(this) {
            log?.apply {
                write(line.toString())
                write("\n")
                flush()
            }
        }
    }

    companion object {
        const val RATE = 16000
        const val DRAFT_STEP_WORDS = 3
        /** A clause closed at punctuation has at least this many words. */
        const val CLAUSE_MIN_WORDS = 3
        /** Without punctuation, this many settled words are closed as a clause. */
        const val CLAUSE_FORCE_WORDS = 10
        private const val TAG = "HebrewLive"
    }
}

/** 16 kHz mono 16-bit audio: the microphone or, during a call, the call via Shizuku. */
interface AudioInput {
    val label: String
    val silenced: Boolean
    /** Fills `out` with up to 100 ms of samples; -1 when the input has ended. */
    fun read(out: ShortArray): Int
    fun close()
}

@SuppressLint("MissingPermission")
class MicInput(private val audioManager: AudioManager) : AudioInput {
    private val record = AudioRecord(
        MediaRecorder.AudioSource.VOICE_RECOGNITION, LiveEngine.RATE,
        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
        maxOf(AudioRecord.getMinBufferSize(LiveEngine.RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT), LiveEngine.RATE * 2),
    )
    val ok = record.state == AudioRecord.STATE_INITIALIZED
    private val session = record.audioSessionId
    @Volatile override var silenced = false
        private set
    private val watcher = object : AudioManager.AudioRecordingCallback() {
        override fun onRecordingConfigChanged(configs: MutableList<AudioRecordingConfiguration>) {
            configs.firstOrNull { it.clientAudioSessionId == session }?.let { silenced = it.isClientSilenced }
        }
    }

    init {
        if (ok) {
            audioManager.registerAudioRecordingCallback(watcher, null)
            record.startRecording()
            silenced = audioManager.activeRecordingConfigurations.firstOrNull { it.clientAudioSessionId == session }?.isClientSilenced == true
        } else {
            record.release()
        }
    }

    override val label = "микрофон"

    override fun read(out: ShortArray): Int = record.read(out, 0, out.size).let { if (it < 0) 0 else it }

    private var closed = false

    override fun close() {
        if (!ok || closed) return
        closed = true
        audioManager.unregisterAudioRecordingCallback(watcher)
        try {
            record.stop()
        } catch (_: Throwable) {
        }
        record.release()
    }
}

/** 16-bit mono WAV of the session, for checking recognition later. */
class WavWriter(private val file: File, private val rate: Int) {
    private val out = java.io.RandomAccessFile(file, "rw").apply {
        setLength(0)
        write(ByteArray(44))
    }
    private var bytes = 0L
    private val buffer = java.nio.ByteBuffer.allocate(RATE_CHUNK * 2).order(java.nio.ByteOrder.LITTLE_ENDIAN)

    @Synchronized
    fun write(samples: ShortArray, n: Int) {
        buffer.clear()
        for (i in 0 until n) buffer.putShort(samples[i])
        out.write(buffer.array(), 0, n * 2)
        bytes += n * 2
    }

    @Synchronized
    fun close() {
        val h = java.nio.ByteBuffer.allocate(44).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        h.put("RIFF".toByteArray()).putInt((36 + bytes).toInt()).put("WAVE".toByteArray())
        h.put("fmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate * 2)
        h.putShort(2).putShort(16).put("data".toByteArray()).putInt(bytes.toInt())
        out.seek(0)
        out.write(h.array())
        out.close()
    }

    companion object {
        private const val RATE_CHUNK = 16000
    }
}
