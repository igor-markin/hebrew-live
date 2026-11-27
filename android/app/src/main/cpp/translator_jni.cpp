// Native MiLMMT translator for the Android trial build: llama.cpp on the CPU, greedy decoding,
// the same raw prompt and stop tokens as the desktop contract (src/hebrew_live/translation.py).
#include <jni.h>
#include <android/log.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <string>
#include <vector>

#include "llama.h"

#define TAG "HebrewLiveMT"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

namespace {

struct Translator {
    llama_model *model = nullptr;
    llama_context *ctx = nullptr;
    llama_sampler *sampler = nullptr;
    const llama_vocab *vocab = nullptr;
    std::atomic<bool> cancel{false};
    // Stats of the last call: prompt tokens, prompt ms, generated tokens, generation ms, first token ms.
    double stats[5] = {0, 0, 0, 0, 0};
};

double now_ms() {
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}

void log_callback(ggml_log_level level, const char *text, void *) {
    if (level >= GGML_LOG_LEVEL_WARN) __android_log_print(ANDROID_LOG_WARN, TAG, "%s", text);
}

// Length of the longest prefix of `s` that ends on a complete UTF-8 character.
size_t complete_utf8(const std::string &s) {
    size_t n = s.size();
    size_t i = n;
    int back = 0;
    while (i > 0 && back < 4) {
        unsigned char c = static_cast<unsigned char>(s[i - 1]);
        if ((c & 0xC0) != 0x80) {
            int need = (c & 0x80) == 0 ? 1 : (c & 0xE0) == 0xC0 ? 2 : (c & 0xF0) == 0xE0 ? 3 : 4;
            return (back + 1 >= need) ? n : i - 1;
        }
        --i;
        ++back;
    }
    return n;
}

jstring to_jstring(JNIEnv *env, const std::string &s) {
    // NewStringUTF needs modified UTF-8; go through a byte array and String(bytes, "UTF-8").
    jbyteArray bytes = env->NewByteArray(static_cast<jsize>(s.size()));
    env->SetByteArrayRegion(bytes, 0, static_cast<jsize>(s.size()), reinterpret_cast<const jbyte *>(s.data()));
    jclass string_class = env->FindClass("java/lang/String");
    jmethodID ctor = env->GetMethodID(string_class, "<init>", "([BLjava/lang/String;)V");
    jstring charset = env->NewStringUTF("UTF-8");
    auto result = static_cast<jstring>(env->NewObject(string_class, ctor, bytes, charset));
    env->DeleteLocalRef(bytes);
    env->DeleteLocalRef(charset);
    env->DeleteLocalRef(string_class);
    return result;
}

std::string from_jstring(JNIEnv *env, jstring s) {
    jclass string_class = env->GetObjectClass(s);
    jmethodID get_bytes = env->GetMethodID(string_class, "getBytes", "(Ljava/lang/String;)[B");
    jstring charset = env->NewStringUTF("UTF-8");
    auto bytes = static_cast<jbyteArray>(env->CallObjectMethod(s, get_bytes, charset));
    jsize len = env->GetArrayLength(bytes);
    std::string out(static_cast<size_t>(len), '\0');
    env->GetByteArrayRegion(bytes, 0, len, reinterpret_cast<jbyte *>(out.data()));
    env->DeleteLocalRef(bytes);
    env->DeleteLocalRef(charset);
    env->DeleteLocalRef(string_class);
    return out;
}

}  // namespace

