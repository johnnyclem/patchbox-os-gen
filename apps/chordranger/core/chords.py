"""Chords and voicings.

A ``Chord`` is a *harmonic idea* — root, quality, optional slash bass, and for
a hand-edited chord an explicit interval set. It has no register. Turning one
into notes you can send down a MIDI cable is the job of ``voice()``, and the
split is deliberate: the same C-7 gets voiced one way for the chord part
(mid register, drop-2) and another for the bass part (one note, two octaves
down), and neither should be able to mutate the other's idea of the chord.

The voicing dial is the Orchid ORC-1 gesture: one detent moves exactly one
note by one octave, so a player walks a voicing up through its inversions and
back without ever leaving the chord. ``walk()`` is that dial, and because it
only ever moves a note by 12 semitones the pitch-class set — the harmony — is
invariant along the whole travel.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from core.theory import (FLAT_KEYS, MIDDLE_C, Scale, note_name, parse_note, pc,
                         snap_to_scale)


@dataclass(frozen=True, slots=True)
class Quality:
    """One chord quality: intervals in semitones from the root.

    ``shell`` names the intervals that carry the identity — root, third,
    seventh — which is what the SHELL voicing keeps and what the bass engine
    consults when it wants a note that is not the root.
    """

    name: str
    label: str                          # what the panel prints after the root
    intervals: tuple[int, ...]
    shell: tuple[int, ...] = (0, 4, 7)
    minor: bool = False                 # lower-case the roman numeral
    tension: int = 0                    # 0 stable · 1 colour · 2 wants to move


QUALITIES: dict[str, Quality] = {q.name: q for q in (
    Quality("maj", "", (0, 4, 7), (0, 4)),
    Quality("min", "m", (0, 3, 7), (0, 3), minor=True),
    Quality("dim", "°", (0, 3, 6), (0, 3, 6), minor=True, tension=2),
    Quality("aug", "+", (0, 4, 8), (0, 4, 8), tension=2),
    Quality("sus2", "sus2", (0, 2, 7), (0, 2), tension=1),
    Quality("sus4", "sus4", (0, 5, 7), (0, 5), tension=1),
    Quality("5", "5", (0, 7), (0, 7)),
    Quality("6", "6", (0, 4, 7, 9), (0, 4, 9), tension=1),
    Quality("min6", "m6", (0, 3, 7, 9), (0, 3, 9), minor=True, tension=1),
    Quality("maj7", "maj7", (0, 4, 7, 11), (0, 4, 11), tension=1),
    Quality("min7", "m7", (0, 3, 7, 10), (0, 3, 10), minor=True, tension=1),
    Quality("dom7", "7", (0, 4, 7, 10), (0, 4, 10), tension=2),
    Quality("min7b5", "m7b5", (0, 3, 6, 10), (0, 3, 6, 10), minor=True,
            tension=2),
    Quality("dim7", "°7", (0, 3, 6, 9), (0, 3, 6, 9), minor=True, tension=2),
    Quality("7sus4", "7sus4", (0, 5, 7, 10), (0, 5, 10), tension=2),
    Quality("add9", "add9", (0, 2, 4, 7), (0, 4, 2), tension=1),
    Quality("min_add9", "m(add9)", (0, 2, 3, 7), (0, 3, 2), minor=True,
            tension=1),
    Quality("maj9", "maj9", (0, 4, 7, 11, 14), (0, 4, 11), tension=1),
    Quality("min9", "m9", (0, 3, 7, 10, 14), (0, 3, 10), minor=True,
            tension=1),
    Quality("dom9", "9", (0, 4, 7, 10, 14), (0, 4, 10), tension=2),
    Quality("dom7b9", "7b9", (0, 4, 7, 10, 13), (0, 4, 10), tension=2),
    Quality("dom7s9", "7#9", (0, 4, 7, 10, 15), (0, 4, 10), tension=2),
    Quality("min11", "m11", (0, 3, 7, 10, 14, 17), (0, 3, 10), minor=True,
            tension=1),
    Quality("dom13", "13", (0, 4, 7, 10, 14, 21), (0, 4, 10), tension=2),
)}

QUALITY_NAMES = tuple(QUALITIES)
# What the Chord screen's quality wheel steps through: the full table is a
# reference, this is the set a player wants under a thumb.
COMMON_QUALITIES = ("maj", "min", "dom7", "maj7", "min7", "sus4", "sus2",
                    "min7b5", "dim", "6", "min6", "add9", "maj9", "min9",
                    "dom9", "aug", "5")

# Longest first: "maj7" must win over "maj" when parsing "Cmaj7".
_SUFFIXES: tuple[tuple[str, str], ...] = tuple(sorted(
    [(q.label, q.name) for q in QUALITIES.values() if q.label]
    + [("", "maj"), ("M7", "maj7"), ("maj", "maj"), ("min", "min"),
       ("-", "min"), ("dim", "dim"), ("aug", "aug"), ("o", "dim"),
       ("m", "min"), ("7", "dom7"), ("9", "dom9")],
    key=lambda pair: -len(pair[0])))


def quality_for(name: str) -> Quality:
    return QUALITIES.get(name, QUALITIES["maj"])


@dataclass(frozen=True, slots=True)
class Chord:
    """Root pitch class + quality, with two escape hatches.

    ``bass`` is a slash chord's pitch class (``C/E``). It changes which note
    the bass engine plays and adds nothing to the upper structure — that is
    what a slash chord *is*, and treating it as an inversion instead would
    make ``C/E`` and a first-inversion C indistinguishable, which they are
    not: one names its bass note, the other merely happens to have E lowest.

    ``notes`` is Chord Edit's output: an explicit, ordered interval set from
    the root that overrides ``quality.intervals``. Once a chord is hand-made
    it stops being derivable from a quality name, so the whole set is stored
    rather than a diff — a quality table that gains a member later must not
    retroactively change what somebody's saved chord sounds like.
    """

    root: int = 0
    quality: str = "maj"
    bass: int | None = None
    notes: tuple[int, ...] = ()
    label: str = ""                     # user override for the pad caption

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root % 12)
        if self.bass is not None:
            object.__setattr__(self, "bass", self.bass % 12)
        if self.notes:
            # Sorted + deduped so two chords built by different edit paths
            # compare equal, and so the voicer can assume ascending input.
            object.__setattr__(self, "notes",
                               tuple(sorted(set(self.notes))))

    # --- identity ------------------------------------------------------------
    @property
    def spec(self) -> Quality:
        return quality_for(self.quality)

    @property
    def intervals(self) -> tuple[int, ...]:
        """Semitones above the root, ascending. Hand-edited chords answer with
        their own set."""
        return self.notes if self.notes else self.spec.intervals

    @property
    def edited(self) -> bool:
        return bool(self.notes)

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in self.intervals)

    @property
    def bass_pc(self) -> int:
        """Which pitch class belongs at the bottom — the slash note if there
        is one, else the root."""
        return self.root if self.bass is None else self.bass

    @property
    def minor(self) -> bool:
        if self.notes:
            return 3 in {i % 12 for i in self.notes} and \
                4 not in {i % 12 for i in self.notes}
        return self.spec.minor

    def symbol(self, flats: bool | None = None) -> str:
        """``"Cmaj7"``, ``"F#m7b5"``, ``"C/E"``. A hand-edited chord keeps its
        nearest quality name with a ``*`` so the panel never claims a chord is
        a textbook Cmaj7 when the player has pulled the fifth out of it."""
        if self.label:
            return self.label
        use_flats = (self.root in FLAT_KEYS) if flats is None else flats
        text = note_name(self.root, use_flats) + self.spec.label
        if self.edited:
            text += "*"
        if self.bass is not None and self.bass != self.root:
            text += "/" + note_name(self.bass, use_flats)
        return text

    def transposed(self, semitones: int) -> "Chord":
        """Chordcat's per-pad transpose: the shape travels, the edit survives."""
        return replace(self, root=(self.root + semitones) % 12,
                       bass=None if self.bass is None
                       else (self.bass + semitones) % 12,
                       label="")

    # --- Chord Edit ----------------------------------------------------------
    def toggled(self, interval: int) -> "Chord":
        """Add or remove one interval (Chordcat Chord Edit, manual p.4).

        The root is not special-cased: pulling it out is how you get the
        rootless voicings a keyboard player leaves to the bass, and the
        engine copes because ``bass_pc`` is an independent idea.
        """
        current = set(self.intervals)
        offset = interval % 12 if interval < 0 else interval
        current.symmetric_difference_update({offset})
        return replace(self, notes=tuple(sorted(current)))

    def with_quality(self, quality: str) -> "Chord":
        """Pick a new quality, dropping any hand edit — the player asked for
        the textbook chord back."""
        return replace(self, quality=quality, notes=(), label="")


