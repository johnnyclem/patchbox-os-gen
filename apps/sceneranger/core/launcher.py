"""The launcher — who is playing, who is queued, and when queues resolve.

Pure state per track: the active slot, the queued slot (a launch waiting
for the quantize boundary), the tick the active clip started, and how many
loops it has done. The engine consults ``boundary`` each tick; with
quantize "off" a queue resolves on the very next drain — that is the
<5–10 ms command-to-MIDI path.
"""
from __future__ import annotations

from rangerkit.events import PPQN, TICKS_PER_BAR

QUANTIZE_MODES = ("off", "beat", "bar")
NOTHING = -1                    # no slot
STOP = -2                       # a stop is queued


def boundary(tick: int, mode: str) -> bool:
    if mode == "off":
        return True
    if mode == "beat":
        return tick % PPQN == 0
    return tick % TICKS_PER_BAR == 0


class TrackLauncher:
    __slots__ = ("active", "queued", "started", "loops")

    def __init__(self) -> None:
        self.active = NOTHING
        self.queued = NOTHING
        self.started = 0
        self.loops = 0

    def queue(self, slot: int) -> None:
        self.queued = slot

    def queue_stop(self) -> None:
        self.queued = STOP if self.active != NOTHING else NOTHING

    def resolve(self, tick: int) -> int | None:
        """At a boundary: apply the queue. Returns the newly active slot,
        STOP for a stop, or None when nothing was queued."""
        if self.queued == NOTHING:
            return None
        queued, self.queued = self.queued, NOTHING
        if queued == STOP:
            self.active = NOTHING
            return STOP
        self.active = queued
        self.started = tick
        self.loops = 0
        return queued

    def position(self, tick: int, length_ticks: int) -> int:
        return (tick - self.started) % length_ticks

    def wrapped(self, tick: int, length_ticks: int) -> bool:
        """Did a loop complete exactly now (and not the launch instant)?"""
        return tick > self.started \
            and (tick - self.started) % length_ticks == 0
