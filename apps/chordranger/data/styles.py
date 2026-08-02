"""The factory styles — six bands that ship on the image.

Each is written as step strings, one character per sixteenth, so a groove can
be read (and edited) without a piano roll. ``X`` accents, ``x`` hits, ``-``
ties the previous note over another step, ``.`` rests.

Everything is written in C. The conversion rules in ``core.style`` bend it
onto whatever chord the player is holding, so none of this data knows or cares
what key the song is in.

The five parts are the same in every style, with the same ids and channels, so
switching styles mid-song does not rearrange the mixer under the player's
hands — and so a chord part muted in one style stays muted in the next.
"""
from __future__ import annotations

from core.style import (CHORD_TONE, DRUM_CHANNEL, ENDING, FILL_AB, FILL_BA,
                        FIXED, INTRO, MAIN_A, MAIN_B, PARALLEL, Part, Phrase,
                        ROLE_BASS, ROLE_CHORD, ROLE_DRUM, ROLE_PHRASE, ROOT,
                        SCALE, Section, Style, chord_hits, merge, repeat,
                        steps)
from core.events import PPQN, TICKS_PER_16TH

# --- GM percussion ------------------------------------------------------------
KICK, RIM, SNARE, CLAP = 36, 37, 38, 39
HAT, HAT_PEDAL, HAT_OPEN = 42, 44, 46
TOM_LOW, TOM_MID, TOM_HI = 45, 47, 50
CRASH, RIDE, SHAKER, COWBELL = 49, 51, 70, 56

# --- the band -----------------------------------------------------------------
# Channels leave 5-9 free for the player's own parts and put the drums on the
# GM percussion channel, which is the one thing every receiving device agrees
# about.
PARTS: tuple[Part, ...] = (
    Part("drum", "DRUMS", ROLE_DRUM, DRUM_CHANNEL, conversion=FIXED,
         velocity=100),
    Part("bass", "BASS", ROLE_BASS, 1, conversion=ROOT, velocity=104),
    Part("chord", "CHORD", ROLE_CHORD, 0, conversion=CHORD_TONE, velocity=92),
    Part("keys", "KEYS", ROLE_PHRASE, 2, conversion=CHORD_TONE, velocity=84),
    Part("lead", "LEAD", ROLE_PHRASE, 3, conversion=SCALE, velocity=88,
         muted=True),
)

PART_IDS = tuple(p.id for p in PARTS)


def _drums(lines: dict[int, str], bars: int = 1) -> Phrase:
    """A drum phrase from note → step string. Every line must be one bar long;
    multi-bar sections repeat, which is what a drummer does too."""
    body = merge(*(steps(pattern, note=note, length=TICKS_PER_16TH)
                   for note, pattern in lines.items()))
    return Phrase(notes=repeat(body, bars), bars=bars, conversion=FIXED)


def _bass(pattern: str, note: int = 36, bars: int = 1,
          length: int = TICKS_PER_16TH * 2) -> Phrase:
    """The style's own written bassline — used when the bass engine is in
    PHRASE mode. Written on C1 so it is unambiguous in the JSON."""
    body = steps(pattern, note=note, velocity=104, length=length)
    return Phrase(notes=repeat(body, bars), bars=bars, conversion=ROOT)


def _chords(pattern: str, bars: int = 1, length: int = PPQN // 2,
            velocity: int = 92) -> Phrase:
    body = chord_hits(pattern, velocity=velocity, length=length)
    return Phrase(notes=repeat(body, bars), bars=bars, conversion=CHORD_TONE)


def _line(pattern: str, note: int, bars: int = 1, velocity: int = 84,
          length: int = TICKS_PER_16TH, conversion: str = CHORD_TONE
          ) -> Phrase:
    body = steps(pattern, note=note, velocity=velocity, length=length)
    return Phrase(notes=repeat(body, bars), bars=bars, conversion=conversion)


def _section(name: str, bars: int, **phrases: Phrase) -> Section:
    return Section(name=name, bars=bars, phrases=dict(phrases))


# --- styles -------------------------------------------------------------------