# --- parsing ------------------------------------------------------------------

def parse_chord(text: str) -> Chord:
    """``"Cmaj7"``, ``"F#m7"``, ``"Bb7sus4"``, ``"C/E"`` → Chord.

    Used by the song editor's text entry and by the factory-data loader, so it
    is strict: an unparseable symbol raises rather than guessing.
    """
    body, _, bass_text = text.strip().partition("/")
    body = body.strip()
    if not body:
        raise ValueError(f"empty chord: {text!r}")
    cursor = 1
    if len(body) > 1 and body[1] in "#b♯♭":
        cursor = 2
    root = parse_note(body[:cursor])
    suffix = body[cursor:]
    for label, name in _SUFFIXES:
        if suffix == label:
            quality = name
            break
    else:
        raise ValueError(f"unknown chord quality: {suffix!r} in {text!r}")
    bass = parse_note(bass_text) if bass_text.strip() else None
    return Chord(root=root, quality=quality, bass=bass)


def detect_chord(notes: tuple[int, ...]) -> Chord | None:
    """Name a set of sounding MIDI notes — the QY "play a chord to set the
    chord" gesture, and how MIDI-in drives the arranger.

    The lowest note is the candidate bass; each pitch class in turn is tried
    as a root and the quality whose intervals match exactly wins. Ambiguity
    is resolved toward the root the *player* implied by playing it lowest,
    which is what an accompanist hears too.
    """
    if len(notes) < 2:
        return None
    lowest = min(notes)
    classes = {pc(n) for n in notes}
    best: tuple[int, Chord] | None = None
    for root in sorted(classes, key=lambda c: (c != pc(lowest), c)):
        wanted = {(n - root) % 12 for n in classes}
        for name, quality in QUALITIES.items():
            if {i % 12 for i in quality.intervals} != wanted:
                continue
            bass = pc(lowest) if pc(lowest) != root else None
            chord = Chord(root=root, quality=name, bass=bass)
            # Fewest intervals wins: a bare triad should not be reported as
            # some five-note quality that happens to reduce to the same set.
            score = len(quality.intervals)
            if best is None or score < best[0]:
                best = (score, chord)
        if best is not None and pc(lowest) == root:
            break                       # the implied root matched; stop here
    return None if best is None else best[1]


