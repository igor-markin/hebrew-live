cmake_minimum_required(VERSION 3.22)
project("hebrewlive" C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT DEFINED LLAMA_SRC)
    message(FATAL_ERROR "LLAMA_SRC is not set; run android/scripts/fetch-deps.sh")
endif()

add_subdirectory(${LLAMA_SRC} build-llama)

add_library(hebrewlive SHARED translator_jni.cpp)
target_compile_options(hebrewlive PRIVATE -Wno-deprecated-declarations)
target_include_directories(hebrewlive PRIVATE ${LLAMA_SRC}/include ${LLAMA_SRC}/ggml/include)
target_link_libraries(hebrewlive llama ggml android log)
