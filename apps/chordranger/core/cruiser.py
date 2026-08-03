"""Chord Cruiser — "what could come next?".

Chordcat's Cruiser answers a question a player asks constantly and a chord
chart never does: given where I am, in this key, which chord will *connect*?
The answer here is a ranked list, scored on three things that pull in
different directions:

1. **Function.** In a key, some moves are the language: V wants I, ii wants V,
   IV goes almost anywhere. This is a table, not a theory engine, because the
   strength of a move is a stylistic fact and tables can be tuned by ear.
2. **Voice leading.** Two chords that share notes, or whose notes are a
   semitone apart, connect regardless of function. This is computed, not
   tabled, and it is what makes the Cruiser useful outside common practice.
3. **Novelty.** A suggestion list where the top three are all the tonic is
   useless. Repeats of the current chord and of the pads the player already
   has are demoted, so the list earns its screen space.

Suggestions carry a ``reason`` string. On a 1280x400 panel there is room for
three words next to each candidate, and a player who can see *why* the box
suggested bVII learns the vocabulary instead of just tapping what is offered.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.chords import (Chord, QUALITIES, VoicingSpec, voice,
                         voicing_options)
from core.theory import Scale, degree_of, scale_for

# Degree → the degrees it most wants to move to, strongest first. Indices are
# 0-based scale degrees (0 = tonic). Major and minor differ enough in their
# dominant behaviour to be worth two tables.
_MAJOR_MOVES: dict[int, tuple[int, ...]] = {
    0: (5, 3, 4, 1, 2),
    1: (4, 6, 2, 0),
    2: (5, 3, 1),
    3: (4, 0, 1, 5),
    4: (0, 5, 3),
    5: (1, 3, 4, 2),
    6: (0, 4, 2),
}
_MINOR_MOVES: dict[int, tuple[int, ...]] = {
    0: (5, 3, 4, 6, 2),
    1: (4, 0, 6),
    2: (5, 6, 3),
    3: (4, 0, 6, 1),
    4: (0, 5, 3),
    5: (2, 3, 1, 6),
    6: (0, 2, 4),
}

_FUNCTION_WORDS = {
    0: "HOME", 1: "PREDOM", 2: "MEDIANT", 3: "SUBDOM", 4: "DOMINANT",
    5: "RELATIVE", 6: "LEADING",
}

MINOR_SCALES = frozenset({"minor", "harmonic_minor", "phrygian", "dorian",
                          "pent_minor", "blues"})


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One candidate: the chord, why it was offered, and how it scored.

    ``notes`` is the voicing the cruiser would use if the player took it —
    computed here so auditioning a suggestion costs nothing at tap time.
    """

    chord: Chord
    score: float
    reason: str
    notes: tuple[int, ...] = ()

    @property
    def symbol(self) -> str:
        return self.chord.symbol()


def voice_leading_cost(a: Chord, b: Chord) -> float:
    """Average semitone distance from each of *a*'s pitch classes to *b*'s.

    Pitch classes, not notes: this asks whether the two harmonies are close,
    which is a property of the chords themselves. How far the actual voices
    move is up to ``core.chords.voice`` and its ``previous`` argument.
    """
    left, right = a.pitch_classes, b.pitch_classes
    if not left or not right:
        return 6.0
    total = 0.0
    for pitch in left:
        total += min(min(abs(pitch - other), 12 - abs(pitch - other))
                     for other in right)
    return total / len(left)


def _diatonic_candidates(root: int, scale: Scale,
                         minor_key: bool) -> list[tuple[int, Chord]]:
    """(degree, chord) for every degree of the scale, as a seventh chord when
    the scale has seven notes and as a triad otherwise — a pentatonic key has
    no diatonic seventh worth the name."""
    triads = ("min", "dim", "maj", "min", "min", "maj", "maj") if minor_key \
        else ("maj", "min", "min", "maj", "maj", "min", "dim")
    sevenths = ("min7", "min7b5", "maj7", "min7", "min7", "maj7", "dom7") \
        if minor_key else \
        ("maj7", "min7", "min7", "maj7", "dom7", "min7", "min7b5")
    table = sevenths if len(scale.degrees) == 7 else triads
    out = []
    for degree, offset in enumerate(scale.degrees[:7]):
        quality = table[degree % len(table)]
        out.append((degree, Chord(root=(root + offset) % 12,
                                  quality=quality)))
    return out