# --- voicing ------------------------------------------------------------------

VOICINGS = ("closed", "open", "drop2", "drop3", "shell", "spread", "rootless",
            "quartal")
VOICING_LABELS = {"closed": "CLOSED", "open": "OPEN", "drop2": "DROP 2",
                  "drop3": "DROP 3", "shell": "SHELL", "spread": "SPREAD",
                  "rootless": "ROOTLS", "quartal": "QUART"}


@dataclass(frozen=True, slots=True)
class VoicingSpec:
    """Everything the chord part needs to turn a Chord into notes.

    ``dial`` is the Orchid voicing wheel — see ``walk``. ``center`` is the
    register the voicing is pulled toward, which is what stops a progression
    from marching off the top of the keyboard as it inverts.
    """

    style: str = "closed"
    dial: int = 0                       # inversion walk, ±
    octave: int = 0                     # whole-voicing octave shift
    spread: int = 0                     # extra octaves between the extremes
    center: int = MIDDLE_C
    max_notes: int = 6
    lock_center: bool = True            # keep the voicing near ``center``


def stack(chord: Chord, base: int = MIDDLE_C) -> tuple[int, ...]:
    """Closed position from ``base``: root at or above it, then the intervals.

    ``base`` is a MIDI note; the root is placed in the octave of ``base``
    rather than at exactly ``base``, so a C and a B voice out near each other
    instead of a semitone apart in principle and an octave apart in fact.
    """
    root = base - (base % 12) + chord.root
    if root - base > 6:
        root -= 12
    elif base - root > 5:
        root += 12
    return tuple(root + i for i in chord.intervals)


