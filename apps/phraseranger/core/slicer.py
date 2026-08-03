"""The slicer — a phrase chopped onto pads, or spread across a keyboard.

Slice mode divides the source track's loop into equal windows, one per pad;
tapping a pad fires that window immediately (the engine schedules its notes
from *now*). Chromatic mode gives every pad the whole phrase transposed —
pad 5 up a fourth, pad 0 down an octave — which turns a captured lick into
an instrument. Velocity layers scale the fired material by how the pad was
struck (on a touch panel: where — upper half soft, lower half full).

Slicing is instant because it computes nothing: pads are ``window`` /
``transposed`` views of the immutable phrase, built on demand.
"""
from __future__ import annotations

from core.phrase import Phrase

PAD_COUNT = 16
MODES = ("slice", "chromatic")
# Chromatic pad transpositions: pad 8 = unison, a two-octave spread.
_CHROMATIC_BASE = 8


def pad_phrase(source: Phrase, mode: str, pad: int) -> Phrase:
    """What one pad fires. Empty source → empty phrase; a dead pad on stage
    must be a no-op, not a crash."""
    if source.empty or not 0 <= pad < PAD_COUNT:
        return Phrase(length_ticks=source.length_ticks)
    if mode == "chromatic":
        return source.transposed((pad - _CHROMATIC_BASE))
    span = max(1, source.length_ticks // PAD_COUNT)
    return source.window(pad * span, span)


def pad_caption(source: Phrase, mode: str, pad: int) -> str:
    if mode == "chromatic":
        offset = pad - _CHROMATIC_BASE
        return f"{offset:+d}" if offset else "·"
    return str(pad + 1)


def velocity_scale(layer: float) -> float:
    """Pad strike position (0 = top/soft, 1 = bottom/full) → scale. The
    floor keeps a soft layer audible rather than decorative."""
    return 0.35 + 0.65 * max(0.0, min(1.0, layer))
