"""Pitch, scale and key vocabulary — the layer everything else agrees on.

Two number spaces run through every Ranger app and mixing them is the classic bug:

* a **pitch class** is 0-11, C=0, with no octave. Chords, scales and keys are
  all defined in pitch classes because "C major" is the same idea in every
  register.
* a **MIDI note** is 0-127, where 60 is middle C. Only the voicing layer
  (``core.chords``) and the engine deal in these.

``pc()`` is the one-way door between them. Nothing in this module allocates or
does I/O, so the whole harmony stack is importable — and testable — on a host
with no audio, no MIDI and no display.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- pitch classes ------------------------------------------------------------

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")

# Keys whose signature is flat-side. Spelling a chord root as Eb rather than D#
# is cosmetic to MIDI and load-bearing to a player reading the panel at speed,
# so the chord symbol formatter asks this table which set of names to use.
FLAT_KEYS = frozenset({1, 3, 5, 8, 10})     # Db, Eb, F, Ab, Bb

MIDDLE_C = 60


def pc(note: int) -> int:
    """Pitch class of a MIDI note (or of an already-reduced pitch class)."""
    return note % 12


def note_name(value: int, flats: bool = False) -> str:
    """Name a pitch class or MIDI note, without an octave number."""
    return (FLAT_NAMES if flats else SHARP_NAMES)[value % 12]


def note_label(midi: int, flats: bool = False) -> str:
    """Name a MIDI note *with* its octave, scientific pitch notation
    (middle C = C4, which is what a player expects to read even though the
    MIDI spec itself is famously silent on the matter)."""
    return f"{note_name(midi, flats)}{midi // 12 - 1}"


def parse_note(name: str) -> int:
    """Pitch class from a note name: ``"C"``, ``"Bb"``, ``"F#"``, ``"eb"``.

    Raises ValueError on anything else — a chord symbol with a typo in it
    should be rejected where it is written, not silently become C.
    """
    text = name.strip()
    if not text:
        raise ValueError("empty note name")
    letter = text[0].upper()
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}.get(letter)
    if base is None:
        raise ValueError(f"not a note name: {name!r}")
    for char in text[1:]:
        if char in "#♯":
            base += 1
        elif char in "b♭":
            base -= 1
        else:
            raise ValueError(f"not a note name: {name!r}")
    return base % 12


# --- scales -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Scale:
    """A mode as semitone offsets from its own tonic.

    ``brightness`` orders the pickers from darkest to brightest rather than
    alphabetically: turning a knob from Phrygian to Lydian should sound like
    a single continuous move, which is exactly what the modal brightness
    order gives you.
    """

    name: str
    label: str
    degrees: tuple[int, ...]
    brightness: int = 0

    def __len__(self) -> int:
        return len(self.degrees)

    def contains(self, pitch: int, root: int) -> bool:
        return (pitch - root) % 12 in self.degrees

    def pitches(self, root: int) -> tuple[int, ...]:
        """The scale's pitch classes, tonic first."""
        return tuple((root + d) % 12 for d in self.degrees)


SCALES: dict[str, Scale] = {s.name: s for s in (
    Scale("locrian", "LOCRIAN", (0, 1, 3, 5, 6, 8, 10), -3),
    Scale("phrygian", "PHRYGIAN", (0, 1, 3, 5, 7, 8, 10), -2),
    Scale("minor", "MINOR", (0, 2, 3, 5, 7, 8, 10), -1),
    Scale("harmonic_minor", "HARM MIN", (0, 2, 3, 5, 7, 8, 11), -1),
    Scale("melodic_minor", "MEL MIN", (0, 2, 3, 5, 7, 9, 11), 0),
    Scale("dorian", "DORIAN", (0, 2, 3, 5, 7, 9, 10), 0),
    Scale("mixolydian", "MIXOLYD", (0, 2, 4, 5, 7, 9, 10), 1),
    Scale("major", "MAJOR", (0, 2, 4, 5, 7, 9, 11), 2),
    Scale("lydian", "LYDIAN", (0, 2, 4, 6, 7, 9, 11), 3),
    Scale("pent_minor", "PENT MIN", (0, 3, 5, 7, 10), -1),
    Scale("pent_major", "PENT MAJ", (0, 2, 4, 7, 9), 2),
    Scale("blues", "BLUES", (0, 3, 5, 6, 7, 10), -1),
    Scale("chroma", "CHROMA", tuple(range(12)), 0),
)}

# Chord Edit works in C/chroma exactly as the Chordcat manual specifies, so an
# edited chord is a set of intervals and never a key-relative idea.
EDIT_SCALE = "chroma"
DEFAULT_SCALE = "major"

SCALE_NAMES = tuple(sorted(SCALES, key=lambda n: (SCALES[n].brightness, n)))


def scale_for(name: str) -> Scale:
    """Look up a scale, falling back to major. Callers are config files and
    saved projects: an unknown name must not stop the instrument booting."""
    return SCALES.get(name, SCALES[DEFAULT_SCALE])


def snap_to_scale(note: int, root: int, scale: Scale, prefer_up: bool = False
                  ) -> int:
    """Nearest MIDI note inside *scale*, keeping the register.

    Ties break downward by default because a phrase note that has to move is
    usually a passing tone resolving into the chord below it; ``prefer_up``
    is for the bass walk-ups, where the opposite is true.
    """
    if scale.contains(note, root):
        return note
    for distance in range(1, 7):
        first, second = ((note + distance, note - distance) if prefer_up
                         else (note - distance, note + distance))
        if scale.contains(first, root):
            return first
        if scale.contains(second, root):
            return second
    return note                         # unreachable for any real scale


# --- degrees and roman numerals ----------------------------------------------

_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII")


def degree_of(pitch: int, root: int, scale: Scale) -> int | None:
    """Scale degree (0-based) of *pitch* in the key, or None if it is not in
    the scale. Used by the cruiser to reason functionally and by the GUI to
    label a pad with a numeral instead of a letter."""
    offset = (pitch - root) % 12
    try:
        return scale.degrees.index(offset)
    except ValueError:
        return None


def roman(degree: int, minor_quality: bool = False, symbol: str = "") -> str:
    """Roman numeral for a 0-based scale degree: ``0 -> "I"``, lower case when
    the chord on it is minor or diminished, with ``symbol`` appended (``"°"``,
    ``"7"``)."""
    numeral = _ROMAN[degree % 7]
    return (numeral.lower() if minor_quality else numeral) + symbol


def transpose_all(notes: tuple[int, ...], semitones: int) -> tuple[int, ...]:
    """Shift MIDI notes, clamped into the legal 0-127 range as a whole rather
    than per note: clamping individually would collapse a voicing's shape at
    the extremes, which sounds far worse than the chord simply not moving."""
    if not notes:
        return notes
    shifted = tuple(n + semitones for n in notes)
    low, high = min(shifted), max(shifted)
    if low < 0:
        shifted = tuple(n + 12 * ((-low + 11) // 12) for n in shifted)
    elif high > 127:
        shifted = tuple(n - 12 * ((high - 127 + 11) // 12) for n in shifted)
    return shifted