def walk(notes: tuple[int, ...], steps: int) -> tuple[int, ...]:
    """Move the voicing by ``steps`` single-note inversions (the Orchid dial).

    One positive step lifts the lowest note an octave; one negative step drops
    the highest. The pitch-class set never changes, which is the property that
    makes this safe to bind to a knob a player turns while a chord is
    sounding: it is voice leading, not re-harmonisation.
    """
    if not notes or not steps:
        return notes
    voices = list(notes)
    for _ in range(abs(steps)):
        voices.sort()
        if steps > 0:
            voices.append(voices.pop(0) + 12)
        else:
            voices.insert(0, voices.pop() - 12)
    return tuple(sorted(voices))


def _apply_style(notes: tuple[int, ...], style: str,
                 chord: Chord) -> tuple[int, ...]:
    voices = sorted(notes)
    if len(voices) < 3 or style in ("closed", ""):
        return tuple(voices)
    if style == "drop2" and len(voices) >= 3:
        voices[-2] -= 12
    elif style == "drop3" and len(voices) >= 4:
        voices[-3] -= 12
    elif style == "open":
        # Alternate voices up an octave from the second: the classic open
        # triad spacing, and for four-note chords a wide two-handed shape.
        for index in range(1, len(voices), 2):
            voices[index] += 12
    elif style == "spread":
        voices = [voices[0]] + [n + 12 for n in voices[1:-1]] + \
                 [voices[-1] + 24]
    elif style == "shell":
        shell = {(chord.root + i) % 12 for i in chord.spec.shell}
        kept = [n for n in voices if n % 12 in shell]
        voices = kept or voices
    elif style == "rootless":
        # Drop the root only when something is left to say the chord with:
        # a power chord with no root is just a fifth.
        kept = [n for n in voices if n % 12 != chord.root]
        if len(kept) >= 2:
            voices = kept
    elif style == "quartal":
        # Stack the chord's own tones in fourths from the lowest — the modal
        # keyboard sound, and it stays diatonic because the candidates are
        # the chord tones themselves.
        classes = sorted(chord.pitch_classes)
        voices = [voices[0]]
        for _ in range(min(3, len(classes) - 1)):
            target = voices[-1] + 5
            nearest = min((c for c in
                           (target - target % 12 + k + o
                            for k in classes for o in (0, 12))
                           if c > voices[-1]),
                          key=lambda n: abs(n - target), default=None)
            if nearest is None:
                break
            voices.append(nearest)
    return tuple(sorted(voices))


