"""Styles — the QY backing band.

A **style** is a band: a set of parts (drums, bass, chord, and a couple of
melodic voices) and, for each of six **sections**, one phrase per part. The
sections are the QY set, and they are six rather than "as many patterns as you
like" on purpose — Intro, Main A, Fill AB, Main B, Fill BA, Ending is a shape
a player can drive with two buttons while both hands are busy:

    INTRO ─▶ MAIN A ──FILL AB──▶ MAIN B ──FILL BA──▶ MAIN A ─▶ ENDING

A **phrase** is written once, in C, over the quality its author had in mind,
and then bent onto whatever chord is current. That bending is the whole trick
of an auto-accompaniment (Yamaha called theirs ABC / note transposition), and
it is the difference between a backing track and a band: a bassline written
over Cmaj7 must land on the right notes over F#m7b5 without anybody writing a
second bassline.

The bending rule is per part, because the parts want different things:

| rule          | what it does                              | who uses it   |
|---------------|-------------------------------------------|---------------|
| ``fixed``     | nothing at all                            | drums         |
| ``root``      | every note becomes the chord's bass note  | simple bass   |
| ``chord_tone``| snap to the nearest tone of the chord      | chords, bass  |
| ``scale``     | transpose, then snap into the key's scale | melodic lines |
| ``parallel``  | transpose by the root delta, unaltered    | riffs, stabs  |

``parallel`` is the honest name for "do what a guitarist does": move the shape
and let the harmony take care of itself. It sounds wrong over a chord that is
not a plain triad, which is exactly when a style author should pick something
else — so the rule is stored per phrase and can be overridden per part.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.chords import Chord, chord_tone_near
from core.events import PPQN, TICKS_PER_16TH, TICKS_PER_BAR
from core.theory import Scale, scale_for, snap_to_scale

# --- sections -----------------------------------------------------------------

INTRO, MAIN_A, FILL_AB, MAIN_B, FILL_BA, ENDING = (
    "intro", "main_a", "fill_ab", "main_b", "fill_ba", "ending")

SECTION_ORDER = (INTRO, MAIN_A, FILL_AB, MAIN_B, FILL_BA, ENDING)
SECTION_LABELS = {INTRO: "INTRO", MAIN_A: "MAIN A", FILL_AB: "FILL AB",
                  MAIN_B: "MAIN B", FILL_BA: "FILL BA", ENDING: "ENDING"}
# The QY70's own lengths. A fill is one bar because it has to fit in the bar
# before the change; an ending is long because it is a cadence, not a stop.
SECTION_BARS = {INTRO: 2, MAIN_A: 2, FILL_AB: 1, MAIN_B: 4, FILL_BA: 1,
                ENDING: 2}
MAIN_SECTIONS = (MAIN_A, MAIN_B)
FILL_SECTIONS = (FILL_AB, FILL_BA)
# Which main a fill hands over to. Kept as data so the arranger never has to
# know that "AB" means "A then B".
FILL_TARGET = {FILL_AB: MAIN_B, FILL_BA: MAIN_A}
FILL_FOR = {(MAIN_A, MAIN_B): FILL_AB, (MAIN_B, MAIN_A): FILL_BA}

# --- conversion rules ---------------------------------------------------------

FIXED, ROOT, CHORD_TONE, SCALE, PARALLEL = (
    "fixed", "root", "chord_tone", "scale", "parallel")
CONVERSIONS = (FIXED, ROOT, CHORD_TONE, SCALE, PARALLEL)

# --- parts --------------------------------------------------------------------

DRUM_CHANNEL = 9                # GM percussion, channel 10 in one-based counting

ROLE_DRUM, ROLE_BASS, ROLE_CHORD, ROLE_PHRASE = ("drum", "bass", "chord",
                                                 "phrase")


@dataclass(frozen=True, slots=True)
class Part:
    """One member of the band.

    ``channel`` is where it plays; ``program`` is sent once when a style is
    loaded (0-127, or -1 to leave the target's patch alone — which is what
    anyone driving a synth they have already dialled in will want).
    """

    id: str
    name: str
    role: str = ROLE_PHRASE
    channel: int = 0
    program: int = -1
    conversion: str = CHORD_TONE
    octave: int = 0
    velocity: int = 100         # scales the phrase's own velocities, 0-127
    muted: bool = False
    level: int = 100            # 0-127, sent as CC7 on load when >= 0

    @property
    def is_drum(self) -> bool:
        return self.role == ROLE_DRUM


@dataclass(frozen=True, slots=True)
class PhraseNote:
    """A note inside a phrase, written in the phrase's source key."""

    tick: int
    note: int
    velocity: int = 100
    length: int = TICKS_PER_16TH

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError("phrase notes need a positive length")


