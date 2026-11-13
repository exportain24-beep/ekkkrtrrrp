"""Documentary sound: calm, serious ambient bed (synthesised, licence-free), ducked under the voice,
the channel signature at the title card, whooshes on chapter cards, soft ticks on data graphics."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from ..audio import SR, db, end_sting, place, signature_bed, swoop_hit, whoosh, data_beep

# A minor – F – C – G (low, slow), 8 s per chord
CHORDS = [(110.0, 130.81, 164.81), (87.31, 110.0, 130.81), (130.81, 164.81, 196.0), (98.0, 123.47, 146.83)]


def ambient_bed(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    seg = 8.0
    for c in range(int(seconds / seg) + 2):
        s0 = c * seg - 1.5
        i0, i1 = max(0, int(s0 * SR)), min(n, int((s0 + seg + 3) * SR))
        if i0 >= n:
            break
        tt = t[i0:i1] - s0
        env = np.clip(tt / 2.5, 0, 1) * np.clip((seg + 3 - tt) / 2.5, 0, 1)
        for k, f in enumerate(CHORDS[c % 4]):
            det = 1 + 0.0015 * (k - 1)
            out[i0:i1] += env * (np.sin(2 * np.pi * f * det * t[i0:i1]) + 0.35 * np.sin(2 * np.pi * f * 2 * t[i0:i1])) / 3
        # sub pulse (heartbeat feel) every 2 s
    pulse = np.zeros(n)
    for b in np.arange(0, seconds, 2.0):
        i = int(b * SR)
        L = min(int(0.6 * SR), n - i)
        if L > 0:
            tt = np.arange(L) / SR
            pulse[i:i + L] += np.sin(2 * np.pi * 55 * tt) * np.exp(-tt * 7)
    noise = np.random.default_rng(3).standard_normal(n) * 0.04
    noise = sosfilt(butter(2, [300, 2500], btype="band", fs=SR, output="sos"), noise)
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * t / 23)
    out = sosfilt(butter(3, 1400, fs=SR, output="sos"), out) * lfo + pulse * 0.35 + noise
    out /= np.max(np.abs(out)) or 1
    return out.astype(np.float32)


def mix(total: float, voice_spans, events, title_at: float) -> np.ndarray:
    n = int(total * SR)
    voice = np.zeros(n, dtype=np.float32)
    for at, a in voice_spans:
        place(voice, a / (np.max(np.abs(a)) or 1), at, db(-1.5))
    win = int(0.05 * SR)
    energy = np.convolve(np.abs(voice), np.ones(win) / win, mode="same")
    talk = np.convolve((energy > 0.01).astype(np.float32), np.ones(int(0.4 * SR)) / int(0.4 * SR), mode="same")
    talk = np.clip(talk * 1.5, 0, 1)
    bed = ambient_bed(total + 1)[:n] * (db(-17) * (1 - talk) + db(-29) * talk)
    # signature track around the title card (brand recognition), faded in/out
    sig = signature_bed(6.0)
    if sig is not None:
        L = len(sig)
        env = np.ones(L, dtype=np.float32)
        f = int(0.8 * SR)
        env[-f:] = np.linspace(1, 0, f)
        place(bed, sig * env, max(0.0, title_at - 0.3), db(-9))
    sfx = np.zeros(n, dtype=np.float32)
    lib = {"swoop": (swoop_hit(), -9), "whoosh": (whoosh(0.7), -14), "beep": (data_beep(), -20), "sting": (end_sting(), -10)}
    for kind, at in events:
        clip, g = lib[kind]
        place(sfx, clip, at, db(g))
    out = voice + bed + sfx
    f = int(1.0 * SR)
    out[-f:] *= np.linspace(1, 0, f)
    peak = np.max(np.abs(out)) or 1
    return (out / peak * 0.97 if peak > 0.97 else out).astype(np.float32)
