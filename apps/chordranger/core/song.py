"""The chord track — a song as a list of chord changes.

This is the QY's Chord track, and it is deliberately not a sequencer. There
are no notes in a song: there are chords, positioned in bars and beats, and
section markers saying which part of the style is playing. Everything you
hear is generated from those two things plus the style, which is why a
four-minute arrangement is a few hundred bytes and why changing the style
re-arranges the whole song instead of replacing half of it.

Positions are (bar, beat) rather than raw ticks because that is how chord
changes are written down and how a player enters them. Ticks appear once, in
``tick_of``, and never leak into the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.chords import Chord, parse_chord
from core.events import BEATS_PER_BAR, PPQN, TICKS_PER_BAR
from core.style import MAIN_A, SECTION_ORDER


@dataclass(frozen=True, slots=True)
class ChordStep:
    """One change: a chord, optionally a section change, at bar/beat.

    ``section`` empty means "keep playing whatever section we are in", which
    is the common case — most changes are harmonic, not formal.
    """

    bar: int
    beat: int = 0
    chord: Chord = field(default_factory=Chord)
    section: str = ""

    @property
    def tick(self) -> int:
        return self.bar * TICKS_PER_BAR + self.beat * PPQN

    def to_dict(self) -> dict:
        data: dict = {"bar": self.bar, "beat": self.beat,
                      "root": self.chord.root, "quality": self.chord.quality}
        if self.chord.bass is not None:
            data["bass"] = self.chord.bass
        if self.chord.notes:
            data["notes"] = list(self.chord.notes)
        if self.section:
            data["section"] = self.section
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ChordStep":
        chord = Chord(root=int(data.get("root", 0)),
                      quality=str(data.get("quality", "maj")),
                      bass=(None if data.get("bass") is None
                            else int(data["bass"])),
                      notes=tuple(int(n) for n in data.get("notes", ())))
        return cls(bar=int(data.get("bar", 0)), beat=int(data.get("beat", 0)),
                   chord=chord, section=str(data.get("section", "")))


@dataclass(frozen=True, slots=True)
class Song:
    """An arrangement: ordered chord steps over a fixed number of bars."""

    name: str = "SONG"
    steps: tuple[ChordStep, ...] = ()
    bars: int = 8
    loop: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps",
                           tuple(sorted(self.steps,
                                        key=lambda s: (s.bar, s.beat))))
        object.__setattr__(self, "bars", max(1, self.bars))

    # --- reading -------------------------------------------------------------
    def step_at(self, bar: int, beat: int = 0) -> ChordStep | None:
        """The change in force at this position — the latest one at or before
        it. A song whose first change is in bar 3 has no chord before then,
        and says so rather than inventing a C."""
        found: ChordStep | None = None
        for step in self.steps:
            if (step.bar, step.beat) <= (bar, beat):
                found = step
            else:
                break
        return found

    def chord_at(self, bar: int, beat: int = 0) -> Chord | None:
        step = self.step_at(bar, beat)
        return None if step is None else step.chord

    def next_chord_after(self, bar: int, beat: int = 0) -> Chord | None:
        """The chord the song moves to next — the lookahead the walking bass
        needs. Wraps to the first change when the song loops, because bar 8
        of a looping song really is followed by bar 1."""
        for step in self.steps:
            if (step.bar, step.beat) > (bar, beat):
                return step.chord
        if self.loop and self.steps:
            return self.steps[0].chord
        return None

    def section_at(self, bar: int, beat: int = 0) -> str:
        """The most recent section marker at or before this position."""
        section = ""
        for step in self.steps:
            if (step.bar, step.beat) <= (bar, beat):
                if step.section:
                    section = step.section
            else:
                break
        return section

    def markers(self) -> tuple[tuple[int, str], ...]:
        """(bar, section) for every section change — what the Song screen's
        ruler draws."""
        return tuple((s.bar, s.section) for s in self.steps if s.section)

    @property
    def empty(self) -> bool:
        return not self.steps

    # --- editing -------------------------------------------------------------
    def with_step(self, step: ChordStep) -> "Song":
        """Add or replace the change at that position, growing the song if the
        change lands past its end — entering a chord in bar 12 of an 8-bar
        song means the song is now 12 bars long, not that the change is lost.
        """
        kept = tuple(s for s in self.steps
                     if (s.bar, s.beat) != (step.bar, step.beat))
        return replace(self, steps=kept + (step,),
                       bars=max(self.bars, step.bar + 1))

    def without_step(self, bar: int, beat: int = 0) -> "Song":
        return replace(self, steps=tuple(
            s for s in self.steps if (s.bar, s.beat) != (bar, beat)))

    def cleared(self) -> "Song":
        return replace(self, steps=())

    def transposed(self, semitones: int) -> "Song":
        return replace(self, steps=tuple(
            replace(s, chord=s.chord.transposed(semitones))
            for s in self.steps))

    # --- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {"name": self.name, "bars": self.bars, "loop": self.loop,
                "steps": [s.to_dict() for s in self.steps]}

    @classmethod
    def from_dict(cls, data: dict) -> "Song":
        return cls(name=str(data.get("name", "SONG")),
                   bars=int(data.get("bars", 8)),
                   loop=bool(data.get("loop", True)),
                   steps=tuple(ChordStep.from_dict(s)
                               for s in data.get("steps", ())))


def from_symbols(symbols: list[str], name: str = "SONG",
                 bars_each: int = 1, section: str = MAIN_A) -> Song:
    """A song from written chord symbols, one every *bars_each* bars.

    The first step carries the section marker so a song built this way starts
    the band in a defined place rather than wherever the arranger happened to
    be left.
    """
    steps: list[ChordStep] = []
    for index, symbol in enumerate(symbols):
        if not symbol:
            continue
        steps.append(ChordStep(bar=index * bars_each, beat=0,
                               chord=parse_chord(symbol),
                               section=section if index == 0 else ""))
    return Song(name=name, steps=tuple(steps),
                bars=max(1, len(symbols) * bars_each))


def valid_section(name: str) -> bool:
    return name in SECTION_ORDER


def quantize_position(tick: int, grid_beats: int = BEATS_PER_BAR
                      ) -> tuple[int, int]:
    """Snap a live tick to the nearest chord-entry position.

    Recording the chord track live is a real workflow — tap pads over the
    metronome, keep the take — and a change entered 40 ms early must land on
    the downbeat it was aimed at, not a beat before it.
    """
    grid = PPQN * max(1, grid_beats)
    snapped = ((tick + grid // 2) // grid) * grid
    bar, rest = divmod(snapped, TICKS_PER_BAR)
    return bar, rest // PPQN
