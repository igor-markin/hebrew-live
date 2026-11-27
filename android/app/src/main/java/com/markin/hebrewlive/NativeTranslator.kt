package com.markin.hebrewlive

/** JNI bridge to llama.cpp (app/src/main/cpp/translator_jni.cpp). */
object NativeTranslator {
    init {
        System.loadLibrary("hebrewlive")
    }

    fun interface TextListener {
        /** Whole translation so far; return false to stop. */
        fun onText(text: String): Boolean
    }

    external fun systemInfo(): String
    external fun load(path: String, threads: Int, nCtx: Int): Long
    external fun setThreads(handle: Long, threads: Int)
    external fun cancel(handle: Long)
    /** prompt tokens, prompt ms, generated tokens, generation ms, first token ms */
    external fun lastStats(handle: Long): DoubleArray
    external fun generate(handle: Long, prompt: String, maxTokens: Int, addBos: Boolean, listener: TextListener): String
    external fun free(handle: Long)
}
