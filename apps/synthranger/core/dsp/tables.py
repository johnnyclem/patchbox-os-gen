"""Band-limited wavetables, mip-mapped per octave.

Every oscillator engine in SynthRanger is a table read — VA shapes, the FM
operators' sine, the wavetable scan, phase distortion's cosine — because a
table read vectorizes and a naive ``sign(sin(x))`` aliases. Each shape gets
one table per octave with the partial count halved as pitch doubles, so
nothing above Nyquist is ever synthesized.

All tables are float32, length ``TABLE_SIZE``, one full cycle, peak-normal.
"""
from __future__ import annotations

import numpy as np

TABLE_SIZE = 2048
MIPS = 10                       # octaves from FREQ_LO up
FREQ_LO = 20.0                  # mip 0 covers 20–40 Hz
_MAX_PARTIALS = 512

_phase = np.arange(TABLE_SIZE) / TABLE_SIZE
SINE = np.sin(2 * np.pi * _phase).astype(np.float32)
COSINE = np.cos(2 * np.pi * _phase).astype(np.float32)


def _additive(amplitude_for) -> list[np.ndarray]:
    """Build MIPS tables; partial k weight from ``amplitude_for(k)``."""
    tables = []
    for mip in range(MIPS):
        top = max(1, int(_MAX_PARTIALS / (2 ** mip)))
        wave = np.zeros(TABLE_SIZE)
        for k in range(1, top + 1):
            a = amplitude_for(k)
            if a:
                wave += a * np.sin(2 * np.pi * k * _phase)
        peak = np.max(np.abs(wave)) or 1.0
        tables.append((wave / peak).astype(np.float32))
    return tables


_SAW = _additive(lambda k: 1.0 / k)
_SQUARE = _additive(lambda k: 1.0 / k if k % 2 else 0.0)
_TRIANGLE = _additive(
    lambda k: ((-1.0) ** ((k - 1) // 2)) / (k * k) if k % 2 else 0.0)
_SINE_MIPS = [SINE] * MIPS

SHAPES = ("sine", "triangle", "saw", "square")
_BY_SHAPE = {"sine": _SINE_MIPS, "triangle": _TRIANGLE, "saw": _SAW,
             "square": _SQUARE}


def mip_for(freq: float) -> int:
    mip = int(np.log2(max(freq, FREQ_LO) / FREQ_LO))
    return min(MIPS - 1, max(0, mip))


def table(shape: str, freq: float) -> np.ndarray:
    return _BY_SHAPE.get(shape, _SAW)[mip_for(freq)]


def read(wave: np.ndarray, phases: np.ndarray) -> np.ndarray:
    """Linear-interp table read; ``phases`` in cycles (any positive)."""
    position = (phases % 1.0) * TABLE_SIZE
    index = position.astype(np.int64)
    frac = (position - index).astype(np.float32)
    nxt = (index + 1) % TABLE_SIZE
    return wave[index] * (1.0 - frac) + wave[nxt] * frac
