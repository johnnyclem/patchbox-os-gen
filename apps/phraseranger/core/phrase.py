"""The phrase — a loop of notes, immutable, tick-domain.

Everything a looper does to material — overdub, undo, reverse, stretch,
decay, slice, transpose — is a pure function from one phrase to another.
That single decision buys the whole feature list: multi-level undo is a
stack of old phrases, scenes are dicts of phrases, and no operation can
corrupt what is currently sounding because nothing is ever edited in place.

A note's position is a tick inside the loop (0 ≤ tick < length_ticks).
Channel is *not* stored: the track's routing owns channel and destination,
so a phrase moved between tracks follows its new home's plumbing.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import PPQN, TICKS_PER_BAR

QUANTIZE_TICKS = PPQN // 4      # a sixteenth
MIN_VELOCITY = 4                # decay floor: quieter than this, the note dies
MAX_BARS = 8


@dataclass(frozen=True, slots=True)
class PhraseNote:
    tick: int
    note: int
    velocity: int
    length_ticks: int

    def to_config(self) -> dict:
        return {"tick": self.tick, "note": self.note,
                "velocity": self.velocity, "length": self.length_ticks}

    @classmethod
    def from_config(cls, raw: dict) -> "PhraseNote":
        return cls(tick=int(raw.get("tick", 0)),
                   note=max(0, min(127, int(raw.get("note", 60)))),
                   velocity=max(1, min(127, int(raw.get("velocity", 96)))),
                   length_ticks=max(1, int(raw.get("length", PPQN // 2))))


@dataclass(frozen=True, slots=True)
class Phrase:
    """A loop. ``notes`` is kept sorted by tick — the engine walks it."""

    notes: tuple[PhraseNote, ...] = ()
    length_ticks: int = TICKS_PER_BAR

    @property
    def bars(self) -> int:
        return max(1, self.length_ticks // TICKS_PER_BAR)

    @property
    def empty(self) -> bool:
        return not self.notes

    def notes_at(self, tick: int) -> tuple[PhraseNote, ...]:
        position = tick % self.length_ticks
        return tuple(n for n in self.notes if n.tick == position)

    # --- the looper's verbs, all pure ----------------------------------------
    def with_note(self, note: PhraseNote,
                  quantize: bool = False) -> "Phrase":
        if quantize:
            snapped = round(note.tick / QUANTIZE_TICKS) * QUANTIZE_TICKS
            note = replace(note, tick=snapped % self.length_ticks)
        else:
            note = replace(note, tick=note.tick % self.length_ticks)
        return replace(self, notes=tuple(sorted(
            self.notes + (note,), key=lambda n: (n.tick, n.note))))

    def reversed(self) -> "Phrase":
        """Play the loop backwards: a note that *started* at t now *ends*
        there — mirror the onsets, keep the lengths."""
        flipped = tuple(sorted(
            (replace(n, tick=(self.length_ticks - n.tick - n.length_ticks)
                     % self.length_ticks) for n in self.notes),
            key=lambda n: (n.tick, n.note)))
        return replace(self, notes=flipped)

    def stretched(self, factor: float) -> "Phrase":
        """Note-level stretch: positions and lengths scale, the *loop length
        does not* — half-time fills two passes, double-time repeats. Notes
        stretched past the loop wrap; that is the tape splicing, audibly."""
        if factor <= 0:
            return self
        stretched = tuple(sorted(
            (replace(n, tick=round(n.tick * factor) % self.length_ticks,
                     length_ticks=max(1, round(n.length_ticks * factor)))
             for n in self.notes), key=lambda n: (n.tick, n.note)))
        return replace(self, notes=stretched)

    def transposed(self, semitones: int) -> "Phrase":
        kept = tuple(replace(n, note=n.note + semitones)
                     for n in self.notes
                     if 0 <= n.note + semitones <= 127)
        return replace(self, notes=kept)

    def decayed(self, factor: float) -> "Phrase":
        """One tape generation: velocities scale, whispers die. This is what
        overdub feedback below 100% does to the old material each pass."""
        factor = max(0.0, min(1.0, factor))
        survivors = []
        for n in self.notes:
            velocity = round(n.velocity * factor)
            if velocity >= MIN_VELOCITY:
                survivors.append(replace(n, velocity=velocity))
        return replace(self, notes=tuple(survivors))

    def with_length(self, bars: int) -> "Phrase":
        """Change the loop length. Shrinking *keeps* out-of-range notes'
        positions modulo the new length rather than deleting them — a loop
        halved should fold, not lose half the take."""
        bars = max(1, min(MAX_BARS, int(bars)))
        length = bars * TICKS_PER_BAR
        folded = tuple(sorted(
            (replace(n, tick=n.tick % length) for n in self.notes),
            key=lambda n: (n.tick, n.note)))
        return replace(self, notes=folded, length_ticks=length)

    def window(self, start: int, span: int) -> "Phrase":
        """The sub-loop [start, start+span) as its own phrase, rebased to 0 —
        what a slice pad holds."""
        picked = tuple(sorted(
            (replace(n, tick=n.tick - start) for n in self.notes
             if start <= n.tick < start + span),
            key=lambda n: (n.tick, n.note)))
        return Phrase(notes=picked, length_ticks=max(1, span))

    # --- persistence ----------------------------------------------------------
    def to_config(self) -> dict:
        return {"length_ticks": self.length_ticks,
                "notes": [n.to_config() for n in self.notes]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Phrase":
        raw = raw or {}
        length = max(1, int(raw.get("length_ticks", TICKS_PER_BAR)))
        notes = tuple(sorted(
            (PhraseNote.from_config(n) for n in raw.get("notes") or ()),
            key=lambda n: (n.tick, n.note)))
        return cls(notes=notes, length_ticks=length)