def _house() -> Style:
    """Four on the floor. The fill is a tom roll, the ending a single stab —
    a house track does not cadence, it stops."""
    hats = {HAT: ".x.x.x.x.x.x.x.x", KICK: "x...x...x...x...",
            CLAP: "....x.......x..."}
    return Style(
        name="HOUSE", bpm=124, genre="house", parts=PARTS, swing=0,
        sections={
            INTRO: _section(INTRO, 2,
                            drum=_drums({KICK: "x...x...x...x...",
                                         HAT: "..x...x...x...x."}, 2),
                            chord=_chords("x...............", 2,
                                          length=PPQN * 2)),
            MAIN_A: _section(MAIN_A, 2, drum=_drums(hats, 2),
                             bass=_bass("x.x...x.x.x...x.", bars=2),
                             chord=_chords("..x...x...x...x.", 2,
                                           length=PPQN // 3)),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({SNARE: "..x.x.xxx.xxxxxx",
                                           KICK: "x...x...x...x..."}),
                              chord=_chords("x.......x.......")),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({**hats, HAT_OPEN: "..x...x...x...x."},
                                         4),
                             bass=_bass("x.x.x.x.x.x.x.x.", bars=4),
                             chord=_chords("..x...x...x...x.", 4,
                                           length=PPQN // 3),
                             keys=_line("....x.......x...", 72, 4,
                                        length=PPQN)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({TOM_HI: "x.x.....",
                                           TOM_MID: "....x.x.",
                                           SNARE: "........xxxxxxxx"})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({KICK: "x...............",
                                          CRASH: "x..............."}, 2),
                             chord=_chords("x...............", 2,
                                           length=PPQN * 4)),
        })


def _ballad() -> Style:
    """Slow, brushed, with the chord part sustaining whole notes and the keys
    arpeggiating underneath. The one to check voice leading with: at 68 BPM
    every inversion choice is audible."""
    return Style(
        name="BALLAD", bpm=68, genre="ballad", parts=PARTS, swing=0,
        sections={
            INTRO: _section(INTRO, 2,
                            keys=_line("x...x...x...x...", 64, 2,
                                       length=PPQN // 2),
                            chord=_chords("x...............", 2,
                                          length=PPQN * 4)),
            MAIN_A: _section(MAIN_A, 2,
                             drum=_drums({KICK: "x.......x.......",
                                          SNARE: "....x.......x...",
                                          HAT: "..x...x...x...x."}, 2),
                             bass=_bass("x.......x.......", bars=2,
                                        length=PPQN),
                             chord=_chords("x...............", 2,
                                           length=PPQN * 4),
                             keys=_line("x..x..x..x..x..x", 64, 2,
                                        length=PPQN // 2)),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({SNARE: "........x.x.x.x.",
                                           KICK: "x......."})),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({KICK: "x.....x.x.......",
                                          SNARE: "....x.......x...",
                                          RIDE: "x.x.x.x.x.x.x.x."}, 4),
                             bass=_bass("x.....x.x.......", bars=4,
                                        length=PPQN),
                             chord=_chords("x.......x.......", 4,
                                           length=PPQN * 2),
                             keys=_line("x..x..x..x..x..x", 64, 4,
                                        length=PPQN // 2),
                             lead=_line("....x......x....", 79, 4,
                                        length=PPQN, conversion=SCALE)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({TOM_MID: "....x.x.",
                                           TOM_LOW: "........x.x.....",
                                           CRASH: "..............x."})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({KICK: "x...............",
                                          CRASH: "x..............."}, 2),
                             bass=_bass("x...............", bars=2,
                                        length=PPQN * 4),
                             chord=_chords("x...............", 2,
                                           length=PPQN * 4)),
        })


