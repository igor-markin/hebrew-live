plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// llama.cpp checkout used for the native translator (scripts/fetch-deps.sh pins the commit).
val llamaSrc = rootProject.file("third_party/llama.cpp").absolutePath
// -Pkleidiai=true: Arm KleidiAI micro-kernels for Q4_0/Q8_0 (sources from scripts/fetch-deps.sh --kleidiai).
val kleidiai = (project.findProperty("kleidiai") as String?) == "true"
val kleidiaiSrc = rootProject.file("third_party/kleidiai").absolutePath

android {
    namespace = "com.markin.hebrewlive"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    buildFeatures {
        aidl = true
        buildConfig = true
    }

    defaultConfig {
        applicationId = "com.markin.hebrewlive"
        minSdk = 33
        targetSdk = 36
        versionCode = 3
        versionName = "0.2.0-pixel" + if (kleidiai) "-kleidiai" else ""
        ndk { abiFilters += listOf("arm64-v8a") }
        externalNativeBuild {
            cmake {
                arguments += listOf(
                    "-DCMAKE_BUILD_TYPE=Release",
                    "-DLLAMA_SRC=$llamaSrc",
                    "-DBUILD_SHARED_LIBS=OFF",
                    "-DLLAMA_BUILD_COMMON=OFF",
                    "-DLLAMA_BUILD_TESTS=OFF",
                    "-DLLAMA_BUILD_EXAMPLES=OFF",
                    "-DLLAMA_BUILD_TOOLS=OFF",
                    "-DLLAMA_BUILD_SERVER=OFF",
                    "-DLLAMA_OPENSSL=OFF",
                    "-DLLAMA_CURL=OFF",
                    "-DGGML_NATIVE=OFF",
                    "-DGGML_OPENMP=OFF",
                    "-DGGML_LLAMAFILE=OFF",
                    "-DGGML_CPU_KLEIDIAI=" + if (kleidiai) "ON" else "OFF",
                    "-DFETCHCONTENT_SOURCE_DIR_KLEIDIAI=$kleidiaiSrc",
                    // Tensor G5 cores are Armv9.2; NEON dotprod/i8mm kernels (no SVE) are the well-tested path.
                    "-DGGML_CPU_ARM_ARCH=armv8.6-a+dotprod+i8mm+fp16",
                )
                cppFlags += "-O3"
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // Trial build for one phone: signed with the debug key so adb can install it.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    externalNativeBuild {
        cmake {
            path("src/main/cpp/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    androidResources {
        // Keep the recognizer files uncompressed so sherpa-onnx can read them from assets quickly.
        noCompress += listOf("onnx", "txt")
    }

    lint {
        checkReleaseBuilds = false
    }

    packaging {
        jniLibs { useLegacyPackaging = false }
    }
}

kotlin {
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}

dependencies {
    implementation(files("libs/sherpa-onnx-1.12.21.aar"))
    // Call audio through Shizuku (already running on the phone for the call recorder).
    implementation("dev.rikka.shizuku:api:13.1.5")
    implementation("dev.rikka.shizuku:provider:13.1.5")
}
