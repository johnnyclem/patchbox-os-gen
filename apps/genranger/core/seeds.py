"""Seed arithmetic and the eight seed slots.

``mix`` is the one hash the whole app derives pattern rngs from. It is
written out arithmetically (splitmix64-style) rather than using ``hash()``,
which Python salts per process — determinism across boots is a product
feature here, not a nicety.
"""
from __future__ import annotations

SLOTS = 8
_MASK = (1 << 64) - 1


def mix(*parts: int) -> int:
    """Fold integers into one well-scrambled 63-bit seed."""
    state = 0x9E3779B97F4A7C15
    for part in parts:
        state = (state ^ (int(part) & _MASK)) * 0xBF58476D1CE4E5B9 & _MASK
        state = (state ^ (state >> 27)) * 0x94D049BB133111EB & _MASK
        state ^= state >> 31
    return state & (_MASK >> 1)


class SeedStore:
    """Eight numbered slots of captured states — the same save/occupied
    shape as MidiRanger's scenes, holding whatever dict the engine captures
    (layer states + macros + key). Empty slots recall nothing rather than
    raising."""

    def __init__(self, slots: dict | None = None) -> None:
        self._slots: dict[int, dict] = {}
        for slot, state in (slots or {}).items():
            slot = int(slot)
            if 0 <= slot < SLOTS and isinstance(state, dict):
                self._slots[slot] = state

    def save(self, slot: int, state: dict) -> bool:
        if not 0 <= int(slot) < SLOTS:
            return False
        self._slots[int(slot)] = state
        return True

    def get(self, slot: int) -> dict | None:
        return self._slots.get(int(slot))

    def occupied(self) -> tuple[bool, ...]:
        return tuple(slot in self._slots for slot in range(SLOTS))

    def to_config(self) -> dict[str, dict]:
        """JSON object keys are strings; keep the file shape honest."""
        return {str(slot): state
                for slot, state in sorted(self._slots.items())}
