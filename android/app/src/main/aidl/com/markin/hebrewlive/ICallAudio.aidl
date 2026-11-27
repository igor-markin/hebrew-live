package com.markin.hebrewlive;

// Runs in a Shizuku user service as the shell user (uid 2000), which may record call audio.
interface ICallAudio {
    // Starts recording `source` (MediaRecorder.AudioSource); returns the read end of a pipe
    // carrying 16 kHz mono 16-bit little-endian PCM, or null when recording could not start.
    ParcelFileDescriptor start(int source) = 1;
    // 1 when Android silences this recording, 0 when it is audible, -1 when not recording.
    int silenced() = 2;
    // Short description of the last start or of its error, for the status line.
    String info() = 3;
    void stop() = 4;
    // Shizuku calls this transaction code to end the service process.
    void destroy() = 16777114;
}
