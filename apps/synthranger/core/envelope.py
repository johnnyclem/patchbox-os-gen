"""ADSR, rendered a block at a time with closed-form segments.

An exponential approach ``level → target`` with coefficient ``c`` per
sample is ``target + (level − target)·cⁿ`` over a whole block — no
per-sample Python. The renderer walks at most a few segment boundaries per
block (attack → decay → sustain), each one a vectorized slice. Release
starts from whatever level the gate left, so early lifts never click.
"""
from __future__ import annotations

import numpy as np

IDLE, ATTACK, DECAY, SUSTAIN, RELEASE = range(5)
_EPS = 1e-3


def _coeff(seconds: float, sample_rate: int) -> float:
    return float(np.exp(-1.0 / (max(0.001, seconds) * sample_rate * 0.3)))


class Envelope:
    __slots__ = ("sample_rate", "stage", "level")

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.stage = IDLE
        self.level = 0.0

    def gate_on(self) -> None:
        self.stage = ATTACK

    def gate_off(self) -> None:
        if self.stage != IDLE:
            self.stage = RELEASE

    def idle(self) -> bool:
        return self.stage == IDLE

    def render(self, frames: int, adsr: tuple) -> np.ndarray:
        attack, decay, sustain, release = adsr
        out = np.empty(frames, dtype=np.float32)
        done = 0
        while done < frames:
            n = frames - done
            if self.stage == IDLE:
                out[done:] = 0.0
                self.level = 0.0
                break
            if self.stage == ATTACK:
                target, seconds = 1.02, attack
            elif self.stage == DECAY:
                target, seconds = sustain, decay
            elif self.stage == SUSTAIN:
                out[done:] = self.level = sustain
                break
            else:
                target, seconds = 0.0, release
            c = _coeff(seconds, self.sample_rate)
            span = self.level - target
            curve = target + span * c ** np.arange(1, n + 1)
            # Where does this segment end inside the block, if it does?
            boundary = n
            if abs(span) > 1e-9:
                exact = (np.log(_EPS / abs(span)) / np.log(c))
                boundary = min(n, max(1, int(exact) + 1))
            hit = np.abs(curve[:boundary] - target) <= _EPS
            if hit.any():
                boundary = int(np.argmax(hit)) + 1
            out[done:done + boundary] = \
                np.clip(curve[:boundary], 0.0, 1.0)
            # Track the *unclipped* level: attack aims slightly past 1.0
            # so it actually arrives, and the arrival test needs to see it.
            self.level = float(curve[boundary - 1])
            done += boundary
            at_target = abs(self.level - target) <= _EPS * 1.5
            if at_target:
                if self.stage == ATTACK:
                    self.stage = DECAY
                elif self.stage == DECAY:
                    self.stage = SUSTAIN
                elif self.stage == RELEASE:
                    self.stage = IDLE
        return out