def _spice(root: int, scale: Scale, minor_key: bool,
           current: Chord) -> list[tuple[Chord, str]]:
    """The non-diatonic candidates worth always having on the list.

    Secondary dominants of the two degrees a player actually tonicises, the
    borrowed subdominant, the flat seven, and a tritone substitution of the
    dominant. Any of these will sound wrong in some context — that is why
    they are scored, not asserted.
    """
    fifth = (root + 7) % 12
    out: list[tuple[Chord, str]] = [
        (Chord(root=(root + 2) % 12, quality="dom7"), "V OF V"),
        (Chord(root=fifth, quality="dom7"), "DOMINANT"),
        (Chord(root=(root + 5) % 12,
               quality="maj" if minor_key else "min"), "BORROWED"),
        (Chord(root=(root + 10) % 12, quality="maj"), "FLAT VII"),
        (Chord(root=(root + 1) % 12, quality="dom7"), "TRITONE SUB"),
        (Chord(root=root, quality="sus4"), "SUSPEND"),
    ]
    # A dominant on the current root tonicises whatever comes next: the
    # single most useful "get me out of here" chord there is.
    if current.quality != "dom7":
        out.append((Chord(root=current.root, quality="dom7"), "MAKE IT 7"))
    return out


def suggest(current: Chord | None, root: int = 0, scale: str = "major",
            limit: int = 8, avoid: tuple[Chord, ...] = ()) -> tuple[
                Suggestion, ...]:
    """Rank chords that could follow *current* in the key of *root*/*scale*.

    ``avoid`` is what the player already has on pads: those are demoted, not
    removed, because sometimes the right answer really is the chord under
    your thumb and the list should say so rather than pretend otherwise.
    """
    scale_obj = scale_for(scale)
    minor_key = scale in MINOR_SCALES
    moves = _MINOR_MOVES if minor_key else _MAJOR_MOVES
    here = (degree_of(current.root, root, scale_obj)
            if current is not None else 0)
    diatonic = _diatonic_candidates(root, scale_obj, minor_key)
    wanted = moves.get(here if here is not None else 0, ())

    scored: dict[tuple[int, str], Suggestion] = {}

    def offer(chord: Chord, base: float, reason: str) -> None:
        key = (chord.root, chord.quality)
        if current is not None and key == (current.root, current.quality):
            return                      # never suggest standing still
        score = base
        if current is not None:
            # 0 semitones average → +2.0, 3 semitones → +0.5. Common tones
            # and semitone moves are what "connects" means.
            score += max(0.0, 2.0 - voice_leading_cost(current, chord) * 0.5)
        # Demote by root, harder for an exact match. A player who already has
        # an F on a pad does not need the list to spend a line on Fmaj7
        # either — but they might still want it, so it is demoted, not cut.
        if any(chord.root == other.root and chord.quality == other.quality
               for other in avoid):
            score -= 1.4
        elif any(chord.root == other.root for other in avoid):
            score -= 0.7
        existing = scored.get(key)
        if existing is None or score > existing.score:
            scored[key] = Suggestion(chord=chord, score=score, reason=reason)

    for degree, chord in diatonic:
        strength = (len(wanted) - wanted.index(degree)) if degree in wanted \
            else 0
        offer(chord, 1.0 + strength * 0.6, _FUNCTION_WORDS.get(degree, ""))
    for chord, reason in _spice(root, scale_obj, minor_key,
                                current or Chord(root=root)):
        offer(chord, 1.1, reason)

    spec = VoicingSpec()
    previous = voice(current, spec) if current is not None else ()
    ranked = sorted(scored.values(), key=lambda s: (-s.score, s.chord.root))
    return tuple(
        Suggestion(chord=s.chord, score=round(s.score, 3), reason=s.reason,
                   notes=voice(s.chord, spec, previous))
        for s in ranked[:limit])


def progression(start: Chord, root: int = 0, scale: str = "major",
                length: int = 4) -> tuple[Chord, ...]:
    """Cruise a whole progression by repeatedly taking the top suggestion.

    This is the "surprise me" button: it fills empty pads or seeds a song's
    chord track. Chords already used are passed as ``avoid`` so the walk keeps
    moving instead of oscillating between two chords forever.
    """
    out = [start]
    for _ in range(max(0, length - 1)):
        picks = suggest(out[-1], root, scale, limit=3, avoid=tuple(out))
        if not picks:
            break
        out.append(picks[0].chord)
    return tuple(out)


def voicings(chord: Chord, spec: VoicingSpec = VoicingSpec(),
             previous: tuple[int, ...] = ()) -> tuple[
                 tuple[str, tuple[int, ...]], ...]:
    """Chordcat's Chord Voicing list for one chord — re-exported here so the
    GUI has a single import for "the cruiser screen's two lists"."""
    return voicing_options(chord, spec, previous)


def quality_alternatives(chord: Chord, limit: int = 6) -> tuple[Chord, ...]:
    """Same root, neighbouring qualities — the other half of Chord Edit.

    Ordered by how far each quality's interval set is from the current one, so
    the first offer is a small recolouring (maj → maj7) and the last is a real
    change of character (maj → min7b5).
    """
    here = set(chord.spec.intervals)

    def distance(name: str) -> tuple[int, str]:
        other = set(QUALITIES[name].intervals)
        return len(here ^ other), name

    names = [n for n in QUALITIES if n != chord.quality]
    return tuple(chord.with_quality(n)
                 for n in sorted(names, key=distance)[:limit])
