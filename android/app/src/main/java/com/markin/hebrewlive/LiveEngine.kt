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
        ensureWorker()
        audioThread = Thread({ audioLoop() }, "asr").apply { start() }
    }

    fun stop() {
        recording = false
        audioThread?.join(3000)
        audioThread = null
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
            rule1 = EndpointRule(false, 2.4f, 0f),
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
                    listener.onStatus("⚠ Идёт звонок: Android заглушил микрофон. Для звука звонка нужен Shizuku с разрешением для Hebrew Live.")
                }
                return input
            }
            if (now - lastCallAttempt < 10_000) return input
            lastCallAttempt = now
            val call = calls.open()
            if (call == null) {
                listener.onStatus("⚠ Идёт звонок, а звук звонка не открылся: ${calls.lastError}")
                return input
            }
            input.close()
            listener.onStatus("Звонок: слушаю ${call.label}")
            return call
        }
        if (input is CallStream && !inCall()) {
            input.close()
            warnedNoShizuku = false
            val mic = openMic() ?: return input
            listener.onStatus("Звонок закончился, слушаю микрофон")
            return mic
        }
        return input
    }

    private var lastSwitchCheck = 0L
    private var lastCallAttempt = 0L
    private var warnedNoShizuku = false

    private fun audioLoop() {
        lastSwitchCheck = 0L
        lastCallAttempt = 0L
        warnedNoShizuku = false
        var input: AudioInput = openMic() ?: run {
            recording = false
            return
        }
        val stream = recognizer.createStream("")
        val chunk = ShortArray(RATE / 10)
        var current: Segment? = null
        var lastDraftWords = 0
        var wasSilenced = false
        listener.onStatus("Слушаю ${input.label}")
        try {
            while (recording) {
                input = switchIfNeeded(input, SystemClock.elapsedRealtime())
                val n = input.read(chunk)
                if (n < 0) {
                    // The call stream ended (the shell process stopped): back to the microphone.
                    input.close()
                    input = openMic() ?: break
                    listener.onStatus("Звук звонка прервался, слушаю микрофон")
                    continue
                }
                silenced = input.silenced
                if (silenced != wasSilenced) {
                    wasSilenced = silenced
                    if (input is MicInput && !inCall()) listener.onStatus(
                        if (silenced) "⚠ Микрофон забрало другое приложение. Распознавание слышит тишину."
                        else "Слушаю ${input.label}"
                    )
                }
                if (n == 0) continue
                wav?.write(chunk, n)
                val samples = FloatArray(n) { chunk[it] / 32768f }
                var energy = 0.0
                for (v in samples) energy += v * v
                levelDb = 10 * Math.log10(energy / n + 1e-9)
                source = input.label
                val t0 = System.nanoTime()
                stream.acceptWaveform(samples, RATE)
                while (recognizer.isReady(stream)) recognizer.decode(stream)
                val text = recognizer.getResult(stream).text.trim()
                val endpoint = recognizer.isEndpoint(stream)
                asrComputeSeconds += (System.nanoTime() - t0) / 1e9
                asrAudioSeconds += n.toDouble() / RATE

                if (text.isNotEmpty()) {
                    val seg = current ?: Segment(ids.incrementAndGet(), SystemClock.elapsedRealtime()).also {
                        current = it
                        lastDraftWords = 0
                        synchronized(segments) { segments.add(it) }
                    }
                    if (text != seg.hebrew) {
                        seg.hebrew = text
                        listener.onSegment(seg)
                        val words = text.split(' ').size
                        if (words >= lastDraftWords + DRAFT_STEP_WORDS) {
                            lastDraftWords = words
                            requestDraft(seg)
                        }
                    }
                }
                if (endpoint) {
                    current?.let { close(it) }
                    current = null
                    recognizer.reset(stream)
                }
            }
            stream.inputFinished()
            while (recognizer.isReady(stream)) recognizer.decode(stream)
            current?.let { seg ->
                val text = recognizer.getResult(stream).text.trim()
                if (text.isNotEmpty()) seg.hebrew = text
                close(seg)
            }
        } finally {
            input.close()
            silenced = false
            levelDb = -90.0
            source = ""
            stream.release()
            listener.onStatus("Пауза")
        }
    }

    private fun close(seg: Segment) {
        seg.final = true
        seg.endedMs = SystemClock.elapsedRealtime()
        listener.onSegment(seg)
        if (translator == null) {
            writeLog(seg)
            return
        }
        finals.add(seg)
        translator?.cancel()  // a running draft yields to the closed phrase
        synchronized(wake) { wake.notifyAll() }
    }

    private fun requestDraft(seg: Segment) {
        if (translator == null) return
        draft = seg
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
            val seg = finals.poll(0, TimeUnit.MILLISECONDS)
            if (t == null || (seg == null && draft == null)) {
                synchronized(wake) { wake.wait(500) }
                continue
            }
            try {
                if (seg != null) translateFinal(t, seg) else translateDraft(t)
            } catch (e: Throwable) {
                Log.e(TAG, "translation failed", e)
                listener.onStatus("Ошибка перевода: ${e.message}")
            }
        }
    }

    private fun translateDraft(t: Translator) {
        val seg = draft ?: return
        draft = null
        if (seg.final) return
        val source = seg.hebrew
        val pairs = contextFor(seg)
        val out = t.translate(source, pairs) { partial ->
            if (seg.final || finals.isNotEmpty()) return@translate false
            seg.russian = partial
            seg.draftFor = source
            listener.onSegment(seg)
            true
        }
        if (!seg.final && finals.isEmpty() && out.isNotEmpty()) {
            seg.russian = out
            seg.draftFor = source
            listener.onSegment(seg)
        }
    }

    private fun translateFinal(t: Translator, seg: Segment) {
        val source = seg.hebrew
        val pairs = contextFor(seg)
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
        listener.onSegment(seg)
        writeLog(seg)
    }

    /** The previous translated phrase, if it ended within 20 s, as in the desktop's pairs. */
    private fun contextFor(seg: Segment): List<Pair<String, String>> {
        val previous = synchronized(segments) {
            val i = segments.indexOf(seg)
            if (i > 0) segments[i - 1] else null
        } ?: return emptyList()
        if (!previous.translated || previous.russian.isEmpty()) return emptyList()
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
