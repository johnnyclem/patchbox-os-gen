"""Scenes — complete instrument states, saved to slots and morphable.

A scene is a plain JSON-able dict of the engine's track states (phrases +
params). Capturing is a copy; recalling is an apply. The blend helper is
kept from the family shape though PhraseRanger does not morph — half a
phrase is not a thing either.
"""
from __future__ import annotations

SLOTS = 8


def blend(a, b, t: float):
    """Blend two parameter trees. ``t`` 0 → all A, 1 → all B."""
    t = max(0.0, min(1.0, float(t)))
    if isinstance(a, bool) or isinstance(b, bool):
        return a if t < 0.5 else b          # bool is int; test it first
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        value = a + (b - a) * t
        return round(value) if isinstance(a, int) and isinstance(b, int) \
            else value
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        return {k: blend(a.get(k), b.get(k), t) if k in a and k in b
                else (a.get(k) if k in a else b.get(k))
                for k in keys}
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) \
            and len(a) == len(b):
        blended = [blend(x, y, t) for x, y in zip(a, b)]
        return tuple(blended) if isinstance(a, tuple) else blended
    return a if t < 0.5 else b


class SceneStore:
    """Eight numbered slots. Empty slots recall nothing rather than raising —
    an empty pad on stage must be a no-op, not a crash."""

    def __init__(self, scenes: dict[int, dict] | None = None) -> None:
        self._scenes: dict[int, dict] = {}
        for slot, scene in (scenes or {}).items():
            slot = int(slot)
            if 0 <= slot < SLOTS and isinstance(scene, dict):
                self._scenes[slot] = scene

    def save(self, slot: int, scene: dict) -> bool:
        if not 0 <= int(slot) < SLOTS:
            return False
        self._scenes[int(slot)] = scene
        return True

    def get(self, slot: int) -> dict | None:
        return self._scenes.get(int(slot))

    def occupied(self) -> tuple[bool, ...]:
        return tuple(slot in self._scenes for slot in range(SLOTS))

    def to_config(self) -> dict[str, dict]:
        """JSON object keys are strings; keep the file shape honest."""
        return {str(slot): scene
                for slot, scene in sorted(self._scenes.items())}
