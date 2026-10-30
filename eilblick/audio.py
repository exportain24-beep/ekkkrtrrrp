"""Original newsroom sound design, synthesised from scratch (no licences needed):
tense news bed, broadcast swoop + sub-bass drop at 0:00, whooshes and data
beeps on every graphic change, and an end stinger. Voice ducks the bed."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

SR = 44100
rng = np.random.default_rng(7)


def db(x: float) -> float:
    return 10 ** (x / 20)


def _env(n, a=0.005, r=0.2):
    t = np.arange(n) / SR
    e = np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))
    return e


def _lp(x, f, order=2):
    return sosfilt(butter(order, f / (SR / 2), "low", output="sos"), x)


def _hp(x, f, order=2):
    return sosfilt(butter(order, f / (SR / 2), "high", output="sos"), x)


def _bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)


def _norm(x, peak=1.0):
    m = np.max(np.abs(x)) or 1
    return (x / m * peak).astype(np.float32)


def saw(freq, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, 0, detune):
        ph = (t * freq * (1 + d)) % 1.0
        out += 2 * ph - 1
    return out / 3


# ------------------------------------------------------------------ bed
CHORDS = [  # D minor newsroom progression (Dm – B♭ – F – C), bar = 2 s at 120 BPM
    [146.83, 174.61, 220.00],
    [116.54, 146.83, 174.61],
    [174.61, 220.00, 261.63],
    [130.81, 164.81, 196.00],
]
ROOTS = [73.42, 58.27, 87.31, 65.41]


def news_bed(seconds: float, bpm: int = 120) -> np.ndarray:
    n = int(seconds * SR)
    out = np.zeros(n)
    beat = 60 / bpm
    bar = beat * 4
    # pad
    for b in range(int(seconds / bar) + 1):
        s = int(b * bar * SR)
        L = min(int(bar * SR), n - s)
        if L <= 0:
            break
        ch = CHORDS[b % 4]
        pad = sum(saw(f, L, 0.004) for f in ch) / 3
        pad = _lp(pad, 900)
        fade = np.minimum(1, np.minimum(np.arange(L), L - np.arange(L)) / (0.08 * SR))
        out[s:s + L] += 0.22 * pad * fade
        # bass pulse on 8ths
        for k in range(8):
            ps = s + int(k * beat / 2 * SR)
            pl = int(0.22 * SR)
            if ps + pl > n:
                break
            t = np.arange(pl) / SR
            f = ROOTS[b % 4]
            tone = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
            out[ps:ps + pl] += 0.35 * tone * _env(pl, 0.003, 0.09) * (1.0 if k % 2 == 0 else 0.7)
    # ticking hats (newsroom "clock")
    hat = _hp(rng.standard_normal(int(0.03 * SR)), 7000) * _env(int(0.03 * SR), 0.0005, 0.012)
    step = beat / 4
    for k in range(int(seconds / step)):
        p = int(k * step * SR)
        if p + len(hat) > n:
            break
        out[p:p + len(hat)] += hat * (0.18 if k % 4 == 0 else 0.08)
    # soft kick on beats 1 and 3
    kl = int(0.25 * SR)
    t = np.arange(kl) / SR
    kick = np.sin(2 * np.pi * (45 + 80 * np.exp(-t * 30)) * t) * _env(kl, 0.001, 0.12)
    for k in range(0, int(seconds / beat), 2):
        p = int(k * beat * SR)
        if p + kl > n:
            break
        out[p:p + kl] += 0.5 * kick
    return _norm(out, 0.9)


# ------------------------------------------------------------------ sfx
def swoop_hit() -> np.ndarray:
    """Broadcast news swoop + sub-bass drop (the 0:00 signature)."""
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    sweep = np.zeros(n)
    rise = int(0.45 * SR)
    for i, lo in enumerate(np.linspace(300, 6000, 12)):
        a, b = int(i * rise / 12), int((i + 1) * rise / 12)
        sweep[a:b] = _bp(noise[a:b + 400], lo, lo * 1.8)[: b - a]
    sweep[:rise] *= np.linspace(0, 1, rise) ** 2
    sweep[rise:] = 0
    hit_t = t[rise:] - t[rise]
    sub = np.sin(2 * np.pi * (30 + 60 * np.exp(-hit_t * 6)) * hit_t) * np.exp(-hit_t * 2.2)
    stab = sum(np.sin(2 * np.pi * f * hit_t) for f in (293.66, 349.23, 440.0, 587.33)) / 4
    stab = stab * np.exp(-hit_t * 5)
    out = sweep * 0.5
    out[rise:] += sub * 1.0 + stab * 0.35
    return _norm(out, 1.0)


def whoosh(length: float = 0.5) -> np.ndarray:
    n = int(length * SR)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    chunks = 16
    for i in range(chunks):
        a, b = i * n // chunks, (i + 1) * n // chunks
        c = 400 + 4000 * np.sin(np.pi * i / chunks)
        out[a:b] = _bp(noise[a:b + 300], c * 0.6, min(c * 1.6, 18000))[: b - a]
    out *= np.sin(np.pi * np.arange(n) / n) ** 2
    return _norm(out, 1.0)


def data_beep() -> np.ndarray:
    parts = []
    for f, d in ((1320, 0.05), (0, 0.03), (1760, 0.07)):
        n = int(d * SR)
        t = np.arange(n) / SR
        parts.append(np.sin(2 * np.pi * f * t) * _env(n, 0.002, d / 2) if f else np.zeros(n))
    return _norm(np.concatenate(parts), 0.8)


def end_sting() -> np.ndarray:
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    chord = sum(np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) for f in (146.83, 220.0, 293.66, 349.23))
    boom = np.sin(2 * np.pi * (40 + 40 * np.exp(-t * 8)) * t)
    out = (0.5 * chord / 4 + boom) * np.exp(-t * 2.5)
    return _norm(out, 1.0)


# ------------------------------------------------------------------ signature bed
_SIG_CACHE = {}


def signature_bed(seconds: float):
    """The channel's own signature track (assets/audio/signature_bed.mp3), always
    started from 0:00 so viewers recognise Eilblick by ear. Returns None if absent."""
    from pathlib import Path
    import subprocess
    path = Path(__file__).resolve().parent.parent / "assets" / "audio" / "signature_bed.mp3"
    if not path.exists():
        return None
    if "a" not in _SIG_CACHE:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
                              "-ar", str(SR), "-"], check=True, capture_output=True).stdout
        _SIG_CACHE["a"] = _norm(np.frombuffer(raw, dtype=np.float32).copy(), 0.9)
    a = _SIG_CACHE["a"]
    n = int(seconds * SR)
    if len(a) < n:
        a = np.tile(a, n // len(a) + 1)
    out = a[:n].copy()
    fi = int(0.25 * SR)
    out[:fi] *= np.linspace(0, 1, fi)
    return out


# ------------------------------------------------------------------ mix
def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float) -> None:
    s = int(at * SR)
    if s >= len(track):
        return
    e = min(len(track), s + len(clip))
    track[s:e] += clip[: e - s] * gain


def mix(total: float, voice_spans: list[tuple[float, np.ndarray]], sfx_events: list[tuple[str, float]],
        cfg: dict) -> np.ndarray:
    n = int(total * SR)
    voice = np.zeros(n, dtype=np.float32)
    for at, a in voice_spans:
        place(voice, a / (np.max(np.abs(a)) or 1), at, db(cfg["voice_db"]))
    # ducking envelope from voice energy
    win = int(0.05 * SR)
    energy = np.convolve(np.abs(voice), np.ones(win) / win, mode="same")
    talking = (energy > 0.01).astype(np.float32)
    smooth = np.convolve(talking, np.ones(int(0.25 * SR)) / int(0.25 * SR), mode="same")
    smooth = np.clip(smooth * 1.5, 0, 1)
    sig = signature_bed(total + 0.5)
    if sig is not None:
        duck = db(cfg["signature_open_db"]) * (1 - smooth) + db(cfg["signature_duck_db"]) * smooth
        bed = sig[:n] * duck
        # let the bed bow out under the end stinger
        tail = int(1.2 * SR)
        bed[-tail:] *= np.linspace(1, 0.25, tail)
    else:
        duck = db(cfg["music_open_db"]) * (1 - smooth) + db(cfg["music_db"]) * smooth
        bed = news_bed(total + 0.5)[:n] * duck
    sfx = np.zeros(n, dtype=np.float32)
    lib = {"swoop": (swoop_hit(), cfg["intro_hit_db"]), "whoosh": (whoosh(), cfg["sfx_db"]),
           "beep": (data_beep(), cfg["sfx_db"] - 3), "sting": (end_sting(), cfg["intro_hit_db"])}
    for kind, at in sfx_events:
        clip, g = lib[kind]
        place(sfx, clip, at, db(g))
    out = voice + bed + sfx
    # fade the last 0.15 s so the loop restarts cleanly
    f = int(0.15 * SR)
    out[-f:] *= np.linspace(1, 0, f)
    peak = np.max(np.abs(out)) or 1
    if peak > 0.98:
        out = out / peak * 0.98
    return out.astype(np.float32)


def write_wav(path, data: np.ndarray) -> None:
    import wave
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
