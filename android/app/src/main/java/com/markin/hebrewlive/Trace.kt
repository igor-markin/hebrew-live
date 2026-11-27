package com.markin.hebrewlive

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.os.Debug
import android.os.PowerManager
import android.os.Process
import android.os.SystemClock
import android.provider.MediaStore
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.Writer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * Detailed journal for tuning: one JSON line per event, for the whole app launch
 * (files/logs/<launch>.jsonl). Each line has `t` (ms since launch), `at` (local time) and `ev`.
 * It holds what was heard and translated, so it stays on the phone until the owner shares it.
 * No serial numbers, addresses or account data are written.
 */
object Trace {
    private const val TAG = "HebrewLiveTrace"
    private const val KEEP_FILES = 30
    private val t0 = SystemClock.elapsedRealtime()
    private val stamp = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US)
    private var out: Writer? = null
    private lateinit var app: Context
    lateinit var dir: File
        private set
    var file: File? = null
        private set

    fun init(context: Context) {
        if (out != null) return
        app = context.applicationContext
        dir = File(app.getExternalFilesDir(null), "logs").apply { mkdirs() }
        dir.listFiles { f -> f.name.endsWith(".jsonl") }?.sortedBy { it.name }?.dropLast(KEEP_FILES - 1)?.forEach { it.delete() }
        val name = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        file = File(dir, "$name.jsonl")
        out = file!!.bufferedWriter()
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, e ->
            error("crash", e, "thread" to thread.name)
            previous?.uncaughtException(thread, e)
        }
        event("app_start",
            "version" to BuildConfig.VERSION_NAME,
            "version_code" to BuildConfig.VERSION_CODE,
            "kleidiai" to BuildConfig.KLEIDIAI,
            "device" to "${Build.MANUFACTURER} ${Build.MODEL}",
            "soc" to "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}",
            "android" to Build.VERSION.RELEASE,
            "sdk" to Build.VERSION.SDK_INT,
            "cores" to Runtime.getRuntime().availableProcessors(),
            "core_max_mhz" to coreMhz("cpuinfo_max_freq"),
            "llama_system" to try { NativeTranslator.systemInfo() } catch (e: Throwable) { e.toString() },
            "pid" to Process.myPid(),
        )
    }

    fun event(ev: String, vararg fields: Pair<String, Any?>) {
        val line = JSONObject()
        line.put("t", SystemClock.elapsedRealtime() - t0)
        line.put("at", synchronized(stamp) { stamp.format(Date()) })
        line.put("ev", ev)
        for ((k, v) in fields) line.put(k, json(v))
        synchronized(this) {
            try {
                out?.apply {
                    write(line.toString())
                    write("\n")
                    flush()
                }
            } catch (e: Throwable) {
                Log.w(TAG, "write", e)
            }
        }
    }

    fun error(ev: String, e: Throwable, vararg fields: Pair<String, Any?>) {
        event(ev, *fields, "error" to e.toString(), "stack" to Log.getStackTraceString(e).take(4000))
    }

    /** Memory, heat and CPU clocks: written every few seconds while listening, and at key moments. */
    fun system(reason: String) {
        val am = app.getSystemService(android.app.ActivityManager::class.java)
        val mem = android.app.ActivityManager.MemoryInfo().also { am.getMemoryInfo(it) }
        val pm = app.getSystemService(PowerManager::class.java)
        val battery = app.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        event("system",
            "reason" to reason,
            "pss_mb" to Debug.getPss() / 1024,
            "avail_mb" to mem.availMem / (1024 * 1024),
            "low_memory" to mem.lowMemory,
            "thermal_status" to pm.currentThermalStatus,
            "thermal_headroom_10s" to pm.getThermalHeadroom(10).toDouble().takeIf { !it.isNaN() },
            "battery_c" to battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1)?.let { it / 10.0 },
            "battery_pct" to battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1),
            "charging" to ((battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0) > 0),
            "core_mhz" to coreMhz("scaling_cur_freq"),
        )
    }

    private fun coreMhz(name: String): List<Int?> = (0 until Runtime.getRuntime().availableProcessors()).map { i ->
        try {
            File("/sys/devices/system/cpu/cpu$i/cpufreq/$name").readText().trim().toInt() / 1000
        } catch (_: Throwable) {
            null
        }
    }

    private fun json(v: Any?): Any = when (v) {
        null -> JSONObject.NULL
        is Double -> if (v.isNaN() || v.isInfinite()) JSONObject.NULL else Math.round(v * 1000) / 1000.0
        is Float -> json(v.toDouble())
        is Map<*, *> -> JSONObject().also { o -> v.forEach { (k, x) -> o.put(k.toString(), json(x)) } }
        is Pair<*, *> -> JSONArray().put(json(v.first)).put(json(v.second))
        is Iterable<*> -> JSONArray().also { a -> v.forEach { a.put(json(it)) } }
        is Array<*> -> JSONArray().also { a -> v.forEach { a.put(json(it)) } }
        else -> v
    }

    /**
     * Packs the journals of this and the previous launch, the session recordings they mention,
     * bench.txt and the app's own logcat into Downloads/hebrew-live-log-<time>.zip; returns its Uri.
     */
    fun pack(sessionsDir: File): Pair<Uri, Long> {
        event("share")
        system("share")
        val journals = dir.listFiles { f -> f.name.endsWith(".jsonl") }?.sortedBy { it.name }?.takeLast(2).orEmpty()
        val text = journals.joinToString("\n") { it.readText() }
        val wavs = sessionsDir.listFiles { f -> f.name.endsWith(".wav") && text.contains(f.name) }?.sortedBy { it.name }.orEmpty()
        val sessionLogs = sessionsDir.listFiles { f -> f.name.endsWith(".jsonl") && wavs.any { w -> w.nameWithoutExtension == f.nameWithoutExtension } }.orEmpty()
        val logcat = try {
            val p = ProcessBuilder("logcat", "-d", "-v", "threadtime", "--pid=${Process.myPid()}").redirectErrorStream(true).start()
            p.inputStream.bufferedReader().readText().also { p.waitFor() }
        } catch (e: Throwable) {
            "logcat: $e"
        }
        val name = "hebrew-live-log-" + SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date()) + ".zip"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, "application/zip")
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val resolver = app.contentResolver
        val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: throw IllegalStateException("Downloads недоступны")
        var size = 0L
        resolver.openOutputStream(uri)!!.use { stream ->
            ZipOutputStream(stream).use { zip ->
                fun add(entry: String, file: File) {
                    zip.putNextEntry(ZipEntry(entry))
                    file.inputStream().use { it.copyTo(zip) }
                    zip.closeEntry()
                    size += file.length()
                }
                journals.forEach { add("logs/${it.name}", it) }
                sessionLogs.forEach { add("sessions/${it.name}", it) }
                wavs.forEach { add("sessions/${it.name}", it) }
                File(app.getExternalFilesDir(null), "bench.txt").takeIf { it.exists() }?.let { add("bench.txt", it) }
                zip.putNextEntry(ZipEntry("logcat.txt"))
                zip.write(logcat.toByteArray())
                zip.closeEntry()
            }
        }
        resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
        return uri to size
    }
}
