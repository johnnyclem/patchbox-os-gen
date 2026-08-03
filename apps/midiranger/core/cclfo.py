"""The CC LFO bank — slow control voltages over MIDI.

Each LFO owns one CC number on one output. Values are computed from the
absolute tick, so two units with the same project and the same transport
position emit the same ramp — deterministic, like everything else here.

Emission is throttled two ways: a resolution grid (no point flooding a DIN
port at tick rate) and a change gate (a NaN-flat LFO parked between two 7-bit
codes sends nothing).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from rangerkit.events import PPQN, TICKS_PER_BAR

SHAPES = ("sine", "triangle", "saw", "square", "random")
RESOLUTION = PPQN // 16         # emit grid: 6 ticks ≈ 64th notes
# Panel-offered periods, in ticks: 1 beat … 8 bars.
PERIODS = (PPQN, PPQN * 2, TICKS_PER_BAR, TICKS_PER_BAR * 2,
           TICKS_PER_BAR * 4, TICKS_PER_BAR * 8)


@dataclass(frozen=True, slots=True)
class LfoParams:
    enabled: bool = False
    shape: str = "sine"
    period: int = TICKS_PER_BAR
    depth: float = 1.0          # 0..1 of the full 0..127 sweep
    center: int = 64
    cc: int = 1
    channel: int = 0
    dest: str = "din_out"

    def normalised(self) -> "LfoParams":
        return replace(
            self,
            shape=self.shape if self.shape in SHAPES else "sine",
            period=self.period if self.period in PERIODS else TICKS_PER_BAR,
            depth=max(0.0, min(1.0, float(self.depth))),
            center=max(0, min(127, int(self.center))),
            cc=max(0, min(119, int(self.cc))),
            channel=max(0, min(15, int(self.channel))))


def _wave(shape: str, phase: float, seed: int, cycle: int) -> float:
    """-1 … 1 for one shape at one phase. ``random`` is S&H: one level per
    resolution step, derived arithmetically (not from ``hash()``, which is
    salted per process) so it replays identically."""
    if shape == "triangle":
        return 4.0 * abs(phase - 0.5) - 1.0
    if shape == "saw":
        return 2.0 * phase - 1.0
    if shape == "square":
        return 1.0 if phase < 0.5 else -1.0
    if shape == "random":
        state = (seed * 1103515245 + cycle * 12345 + 42) & 0x7FFFFFFF
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return (state % 2001) / 1000.0 - 1.0
    return math.sin(2.0 * math.pi * phase)


class CcLfo:
    """One LFO. ``on_tick`` answers the CC value to send, or None."""

    def __init__(self, params: LfoParams | None = None, seed: int = 1) -> None:
        self.params = (params or LfoParams()).normalised()
        self.seed = seed
        self._last: int | None = None

    def set_params(self, params: LfoParams) -> None:
        self.params = params.normalised()
        self._last = None           # re-emit on the next grid point

    def value_at(self, tick: int) -> int:
        p = self.params
        phase = (tick % p.period) / p.period
        if p.shape == "random":
            cycle = tick // RESOLUTION
        else:
            cycle = tick // p.period
        level = _wave(p.shape, phase, self.seed, cycle)
        value = p.center + level * p.depth * 63.5
        return max(0, min(127, round(value)))

    def on_tick(self, tick: int) -> int | None:
        p = self.params
        if not p.enabled or tick % RESOLUTION:
            return None
        value = self.value_at(tick)
        if value == self._last:
            return None
        self._last = value
        return value
