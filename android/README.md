# Hebrew Live for Android (trial build)

A self-contained trial of the Hebrew Live stack on one phone (Pixel 10 Pro XL, Tensor G5,
Android 17), with no Mac in the loop. It is a separate app; the desktop code is untouched.

```text
microphone 16 kHz ─► sherpa-onnx zipformer2 (ivrit.ai, int8, CPU, 2 threads)
                        │ phrase closes on 0.8 s of silence or at 20 s
                        ▼
                  MiLMMT-46-4B Q4_K_M GGUF ─► llama.cpp (CPU, NEON dotprod/i8mm)
                        │ draft for an open phrase every 3 new words, final with the previous phrase as context
                        ▼
                  screen: Hebrew above, Russian below; numbers at the top
```

| Part | Desktop | Android trial |
| --- | --- | --- |
| Recognition | zipformer2-66m streaming, sherpa-onnx | same model and hashes, sherpa-onnx 1.12.21 AAR, bundled in the APK (72 MB) |
| Phrase boundaries | Silero VAD | sherpa-onnx endpoint rules (Silero not used yet) |
| Translation | MiLMMT-46-4B 4-bit MLX | MiLMMT-46-4B v1.0 Q4_K_M GGUF (2.49 GB), llama.cpp, same prompt and stop tokens |
| Audio | microphone, phone call via scrcpy | microphone; during a phone call the other side's voice via Shizuku |

The translation model is not in the APK. The app downloads it once from the pinned Hugging Face
revision (`ModelStore.kt`, SHA-256 checked), or it can be copied over adb:

```sh
adb push MiLMMT-46-4B-v1.0.Q4_K_M.gguf /sdcard/Android/data/com.markin.hebrewlive/files/models/
```

Then press **Проверить** in the app (it checks the SHA-256 once).

## Phone calls

During a call Android silences the microphone of every ordinary app, so the app cannot hear the call by
itself. When Shizuku is running and has allowed Hebrew Live, the app starts `CallAudioService` as a Shizuku
user service: a separate process under the shell user that records `VOICE_DOWNLINK` (the other side, as the
desktop phone mode; `VOICE_CALL` if that fails) and passes 16 kHz PCM to the app through a pipe. The app
switches to it when the phone enters a call and back to the microphone when the call ends.

## Faster model and test builds

**Сделать быструю модель Q4_0** downloads the Q8_0 GGUF (4.13 GB, SHA-256 checked) and requantizes it on the
phone to Q4_0 for every tensor (`--pure`), so that the ARM repacked kernels cover all of them; the Q8_0 file
is deleted afterwards. **Замер перевода** tries 2 to 6 threads and keeps the fastest. `-Pkleidiai=true` builds
the same app with Arm KleidiAI kernels in llama.cpp (`./scripts/fetch-deps.sh --kleidiai` first).

## Build

```sh
cd android
./scripts/fetch-deps.sh     # llama.cpp at a pinned commit, sherpa-onnx AAR, recognizer files; all SHA-256 checked
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew assembleRelease   # needs JDK 17+, Android SDK 36, NDK 28.2.13676358, CMake 3.31.6
adb install -r app/build/outputs/apk/release/app-release.apk
```

The release APK is signed with the local debug key: it is a trial for one phone, not for distribution.

## Journal for tuning

Every launch writes `files/logs/<time>.jsonl`, one JSON line per event with `t` (ms since launch) and `ev`:
`app_start` (build, KleidiAI, device, llama.cpp CPU features), `mt_loaded`, `session_start` (settings),
`input` and `silenced` (microphone or call, audio mode, Shizuku state), `audio` (each second: level, recognizer
cost), `asr_partial` and `asr_final` (text with its place in the session WAV), `mt` (each model call: exact
prompt, output, why it stopped, wait, prompt and generation times, tokens/s), `system` (every 5 s: memory,
heat status, battery temperature, CPU clocks), `bench_*`, errors and crashes. **Поделиться журналом** packs
the journals of this and the previous launch, their WAVs, `bench.txt` and the app's logcat into
`Downloads/hebrew-live-log-<time>.zip` and opens the share sheet. These files hold call audio and text: they
stay on the phone until shared and must not be committed.

## What it records

Each session writes `files/sessions/<time>.jsonl` (one line per phrase: Hebrew, Russian, phrase length,
time from end of phrase to finished translation, prompt and generation tokens and times) and
`<time>.wav` (16 kHz mono) on the phone, nothing else and nowhere else. **Замер перевода** translates five
fixed phrases with 4 and 6 threads, keeps the faster count and appends the result to `files/bench.txt`.

```sh
adb pull /sdcard/Android/data/com.markin.hebrewlive/files/sessions
adb pull /sdcard/Android/data/com.markin.hebrewlive/files/bench.txt
```

## Checked so far

- On a cloud x86 machine (4 cores), the same JNI code with the same GGUF: three test phrases translated
  as on the desktop (for example «Пожалуйста, нажмите 1, чтобы поговорить с представителем.»), 7–8 tokens/s,
  streaming, early stop and stats work; BOS on or off gave identical text.
- The recognizer settings replayed over 90 s of a recorded Maccabi call (Python sherpa-onnx): 7 phrases,
  0.056 s of compute per second of audio.
- Not yet run on the phone: speed, memory and quality on the Pixel are unmeasured.
