"""The master bus: one-knob filter, tempo-synced delay, small-room reverb.

Everything here is block-vectorized numpy with no per-sample Python — the
delay and every reverb stage keep their loop times longer than one render
block (256 frames), so feedback only ever reads samples written on earlier
blocks and a whole block can be processed at once. The one-knob filter is a
short Hann FIR with carried tail state: below center it closes as a
low-pass, above center the same kernel's complement makes the high-pass,
and the middle tenth is bit-exact passthrough.

It is a deliberately lo-fi bus — a groovebox color, not a mastering chain.
Retuning the delay while it rings jumps rather than glides; that stays
documented character. The reverb is four combs and two allpasses, and
since suite stretch S1 the combs are *dampable*: each feedback path runs
through a shared closed-form one-pole (``rangerkit.audio.dsp.OnePole``) —
the loop time stays longer than a block, so damping costs a few numpy
calls and no per-sample Python. Damping 0 bypasses the poles bit-exactly,
which is also why every pre-S1 rendering is unchanged by default.
"""
from __future__ import annotations

import numpy as np

from rangerkit.audio.dsp import OnePole

DELAY_FEEDBACK = 0.35
DELAY_MIN_S, DELAY_MAX_S = 0.06, 2.0
#: division index -> beats of delay (CC 85 picks one)
DELAY_DIVISIONS = (0.5, 0.75, 1.0, 2.0)
#: loop samples, feedback gain — all loops longer than one block
_COMBS = ((1116, 0.79), (1188, 0.78), (1277, 0.77), (1356, 0.76))
_ALLPASSES = (556, 441)
_ALLPASS_G = 0.5
_MAX_KERNEL = 64
_NEUTRAL_LO, _NEUTRAL_HI = 0.45, 0.55


class _Ring:
    """A circular delay line; loop time = its length (> one block)."""

    def __init__(self, length: int) -> None:
        self.buffer = np.zeros(length, dtype=np.float32)
        self.write = 0

    def tap(self, frames: int, delay: int | None = None) -> np.ndarray:
        span = delay if delay is not None else len(self.buffer)
        start = (self.write - span) % len(self.buffer)
        index = (start + np.arange(frames)) % len(self.buffer)
        return self.buffer[index].copy()

    def push(self, block: np.ndarray) -> None:
        index = (self.write + np.arange(len(block))) % len(self.buffer)
        self.buffer[index] = block.astype(np.float32)
        self.write = (self.write + len(block)) % len(self.buffer)