@dataclass(frozen=True, slots=True)
class Phrase:
    """One part's music for one section.

    ``source_root`` and ``source_quality`` say what the notes were written
    over. Everything is written over C in the factory data, but the field
    exists so an imported phrase does not have to be transposed on the way in
    — losing the information that it was conceived in F.
    """

    notes: tuple[PhraseNote, ...] = ()
    bars: int = 1
    conversion: str = ""        # "" = inherit the part's rule
    source_root: int = 0
    source_quality: str = "maj"

    @property
    def ticks(self) -> int:
        return self.bars * TICKS_PER_BAR

    def rule(self, part: Part) -> str:
        return self.conversion or part.conversion

    def at(self, tick: int) -> tuple[PhraseNote, ...]:
        """Notes starting exactly on *tick* within the phrase.

        Linear, because a phrase is a handful of notes and the tick loop runs
        at 96 PPQN — an index here would be optimising the wrong thing and
        would need invalidating on every edit.
        """
        return tuple(n for n in self.notes if n.tick == tick)


@dataclass(frozen=True, slots=True)
class Section:
    """One section of a style: a phrase per part id."""

    name: str
    bars: int = 1
    phrases: dict[str, Phrase] = field(default_factory=dict)

    @property
    def ticks(self) -> int:
        return self.bars * TICKS_PER_BAR

    def phrase_for(self, part_id: str) -> Phrase | None:
        return self.phrases.get(part_id)


@dataclass(frozen=True, slots=True)
class Style:
    """A band, its six sections, and the tempo it was written at."""

    name: str = "INIT"
    bpm: float = 110.0
    parts: tuple[Part, ...] = ()
    sections: dict[str, Section] = field(default_factory=dict)
    genre: str = ""
    swing: int = 0              # 0-100 %, applied to off-16ths by the engine

    def part(self, part_id: str) -> Part | None:
        for item in self.parts:
            if item.id == part_id:
                return item
        return None

    def section(self, name: str) -> Section | None:
        return self.sections.get(name)

    def has(self, name: str) -> bool:
        section = self.sections.get(name)
        return section is not None and bool(section.phrases)

    def with_part(self, part: Part) -> "Style":
        parts = tuple(part if p.id == part.id else p for p in self.parts)
        return replace(self, parts=parts)


# --- chord conversion ---------------------------------------------------------

def convert_note(note: int, chord: Chord, rule: str, scale: Scale,
                 key_root: int = 0, source_root: int = 0) -> int:
    """Bend one phrase note onto *chord* — the heart of the backing band.

    All rules except ``fixed`` first transpose by the root delta, so a phrase
    keeps its shape; they differ in what they do afterwards about the notes
    that shape lands on.
    """
    if rule == FIXED:
        return note
    delta = (chord.root - source_root) % 12
    # Move by the shorter way round: a phrase written in C played over B
    # should drop a semitone, not climb eleven and take the whole line with it.
    if delta > 6:
        delta -= 12
    moved = note + delta
    if rule == ROOT:
        # Keep the phrase's register, take the chord's bass note. This is what
        # makes a one-note-per-bar bass part follow a slash chord correctly.
        octave = moved - (moved % 12)
        candidate = octave + chord.bass_pc
        if candidate - moved > 6:
            candidate -= 12
        elif moved - candidate > 5:
            candidate += 12
        return candidate
    if rule == CHORD_TONE:
        return chord_tone_near(chord, moved)
    if rule == SCALE:
        return snap_to_scale(moved, key_root, scale)
    return moved                        # PARALLEL


