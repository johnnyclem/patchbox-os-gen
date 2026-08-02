"""The chordset — twelve pads, one chord each (Chordcat's keyboard).

A chordset is the performance surface: the player's whole harmonic vocabulary
for a tune, laid out under twelve fingers so a progression is a sequence of
*taps*, not a sequence of decisions. Everything else in ChordRanger — the
arranger, the bass engine, the song's chord track — consumes chords; this is
where they come from.

Two design points worth stating, because both were arrived at the hard way in
the instruments this borrows from:

* A pad stores a **chord**, not a degree. Degrees are elegant and they break
  the moment a player wants a borrowed IV-minor sitting next to a secondary
  dominant, which is precisely the pad they reach for most. The key is kept
  alongside so the panel can still *print* a numeral.
* Transpose is per pad (manual v1.30 §Transpose) and the chordset also has a
  global key. They are separate because a player transposing one pad is
  fixing a chord, and a player transposing the set is moving the song.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from core.chords import Chord, parse_chord
from core.theory import DEFAULT_SCALE, note_name, roman, scale_for

PAD_COUNT = 12

SCHEMA_VERSION = 1

# The diatonic seventh qualities of each scale degree, by scale family. A
# chordset generated for a key should sound like that key immediately — a
# player who has to fix every pad before playing has been given homework, not
# an instrument.
_MAJOR_TRIADS = ("maj", "min", "min", "maj", "maj", "min", "dim")
_MAJOR_SEVENTHS = ("maj7", "min7", "min7", "maj7", "dom7", "min7", "min7b5")
_MINOR_TRIADS = ("min", "dim", "maj", "min", "min", "maj", "maj")
_MINOR_SEVENTHS = ("min7", "min7b5", "maj7", "min7", "min7", "maj7", "dom7")


@dataclass(frozen=True, slots=True)
class Pad:
    """One touch key.

    ``transpose`` is applied when the pad is *read*, never folded into the
    chord, so a player can walk a pad up five semitones and back down and get
    the chord they started with rather than an accumulation of rounding.
    """

    chord: Chord = field(default_factory=Chord)
    transpose: int = 0
    enabled: bool = True

    @property
    def resolved(self) -> Chord:
        return (self.chord.transposed(self.transpose) if self.transpose
                else self.chord)

    def to_dict(self) -> dict:
        data: dict = {"root": self.chord.root, "quality": self.chord.quality}
        if self.chord.bass is not None:
            data["bass"] = self.chord.bass
        if self.chord.notes:
            data["notes"] = list(self.chord.notes)
        if self.chord.label:
            data["label"] = self.chord.label
        if self.transpose:
            data["transpose"] = self.transpose
        if not self.enabled:
            data["enabled"] = False
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Pad":
        chord = Chord(root=int(data.get("root", 0)),
                      quality=str(data.get("quality", "maj")),
                      bass=(None if data.get("bass") is None
                            else int(data["bass"])),
                      notes=tuple(int(n) for n in data.get("notes", ())),
                      label=str(data.get("label", "")))
        return cls(chord=chord, transpose=int(data.get("transpose", 0)),
                   enabled=bool(data.get("enabled", True)))


@dataclass(frozen=True, slots=True)
class Chordset:
    """Twelve pads plus the key they were built for."""

    name: str = "INIT"
    root: int = 0
    scale: str = DEFAULT_SCALE
    pads: tuple[Pad, ...] = ()
    author: str = ""

    def __post_init__(self) -> None:
        pads = list(self.pads)[:PAD_COUNT]
        pads += [Pad(enabled=False) for _ in range(PAD_COUNT - len(pads))]
        object.__setattr__(self, "pads", tuple(pads))
        object.__setattr__(self, "root", self.root % 12)

    # --- reading -------------------------------------------------------------
    def chord_at(self, index: int) -> Chord | None:
        """The chord a tap on pad *index* means, or None for a dead pad."""
        if not 0 <= index < PAD_COUNT:
            return None
        pad = self.pads[index]
        return pad.resolved if pad.enabled else None

    def caption(self, index: int) -> str:
        chord = self.chord_at(index)
        return "" if chord is None else chord.symbol()

    def numeral(self, index: int) -> str:
        """Roman numeral for the pad *in this chordset's key*.

        A dominant seventh sitting a fifth above a degree of the key is
        labelled ``V/ii`` rather than by its own root: that is what it is
        doing, and "II7" tells a player nothing they cannot already read off
        the chord symbol beside it. A chord with no relationship to the key
        gets no numeral at all — blank is honest, and a wrong numeral on a
        panel being read at speed is worse than none.
        """
        chord = self.chord_at(index)
        if chord is None:
            return ""
        scale = scale_for(self.scale)
        offset = (chord.root - self.root) % 12
        diatonic_root = offset in scale.degrees
        if chord.quality in ("dom7", "dom9", "dom7b9", "dom7s9", "dom13") \
                and not chord.pitch_classes <= set(scale.pitches(self.root)):
            target = (chord.root + 5 - self.root) % 12
            if target in scale.degrees:
                index_of = scale.degrees.index(target)
                minor = _MAJOR_TRIADS[index_of % 7] in ("min", "dim") \
                    if self.scale == "major" else False
                return "V/" + roman(index_of, minor)
        if not diatonic_root:
            return ""
        degree = scale.degrees.index(offset)
        suffix = "°" if chord.quality in ("dim", "dim7", "min7b5") else ""
        return roman(degree, chord.minor, suffix)

    # --- editing -------------------------------------------------------------
    def with_pad(self, index: int, pad: Pad) -> "Chordset":
        pads = list(self.pads)
        pads[index] = pad
        return replace(self, pads=tuple(pads))

    def with_chord(self, index: int, chord: Chord) -> "Chordset":
        return self.with_pad(index, replace(self.pads[index], chord=chord,
                                            enabled=True))

    def transposed_pad(self, index: int, semitones: int) -> "Chordset":
        """Chordcat's hold-a-pad-and-press-</> gesture."""
        pad = self.pads[index]
        return self.with_pad(index, replace(
            pad, transpose=max(-24, min(24, pad.transpose + semitones))))

    def transposed(self, semitones: int) -> "Chordset":
        """Move the whole set — the song changed key, the layout did not."""
        return replace(self, root=(self.root + semitones) % 12,
                       pads=tuple(replace(p, chord=p.chord.transposed(
                           semitones)) for p in self.pads))

    # --- persistence ---------------------------------------------------------
    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "name": self.name,
                "root": self.root, "scale": self.scale, "author": self.author,
                "pads": [p.to_dict() for p in self.pads]}

    @classmethod
    def from_dict(cls, data: dict) -> "Chordset":
        return cls(name=str(data.get("name", "INIT")),
                   root=int(data.get("root", 0)),
                   scale=str(data.get("scale", DEFAULT_SCALE)),
                   author=str(data.get("author", "")),
                   pads=tuple(Pad.from_dict(p) for p in data.get("pads", ())))

    def save(self, path: Path) -> None:
        """Atomic write: a chordset saved while the transport is running must
        never be found half-written after a power cut on stage."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Chordset":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# --- generated sets -----------------------------------------------------------

def diatonic(root: int = 0, scale: str = DEFAULT_SCALE, sevenths: bool = False,
             name: str = "") -> Chordset:
    """The seven diatonic chords, then five useful outsiders.

    Pads 8-12 are where a generated set earns its keep: a secondary dominant
    of V, the minor iv (or major IV in a minor key), a bVII, a sus4 on the
    tonic and the relative's tonic. Those five are the chords a player reaches
    for first when the diatonic seven run out.
    """
    scale_obj = scale_for(scale)
    minor_key = scale in ("minor", "harmonic_minor", "phrygian", "dorian",
                          "pent_minor", "blues")
    if sevenths:
        qualities = _MINOR_SEVENTHS if minor_key else _MAJOR_SEVENTHS
    else:
        qualities = _MINOR_TRIADS if minor_key else _MAJOR_TRIADS
    degrees = scale_obj.degrees[:7]
    pads: list[Pad] = []
    for index, offset in enumerate(degrees):
        pads.append(Pad(Chord(root=(root + offset) % 12,
                              quality=qualities[index % len(qualities)])))
    fifth = (root + 7) % 12
    extras = [
        Chord(root=(root + 2) % 12, quality="dom7"),        # V/V
        Chord(root=(root + 5) % 12, quality="maj" if minor_key else "min"),
        Chord(root=(root + 10) % 12, quality="maj"),        # bVII
        Chord(root=root, quality="sus4"),
        Chord(root=fifth, quality="dom7"),
    ]
    for chord in extras[:PAD_COUNT - len(pads)]:
        pads.append(Pad(chord))
    label = name or f"{note_name(root)} {scale_obj.label}"
    return Chordset(name=label, root=root, scale=scale, pads=tuple(pads))


def from_symbols(symbols: list[str], name: str = "SET", root: int = 0,
                 scale: str = DEFAULT_SCALE) -> Chordset:
    """Build a set from written chord symbols — how the factory data and the
    tests describe a chordset without hand-encoding pitch classes."""
    pads = [Pad(parse_chord(s)) if s else Pad(enabled=False) for s in symbols]
    return Chordset(name=name, root=root, scale=scale, pads=tuple(pads))


def factory_chordsets() -> tuple[Chordset, ...]:
    """The sets that ship on the image. Kept in code rather than data files
    because a unit whose data partition is empty — first boot, or a card
    swapped in the field — must still come up playable."""
    return (
        diatonic(0, "major", name="C MAJOR"),
        diatonic(0, "major", sevenths=True, name="C MAJOR 7"),
        diatonic(9, "minor", name="A MINOR"),
        from_symbols(
            ["Cmaj7", "Am7", "Dm7", "G7", "Em7", "A7", "Fmaj7", "F#m7b5",
             "Bm7b5", "E7", "Cm7", "Ab7"],
            name="STANDARDS", root=0, scale="major"),
        from_symbols(
            ["Am7", "D7", "Gmaj7", "Cmaj7", "F#m7b5", "B7", "Em7", "A7",
             "Dm7", "G7", "Cmaj7", "Bm7b5"],
            name="TURNAROUND", root=7, scale="major"),
        from_symbols(
            ["Fm7", "Bbm7", "Eb7", "Abmaj7", "Dbmaj7", "Gm7b5", "C7", "Fm9",
             "Bb7", "Ebmaj7", "Db7", "Cm7"],
            name="MODAL FM", root=5, scale="minor"),
        from_symbols(
            ["C5", "F5", "G5", "Bb5", "Eb5", "D5", "A5", "E5",
             "Csus4", "Fsus4", "Gsus4", "Bb5"],
            name="POWER", root=0, scale="pent_minor"),
    )
