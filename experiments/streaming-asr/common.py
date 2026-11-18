"""Shared helpers for the streaming-ASR experiment: where the data live, how audio is loaded and levelled.

Nothing here imports the app. Data and outputs stay outside the repository:
  REFS = ~/Library/Caches/hebrew-live-refs            (eval sets, models, venvs)
  OUT  = REFS / 'streaming-asr-out'                    (hypotheses and traces; they hold speech text)
"""
import csv
import json
from pathlib import Path

import numpy as np

REFS = Path.home() / 'Library' / 'Caches' / 'hebrew-live-refs'
OUT = REFS / 'streaming-asr-out'
MODEL = REFS / 'zipformer2-66m-streaming-he'
IVRIT = {'d1': REFS / 'ivrit-eval-d1' / 'extracted', 'whatsapp': REFS / 'ivrit-eval-whatsapp' / 'extracted'}
FLEURS_TSV = REFS / 'fleurs-he_il' / 'data' / 'he_il' / 'test.tsv'
FLEURS_AUDIO = REFS / 'fleurs-he_il-test' / 'test'
RATE = 16000


def references(name):
    """{key: reference text} for 'd1', 'whatsapp' or 'fleurs'."""
    if name == 'fleurs':
        rows = csv.reader(FLEURS_TSV.open(encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE)
        return {row[1]: row[2] for row in rows}
    return json.loads((IVRIT[name] / 'texts.json').read_text(encoding='utf-8'))


def keys(name, limit=None):
    if name == 'fleurs':
        rows = csv.reader(FLEURS_TSV.open(encoding='utf-8'), delimiter='\t', quoting=csv.QUOTE_NONE)
        found = [row[1] for row in rows]
    else:
        found = sorted(references(name), key=int)
    return found[:limit]


def load(name, key):
    """16 kHz mono float32."""
    import soundfile as sf
    path = FLEURS_AUDIO / key if name == 'fleurs' else IVRIT[name] / f'{key}.wav'
    audio, rate = sf.read(path, dtype='float32', always_2d=True)
    audio = audio.mean(axis=1)
    if rate != RATE:
        import soxr
        audio = soxr.resample(audio, rate, RATE)
    return np.ascontiguousarray(audio, dtype=np.float32)


def frame_db(audio, frame=320):
    """Level of each 20 ms frame in dBFS (RMS, full scale sine = -3 dBFS)."""
    n = len(audio) // frame
    if n == 0:
        return np.array([-120.])
    power = (audio[:n * frame].reshape(n, frame).astype(np.float64) ** 2).mean(axis=1)
    return 10 * np.log10(power + 1e-12)


def active_level(audio):
    """Active-speech level in dBFS: mean power of the frames within 30 dB of the 95th-percentile frame.

    Close to speakerphone levels (-25 dBFS near speaker, -33..-40 far speaker)."""
    db = frame_db(audio)
    top = np.percentile(db, 95)
    loud = db[db > top - 30]
    return float(10 * np.log10(np.mean(10 ** (loud / 10))))


def set_level(audio, target_dbfs):
    """Scale the whole recording so its active level equals target_dbfs (no limiter needed: only attenuation is used)."""
    gain = 10 ** ((target_dbfs - active_level(audio)) / 20)
    return np.clip(audio * gain, -1, 1).astype(np.float32), 20 * np.log10(gain)


def add_floor(audio, dbfs, seed=0):
    """Add a steady pink-noise floor at `dbfs` RMS (room/line noise under a quiet far speaker)."""
    rng = np.random.default_rng(seed)
    n = len(audio)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    f[0] = f[1]
    noise = np.fft.irfft(spectrum / np.sqrt(f), n)
    noise = noise / np.sqrt(np.mean(noise ** 2)) * 10 ** (dbfs / 20)
    return np.clip(audio + noise, -1, 1).astype(np.float32)


def speech_end(audio, below_db=30):
    """Seconds where the last frame within `below_db` of the loudest 95th-percentile frame ends."""
    db = frame_db(audio)
    top = np.percentile(db, 95)
    idx = np.nonzero(db > top - below_db)[0]
    return (idx[-1] + 1) * 0.02 if len(idx) else 0.


def synthetic(kind, seconds=60, seed=0):
    """Non-speech test signals. Levels are RMS dBFS."""
    rng = np.random.default_rng(seed)
    n = seconds * RATE

    def at(x, dbfs):
        x = x - x.mean()
        return (x / np.sqrt(np.mean(x ** 2)) * 10 ** (dbfs / 20)).astype(np.float32)

    def colored(exponent):
        spectrum = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / RATE)
        f[0] = f[1]
        return np.fft.irfft(spectrum / f ** (exponent / 2), n)

    if kind == 'silence':
        return np.zeros(n, np.float32)
    if kind == 'dither':           # near-silence a real microphone gives: -70 dBFS white noise
        return at(rng.standard_normal(n), -70)
    level = int(kind.rsplit('_', 1)[1])
    if kind.startswith('white_'):
        return at(rng.standard_normal(n), level)
    if kind.startswith('pink_'):
        return at(colored(1), level)
    if kind.startswith('brown_'):  # rumble, fan, car
        return at(colored(2), level)
    if kind.startswith('hum_'):    # 50 Hz mains hum with harmonics
        t = np.arange(n) / RATE
        return at(sum(np.sin(2 * np.pi * 50 * k * t) / k for k in range(1, 6)), level)
    if kind.startswith('clicks_'):  # keyboard-like transients on a -65 dBFS floor
        x = rng.standard_normal(n) * 10 ** (-65 / 20)
        for start in rng.integers(0, n - 400, size=seconds * 4):
            x[start:start + 400] += rng.standard_normal(400) * np.exp(-np.arange(400) / 60)
        return at(x, level)
    raise ValueError(kind)


SYNTHETIC = ['silence', 'dither', 'white_-60', 'white_-45', 'white_-30', 'pink_-50', 'pink_-35',
             'brown_-45', 'brown_-30', 'hum_-40', 'clicks_-40']


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)