def render_phrase(phrase: Phrase, part: Part, chord: Chord, scale_name: str,
                  key_root: int = 0) -> tuple[tuple[int, int, int, int], ...]:
    """The whole phrase over one chord, as (tick, note, velocity, length).

    A plain tuple rather than MidiEvents because this is called from the tick
    loop's neighbourhood and the caller wants to add its own channel, octave
    and velocity scaling without rebuilding a frozen dataclass per note.
    """
    scale = scale_for(scale_name)
    rule = phrase.rule(part)
    out = []
    for item in phrase.notes:
        note = convert_note(item.note, chord, rule, scale, key_root,
                            phrase.source_root)
        note += 12 * part.octave
        if not 0 <= note <= 127:
            continue
        velocity = max(1, min(127, item.velocity * part.velocity // 100))
        out.append((item.tick, note, velocity, item.length))
    return tuple(out)


# --- authoring helpers --------------------------------------------------------

def steps(pattern: str, note: int, velocity: int = 100,
          length: int = TICKS_PER_16TH, grid: int = TICKS_PER_16TH,
          accent: int = 18) -> tuple[PhraseNote, ...]:
    """Write a phrase line as a step string.

    ``"x..x..x..x..x..."`` is a 16-step bar. ``X`` is an accent, ``x`` a
    normal hit, ``-`` extends the previous note by one step, and ``.`` is a
    rest. Being able to read a groove as a row of characters is why the
    factory styles are legible at all.
    """
    out: list[PhraseNote] = []
    index = 0
    for char in pattern:
        if char in "xX":
            hit = velocity + (accent if char == "X" else 0)
            out.append(PhraseNote(tick=index * grid, note=note,
                                  velocity=max(1, min(127, hit)),
                                  length=length))
        elif char == "-" and out:
            last = out[-1]
            out[-1] = replace(last, length=last.length + grid)
        elif char not in ".":
            raise ValueError(f"bad step character {char!r} in {pattern!r}")
        index += 1                      # every character is one grid step
    return tuple(out)


def merge(*lines: tuple[PhraseNote, ...]) -> tuple[PhraseNote, ...]:
    """Combine step lines into one phrase body, ordered by tick."""
    notes: list[PhraseNote] = []
    for line in lines:
        notes.extend(line)
    return tuple(sorted(notes, key=lambda n: (n.tick, n.note)))


def repeat(notes: tuple[PhraseNote, ...], times: int,
           span: int = TICKS_PER_BAR) -> tuple[PhraseNote, ...]:
    """Repeat a one-bar body across *times* bars."""
    out: list[PhraseNote] = []
    for bar in range(max(1, times)):
        out.extend(replace(n, tick=n.tick + bar * span) for n in notes)
    return tuple(out)


def swing_tick(tick: int, amount: int, grid: int = TICKS_PER_16TH) -> int:
    """Delay off-grid steps by *amount* percent of half a grid unit.

    50 % is a triplet feel, 0 % is straight. Applied at render time rather
    than baked into phrases so a style's swing is a knob and not a rewrite.
    """
    if amount <= 0:
        return tick
    if (tick // grid) % 2 == 0:
        return tick
    return tick + (grid * min(100, amount)) // 200


def chord_hits(pattern: str, velocity: int = 96,
               length: int = PPQN // 2) -> tuple[PhraseNote, ...]:
    """A rhythm for the chord part, written on middle C.

    The note value is irrelevant — ``chord_tone`` conversion will move it onto
    the chord — but it has to be *somewhere*, and middle C keeps a phrase
    readable if anybody opens the JSON.
    """
    return steps(pattern, note=60, velocity=velocity, length=length)
