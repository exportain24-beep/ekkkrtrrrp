"""ElevenLabs voice-over (German news voice) with word-level timestamps,
generated per segment so every headline block can be timed exactly."""
from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

from .config import TMP, env, settings

SR = 44100


@dataclass
class Segment:
    text: str
    audio: np.ndarray            # mono float32, SR
    words: list[tuple[str, float, float]]

    @property
    def duration(self) -> float:
        return len(self.audio) / SR


def decode_to_array(data: bytes, tmpname: str) -> np.ndarray:
    src = TMP / f"{tmpname}.mp3"
    src.write_bytes(data)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def _words_from_alignment(al: dict) -> list[tuple[str, float, float]]:
    chars = al["characters"]
    st = al["character_start_times_seconds"]
    en = al["character_end_times_seconds"]
    words, cur, s0, e0 = [], "", None, 0.0
    for c, s, e in zip(chars, st, en):
        if c.isspace():
            if cur:
                words.append((cur, s0, e0))
            cur, s0 = "", None
        else:
            if s0 is None:
                s0 = s
            cur += c
            e0 = e
    if cur:
        words.append((cur, s0, e0))
    return words


def _trim_silence(audio: np.ndarray, words, thresh=0.01) -> tuple[np.ndarray, list]:
    """Cut trailing silence (keeps the pacing tight like a real news desk)."""
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        return audio, words
    end = min(len(audio), idx[-1] + int(0.08 * SR))
    return audio[:end], words


def synth(text: str, name: str, prev_text: str = "", next_text: str = "") -> Segment:
    v = settings()["voice"]
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{v['voice_id']}/with-timestamps",
        params={"output_format": v["output_format"]},
        headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "content-type": "application/json"},
        json={
            "text": text,
            "model_id": v["model_id"],
            "voice_settings": v["settings"],
            "previous_text": prev_text or None,
            "next_text": next_text or None,
        },
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    data = r.json()
    audio = decode_to_array(base64.b64decode(data["audio_base64"]), name)
    al = data.get("alignment") or data.get("normalized_alignment")
    words = _words_from_alignment(al) if al else []
    audio, words = _trim_silence(audio, words)
    return Segment(text, audio, words)


def fake(text: str, name: str, **_) -> Segment:
    """Offline stand-in for tests: a quiet tone with estimated word timings."""
    words, t = [], 0.05
    for w in text.split():
        d = 0.16 + 0.055 * len(w)
        words.append((w, t, t + d))
        t += d + 0.05
    n = int((t + 0.1) * SR)
    tt = np.arange(n) / SR
    audio = (0.12 * np.sin(2 * np.pi * 180 * tt) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * tt))).astype(np.float32)
    return Segment(text, audio, words)


def voice_all(texts: list[str], offline: bool = False) -> list[Segment]:
    fn = fake if offline else synth
    segs = []
    for i, t in enumerate(texts):
        segs.append(fn(t, f"voice_{i}", prev_text=texts[i - 1] if i else "",
                       next_text=texts[i + 1] if i + 1 < len(texts) else ""))
    return segs
