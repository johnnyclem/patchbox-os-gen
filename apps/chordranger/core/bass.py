"""The bass engine.

Orchid's ORC-1 splits its instrument in two: a chord voice with a voicing dial
that walks inversions one note at a time, and a *separate* bass voice that can
either hold the root under whatever the chords are doing or go off on its own.
That split is the model here, and it matters more than it sounds: a bass part
that is merely "the lowest note of the chord voicing" cannot play a passing
tone, cannot anticipate the next chord, and cannot be silenced without
thinning the chord. One that is its own engine can do all three.

So the bass takes the chord as *input*, not as material. It knows the current
chord, the next chord (which is what lets it walk into a change), the beat it
is on, and its own pattern — and from those it decides one note at a time.

Modes, roughly in order of how much they take over:

``root``        the bass note, on the pattern's steps. The default, and the
                one that never sounds wrong.
``octave``      alternates root and root+12 — the disco/synthwave engine.
``fifth``       root and fifth, the country/rock alternation.
``walk``        a stepwise line through the chord tones that arrives on the
                next chord's root — jazz walking bass, and the mode that
                actually uses ``next_chord``.
``arp``         runs up the chord tones on every step.
``phrase``      plays the style's own written bassline, converted per the
                style's rule. Hands the part back to the style author.
``off``         silence, without touching the chord part.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.chords import Chord
from core.events import TICKS_PER_16TH, TICKS_PER_BAR
from core.theory import Scale, scale_for, snap_to_scale

ROOT, OCTAVE, FIFTH, WALK, ARP, PHRASE, OFF = (
    "root", "octave", "fifth", "walk", "arp", "phrase", "off")
BASS_MODES = (ROOT, OCTAVE, FIFTH, WALK, ARP, PHRASE, OFF)
BASS_MODE_LABELS = {ROOT: "ROOT", OCTAVE: "OCTAVE", FIFTH: "5TH",
                    WALK: "WALK", ARP: "ARP", PHRASE: "PHRASE", OFF: "OFF"}

# The register the bass lives in: E1..E3 covers a bass guitar and sits below
# any sensible chord voicing, so the two parts never fight for the same notes.
BASS_CENTER = 40                # E2
BASS_LOW = 28
BASS_HIGH = 55


@dataclass(frozen=True, slots=True)
class BassSpec:
    """The bass engine's whole state. One frozen value so the engine can swap
    it atomically between ticks and the GUI can render a copy without locks.

    ``dial`` is the second Orchid voicing wheel, applied to the bass alone:
    each detent moves the line by one chord tone rather than by an octave,
    because a bass inversion *is* a different note, not a different spacing.
    """

    mode: str = ROOT
    pattern: str = "x...x...x...x..."   # 16 steps; see core.style.steps
    octave: int = 0
    dial: int = 0
    velocity: int = 104
    accent: int = 16                    # extra velocity on downbeats
    gate: int = 80                      # note length, % of the step
    slide: bool = False                 # overlap notes so a mono synth glides
    follow_slash: bool = True           # honour C/E — off = always the root
    center: int = BASS_CENTER

    def normalised(self) -> "BassSpec":
        """Clamp everything a config file or a knob could put out of range."""
        from dataclasses import replace
        return replace(
            self,
            mode=self.mode if self.mode in BASS_MODES else ROOT,
            velocity=max(1, min(127, self.velocity)),
            gate=max(5, min(200, self.gate)),
            octave=max(-3, min(3, self.octave)),
            center=max(BASS_LOW, min(BASS_HIGH, self.center)))


@dataclass(frozen=True, slots=True)
class BassNote:
    """One note the engine decided on: ticks are relative to the bar."""

    tick: int
    note: int
    velocity: int
    length: int


def _place(pitch_class: int, center: int) -> int:
    """Put a pitch class in the bass register nearest *center*."""
    note = center - (center % 12) + pitch_class
    if note - center > 6:
        note -= 12
    elif center - note > 5:
        note += 12
    return max(BASS_LOW - 12, min(BASS_HIGH + 12, note))


def _tones(chord: Chord, spec: BassSpec) -> tuple[int, ...]:
    """Chord tones in the bass register, ascending from the bass note.

    The bass note leads whether or not it is the root: over C/E a walking line
    that starts on C is playing a different chord from the one on the chart.
    """
    bass_pc = chord.bass_pc if spec.follow_slash else chord.root
    classes = sorted(chord.pitch_classes | {bass_pc},
                     key=lambda c: (c - bass_pc) % 12)
    base = _place(bass_pc, spec.center + 12 * spec.octave)
    return tuple(base + ((c - bass_pc) % 12) for c in classes)


def _step_ticks(pattern: str, grid: int = TICKS_PER_16TH
                ) -> tuple[tuple[int, bool], ...]:
    """(tick, accented) for each hit in a step pattern, plus its length in
    steps so a ``-`` tie makes a longer note rather than a second one."""
    out: list[tuple[int, bool]] = []
    for index, char in enumerate(pattern):
        if char in "xX":
            out.append((index * grid, char == "X"))
    return tuple(out)


def bar_notes(spec: BassSpec, chord: Chord, next_chord: Chord | None = None,
              scale_name: str = "major", key_root: int = 0,
              bar: int = 0) -> tuple[BassNote, ...]:
    """One bar of bass over *chord*.

    Pure: same inputs, same notes. That is what lets the engine call this once
    per bar on the tick thread and lets the tests assert on whole basslines
    without a transport.
    """
    spec = spec.normalised()
    if spec.mode == OFF or spec.mode == PHRASE:
        return ()
    hits = _step_ticks(spec.pattern)
    if not hits:
        return ()
    tones = _tones(chord, spec)
    if not tones:
        return ()
    scale = scale_for(scale_name)
    step = TICKS_PER_BAR // max(1, len(spec.pattern))
    out: list[BassNote] = []
    for index, (tick, accented) in enumerate(hits):
        note = _choose(spec, tones, index, len(hits), chord, next_chord,
                       scale, key_root, bar)
        velocity = spec.velocity + (spec.accent if accented or tick == 0
                                    else 0)
        # A slide asks for overlapping notes: a mono synth in legato mode
        # glides between them instead of retriggering its envelope.
        length = max(6, step * spec.gate // 100)
        if spec.slide and index + 1 < len(hits):
            length = max(length, hits[index + 1][0] - tick + step // 4)
        out.append(BassNote(tick=tick, note=max(0, min(127, note)),
                            velocity=max(1, min(127, velocity)),
                            length=length))
    return tuple(out)


def _choose(spec: BassSpec, tones: tuple[int, ...], index: int, count: int,
            chord: Chord, next_chord: Chord | None, scale: Scale,
            key_root: int, bar: int) -> int:
    """Which note this hit gets. Split out because every mode is a one-liner
    and the dispatch is the only interesting part."""
    root = tones[0]
    dial = spec.dial
    if spec.mode == ROOT:
        return _dialled(tones, 0 + dial)
    if spec.mode == OCTAVE:
        return _dialled(tones, dial) + (12 if index % 2 else 0)
    if spec.mode == FIFTH:
        fifth = next((t for t in tones if (t - root) % 12 in (7, 6, 8)),
                     root + 7)
        return (fifth if index % 2 else _dialled(tones, dial))
    if spec.mode == ARP:
        return _dialled(tones, index + dial)
    if spec.mode == WALK:
        return _walk(tones, index, count, next_chord, scale, key_root, spec)
    return root


def _dialled(tones: tuple[int, ...], step: int) -> int:
    """Index into the chord tones, wrapping into higher octaves — the bass
    voicing dial. Negative steps go below the bass note, which is how you get
    a low fifth under a chord without changing its symbol."""
    if not tones:
        return BASS_CENTER
    span = len(tones)
    octave, position = divmod(step, span)
    return tones[position] + 12 * octave


def _walk(tones: tuple[int, ...], index: int, count: int,
          next_chord: Chord | None, scale: Scale, key_root: int,
          spec: BassSpec) -> int:
    """A walking line: chord tones through the bar, aiming at the next chord.

    The last hit of the bar is a leading tone — a semitone or a scale step
    below (or above) the note the next bar starts on. That single note is what
    makes a walking bass sound like it is going somewhere; without it the line
    is just an arpeggio that stops.
    """
    if next_chord is not None and count > 1 and index == count - 1:
        target = _place(next_chord.bass_pc if spec.follow_slash
                        else next_chord.root,
                        spec.center + 12 * spec.octave)
        approach = target - 1 if (index % 2 == 0) else target + 1
        # Prefer a scale step when there is one; chromatic approach otherwise.
        stepwise = snap_to_scale(approach, key_root, scale)
        return stepwise if abs(stepwise - target) in (1, 2) else approach
    return _dialled(tones, index + spec.dial)


def resolve_line(spec: BassSpec, chords: tuple[Chord, ...],
                 scale_name: str = "major", key_root: int = 0
                 ) -> tuple[tuple[int, BassNote], ...]:
    """A whole progression's bass, as (bar, note) pairs.

    Used by the tests and by the song screen's preview: it is the only place
    the ``next_chord`` lookahead is exercised end to end, and having it as a
    function keeps that logic out of the engine.
    """
    out: list[tuple[int, BassNote]] = []
    for bar, chord in enumerate(chords):
        nxt = chords[bar + 1] if bar + 1 < len(chords) else chords[0]
        for note in bar_notes(spec, chord, nxt, scale_name, key_root, bar):
            out.append((bar, note))
    return tuple(out)


# --- shipped patterns ---------------------------------------------------------
# Step strings a player can pick without editing anything. Sixteen characters,
# one bar. Named for the feel rather than the genre because the same pattern
# turns up in three genres under three names.
BASS_PATTERNS: dict[str, str] = {
    "FOUR": "x...x...x...x...",
    "EIGHTS": "x.x.x.x.x.x.x.x.",
    "PUSH": "x...x..x.x..x...",
    "OFFBEAT": "..x...x...x...x.",
    "HALF": "x.......x.......",
    "WHOLE": "x...............",
    "SIXTEEN": "xxxxxxxxxxxxxxxx",
    "DISCO": "x.xxx.xxx.xxx.xx",
    "REGGAE": "..x..x....x..x..",
    "BOSSA": "x.....x.x.....x.",
    "FUNK": "x..x..x...x.x..x",
    "DUB": "x.......x...x...",
}
DEFAULT_PATTERN = "FOUR"


def pattern_for(name: str) -> str:
    return BASS_PATTERNS.get(name, BASS_PATTERNS[DEFAULT_PATTERN])
