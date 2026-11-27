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

    /** Downloads Q4_K_M with resume, then checks SHA-256. Throws on failure. */
    fun download(progress: (Long, Long) -> Unit) {
        fetch(URL_STRING, SIZE, SHA256, file, progress)
        verified.writeText(SHA256)
    }

    // ---- Fast variant: every tensor Q4_0, made on the phone from the Q8_0 file ----

    val fastFile = File(folder, FAST_FILE_NAME)
    private val fastMarker = File(folder, "$FAST_FILE_NAME.done")
    private val q8File = File(folder, Q8_FILE_NAME)

    fun fastReady(): Boolean = fastFile.isFile && fastMarker.isFile

    /**
     * Downloads Q8_0 (4.13 GB, SHA-256 checked), requantizes it to Q4_0 for all tensors on the
     * phone, then deletes the Q8_0 file. `stage` gets a line for the screen.
     */
    fun prepareFast(stage: (String) -> Unit) {
        if (!(q8File.isFile && q8File.length() == Q8_SIZE)) {
            fetch(Q8_URL, Q8_SIZE, Q8_SHA256, q8File) { done, total ->
                stage(String.format(java.util.Locale.US, "Скачиваю Q8_0: %.2f из %.2f ГБ (%d %%)", done / 1e9, total / 1e9, done * 100 / total))
            }
        }
        stage("Делаю Q4_0 на телефоне…")
        val tmp = File(folder, "$FAST_FILE_NAME.tmp")
        tmp.delete()
        val t0 = System.currentTimeMillis()
        val rc = NativeTranslator.quantizeQ4_0(q8File.absolutePath, tmp.absolutePath, 6)
        if (rc != 0 || !tmp.isFile) throw IllegalStateException("Не удалось сделать Q4_0 (код $rc)")
        fastFile.delete()
        if (!tmp.renameTo(fastFile)) throw IllegalStateException("Не удалось переименовать Q4_0")
        fastMarker.writeText("from $Q8_SHA256 in ${System.currentTimeMillis() - t0} ms")
        q8File.delete()
        stage("Q4_0 готова за ${(System.currentTimeMillis() - t0) / 1000} с")
    }

    /** Resumable download into `dest` through `dest.part`, checked against `sha`. */
    private fun fetch(url: String, size: Long, sha: String, dest: File, progress: (Long, Long) -> Unit) {
        cancelled = false
        val part = File(dest.parentFile, dest.name + ".part")
        var have = if (part.isFile) part.length() else 0L
        if (have > size) {
            part.delete()
            have = 0
        }
        if (have < size) {
            val connection = (URL(url).openConnection() as HttpURLConnection).apply {
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
                            progress(have, size)
                        }
                    }
                }
            }
            connection.disconnect()
        }
        if (part.length() != size) throw IllegalStateException("Скачано ${part.length()} из $size байт")
        val digest = sha256(part, progress)
        if (digest != sha) {
            part.delete()
            throw IllegalStateException("Контрольная сумма не совпала, файл удалён")
        }
        dest.delete()
        if (!part.renameTo(dest)) throw IllegalStateException("Не удалось переименовать файл")
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

        const val Q8_FILE_NAME = "MiLMMT-46-4B-v1.0.Q8_0.gguf"
        const val Q8_SIZE = 4_130_401_312L
        const val Q8_SHA256 = "92796e263e22461c273c9f964ba4c1454d8dc764a482af60bc1ad9c269d9e7d0"
        const val Q8_URL =
            "https://huggingface.co/mradermacher/MiLMMT-46-4B-v1.0-GGUF/resolve/$REVISION/$Q8_FILE_NAME"
        const val FAST_FILE_NAME = "MiLMMT-46-4B-v1.0.Q4_0-pure.gguf"
    }
}
