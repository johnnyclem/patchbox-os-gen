"""The voice filter — vectorized IIR without per-sample Python.

A one-pole low-pass ``y[n] = (1−a)x[n] + a·y[n−1]`` has a closed form over
a block: ``y = a^n·y0 + Σ (1−a)a^{n−k} x[k]``, computable with a cumulative
sum after scaling by ``a^{−k}``. That scaling explodes for small ``a``, so
the implementation branches: smooth poles (a ≥ 0.5) use the cumsum form in
float64 sub-chunks of 32 (worst case ratio 2³² — fine in float64), fast
poles (a < 0.5) truncate to a ≤ 24-tap FIR (a^24 < 1e−7). Either way the
per-block cost is a handful of numpy calls.

The 12 dB filter is two cascaded poles. **Resonance is not a feedback
loop**: it is a cutoff-tracking band emphasis — the difference between the
two stages (a band-pass) scaled by ``res`` and added back. Stable by
construction at every setting, fully parallel, and a documented color
rather than a Moog imitation. ``hp`` mode is the complement ``x − lp``.
"""
from __future__ import annotations

import numpy as np

CHUNK = 32
CUTOFF_HZ_LO, CUTOFF_HZ_HI = 40.0, 16000.0
MODES = ("lp", "hp")


def pole_for(cutoff: float, sample_rate: int) -> float:
    """Normalized cutoff 0..1 (log-swept 40 Hz..16 kHz) → pole ``a``."""
    cutoff = min(1.0, max(0.0, cutoff))
    hz = CUTOFF_HZ_LO * (CUTOFF_HZ_HI / CUTOFF_HZ_LO) ** cutoff
    return float(np.exp(-2.0 * np.pi * hz / sample_rate))


class OnePole:
    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state = 0.0

    def process(self, x: np.ndarray, a: float) -> np.ndarray:
        if a < 1e-4:
            self.state = float(x[-1])
            return x.astype(np.float32)
        if a < 0.5:
            taps = max(1, int(np.ceil(-7.0 / np.log10(a))))
            kernel = (1.0 - a) * a ** np.arange(taps)
            y = np.convolve(x, kernel)[:len(x)]
            # Carry the previous block's state through the (short) tail.
            decay = a ** np.arange(1, min(taps, len(x)) + 1)
            y[:len(decay)] += self.state * decay
        else:
            y = np.empty(len(x), dtype=np.float64)
            level = self.state
            for start in range(0, len(x), CHUNK):
                part = x[start:start + CHUNK].astype(np.float64)
                n = len(part)
                powers = a ** np.arange(1, n + 1)
                scaled = np.cumsum(part * (1.0 - a) / powers)
                y[start:start + n] = powers * (level + scaled)
                level = y[start + n - 1]
        self.state = float(y[-1])
        return y.astype(np.float32)


class VoiceFilter:
    """Two cascaded poles + band emphasis; one instance per voice."""

    __slots__ = ("sample_rate", "_p1", "_p2")

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._p1 = OnePole()
        self._p2 = OnePole()

    def process(self, x: np.ndarray, cutoff: float, res: float,
                mode: str = "lp") -> np.ndarray:
        a = pole_for(cutoff, self.sample_rate)
        lp1 = self._p1.process(x, a)
        lp2 = self._p2.process(lp1, a)
        band = lp1 - lp2
        res = min(1.0, max(0.0, res))
        if mode == "hp":
            return (x - lp2 + band * res * 2.0).astype(np.float32)
        return (lp2 + band * res * 2.0).astype(np.float32)
