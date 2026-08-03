"""Regenerate the shipped rk909 kit — synthesized drums, no third-party
audio, so the kit is CC0-clean by construction and the repo carries its own
provenance.

    python bench/make_kit.py            # rewrites data/kits/rk909/

Deterministic: a fixed numpy seed, so a regenerated kit is byte-identical
and a diff in data/kits means somebody changed *this file*.
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR = 48000
OUT = ROOT / "data" / "kits" / "rk909"


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def _env(t: np.ndarray, decay: float) -> np.ndarray:
    return np.exp(-t / decay)


def _sweep(f0: float, f1: float, seconds: float, decay: float,
           drive: float = 1.5) -> np.ndarray:
    t = _t(seconds)
    freq = f1 + (f0 - f1) * np.exp(-t / (seconds * 0.18))
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.tanh(np.sin(phase) * drive) * _env(t, decay)


def _noise(rng, seconds: float, decay: float, bright: float = 0.0
           ) -> np.ndarray:
    t = _t(seconds)
    n = rng.uniform(-1, 1, len(t))
    if bright > 0:
        hp = np.diff(n, prepend=0.0)
        n = n * (1 - bright) + hp * bright * 2.0
    return n * _env(t, decay)


def _metal(rng, seconds: float, decay: float) -> np.ndarray:
    t = _t(seconds)
    tone = np.zeros_like(t)
    for f in (317.0, 466.0, 587.0, 803.0, 1153.0, 1483.0):
        tone += np.sign(np.sin(2 * np.pi * f * 6.13 * t))
    hp = np.diff(tone / 6.0, prepend=0.0)
    n = _noise(rng, seconds, decay, bright=0.85)
    return (hp * _env(t, decay) * 0.6 + n * 0.6)


def build(rng) -> dict[str, np.ndarray]:
    clap_t = _t(0.28)
    clap = np.zeros_like(clap_t)
    for k, when in enumerate((0.0, 0.012, 0.024)):
        idx = int(when * SR)
        burst = _noise(rng, 0.28 - when, 0.008 + 0.02 * (k == 2),
                       bright=0.5)
        clap[idx:idx + len(burst)] += burst
    clap += _noise(rng, 0.28, 0.09, bright=0.4) * 0.5

    cow_t = _t(0.30)
    cow = (np.sign(np.sin(2 * np.pi * 540 * cow_t))
           + np.sign(np.sin(2 * np.pi * 800 * cow_t))) * 0.5 \
        * _env(cow_t, 0.07)

    snare_body = _sweep(195, 168, 0.24, 0.055, drive=1.2)

    return {
        "kick": _sweep(112, 43, 0.42, 0.13, drive=2.2),
        "snare_soft": snare_body * 0.8
        + _noise(rng, 0.24, 0.07, bright=0.55) * 0.5,
        "snare_hard": snare_body
        + _noise(rng, 0.24, 0.10, bright=0.65) * 0.9,
        "clap": clap,
        "rim": _noise(rng, 0.07, 0.006, bright=0.7) * 0.8
        + _sweep(760, 720, 0.07, 0.012, drive=1.0),
        "chat": _metal(rng, 0.09, 0.021),
        "ohat": _metal(rng, 0.50, 0.13),
        "ltom": _sweep(150, 88, 0.34, 0.11, drive=1.6),
        "htom": _sweep(238, 145, 0.28, 0.09, drive=1.6),
        "ride": _metal(rng, 0.90, 0.30) * 0.5
        + _sweep(1970, 1930, 0.9, 0.35, drive=0.7) * 0.25,
        "crash": _metal(rng, 1.10, 0.32) * 0.8,
        "cowb": cow,
        "shkr": _noise(rng, 0.13, 0.035, bright=0.75),
    }


PADS = [
    # name, note, layers[(floor, file)], choke, mute group
    ("KICK", 36, [(0, "kick.wav")], 0, 0),
    ("SNAR", 38, [(0, "snare_soft.wav"), (96, "snare_hard.wav")], 0, 0),
    ("CLAP", 39, [(0, "clap.wav")], 0, 0),
    ("RIM", 37, [(0, "rim.wav")], 0, 0),
    ("CHAT", 42, [(0, "chat.wav")], 1, 1),
    ("OHAT", 46, [(0, "ohat.wav")], 1, 1),
    ("LTOM", 45, [(0, "ltom.wav")], 0, 0),
    ("HTOM", 50, [(0, "htom.wav")], 0, 0),
    ("RIDE", 51, [(0, "ride.wav")], 0, 2),
    ("CRSH", 49, [(0, "crash.wav")], 0, 2),
    ("COWB", 56, [(0, "cowb.wav")], 0, 0),
    ("SHKR", 70, [(0, "shkr.wav")], 0, 0),
]

SENDS = {"SNAR": (0.0, 0.18), "CLAP": (0.10, 0.22), "RIM": (0.0, 0.12),
         "OHAT": (0.0, 0.10), "RIDE": (0.0, 0.15), "CRSH": (0.0, 0.25),
         "COWB": (0.12, 0.0)}


def write_wav(path: Path, data: np.ndarray) -> None:
    peak = float(np.max(np.abs(data))) or 1.0
    scaled = (data / peak * 0.891 * 32767).astype("<i2")   # -1 dBFS
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(scaled.tobytes())


def main() -> int:
    rng = np.random.RandomState(0x909)
    OUT.mkdir(parents=True, exist_ok=True)
    samples = build(rng)
    total = 0
    for name, data in samples.items():
        path = OUT / f"{name}.wav"
        write_wav(path, data)
        total += path.stat().st_size
    pads = []
    for name, note, layers, choke, group in PADS:
        delay_send, reverb_send = SENDS.get(name, (0.0, 0.0))
        pads.append({"name": name, "note": note, "layers": layers,
                     "choke": choke, "group": group,
                     "delay_send": delay_send, "reverb_send": reverb_send})
    kit = {"name": "rk909", "dest": "internal", "channel": 9, "pads": pads}
    (OUT / "kit.json").write_text(json.dumps(kit, indent=1) + "\n",
                                  encoding="utf-8")
    print(f"rk909: {len(samples)} samples, {total / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
