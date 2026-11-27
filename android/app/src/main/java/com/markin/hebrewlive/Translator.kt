package com.markin.hebrewlive

import java.io.File

data class MtStats(
    val promptTokens: Int,
    val promptMs: Double,
    val tokens: Int,
    val genMs: Double,
    val firstTokenMs: Double,
    val stop: String = "",
) {
    val tokensPerSecond: Double get() = if (genMs > 0) tokens * 1000.0 / genMs else 0.0
    val totalMs: Double get() = promptMs + genMs
}

/**
 * MiLMMT through llama.cpp. Same prompt contract as the desktop app
 * (src/hebrew_live/translation.py): raw text, no chat template, greedy, stop on <eos>/<end_of_turn>.
 * Not thread safe: one caller at a time (TranslationWorker).
 */
class Translator(model: File, threads: Int) : AutoCloseable {
    val modelName: String = model.name
    private val handle: Long = NativeTranslator.load(model.absolutePath, threads, 2048)

    init {
        require(handle != 0L) { "Не удалось загрузить модель перевода" }
    }

    var threads: Int = threads
        set(value) {
            field = value
            NativeTranslator.setThreads(handle, value)
        }

    var lastStats: MtStats = MtStats(0, 0.0, 0, 0.0, 0.0)
        private set
    /** The exact prompt and token budget of the last call, for the journal. */
    var lastPrompt: String = ""
        private set
    var lastBudget: Int = 0
        private set

    fun cancel() = NativeTranslator.cancel(handle)

    /**
     * `pairs`: (Hebrew, Russian) of the sentences right before `text`; they open both sides of the
     * prompt so the model continues its own translation, as the desktop does.
     */
    fun translate(text: String, pairs: List<Pair<String, String>> = emptyList(), onText: (String) -> Boolean = { true }): String {
        val prompt: String
        val done: String
        if (pairs.isEmpty()) {
            prompt = "Translate this from Hebrew to Russian:\nHebrew: $text\nRussian:"
            done = ""
        } else {
            val before = pairs.joinToString(" ") { it.first }
            done = pairs.joinToString(" ") { it.second }
            prompt = "Translate this from Hebrew to Russian:\nHebrew: $before $text\nRussian: $done"
        }
        // Desktop budget: 4 x source tokens + 32, between 96 and 512 (source tokens ~ chars / 3).
        val budget = (4 * (text.length / 3 + 1) + 32).coerceIn(96, 512)
        lastPrompt = prompt
        lastBudget = budget
        val raw = NativeTranslator.generate(handle, prompt, budget, ADD_BOS) { onText(it.trim()) }
        val s = NativeTranslator.lastStats(handle)
        lastStats = MtStats(s[0].toInt(), s[1], s[2].toInt(), s[3], s[4], STOPS.getOrElse(s[5].toInt()) { "?" })
        return raw.trim()
    }

    override fun close() = NativeTranslator.free(handle)

    companion object {
        /** No BOS, as the desktop MLX path (add_special_tokens=False); the host check gave the same text either way. */
        const val ADD_BOS = false
        /** Why generation ended, by the native STOP_* code. */
        val STOPS = listOf("eos", "newline", "budget", "cancel", "superseded", "error")
    }
}
