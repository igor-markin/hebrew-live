package com.markin.hebrewlive

import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.IBinder
import android.os.ParcelFileDescriptor
import android.util.Log
import rikka.shizuku.Shizuku
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * App side of call audio: Shizuku state, its permission, and the CallAudioService connection.
 * Shizuku is already running on this phone for the call recorder.
 */
class CallAudio(private val context: Context) {
    enum class State { NO_SHIZUKU, NO_PERMISSION, READY }

    @Volatile private var service: ICallAudio? = null
    @Volatile private var connected = CountDownLatch(1)
    @Volatile var lastError: String = ""
        private set

    private val args = Shizuku.UserServiceArgs(ComponentName(context.packageName, CallAudioService::class.java.name))
        .daemon(false)
        .processNameSuffix("callaudio")
        .debuggable(false)
        .version(BuildConfig.VERSION_CODE)

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            service = if (binder != null && binder.pingBinder()) ICallAudio.Stub.asInterface(binder) else null
            connected.countDown()
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            service = null
            connected = CountDownLatch(1)
        }
    }

    fun state(): State = try {
        when {
            !Shizuku.pingBinder() || Shizuku.isPreV11() -> State.NO_SHIZUKU
            Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED -> State.NO_PERMISSION
            else -> State.READY
        }
    } catch (e: Throwable) {
        State.NO_SHIZUKU
    }

    /** Shows Shizuku's own dialog; the answer comes to the listener. */
    fun requestPermission(onResult: (Boolean) -> Unit) {
        val listener = object : Shizuku.OnRequestPermissionResultListener {
            override fun onRequestPermissionResult(requestCode: Int, grantResult: Int) {
                if (requestCode != REQUEST) return
                Shizuku.removeRequestPermissionResultListener(this)
                onResult(grantResult == PackageManager.PERMISSION_GRANTED)
            }
        }
        Shizuku.addRequestPermissionResultListener(listener)
        Shizuku.requestPermission(REQUEST)
    }

    /** Starts the shell process early, so that switching to the call takes no time. Main thread. */
    fun bind() {
        if (service != null || state() != State.READY) return
        try {
            Shizuku.bindUserService(args, connection)
        } catch (e: Throwable) {
            lastError = e.toString()
            Log.w(TAG, "bindUserService", e)
        }
    }

    fun unbind() {
        try {
            Shizuku.unbindUserService(args, connection, true)
        } catch (_: Throwable) {
        }
        service = null
        connected = CountDownLatch(1)
    }

    /**
     * Opens the other side's voice of the current call (VOICE_DOWNLINK, as the desktop's phone mode),
     * falling back to both sides (VOICE_CALL). Any thread except main; waits up to 5 s for the service.
     */
    fun open(): CallStream? {
        val s = service ?: run {
            connected.await(5, TimeUnit.SECONDS)
            service
        } ?: run {
            lastError = "служба Shizuku не подключилась"
            return null
        }
        return try {
            for (source in intArrayOf(MediaRecorder.AudioSource.VOICE_DOWNLINK, MediaRecorder.AudioSource.VOICE_CALL)) {
                val fd = s.start(source)
                if (fd != null) return CallStream(s, fd, source)
                lastError = s.info()
            }
            null
        } catch (e: Throwable) {
            lastError = e.toString()
            null
        }
    }

    companion object {
        private const val TAG = "HebrewLiveCall"
        private const val REQUEST = 17
    }
}

/** PCM from the shell process; read() fills whole 100 ms blocks. */
class CallStream(private val service: ICallAudio, fd: ParcelFileDescriptor, val source: Int) : AudioInput {
    private val input = ParcelFileDescriptor.AutoCloseInputStream(fd)
    private val bytes = ByteArray(LiveEngine.RATE / 10 * 2)
    private var checked = 0L
    @Volatile private var silent = false

    override val label: String
        get() = if (source == MediaRecorder.AudioSource.VOICE_DOWNLINK) "звонок, голос собеседника" else "звонок, обе стороны"

    override fun read(out: ShortArray): Int {
        var got = 0
        while (got < bytes.size) {
            val n = input.read(bytes, got, bytes.size - got)
            if (n < 0) return if (got == 0) -1 else got / 2
            got += n
        }
        val samples = got / 2
        for (i in 0 until samples) {
            out[i] = ((bytes[2 * i].toInt() and 0xFF) or (bytes[2 * i + 1].toInt() shl 8)).toShort()
        }
        return samples
    }

    override val silenced: Boolean
        get() {
            val now = System.currentTimeMillis()
            if (now - checked > 1000) {
                checked = now
                silent = try {
                    service.silenced() == 1
                } catch (_: Throwable) {
                    false
                }
            }
            return silent
        }

    override fun close() {
        try {
            service.stop()
        } catch (_: Throwable) {
        }
        try {
            input.close()
        } catch (_: Throwable) {
        }
    }
}
