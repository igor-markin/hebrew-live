package com.markin.hebrewlive

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * The translation model lives outside the APK, in the app's own external folder, so it can be
 * downloaded by the app or copied with `adb push` (android/README.md).
 */
class ModelStore(context: Context) {
    val folder: File = File(context.getExternalFilesDir(null), "models").apply { mkdirs() }
    val file = File(folder, FILE_NAME)
    private val part = File(folder, "$FILE_NAME.part")
    private val verified = File(folder, "$FILE_NAME.verified")

    @Volatile
    var cancelled = false

    fun isReady(): Boolean = file.isFile && file.length() == SIZE && verified.isFile

    /** A copied file of the right size that has not been checked yet. */
    fun needsCheck(): Boolean = file.isFile && file.length() == SIZE && !verified.isFile

    fun partialBytes(): Long = if (part.isFile) part.length() else 0L

    /** Checks the SHA-256 of a present file. `progress(done, total)`. */
    fun verify(progress: (Long, Long) -> Unit): Boolean {
        val ok = sha256(file, progress) == SHA256
        if (ok) verified.writeText(SHA256) else verified.delete()
        return ok
    }

    /** Downloads with resume, then checks SHA-256. Throws on failure. */
    fun download(progress: (Long, Long) -> Unit) {
        cancelled = false
        var have = partialBytes()
        if (have > SIZE) {
            part.delete()
            have = 0
        }
        if (have < SIZE) {
            val connection = (URL(URL_STRING).openConnection() as HttpURLConnection).apply {
                connectTimeout = 30_000
                readTimeout = 60_000
                instanceFollowRedirects = true
                if (have > 0) setRequestProperty("Range", "bytes=$have-")
            }
            val code = connection.responseCode
            if (code != 200 && code != 206) throw IllegalStateException("Сервер ответил $code")
            if (code == 200) have = 0  // no resume support: start over
            connection.inputStream.use { input ->
                FileOutputStream(part, have > 0).use { output ->
                    val buffer = ByteArray(1 shl 20)
                    var last = 0L
                    while (true) {
                        if (cancelled) throw InterruptedException("Остановлено")
                        val read = input.read(buffer)
                        if (read < 0) break
                        output.write(buffer, 0, read)
                        have += read
                        if (have - last > 8L shl 20) {
                            last = have
                            progress(have, SIZE)
                        }
                    }
                }
            }
            connection.disconnect()
        }
        if (part.length() != SIZE) throw IllegalStateException("Скачано ${part.length()} из $SIZE байт")
        val digest = sha256(part, progress)
        if (digest != SHA256) {
            part.delete()
            throw IllegalStateException("Контрольная сумма не совпала, файл удалён")
        }
        file.delete()
        if (!part.renameTo(file)) throw IllegalStateException("Не удалось переименовать файл")
        verified.writeText(SHA256)
    }

    private fun sha256(f: File, progress: (Long, Long) -> Unit): String {
        val md = MessageDigest.getInstance("SHA-256")
        RandomAccessFile(f, "r").use { raf ->
            val buffer = ByteArray(4 shl 20)
            var done = 0L
            while (true) {
                val read = raf.read(buffer)
                if (read < 0) break
                md.update(buffer, 0, read)
                done += read
                if (done % (256L shl 20) < buffer.size) progress(done, f.length())
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        const val FILE_NAME = "MiLMMT-46-4B-v1.0.Q4_K_M.gguf"
        const val SIZE = 2_489_893_152L
        const val SHA256 = "25424cbb5423afaa22b1b53bfb3d8aa116cfd84b5f8dcfa82363bfb3c4221ddf"
        // Pinned revision of mradermacher/MiLMMT-46-4B-v1.0-GGUF (static quants of xiaomi-research/MiLMMT-46-4B-v1.0).
        const val REVISION = "3d05b58ace3d89a89af0574cdc49c84567f33969"
        const val URL_STRING =
            "https://huggingface.co/mradermacher/MiLMMT-46-4B-v1.0-GGUF/resolve/$REVISION/$FILE_NAME"
    }
}
