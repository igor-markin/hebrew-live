package com.markin.hebrewlive

import android.annotation.SuppressLint
import android.app.Application
import android.app.Instrumentation
import android.content.AttributionSource
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.os.Binder
import android.os.ParcelFileDescriptor
import android.os.Process
import android.util.Log
import java.io.IOException
import java.io.OutputStream

/**
 * Shizuku user service: lives in a separate process started as the shell user, the same way
 * scrcpy and call recorders get call audio without root. An ordinary app is silenced by Android
 * during a phone call; the shell user is not. The audio goes to the app through a pipe.
 */
class CallAudioService() : ICallAudio.Stub() {
    /** Shizuku 13+ prefers the constructor with a Context. */
    constructor(@Suppress("UNUSED_PARAMETER") context: Context) : this()

    private var record: AudioRecord? = null
    private var pump: Thread? = null
    @Volatile private var running = false
    @Volatile private var info = "не запускалась"

    override fun start(source: Int): ParcelFileDescriptor? = withShellIdentity {
        synchronized(this) {
            stopLocked()
            ShellEnv.prepare()
            val opened = open(source) ?: return@withShellIdentity null
            val (rec, rate) = opened
            val pipe = ParcelFileDescriptor.createPipe()
            try {
                rec.startRecording()
            } catch (e: Throwable) {
                info = "startRecording: $e"
                rec.release()
                pipe.forEach { it.close() }
                return@withShellIdentity null
            }
            record = rec
            running = true
            info = "uid ${Process.myUid()}, источник $source, $rate Гц"
            val out = ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])
            pump = Thread({ pumpLoop(rec, rate, out) }, "call-audio").apply { start() }
            pipe[0]
        }
    }

    override fun silenced(): Int = withShellIdentity {
        val rec = record ?: return@withShellIdentity -1
        when (rec.activeRecordingConfiguration?.isClientSilenced) {
            true -> 1
            false -> 0
            null -> -1
        }
    }

    override fun info(): String = info

    override fun stop() = withShellIdentity { synchronized(this) { stopLocked() } }

    override fun destroy() {
        stop()
        System.exit(0)
    }

    private fun stopLocked() {
        running = false
        pump?.join(1000)
        pump = null
        record = null
    }

    @SuppressLint("MissingPermission")
    private fun open(source: Int): Pair<AudioRecord, Int>? {
        for (rate in intArrayOf(LiveEngine.RATE, 48000)) {
            try {
                val format = AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(rate)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build()
                val min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
                val rec = AudioRecord.Builder()
                    .setContext(ShellContext.instance)
                    .setAudioSource(source)
                    .setAudioFormat(format)
                    .setBufferSizeInBytes(maxOf(min, rate * 2))
                    .build()
                if (rec.state == AudioRecord.STATE_INITIALIZED) return rec to rate
                rec.release()
                info = "источник $source, $rate Гц: не инициализирован"
            } catch (e: Throwable) {
                Log.w(TAG, "open source $source at $rate Hz", e)
                info = "источник $source, $rate Гц: $e"
            }
        }
        return null
    }

    /** Reads 100 ms blocks, brings 48 kHz down to 16 kHz by averaging threes, writes PCM to the pipe. */
    private fun pumpLoop(rec: AudioRecord, rate: Int, out: OutputStream) {
        val factor = rate / LiveEngine.RATE
        val input = ShortArray(rate / 10)
        val bytes = ByteArray(input.size / factor * 2)
        try {
            while (running) {
                val n = rec.read(input, 0, input.size)
                if (n <= 0) {
                    if (n < 0) {
                        info = "read: $n"
                        break
                    }
                    continue
                }
                val m = n / factor
                for (i in 0 until m) {
                    var sum = 0
                    for (k in 0 until factor) sum += input[i * factor + k]
                    val v = sum / factor
                    bytes[2 * i] = (v and 0xFF).toByte()
                    bytes[2 * i + 1] = ((v shr 8) and 0xFF).toByte()
                }
                out.write(bytes, 0, m * 2)
            }
        } catch (_: IOException) {
            // The app closed its end: it stopped listening.
        } finally {
            running = false
            try {
                rec.stop()
            } catch (_: Throwable) {
            }
            rec.release()
            try {
                out.close()
            } catch (_: IOException) {
            }
        }
    }

    private inline fun <T> withShellIdentity(block: () -> T): T {
        val token = Binder.clearCallingIdentity()
        try {
            return block()
        } finally {
            Binder.restoreCallingIdentity(token)
        }
    }

    companion object {
        private const val TAG = "HebrewLiveCall"
    }
}

/**
 * Makes the shell process look enough like an app for AudioRecord, as scrcpy does
 * (Workarounds.java): bound application info and an initial Application for com.android.shell.
 */
@SuppressLint("PrivateApi", "DiscouragedPrivateApi", "SoonBlockedPrivateApi")
internal object ShellEnv {
    private val activityThreadClass by lazy { Class.forName("android.app.ActivityThread") }
    private val activityThread: Any by lazy {
        activityThreadClass.getDeclaredMethod("currentActivityThread").invoke(null)
            ?: activityThreadClass.getDeclaredMethod("systemMain").invoke(null)!!
    }
    val systemContext: Context by lazy {
        activityThreadClass.getDeclaredMethod("getSystemContext").invoke(activityThread) as Context
    }
    @Volatile private var prepared = false

    @Synchronized
    fun prepare() {
        if (prepared) return
        prepared = true
        attempt("configuration controller") {
            val controllerClass = Class.forName("android.app.ConfigurationController")
            val internalClass = Class.forName("android.app.ActivityThreadInternal")
            val controller = controllerClass.getDeclaredConstructor(internalClass).apply { isAccessible = true }
                .newInstance(activityThread)
            field("mConfigurationController").set(activityThread, controller)
        }
        attempt("bound application") {
            val bindDataClass = Class.forName("android.app.ActivityThread\$AppBindData")
            val bindData = bindDataClass.getDeclaredConstructor().apply { isAccessible = true }.newInstance()
            val appInfo = ApplicationInfo().apply { packageName = ShellContext.PACKAGE }
            bindDataClass.getDeclaredField("appInfo").apply { isAccessible = true }.set(bindData, appInfo)
            field("mBoundApplication").set(activityThread, bindData)
        }
        attempt("initial application") {
            val app = Instrumentation.newApplication(Application::class.java, ShellContext.instance)
            field("mInitialApplication").set(activityThread, app)
        }
    }

    private fun field(name: String) = activityThreadClass.getDeclaredField(name).apply { isAccessible = true }

    private inline fun attempt(what: String, block: () -> Unit) {
        try {
            block()
        } catch (e: Throwable) {
            Log.w("HebrewLiveCall", "shell workaround '$what' failed", e)
        }
    }
}

/** The system context presented as com.android.shell, uid 2000, for AudioRecord's permission checks. */
internal class ShellContext private constructor() : ContextWrapper(ShellEnv.systemContext) {
    override fun getPackageName(): String = PACKAGE
    override fun getOpPackageName(): String = PACKAGE
    override fun getAttributionSource(): AttributionSource =
        AttributionSource.Builder(Process.SHELL_UID).setPackageName(PACKAGE).build()
    override fun getDeviceId(): Int = Context.DEVICE_ID_DEFAULT
    override fun getApplicationContext(): Context = this

    companion object {
        const val PACKAGE = "com.android.shell"
        val instance: ShellContext by lazy { ShellContext() }
    }
}
