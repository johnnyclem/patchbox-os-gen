"""Shared block-DSP primitives — vectorized IIR without per-sample Python.

The one-pole low-pass ``y[n] = (1−a)x[n] + a·y[n−1]`` has a closed form
over a block: ``y = a^n·y0 + Σ (1−a)a^{n−k} x[k]``, computable with a
cumulative sum after scaling by ``a^{−k}``. That scaling explodes for
small ``a``, so the implementation branches: smooth poles (a ≥ 0.5) use
the cumsum form in float64 sub-chunks of 32 (worst-case ratio 2³² — fine
in float64), fast poles (a < 0.5) truncate to a ≤ 24-tap FIR (a^24 <
1e−7). Either way the per-block cost is a handful of numpy calls, which
is what lets reverb damping, envelope followers and voice filters run on
the audio path without a single Python sample loop.

First shipped inside SynthRanger's dsp; promoted here (suite stretch S1)
so GrooveRanger's bus and future consumers share one tested copy.
"""
from __future__ import annotations

import numpy as np

CHUNK = 32


class OnePole:
    """Stateful one-pole low-pass; ``a`` may change freely per call."""

    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state = 0.0

    def process(self, x: np.ndarray, a: float) -> np.ndarray:
        if a < 1e-4:
            self.state = float(x[-1]) if len(x) else self.state
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