extern "C" {

JNIEXPORT jstring JNICALL
Java_com_markin_hebrewlive_NativeTranslator_systemInfo(JNIEnv *env, jobject) {
    return env->NewStringUTF(llama_print_system_info());
}

JNIEXPORT jlong JNICALL
Java_com_markin_hebrewlive_NativeTranslator_load(JNIEnv *env, jobject, jstring jpath, jint threads, jint n_ctx) {
    llama_log_set(log_callback, nullptr);
    llama_backend_init();
    std::string path = from_jstring(env, jpath);

    llama_model_params mparams = llama_model_default_params();
    auto *t = new Translator();
    t->model = llama_model_load_from_file(path.c_str(), mparams);
    if (!t->model) {
        LOGE("model load failed: %s", path.c_str());
        delete t;
        return 0;
    }
    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx = static_cast<uint32_t>(n_ctx);
    cparams.n_batch = 512;
    cparams.n_ubatch = 512;
    cparams.n_threads = threads;
    cparams.n_threads_batch = threads;
    cparams.no_perf = true;
    t->ctx = llama_init_from_model(t->model, cparams);
    if (!t->ctx) {
        LOGE("context init failed");
        llama_model_free(t->model);
        delete t;
        return 0;
    }
    t->vocab = llama_model_get_vocab(t->model);
    t->sampler = llama_sampler_init_greedy();
    LOGI("loaded %s, threads %d, ctx %d", path.c_str(), threads, n_ctx);
    return reinterpret_cast<jlong>(t);
}

JNIEXPORT void JNICALL
Java_com_markin_hebrewlive_NativeTranslator_setThreads(JNIEnv *, jobject, jlong handle, jint threads) {
    auto *t = reinterpret_cast<Translator *>(handle);
    if (t) llama_set_n_threads(t->ctx, threads, threads);
}

JNIEXPORT void JNICALL
Java_com_markin_hebrewlive_NativeTranslator_cancel(JNIEnv *, jobject, jlong handle) {
    auto *t = reinterpret_cast<Translator *>(handle);
    if (t) t->cancel = true;
}

JNIEXPORT jdoubleArray JNICALL
Java_com_markin_hebrewlive_NativeTranslator_lastStats(JNIEnv *env, jobject, jlong handle) {
    auto *t = reinterpret_cast<Translator *>(handle);
    jdoubleArray out = env->NewDoubleArray(5);
    if (t) env->SetDoubleArrayRegion(out, 0, 5, t->stats);
    return out;
}

// Translates `prompt` (already formatted). `listener.onText(String)` gets the whole text so far
// after each complete character; returning false stops generation.
JNIEXPORT jstring JNICALL
Java_com_markin_hebrewlive_NativeTranslator_generate(JNIEnv *env, jobject, jlong handle, jstring jprompt,
                                                     jint max_tokens, jboolean add_bos, jobject listener) {
    auto *t = reinterpret_cast<Translator *>(handle);
    if (!t) return env->NewStringUTF("");
    t->cancel = false;
    std::memset(t->stats, 0, sizeof(t->stats));

    jclass listener_class = env->GetObjectClass(listener);
    jmethodID on_text = env->GetMethodID(listener_class, "onText", "(Ljava/lang/String;)Z");

    const double t0 = now_ms();
    std::string prompt = from_jstring(env, jprompt);
    int n = -llama_tokenize(t->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), nullptr, 0, add_bos, true);
    std::vector<llama_token> tokens(static_cast<size_t>(n));
    llama_tokenize(t->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()), tokens.data(), n, add_bos, true);

    const int n_ctx = static_cast<int>(llama_n_ctx(t->ctx));
    if (n + max_tokens > n_ctx) max_tokens = std::max(16, n_ctx - n);
    if (n >= n_ctx) {
        LOGE("prompt too long: %d tokens", n);
        return env->NewStringUTF("");
    }

    llama_memory_clear(llama_get_memory(t->ctx), true);
    llama_sampler_reset(t->sampler);
    for (int i = 0; i < n; i += 512) {
        int len = std::min(512, n - i);
        if (llama_decode(t->ctx, llama_batch_get_one(tokens.data() + i, len)) != 0) {
            LOGE("prompt decode failed");
            return env->NewStringUTF("");
        }
    }
    const double t1 = now_ms();
    t->stats[0] = n;
    t->stats[1] = t1 - t0;

    std::string text;
    size_t emitted = 0;
    int generated = 0;
    char piece[256];
    for (; generated < max_tokens; ++generated) {
        if (t->cancel) break;
        llama_token id = llama_sampler_sample(t->sampler, t->ctx, -1);
        // MiLMMT stops on <eos> (1) and <end_of_turn> (106), as in translation.configure.
        if (id == 1 || id == 106 || llama_vocab_is_eog(t->vocab, id)) break;
        int len = llama_token_to_piece(t->vocab, id, piece, sizeof(piece), 0, false);
        if (len > 0) text.append(piece, static_cast<size_t>(len));
        if (generated == 0) t->stats[4] = now_ms() - t0;
        // One translation is one line; the model would otherwise start a new "Hebrew:" turn.
        size_t newline = text.find('\n');
        if (newline != std::string::npos) {
            text.resize(newline);
            ++generated;
            break;
        }
        size_t complete = complete_utf8(text);
        if (complete > emitted) {
            emitted = complete;
            jstring partial = to_jstring(env, text.substr(0, complete));
            jboolean keep = env->CallBooleanMethod(listener, on_text, partial);
            env->DeleteLocalRef(partial);
            if (!keep) {
                ++generated;
                break;
            }
        }
        if (llama_decode(t->ctx, llama_batch_get_one(&id, 1)) != 0) {
            LOGE("token decode failed");
            break;
        }
    }
    t->stats[2] = generated;
    t->stats[3] = now_ms() - t1;
    env->DeleteLocalRef(listener_class);
    return to_jstring(env, text.substr(0, complete_utf8(text)));
}

// Requantizes a GGUF to Q4_0 for every tensor (--pure): the ARM repack path covers all of them,
// including the tied output/embedding matrix, which is Q6_K in Q4_K_M. Returns 0 on success.
JNIEXPORT jint JNICALL
Java_com_markin_hebrewlive_NativeTranslator_quantizeQ4_10(JNIEnv *env, jobject, jstring jin, jstring jout, jint threads) {
    llama_log_set(log_callback, nullptr);
    llama_backend_init();
    std::string in = from_jstring(env, jin);
    std::string out = from_jstring(env, jout);
    llama_model_quantize_params params = llama_model_quantize_default_params();
    params.nthread = threads;
    params.ftype = LLAMA_FTYPE_MOSTLY_Q4_0;
    params.allow_requantize = true;
    params.pure = true;
    const double t0 = now_ms();
    uint32_t rc = llama_model_quantize(in.c_str(), out.c_str(), &params);
    LOGI("quantize %s -> %s: %u in %.0f ms", in.c_str(), out.c_str(), rc, now_ms() - t0);
    return static_cast<jint>(rc);
}

JNIEXPORT void JNICALL
Java_com_markin_hebrewlive_NativeTranslator_free(JNIEnv *, jobject, jlong handle) {
    auto *t = reinterpret_cast<Translator *>(handle);
    if (!t) return;
    llama_sampler_free(t->sampler);
    llama_free(t->ctx);
    llama_model_free(t->model);
    delete t;
}

}  // extern "C"
