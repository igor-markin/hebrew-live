package com.markin.hebrewlive

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import java.util.Locale
import kotlin.concurrent.thread

/**
 * Trial build of Hebrew Live for one Pixel: everything runs on the phone, no Mac.
 * One screen: model state, Start/Pause, live phrases (Hebrew above, Russian below), speed numbers.
 */
class MainActivity : Activity(), LiveEngine.Listener {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var store: ModelStore
    private lateinit var engine: LiveEngine
    private var translator: Translator? = null

    private lateinit var status: TextView
    private lateinit var modelLine: TextView
    private lateinit var modelButton: Button
    private lateinit var startButton: Button
    private lateinit var benchButton: Button
    private lateinit var metrics: TextView
    private lateinit var list: LinearLayout
    private lateinit var scroll: ScrollView
    private val views = HashMap<Int, Pair<TextView, TextView>>()
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        store = ModelStore(this)
        engine = LiveEngine(assets, File(getExternalFilesDir(null), "sessions"), this)
        buildUi()
        refreshModel()
        thread(name = "asr-load") {
            val ms = engine.warmUpRecognizer()
            main.post { status.text = "Распознавание загружено за ${ms} мс" }
        }
        if (store.isReady()) loadTranslator()
        main.postDelayed(object : Runnable {
            override fun run() {
                showMetrics()
                main.postDelayed(this, 1000)
            }
        }, 1000)
    }

    override fun onDestroy() {
        engine.stop()
        translator?.close()
        super.onDestroy()
    }

    // ---------- UI ----------

    private fun dp(v: Int) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

    private fun text(size: Float, color: Int = FG, bold: Boolean = false) = TextView(this).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun buildUi() {
        window.statusBarColor = BG
        window.navigationBarColor = BG
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG)
            setPadding(dp(16), dp(40), dp(16), dp(16))
        }
        root.addView(text(22f, bold = true).apply { text = "Hebrew Live · Pixel" })
        status = text(14f, MUTED).apply { text = "Загружаю распознавание…" }
        root.addView(status)

        modelLine = text(14f, MUTED)
        modelButton = button("Скачать") { onModelButton() }
        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(8), 0, dp(8))
            addView(modelLine, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(modelButton)
        })

        startButton = button("▶ Начать") { onStartPressed() }
        benchButton = button("Замер перевода") { onBench() }
        val clear = button("Очистить") {
            engine.clear()
            views.clear()
            list.removeAllViews()
        }
        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(startButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.3f))
            addView(benchButton, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1.3f))
            addView(clear, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        })

        metrics = text(12f, MUTED).apply {
            typeface = Typeface.MONOSPACE
            setPadding(0, dp(6), 0, dp(6))
        }
        root.addView(metrics)

        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        scroll = ScrollView(this).apply { addView(list) }
        root.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        setContentView(root)
    }

    private fun refreshModel() {
        when {
            translator != null -> {
                modelLine.text = "Перевод: MiLMMT-46-4B Q4_K_M, ${translator?.threads} потоков"
                modelButton.visibility = View.GONE
            }
            store.isReady() -> {
                modelLine.text = "Модель перевода на телефоне, загружаю…"
                modelButton.visibility = View.GONE
            }
            store.needsCheck() -> {
                modelLine.text = "Модель перевода скопирована, нужна проверка"
                modelButton.text = "Проверить"
                modelButton.visibility = View.VISIBLE
            }
            else -> {
                val part = store.partialBytes()
                modelLine.text = if (part > 0) "Модель перевода: скачано ${gb(part)} из ${gb(ModelStore.SIZE)}"
                else "Модели перевода нет (${gb(ModelStore.SIZE)}). Без неё будет только иврит."
                modelButton.text = if (part > 0) "Докачать" else "Скачать"
                modelButton.visibility = View.VISIBLE
            }
        }
        benchButton.isEnabled = translator != null
    }

    private fun onModelButton() {
        if (busy) {
            store.cancelled = true
            return
        }
        busy = true
        modelButton.text = "Стоп"
        val checking = store.needsCheck()
        thread(name = "model") {
            try {
                if (checking) {
                    val ok = store.verify { done, total -> main.post { modelLine.text = "Проверяю ${percent(done, total)}" } }
                    if (!ok) throw IllegalStateException("Файл модели не совпал с контрольной суммой")
                } else {
                    store.download { done, total ->
                        main.post { modelLine.text = "Скачиваю ${gb(done)} из ${gb(total)} (${percent(done, total)})" }
                    }
                }
                main.post {
                    busy = false
                    refreshModel()
                    loadTranslator()
                }
            } catch (e: Throwable) {
                main.post {
                    busy = false
                    refreshModel()
                    status.text = "Модель: ${e.message}"
                }
            }
        }
    }

    private fun loadTranslator() {
        status.text = "Загружаю перевод…"
        val threads = getPreferences(MODE_PRIVATE).getInt("threads", DEFAULT_THREADS)
        thread(name = "mt-load") {
            val t0 = SystemClock.elapsedRealtime()
            try {
                val t = Translator(store.file, threads)
                // One short call maps the weights in, so the first phrase is not slow.
                t.translate("שלום")
                val ms = SystemClock.elapsedRealtime() - t0
                main.post {
                    translator = t
                    engine.attachTranslator(t)
                    status.text = "Перевод загружен за ${"%.1f".format(Locale.US, ms / 1000.0)} с"
                    refreshModel()
                }
            } catch (e: Throwable) {
                main.post { status.text = "Перевод не загрузился: ${e.message}" }
            }
        }
    }

    private fun onStartPressed() {
        if (engine.isRecording) {
            engine.stop()
            startButton.text = "▶ Начать"
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
            return
        }
        engine.start()
        startButton.text = "⏸ Пауза"
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) onStartPressed()
        else status.text = "Нет доступа к микрофону"
    }

    /** Five fixed phrases with 4 and 6 threads; keeps the faster count. */
    private fun onBench() {
        val t = translator ?: return
        if (engine.isRecording) {
            status.text = "Сначала пауза"
            return
        }
        benchButton.isEnabled = false
        status.text = "Замер: 2 × 5 фраз…"
        thread(name = "bench") {
            val report = StringBuilder()
            var best = 0 to 0.0
            for (threads in listOf(4, 6)) {
                t.threads = threads
                t.translate(BENCH.first())
                var tokens = 0
                var genMs = 0.0
                var totalMs = 0.0
                var firstMs = 0.0
                val lines = mutableListOf<String>()
                for (phrase in BENCH) {
                    val out = t.translate(phrase)
                    val s = t.lastStats
                    tokens += s.tokens
                    genMs += s.genMs
                    totalMs += s.totalMs
                    firstMs += s.firstTokenMs
                    lines += out
                }
                val tps = tokens * 1000.0 / genMs
                if (tps > best.second) best = threads to tps
                report.append(String.format(Locale.US, "%d потоков: %.1f ток/с, первый токен %.2f с, фраза %.2f с\n",
                    threads, tps, firstMs / BENCH.size / 1000, totalMs / BENCH.size / 1000))
                if (threads == 4) lines.forEachIndexed { i, s -> report.append("  ${i + 1}. $s\n") }
                main.post { status.text = report.toString().trim() }
            }
            t.threads = best.first
            getPreferences(MODE_PRIVATE).edit().putInt("threads", best.first).apply()
            report.append("Оставил ${best.first} потоков")
            File(getExternalFilesDir(null), "bench.txt").appendText(report.toString() + "\n\n")
            main.post {
                status.text = report.toString()
                benchButton.isEnabled = true
                refreshModel()
            }
        }
    }

    private fun showMetrics() {
        val am = getSystemService(ActivityManager::class.java)
        val mem = ActivityManager.MemoryInfo().also { am.getMemoryInfo(it) }
        val pss = android.os.Debug.getPss() / 1024
        val rtf = if (engine.asrAudioSeconds > 0) engine.asrComputeSeconds / engine.asrAudioSeconds else 0.0
        val last = synchronized(engine.segments) { engine.segments.lastOrNull { it.translated } }
        val mt = last?.stats?.let {
            String.format(Locale.US, "перевод %.1f ток/с, первый токен %.2f с, после конца фразы %.2f с",
                it.tokensPerSecond, it.firstTokenMs / 1000, (last.translatedMs - last.endedMs) / 1000.0)
        } ?: "перевод —"
        metrics.text = String.format(Locale.US, "распознавание %.3f с на 1 с звука · память приложения %d МБ, свободно %.1f ГБ\n%s",
            rtf, pss, mem.availMem / 1e9, mt)
    }

    // ---------- engine callbacks (any thread) ----------

    override fun onSegment(segment: Segment) {
        main.post { render(segment) }
    }

    override fun onStatus(text: String) {
        main.post { status.text = text }
    }

    private fun render(seg: Segment) {
        val pair = views.getOrPut(seg.id) {
            val he = text(17f, MUTED).apply {
                textDirection = View.TEXT_DIRECTION_RTL
                gravity = Gravity.END
            }
            val ru = text(20f)
            val box = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(12), dp(10), dp(12), dp(10))
                setBackgroundColor(CARD)
                addView(he)
                addView(ru)
            }
            list.addView(box, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(8)
            })
            he to ru
        }
        pair.first.text = seg.hebrew
        pair.first.setTextColor(if (seg.final) FG else MUTED)
        pair.second.text = seg.russian
        // Draft (open phrase or unfinished translation) in grey, final translation in white.
        pair.second.setTextColor(if (seg.translated) FG else MUTED)
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun gb(bytes: Long) = String.format(Locale.US, "%.2f ГБ", bytes / 1e9)
    private fun percent(done: Long, total: Long) = "${done * 100 / maxOf(total, 1)} %"

    companion object {
        private val BG = Color.rgb(0x16, 0x16, 0x1d)
        private val CARD = Color.rgb(0x24, 0x24, 0x2e)
        private val FG = Color.rgb(0xf2, 0xf2, 0xf5)
        private val MUTED = Color.rgb(0x9a, 0x9a, 0xa8)
        private const val DEFAULT_THREADS = 4
        private val BENCH = listOf(
            "שלום, אני רוצה לקבוע תור לרופא שיניים ביום שלישי בשעה עשר בבוקר",
            "אני חבר במכבי, האם הטיפול מכוסה בביטוח המשלים",
            "אנא הקישו אחת כדי לדבר עם נציג",
            "המשלוח שלך יגיע מחר בין שמונה בבוקר לשתיים בצהריים",
            "אפשר לשלם בכרטיס אשראי או בהעברה בנקאית",
        )
    }
}
