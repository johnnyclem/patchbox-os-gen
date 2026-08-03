"""The clip — a launchable loop of MIDI, immutable, tick-domain.

The same structural bet as PhraseRanger's phrase (values, pure verbs), plus
the session-view identity: a follow action (what happens when the clip has
looped its count), launch probability on that action, velocity scale and
transpose applied at emit. A clip stores no channel — the track owns the
plumbing, so clips move between tracks freely.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import PPQN, TICKS_PER_BAR

QUANTIZE_TICKS = PPQN // 4      # record quantize: a sixteenth
MAX_BARS = 8
FOLLOW_ACTIONS = ("none", "again", "next", "prev", "random", "stop")


@dataclass(frozen=True, slots=True)
class ClipNote:
    tick: int
    note: int
    velocity: int
    length_ticks: int

    def to_config(self) -> dict:
        return {"tick": self.tick, "note": self.note,
                "velocity": self.velocity, "length": self.length_ticks}

    @classmethod
    def from_config(cls, raw: dict) -> "ClipNote":
        return cls(tick=int(raw.get("tick", 0)),
                   note=max(0, min(127, int(raw.get("note", 60)))),
                   velocity=max(1, min(127, int(raw.get("velocity", 96)))),
                   length_ticks=max(1, int(raw.get("length", PPQN // 2))))


@dataclass(frozen=True, slots=True)
class Clip:
    notes: tuple[ClipNote, ...] = ()
    length_ticks: int = TICKS_PER_BAR
    follow: str = "none"
    follow_loops: int = 1       # loops before the action fires
    follow_probability: float = 1.0
    velocity_scale: float = 1.0
    transpose: int = 0

    @property
    def bars(self) -> int:
        return max(1, self.length_ticks // TICKS_PER_BAR)

    @property
    def empty(self) -> bool:
        return not self.notes

    def normalised(self) -> "Clip":
        return replace(
            self,
            follow=self.follow if self.follow in FOLLOW_ACTIONS else "none",
            follow_loops=max(1, min(16, int(self.follow_loops))),
            follow_probability=max(0.0, min(1.0,
                                            float(self.follow_probability))),
            velocity_scale=max(0.1, min(2.0, float(self.velocity_scale))),
            transpose=max(-24, min(24, int(self.transpose))))

    def notes_at(self, position: int) -> tuple[ClipNote, ...]:
        position %= self.length_ticks
        return tuple(n for n in self.notes if n.tick == position)

    def with_note(self, note: ClipNote, quantize: bool = True) -> "Clip":
        tick = note.tick
        if quantize:
            tick = round(tick / QUANTIZE_TICKS) * QUANTIZE_TICKS
        note = replace(note, tick=tick % self.length_ticks)
        return replace(self, notes=tuple(sorted(
            self.notes + (note,), key=lambda n: (n.tick, n.note))))

    def with_length(self, bars: int) -> "Clip":
        bars = max(1, min(MAX_BARS, int(bars)))
        length = bars * TICKS_PER_BAR
        folded = tuple(sorted(
            (replace(n, tick=n.tick % length) for n in self.notes),
            key=lambda n: (n.tick, n.note)))
        return replace(self, notes=folded, length_ticks=length)

    def shaped(self, note: ClipNote, intensity: float = 1.0) -> tuple[int,
                                                                      int]:
        """(pitch, velocity) after the clip's transpose/scale and the global
        scene intensity. Clamped, never dropped — a launched clip plays."""
        pitch = max(0, min(127, note.note + self.transpose))
        velocity = max(1, min(127, round(note.velocity
                                         * self.velocity_scale
                                         * max(0.1, intensity))))
        return pitch, velocity

    def to_config(self) -> dict:
        return {"length_ticks": self.length_ticks, "follow": self.follow,
                "follow_loops": self.follow_loops,
                "follow_probability": self.follow_probability,
                "velocity_scale": self.velocity_scale,
                "transpose": self.transpose,
                "notes": [n.to_config() for n in self.notes]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Clip":
        raw = raw or {}
        notes = tuple(sorted(
            (ClipNote.from_config(n) for n in raw.get("notes") or ()),
            key=lambda n: (n.tick, n.note)))
        fields = {k: raw[k] for k in ("follow", "follow_loops",
                                      "follow_probability",
                                      "velocity_scale", "transpose")
                  if k in raw}
        return cls(notes=notes,
                   length_ticks=max(1, int(raw.get("length_ticks",
                                                   TICKS_PER_BAR))),
                   **fields).normalised()