def _bossa() -> Style:
    """The clave-ish guitar comp against a two-feel bass. Chord part uses
    ``parallel`` on the stabs so the voicing keeps its shape."""
    comp = "..x..x....x..x.."
    return Style(
        name="BOSSA", bpm=132, genre="latin", parts=PARTS, swing=0,
        sections={
            INTRO: _section(INTRO, 2,
                            drum=_drums({RIM: "..x..x....x..x..",
                                         SHAKER: "x.x.x.x.x.x.x.x."}, 2),
                            chord=_chords(comp, 2, length=PPQN // 2)),
            MAIN_A: _section(MAIN_A, 2,
                             drum=_drums({RIM: "..x..x....x..x..",
                                          SHAKER: "x.x.x.x.x.x.x.x.",
                                          KICK: "x.......x......."}, 2),
                             bass=_bass("x.....x.x.....x.", bars=2,
                                        length=PPQN // 2),
                             chord=_chords(comp, 2, length=PPQN // 2)),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({TOM_HI: "x.x.x.x.",
                                           SHAKER: "x.x.x.x.x.x.x.x."})),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({RIM: "..x..x....x..x..",
                                          SHAKER: "xxxxxxxxxxxxxxxx",
                                          KICK: "x.......x.......",
                                          HAT_OPEN: "....x.......x..."}, 4),
                             bass=_bass("x.....x.x.....x.", bars=4,
                                        length=PPQN // 2),
                             chord=_chords(comp, 4, length=PPQN // 2),
                             keys=_line("....x.......x...", 76, 4,
                                        length=PPQN // 2)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({SNARE: "x.x.x.x.x.x.x.x.",
                                           CRASH: "..............x."})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({RIM: "..x..x....x.....",
                                          CRASH: "x..............."}, 2),
                             bass=_bass("x.......", bars=2, length=PPQN * 2),
                             chord=_chords("x.......x.......", 2,
                                           length=PPQN * 2)),
        })


def _funk() -> Style:
    """Sixteenth-note hats, a syncopated kick and short chord stabs. The
    style whose bassline is worth hearing in PHRASE mode."""
    return Style(
        name="FUNK", bpm=102, genre="funk", parts=PARTS, swing=12,
        sections={
            INTRO: _section(INTRO, 2,
                            drum=_drums({HAT: "xxxxxxxxxxxxxxxx",
                                         KICK: "x.......x......."}, 2),
                            chord=_chords("...x............", 2,
                                          length=PPQN // 4)),
            MAIN_A: _section(MAIN_A, 2,
                             drum=_drums({HAT: "xxxxxxxxxxxxxxxx",
                                          KICK: "x..x..x...x.x...",
                                          SNARE: "....X.......X..."}, 2),
                             bass=_bass("x..x..x...x.x...", bars=2,
                                        length=TICKS_PER_16TH),
                             chord=_chords("...x....x..x....", 2,
                                           length=PPQN // 4)),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({SNARE: "x.xxx.xxx.xxx.xx",
                                           KICK: "x.......x......."})),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({HAT: "xxxxxxxxxxxxxxxx",
                                          HAT_OPEN: "......x.......x.",
                                          KICK: "x..x..x...x.x...",
                                          SNARE: "....X.......X...",
                                          CLAP: "............X..."}, 4),
                             bass=_bass("x..x..x.x.x.x..x", bars=4,
                                        length=TICKS_PER_16TH),
                             chord=_chords("...x....x..x..x.", 4,
                                           length=PPQN // 4),
                             keys=_line("..x..x....x..x..", 72, 4,
                                        length=PPQN // 4),
                             lead=_line("x...........x...", 84, 4,
                                        length=PPQN // 2, conversion=SCALE)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({TOM_HI: "x.x.....",
                                           TOM_MID: "....x.x.",
                                           TOM_LOW: "........xxxx....",
                                           CRASH: "..............x."})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({KICK: "x.......x.......",
                                          CRASH: "x..............."}, 2),
                             bass=_bass("x.......x.......", bars=2),
                             chord=_chords("x.......x.......", 2,
                                           length=PPQN)),
        })


def _rock() -> Style:
    """Eighths on the hat, backbeat snare, power-chord stabs. Chord part is
    ``parallel`` so a fifth stays a fifth over every chord in the set."""
    stabs = Phrase(notes=repeat(chord_hits("x.x...x.x.x...x.", velocity=100,
                                           length=PPQN // 2), 2),
                   bars=2, conversion=PARALLEL)
    return Style(
        name="ROCK", bpm=138, genre="rock", parts=PARTS, swing=0,
        sections={
            INTRO: _section(INTRO, 2,
                            drum=_drums({HAT: "x.x.x.x.x.x.x.x.",
                                         KICK: "x.......x......."}, 2),
                            chord=_chords("x.......x.......", 2,
                                          length=PPQN)),
            MAIN_A: _section(MAIN_A, 2,
                             drum=_drums({HAT: "x.x.x.x.x.x.x.x.",
                                          KICK: "x.....x.x.......",
                                          SNARE: "....X.......X..."}, 2),
                             bass=_bass("x.x.x.x.x.x.x.x.", bars=2),
                             chord=stabs),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({SNARE: "....x.x.xxxxxxxx",
                                           KICK: "x......."})),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({RIDE: "x.x.x.x.x.x.x.x.",
                                          KICK: "x.....x.x...x...",
                                          SNARE: "....X.......X...",
                                          CRASH: "x..............."}, 4),
                             bass=_bass("x.x.x.x.x.x.x.x.", bars=4),
                             chord=_chords("x.x...x.x.x...x.", 4,
                                           length=PPQN // 2, velocity=100),
                             lead=_line("........x...x...", 76, 4,
                                        length=PPQN // 2, conversion=SCALE)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({TOM_HI: "x.x.x.x.",
                                           TOM_LOW: "........x.x.x.x.",
                                           CRASH: "..............x."})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({KICK: "x.......x...x...",
                                          CRASH: "x...........x..."}, 2),
                             bass=_bass("x.......x...x...", bars=2),
                             chord=_chords("x.......x...x...", 2,
                                           length=PPQN)),
        })


def _lofi() -> Style:
    """Swung, sparse, seventh-chord territory. Swing is 34 % — enough to feel
    it, not so much that it becomes a shuffle."""
    return Style(
        name="LOFI", bpm=84, genre="lofi", parts=PARTS, swing=34,
        sections={
            INTRO: _section(INTRO, 2,
                            drum=_drums({HAT: "..x...x...x...x.",
                                         KICK: "x.......x......."}, 2),
                            chord=_chords("x...............", 2,
                                          length=PPQN * 2)),
            MAIN_A: _section(MAIN_A, 2,
                             drum=_drums({HAT: "..x...x...x...x.",
                                          KICK: "x.....x.....x...",
                                          SNARE: "....x.......x..."}, 2),
                             bass=_bass("x.....x.....x...", bars=2,
                                        length=PPQN // 2),
                             chord=_chords("x.......x.......", 2,
                                           length=PPQN * 2),
                             keys=_line("....x.....x.....", 67, 2,
                                        length=PPQN // 2)),
            FILL_AB: _section(FILL_AB, 1,
                              drum=_drums({SNARE: "........x.x.x.x.",
                                           HAT: "..x...x."})),
            MAIN_B: _section(MAIN_B, 4,
                             drum=_drums({HAT: "..x...x...x...x.",
                                          HAT_OPEN: "..............x.",
                                          KICK: "x.....x.....x...",
                                          SNARE: "....x.......x...",
                                          SHAKER: "x.x.x.x.x.x.x.x."}, 4),
                             bass=_bass("x.....x.....x...", bars=4,
                                        length=PPQN // 2),
                             chord=_chords("x.......x.......", 4,
                                           length=PPQN * 2),
                             keys=_line("....x.....x...x.", 67, 4,
                                        length=PPQN // 2),
                             lead=_line("..........x.....", 81, 4,
                                        length=PPQN, conversion=SCALE)),
            FILL_BA: _section(FILL_BA, 1,
                              drum=_drums({TOM_MID: "x.x.....",
                                           SNARE: "........x.x.....",
                                           CRASH: "..............x."})),
            ENDING: _section(ENDING, 2,
                             drum=_drums({KICK: "x...............",
                                          CRASH: "x..............."}, 2),
                             bass=_bass("x...............", bars=2,
                                        length=PPQN * 4),
                             chord=_chords("x...............", 2,
                                           length=PPQN * 4)),
        })


_BUILDERS = (_house, _ballad, _bossa, _funk, _rock, _lofi)


def factory_styles() -> tuple[Style, ...]:
    return tuple(build() for build in _BUILDERS)


def style_named(name: str) -> Style:
    """Look up a factory style by name, falling back to the first one. Config
    files and saved projects feed this, so an unknown name must not be fatal."""
    for style in factory_styles():
        if style.name == name:
            return style
    return factory_styles()[0]
