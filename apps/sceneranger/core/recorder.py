"""The slot recorder — live MIDI into a clip slot, in time.

One armed slot at a time. Recording into an empty slot builds a new clip
whose length rounds *up* to whole bars at disarm (a take that ran 1.2 bars
meant 2); recording into a filled slot overdubs at its existing length.
Open notes close at disarm — a take never holds a key the player released.
"""
from __future__ import annotations

from rangerkit.events import TICKS_PER_BAR

from core.clip import Clip, ClipNote, MAX_BARS

MAX_OPEN = 32


class SlotRecorder:
    def __init__(self) -> None:
        self.track = -1
        self.scene = -1
        self.base: Clip | None = None   # what the slot held at arm time
        self.started = 0                # absolute tick recording began
        self._open: dict[int, tuple[int, int]] = {}
        self._farthest = 0
        self._take: Clip | None = None

    @property
    def recording(self) -> bool:
        return self.track >= 0

    def arm(self, track: int, scene: int, existing: Clip | None,
            tick: int) -> None:
        self.track, self.scene = track, scene
        self.base = existing
        self.started = tick
        self._open.clear()
        self._farthest = 0
        # Overdub captures into the existing loop; a fresh take records into
        # a maximal scratch loop and is trimmed at disarm.
        self._take = existing if existing is not None \
            else Clip(length_ticks=MAX_BARS * TICKS_PER_BAR)

    def note_on(self, tick: int, note: int, velocity: int) -> None:
        if not self.recording or len(self._open) >= MAX_OPEN:
            return
        position = (tick - self.started) % self._take.length_ticks
        self._open[note] = (position, velocity)
        self._farthest = max(self._farthest, tick - self.started)

    def note_off(self, tick: int, note: int) -> None:
        opened = self._open.pop(note, None)
        if opened is None or not self.recording:
            return
        start, velocity = opened
        position = (tick - self.started) % self._take.length_ticks
        length = max(1, (position - start) % self._take.length_ticks)
        self._take = self._take.with_note(
            ClipNote(tick=start, note=note, velocity=velocity,
                     length_ticks=length))
        self._farthest = max(self._farthest, tick - self.started)

    def land(self, tick: int) -> tuple[int, int, Clip | None]:
        """Disarm. Returns (track, scene, clip-or-None). A take with no
        notes answers the base clip unchanged (arming and bailing is free).
        """
        if not self.recording or self._take is None:
            return -1, -1, None
        for note in list(self._open):
            self.note_off(tick, note)
        track, scene = self.track, self.scene
        take, base = self._take, self.base
        self.track = self.scene = -1
        self.base = None
        if take is base or take.empty:
            return track, scene, base
        if base is None:
            bars = max(1, -(-max(1, self._farthest) // TICKS_PER_BAR))
            take = take.with_length(min(MAX_BARS, bars))
        return track, scene, take

    def open_notes(self) -> tuple[int, ...]:
        return tuple(sorted(self._open))
