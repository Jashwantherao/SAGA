"""Procedural retro SFX - harness-owned, deterministic, no model involved.

Flux/MusicGen cover art and music, but there is no clean local model for
short sound effects, so the harness synthesizes them directly: four
chiptune-style cues (pickup, hit, win, lose) written as 16-bit mono WAVs
into the generated project's assets. The Coder's few-shots call them via
the Sfx autoload; the LLM never touches audio itself.
"""

import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050


def _envelope(n: int, attack: float = 0.01, decay_power: float = 3.0) -> np.ndarray:
    t = np.linspace(0.0, 1.0, n)
    return np.minimum(t / max(attack, 1e-6), 1.0) * (1.0 - t) ** decay_power


def _tone(freq_start: float, freq_end: float, duration: float, shape: str = "square") -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    freq = np.linspace(freq_start, freq_end, n)
    phase = 2.0 * np.pi * np.cumsum(freq) / SAMPLE_RATE
    if shape == "square":
        samples = np.sign(np.sin(phase)) * 0.5
    elif shape == "saw":
        samples = (((phase / (2.0 * np.pi)) % 1.0) * 2.0 - 1.0) * 0.5
    else:
        samples = np.sin(phase) * 0.7
    return samples * _envelope(n)


def _notes(freqs: list[float], note_duration: float = 0.12, shape: str = "square") -> np.ndarray:
    return np.concatenate([_tone(f, f, note_duration, shape) for f in freqs])


def _write_wav(path: Path, samples: np.ndarray) -> None:
    data = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(data.tobytes())


def write_default_sfx(assets_dir: Path) -> None:
    """Write the four standard cues the Sfx autoload expects."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    _write_wav(assets_dir / "sfx_pickup.wav", _tone(880, 1568, 0.12))
    _write_wav(assets_dir / "sfx_hit.wav", _tone(220, 70, 0.22, "saw"))
    _write_wav(assets_dir / "sfx_win.wav", _notes([523.25, 659.25, 783.99, 1046.5], 0.14))
    _write_wav(assets_dir / "sfx_lose.wav", _notes([392.0, 329.63, 261.63, 196.0], 0.18, "saw"))
