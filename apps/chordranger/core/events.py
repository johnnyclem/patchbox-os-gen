"""MIDI event model. Ticks at PPQN=96 are the only time unit in the engine.

Stored music (phrases, chord tracks) uses ``NOTE``, an *interval* carrying its
own length. Note-offs are derived by the scheduler and never written down: a
held chord whose off got lost in an edit is the single most common way a MIDI
instrument ends up screaming, and a model with no note-off to lose cannot do
it.

``NOTE_ON``/``NOTE_OFF`` exist only at the wire boundary — what the engine
emits and what arrives from a keyboard.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

PPQN = 96                       # ticks per quarter note
TICKS_PER_16TH = PPQN // 4
BEATS_PER_BAR = 4               # 4/4 only for now; the arranger assumes it
TICKS_PER_BAR = PPQN * BEATS_PER_BAR


class EventKind(Enum):
    NOTE = auto()               # interval, uses length_ticks — the stored form
    NOTE_ON = auto()            # wire only
    NOTE_OFF = auto()           # wire only
    CC = auto()
    PROGRAM = auto()
    PITCH_BEND = auto()


WIRE_KINDS = frozenset({EventKind.NOTE_ON, EventKind.NOTE_OFF, EventKind.CC,
                        EventKind.PROGRAM, EventKind.PITCH_BEND})


@dataclass(frozen=True, slots=True)
class MidiEvent:
    """One event. ``tick`` is relative to whatever contains it — a phrase's
    start, or the transport, depending on who is holding it."""

    kind: EventKind
    tick: int = 0
    channel: int = 0            # 0-15
    data1: int = 0              # note number / cc number / program
    data2: int = 0              # velocity / cc value
    length_ticks: int = 0       # NOTE only

    def __post_init__(self) -> None:
        if self.kind is EventKind.NOTE and self.length_ticks <= 0:
            raise ValueError("NOTE events need length_ticks > 0")
        if self.kind in (EventKind.NOTE_ON, EventKind.NOTE_OFF) \
                and self.length_ticks:
            raise ValueError("wire note edges carry no length")


def note_on(channel: int, note: int, velocity: int) -> MidiEvent:
    return MidiEvent(EventKind.NOTE_ON, 0, channel, note, velocity)


def note_off(channel: int, note: int) -> MidiEvent:
    return MidiEvent(EventKind.NOTE_OFF, 0, channel, note, 0)


def bars_to_ticks(bars: float) -> int:
    return int(round(bars * TICKS_PER_BAR))


def ticks_to_bar_beat(tick: int) -> tuple[int, int, int]:
    """(bar, beat, tick-in-beat), all 0-based — the transport readout's
    source. The panel adds one to each because musicians count from one and
    the code does not."""
    bar, rest = divmod(max(0, tick), TICKS_PER_BAR)
    beat, sub = divmod(rest, PPQN)
    return bar, beat, sub
