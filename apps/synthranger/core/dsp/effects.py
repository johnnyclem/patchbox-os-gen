"""Part and master effects — block-vectorized, no serial feedback inside a
block.

* ``drive`` — a stateless tanh waveshaper with gain compensation.
* ``Chorus`` — one modulated tap over an *input* history ring (no
  feedback, so the read may sit closer than a block); the tap position
  ramps linearly across each block toward the LFO's new target, which is
  zipper-free without per-sample sines.
* ``Delay`` — a feedback echo whose loop time is clamped above one block,
  same discipline as GrooveRanger's bus.
"""
from __future__ import annotations

import numpy as np


def drive(x: np.ndarray, amount: float) -> np.ndarray:
    amount = min(1.0, max(0.0, amount))
    if amount <= 0.0:
        return x
    gain = 1.0 + amount * 6.0
    return (np.tanh(x * gain) / np.tanh(gain) ** 0.5).astype(np.float32)


class Chorus:
    __slots__ = ("sample_rate", "_ring", "_write", "_phase", "_last")

    RING_S = 0.06
    BASE_S, SWEEP_S = 0.014, 0.008
    RATE_HZ = 0.6

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._ring = np.zeros(int(sample_rate * self.RING_S) + 2,
                              dtype=np.float32)
        self._write = 0
        self._phase = 0.0
        self._last = self.BASE_S * sample_rate

    def process(self, x: np.ndarray, amount: float) -> np.ndarray:
        amount = min(1.0, max(0.0, amount))
        n = len(x)
        ring = self._ring
        index = (self._write + np.arange(n)) % len(ring)
        ring[index] = x
        self._write = (self._write + n) % len(ring)
        if amount <= 0.0:
            return x
        self._phase = (self._phase + self.RATE_HZ * n
                       / self.sample_rate) % 1.0
        target = (self.BASE_S + self.SWEEP_S
                  * 0.5 * (1.0 + np.sin(2 * np.pi * self._phase))) \
            * self.sample_rate
        delays = np.linspace(self._last, target, n)
        self._last = float(target)
        positions = (self._write - n + np.arange(n) - delays) % len(ring)
        low = positions.astype(np.int64)
        frac = (positions - low).astype(np.float32)
        wet = ring[low] * (1.0 - frac) + ring[(low + 1) % len(ring)] * frac
        return (x * (1.0 - 0.5 * amount) + wet * 0.5 * amount * 2.0) \
            .astype(np.float32)


class Delay:
    __slots__ = ("sample_rate", "_ring", "_write", "feedback")

    MIN_S, MAX_S = 0.06, 1.5

    def __init__(self, sample_rate: int, feedback: float = 0.4) -> None:
        self.sample_rate = sample_rate
        self._ring = np.zeros(int(sample_rate * self.MAX_S) + 1,
                              dtype=np.float32)
        self._write = 0
        self.feedback = feedback

    def process(self, send: np.ndarray, seconds: float) -> np.ndarray:
        seconds = min(self.MAX_S, max(self.MIN_S, seconds))
        delay = int(seconds * self.sample_rate)
        ring = self._ring
        n = len(send)
        start = (self._write - delay) % len(ring)
        read_index = (start + np.arange(n)) % len(ring)
        echo = ring[read_index].copy()
        write_index = (self._write + np.arange(n)) % len(ring)
        ring[write_index] = send + echo * self.feedback
        self._write = (self._write + n) % len(ring)
        return echo
