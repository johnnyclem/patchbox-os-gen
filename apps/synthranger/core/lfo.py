"""Control-rate LFO — one value per render block.

At 256 frames the control rate is ~187 Hz, plenty for vibrato and filter
sweeps; destinations that would zipper (none of ours at these depths)
would ramp instead. Sample-and-hold draws from a seeded rng handed in by
the synth so twin engines stay deterministic.
"""
from __future__ import annotations

import math


class Lfo:
    __slots__ = ("_phase", "_held", "_held_at")

    def __init__(self) -> None:
        self._phase = 0.0
        self._held = 0.0
        self._held_at = -1

    def step(self, rate_hz: float, shape: str, frames: int,
             sample_rate: int, rng) -> float:
        """Advance one block; returns the value in −1..1."""
        self._phase = (self._phase + rate_hz * frames / sample_rate)
        cycle, phase = divmod(self._phase, 1.0)
        if shape == "triangle":
            return 4.0 * abs(phase - 0.5) - 1.0
        if shape == "square":
            return 1.0 if phase < 0.5 else -1.0
        if shape == "sh":
            if int(cycle) != self._held_at:
                self._held_at = int(cycle)
                self._held = rng.uniform(-1.0, 1.0)
            return self._held
        return math.sin(2.0 * math.pi * phase)
