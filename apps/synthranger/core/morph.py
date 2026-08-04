"""Patch morphing — one knob between two complete sounds.

A part carries patches A and B and a morph position; the *effective* patch
is A with every numeric field linearly interpolated toward B (envelope
times too — they are numbers like any other) and categorical fields
snapping at the midpoint. Morphing never writes back: turn the knob to 0
and A is exactly A again, the family's lens rule.
"""
from __future__ import annotations

from dataclasses import replace

from core.patch import NUMERIC_FIELDS, Patch


def morphed(a: Patch, b: Patch, t: float) -> Patch:
    t = min(1.0, max(0.0, float(t)))
    if t <= 0.0:
        return a
    if t >= 1.0:
        return b
    values = {}
    for name in NUMERIC_FIELDS:
        va, vb = getattr(a, name), getattr(b, name)
        values[name] = va + (vb - va) * t
    for name in ("amp_env", "mod_env"):
        ea, eb = getattr(a, name), getattr(b, name)
        values[name] = tuple(x + (y - x) * t for x, y in zip(ea, eb))
    snap = b if t >= 0.5 else a
    for name in ("engine", "shape", "filter_mode", "lfo_dest",
                 "lfo_shape"):
        values[name] = getattr(snap, name)
    return replace(a, **values).normalised()