def voice(chord: Chord, spec: VoicingSpec = VoicingSpec(),
          previous: tuple[int, ...] = ()) -> tuple[int, ...]:
    """Chord + voicing spec → MIDI notes, ascending.

    ``previous`` is the last chord's notes. When it is given and the spec has
    not been dialled anywhere in particular, the inversion closest to it wins,
    so a progression moves by the smallest distance it can — the thing that
    separates an arranger that sounds like a band from one that sounds like a
    chord chart being read aloud.
    """
    notes = stack(chord, spec.center)
    if len(notes) > spec.max_notes:
        # Trim from the middle: the extremes carry the identity (bass) and
        # the colour (top), so a 13th chord on a five-voice budget should
        # lose its fifth, not its 13th.
        keep = [notes[0], *notes[-(spec.max_notes - 1):]]
        notes = tuple(sorted(set(keep)))
    notes = _apply_style(notes, spec.style, chord)
    if previous and spec.dial == 0:
        notes = nearest_inversion(notes, previous)
    notes = walk(notes, spec.dial)
    if spec.spread:
        notes = tuple(sorted(notes[:1] + tuple(n + 12 * spec.spread
                                               for n in notes[1:])))
    if spec.octave:
        notes = tuple(n + 12 * spec.octave for n in notes)
    if spec.lock_center and notes:
        notes = _recenter(notes, spec.center + 12 * spec.octave)
    return tuple(n for n in notes if 0 <= n <= 127)


def _recenter(notes: tuple[int, ...], center: int) -> tuple[int, ...]:
    """Shift the whole voicing by octaves until its mean is nearest *center*.

    Whole octaves only: this is a register correction, and moving a voicing by
    anything else would transpose the music.
    """
    mean = sum(notes) / len(notes)
    shift = round((center - mean) / 12)
    return tuple(n + 12 * shift for n in notes) if shift else notes


def nearest_inversion(notes: tuple[int, ...], previous: tuple[int, ...],
                      reach: int = 3) -> tuple[int, ...]:
    """The inversion of *notes* that moves least from *previous*.

    Distance is the sum over the new voices of the semitones to the closest
    old voice — cheap, and it matches what "smooth" means to an ear: no single
    voice makes a big leap.
    """
    if not previous or not notes:
        return notes
    best = notes
    best_key: tuple[int, int] | None = None
    for steps in range(-reach, reach + 1):
        candidate = walk(notes, steps)
        cost = sum(min(abs(n - p) for p in previous) for n in candidate)
        # Ties go to the smaller absolute dial position, so a chord repeated
        # bar after bar does not silently drift an inversion each time.
        key = (cost, abs(steps))
        if best_key is None or key < best_key:
            best, best_key = candidate, key
    return best


def voicing_options(chord: Chord, spec: VoicingSpec = VoicingSpec(),
                    previous: tuple[int, ...] = ()
                    ) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Every voicing style for this chord — the Chordcat Chord Voicing list.

    Returned as (label, notes) so the panel can print the shape and audition
    it without re-deriving anything.
    """
    out = []
    for style in VOICINGS:
        notes = voice(chord, replace(spec, style=style), previous)
        if notes:
            out.append((VOICING_LABELS[style], notes))
    return tuple(out)


def chord_tone_near(chord: Chord, target: int,
                    scale: Scale | None = None) -> int:
    """Nearest chord tone to *target*, in *target*'s register.

    This is the QY note-transposition rule in one function: a phrase written
    over C major, replayed over F-7, lands each of its notes on the nearest
    tone of F-7 instead of being blindly transposed. ``scale`` is a fallback
    for phrase notes deliberately marked as passing tones.
    """
    classes = sorted(chord.pitch_classes)
    if not classes:
        return target
    candidates = [target - target % 12 + c + octave
                  for c in classes for octave in (-12, 0, 12)]
    best = min(candidates, key=lambda n: (abs(n - target), n))
    if scale is not None and abs(best - target) > 2:
        # A long way to the nearest chord tone means the phrase note was
        # colour, not structure; keeping it in the scale preserves the line.
        return snap_to_scale(target, 0, scale)
    return best
