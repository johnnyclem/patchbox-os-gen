"""Cruise — the slow hand that keeps the piece evolving.

Coherence rules, learned from every generative box that turned to mush:
one layer mutates per firing (round-robin over the unlocked layers, so
nothing is starved and nothing churns), firings land on bar lines, and the
interval between them comes from the speed knob on a musical scale (every
bar at full speed, every 16 at a crawl).
"""
from __future__ import annotations

from rangerkit.events import TICKS_PER_BAR

SPEED_BARS = (16, 8, 4, 2, 1)   # speed 0..1 sweeps crawl → every bar


def interval_ticks(speed: float) -> int:
    speed = max(0.0, min(1.0, float(speed)))
    index = min(len(SPEED_BARS) - 1, int(speed * len(SPEED_BARS)))
    return SPEED_BARS[index] * TICKS_PER_BAR


class Cruise:
    def __init__(self) -> None:
        self.on = True
        self.speed = 0.5
        self.chaos = 0.35
        self._cursor = 0            # round-robin position

    def due(self, tick: int) -> bool:
        return self.on and tick > 0 and tick % interval_ticks(self.speed) == 0

    def next_layer(self, candidates: list[int]) -> int | None:
        """Round-robin over the mutable layer indices. None when everything
        is locked — cruise then idles rather than fighting the player."""
        if not candidates:
            return None
        self._cursor += 1
        return candidates[self._cursor % len(candidates)]
