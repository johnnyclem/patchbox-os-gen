"""Commands in, snapshots out — the only contract between GUI and engine.

The GUI never touches engine state. It posts immutable ``Command`` values onto
a queue the tick thread drains once per tick, and it renders the immutable
``EngineSnapshot`` the tick thread publishes once per frame. Two consequences
make this worth the ceremony:

* the engine has no locks, because nothing else writes to it; and
* the GUI can die — crash, be closed, be run under a test harness that never
  draws a pixel — without the music stopping. On an instrument that plays
  live, that is not a nicety.

Every command is a frozen dataclass with no methods. Behaviour belongs to the
engine, which is the only thing that knows whether a request is currently
legal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.bass import BassSpec
from core.chords import Chord, VoicingSpec
from core.chordset import Chordset
from core.song import ChordStep, Song
from core.style import Style

# --- transport ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Play:
    """Start. ``section`` empty means "wherever the arranger already is"."""
    section: str = ""


@dataclass(frozen=True, slots=True)
class Stop:
    pass


@dataclass(frozen=True, slots=True)
class TogglePlay:
    pass


@dataclass(frozen=True, slots=True)
class Panic:
    """All notes off on every channel. Never queued, never quantised."""


@dataclass(frozen=True, slots=True)
class SetTempo:
    bpm: float


@dataclass(frozen=True, slots=True)
class NudgeTempo:
    delta: float


@dataclass(frozen=True, slots=True)
class SetMetronome:
    on: bool


# --- harmony ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PadDown:
    """A touch key went down. ``velocity`` 0 means the panel, which has no
    velocity; a MIDI trigger passes its own."""
    index: int
    velocity: int = 0


@dataclass(frozen=True, slots=True)
class PadUp:
    index: int


@dataclass(frozen=True, slots=True)
class SetChord:
    """Set the current chord directly — MIDI chord detection, the song track,
    or the cruiser auditioning a suggestion."""
    chord: Chord
    latch: bool = True


@dataclass(frozen=True, slots=True)
class SetLatch:
    """Latched: a pad tap holds until the next one. Unlatched: the chord
    lasts as long as the finger does."""
    on: bool


@dataclass(frozen=True, slots=True)
class SetKey:
    root: int
    scale: str = ""


@dataclass(frozen=True, slots=True)
class TransposeChordset:
    semitones: int


@dataclass(frozen=True, slots=True)
class SetChordset:
    chordset: Chordset


@dataclass(frozen=True, slots=True)
class SetPad:
    """Chord Edit's commit: replace one pad's chord."""
    index: int
    chord: Chord


@dataclass(frozen=True, slots=True)
class TransposePad:
    index: int
    semitones: int


# --- band ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestSection:
    name: str


@dataclass(frozen=True, slots=True)
class SetStyle:
    style: Style


@dataclass(frozen=True, slots=True)
class SetVoicing:
    spec: VoicingSpec


@dataclass(frozen=True, slots=True)
class SetBass:
    spec: BassSpec


@dataclass(frozen=True, slots=True)
class SetStrum:
    ticks: int


@dataclass(frozen=True, slots=True)
class SetPartMute:
    part_id: str
    muted: bool


@dataclass(frozen=True, slots=True)
class SetPartField:
    """One numeric field of a part — octave, velocity, channel, level. A
    single command rather than four keeps the mixer screen's plumbing to one
    line per control."""
    part_id: str
    field: str
    value: int


# --- song ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SetSongMode:
    on: bool


@dataclass(frozen=True, slots=True)
class SetSong:
    song: Song


@dataclass(frozen=True, slots=True)
class WriteChordStep:
    step: ChordStep


@dataclass(frozen=True, slots=True)
class EraseChordStep:
    bar: int
    beat: int = 0


@dataclass(frozen=True, slots=True)
class SetRecord:
    """Arm chord-track recording: pad taps are written to the song at the
    quantised position while the transport runs."""
    on: bool


@dataclass(frozen=True, slots=True)
class Locate:
    """Jump the song position, in bars."""
    bar: int


# --- I/O ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BindOutput:
    endpoint_id: str
    port_name: str


@dataclass(frozen=True, slots=True)
class UnbindOutput:
    endpoint_id: str


@dataclass(frozen=True, slots=True)
class SetClockOut:
    on: bool


Command = object                # structural: the engine dispatches on type


# --- snapshot -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartView:
    """One part as the mixer draws it."""

    id: str
    name: str
    role: str
    channel: int
    muted: bool
    velocity: int
    octave: int
    active: int = 0             # notes currently sounding, for the meter


@dataclass(frozen=True, slots=True)
class EngineSnapshot:
    """Everything the panel needs for one frame. Immutable and self-contained:
    a screen holding one from three frames ago still renders consistently."""

    playing: bool = False
    recording: bool = False
    bpm: float = 110.0
    tick: int = 0
    bar: int = 0
    beat: int = 0
    section: str = "main_a"
    next_section: str = ""
    section_bar: int = 0
    section_bars: int = 1
    chord_symbol: str = ""
    chord: Chord | None = None
    next_chord_symbol: str = ""
    held_pad: int = -1
    latch: bool = True
    key_root: int = 0
    scale: str = "major"
    style_name: str = ""
    chordset_name: str = ""
    pad_captions: tuple[str, ...] = ()
    pad_numerals: tuple[str, ...] = ()
    pad_active: tuple[bool, ...] = ()
    # The pads' actual chords, not just their captions: the chord editor needs
    # the real interval set, and a hand-edited chord cannot be recovered by
    # parsing "Cmaj7*" back. Chords are frozen, so this shares rather than
    # copies.
    pad_chords: tuple = ()
    parts: tuple[PartView, ...] = ()
    voicing: VoicingSpec = field(default_factory=VoicingSpec)
    bass: BassSpec = field(default_factory=BassSpec)
    strum: int = 0
    song_mode: bool = False
    song_bar: int = 0
    song_bars: int = 8
    song_name: str = ""
    # The song flattened to one (chord, section marker) pair per bar. The
    # Song screen draws a grid of bars, and asking it to walk a list of
    # changes per cell per frame would put song-model logic in a renderer.
    song_bars_view: tuple = ()
    chord_notes: tuple[int, ...] = ()
    metronome: bool = False
    clock_out: bool = False
    backend: str = "null"
    output_bound: bool = False
    voices: int = 0             # notes sounding across all parts
    late_ticks: int = 0         # ticks the RT loop woke up late for
    message: str = ""