class FxBus:
    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.filter = 0.5            # one knob: 0 = dark LP … 1 = thin HP
        self.level = 1.0
        self.reverb = 0.3            # return level for the reverb sends
        self.bpm = 120.0
        self.division = 2            # index into DELAY_DIVISIONS
        self.damp = 0.0              # 0 = the original undamped tail
        self.duck = 0.0              # sidechain depth on the returns
        self._duck_env = 0.0
        self._duck_gain = 1.0
        self._delay = _Ring(int(sample_rate * DELAY_MAX_S) + 1)
        self._combs = [(_Ring(length), gain, OnePole())
                       for length, gain in _COMBS]
        self._allpasses = [_Ring(length) for length in _ALLPASSES]
        self._tail = np.zeros((0, 2), dtype=np.float32)
        self._kernel: np.ndarray | None = None
        self._kernel_for = -1.0

    # --- knobs -----------------------------------------------------------------
    def set_filter(self, value: float) -> None:
        self.filter = max(0.0, min(1.0, float(value)))

    def set_level(self, value: float) -> None:
        self.level = max(0.0, min(1.27, float(value)))

    def set_reverb(self, value: float) -> None:
        self.reverb = max(0.0, min(1.0, float(value)))

    def set_delay_division(self, index: int) -> None:
        self.division = max(0, min(len(DELAY_DIVISIONS) - 1, int(index)))

    def set_damp(self, value: float) -> None:
        self.damp = max(0.0, min(1.0, float(value)))

    def set_duck(self, value: float) -> None:
        self.duck = max(0.0, min(1.0, float(value)))

    def set_tempo(self, bpm: float) -> None:
        self.bpm = max(20.0, min(300.0, float(bpm)))

    def _delay_samples(self) -> int:
        seconds = DELAY_DIVISIONS[self.division] * 60.0 / self.bpm
        seconds = max(DELAY_MIN_S, min(DELAY_MAX_S, seconds))
        return int(seconds * self.sample_rate)

    # --- the block -------------------------------------------------------------
    def process(self, dry: np.ndarray, delay_send: np.ndarray,
                reverb_send: np.ndarray,
                key: np.ndarray | None = None) -> np.ndarray:
        frames = len(dry)
        out = dry.astype(np.float32).copy()
        duck_gain = self._duck_ramp(key, frames)
        echo = self._delay.tap(frames, self._delay_samples())
        self._delay.push(delay_send + echo * DELAY_FEEDBACK)
        echo = echo * duck_gain
        out[:, 0] += echo
        out[:, 1] += echo
        wet = np.zeros(frames, dtype=np.float32)
        # damp → pole: 0 stays bit-exact bypass; 1 is a dark ~0.94 pole.
        a_damp = self.damp * 0.94
        for ring, gain, pole in self._combs:
            fed = ring.tap(frames)
            if a_damp > 0.0:
                fed = pole.process(fed, a_damp)
            ring.push(reverb_send + fed * gain)
            wet += fed
        for ring in self._allpasses:
            delayed = ring.tap(frames)
            ring.push(wet + delayed * _ALLPASS_G)
            wet = delayed - _ALLPASS_G * wet
        wet = wet * (self.reverb * 0.25) * duck_gain
        out[:, 0] += wet
        out[:, 1] += wet
        out = self._one_knob(out)
        return np.clip(out * self.level, -1.0, 1.0).astype(np.float32)

    # --- the sidechain ---------------------------------------------------------
    def _duck_ramp(self, key, frames: int):
        """Gain for this block's returns: instant attack on the key's
        block peak, ~150 ms release, ramped from last block's gain so the
        pump never zippers. duck 0 (or no key) is exactly gain 1."""
        if self.duck <= 0.0 or key is None:
            self._duck_env = 0.0
            self._duck_gain = 1.0
            return np.float32(1.0)
        peak = float(np.max(np.abs(key))) if len(key) else 0.0
        release = float(np.exp(-frames / (self.sample_rate * 0.15)))
        self._duck_env = max(peak, self._duck_env * release)
        target = 1.0 - self.duck * min(1.0, self._duck_env * 1.5)
        ramp = np.linspace(self._duck_gain, target, frames,
                           dtype=np.float32)
        self._duck_gain = target
        return ramp

    # --- the one-knob filter ---------------------------------------------------
    def _one_knob(self, block: np.ndarray) -> np.ndarray:
        f = self.filter
        if _NEUTRAL_LO <= f <= _NEUTRAL_HI:
            return block
        closed = (_NEUTRAL_LO - f) / _NEUTRAL_LO if f < _NEUTRAL_LO \
            else (f - _NEUTRAL_HI) / (1.0 - _NEUTRAL_HI)
        if closed != self._kernel_for:
            length = 2 + int(closed * closed * (_MAX_KERNEL - 2))
            kernel = np.hanning(length + 2)[1:-1].astype(np.float32)
            self._kernel = kernel / kernel.sum()
            self._kernel_for = closed
            self._tail = np.zeros((0, 2), dtype=np.float32)
        kernel = self._kernel
        history = np.concatenate([self._tail, block]) \
            if len(self._tail) else block
        skip = len(self._tail)
        low = np.stack(
            [np.convolve(history[:, 0], kernel)[skip:skip + len(block)],
             np.convolve(history[:, 1], kernel)[skip:skip + len(block)]],
            axis=1).astype(np.float32)
        keep = len(kernel) - 1
        self._tail = history[-keep:].copy() if keep else \
            np.zeros((0, 2), dtype=np.float32)
        return low if f < _NEUTRAL_LO else (block - low)
