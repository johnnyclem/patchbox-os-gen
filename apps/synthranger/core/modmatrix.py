"""The mod matrix — four slots per part, resolved once per block.

Sources are the performance surface: the XY pad, the mod wheel (CC 1),
velocity and the part's LFO. Destinations are offsets applied to the
effective patch for one block — nothing is ever written back into the
patch, the same lens rule as morphing. ``timbre`` is the one indirection:
it lands on whichever parameter gives the current engine its character
(wavetable position, PD warp, FM index, or VA detune).
"""
from __future__ import annotations

from dataclasses import dataclass

MOD_SOURCES = ("none", "xy_x", "xy_y", "mod_wheel", "velocity", "lfo")
MOD_DESTS = ("none", "cutoff", "pitch", "timbre", "resonance", "drive")
SLOTS = 4


@dataclass(frozen=True, slots=True)
class ModSlot:
    source: str = "none"
    dest: str = "none"
    amount: float = 0.0

    def normalised(self) -> "ModSlot":
        return ModSlot(
            source=self.source if self.source in MOD_SOURCES else "none",
            dest=self.dest if self.dest in MOD_DESTS else "none",
            amount=max(-1.0, min(1.0, float(self.amount))))

    def to_config(self) -> list:
        return [self.source, self.dest, self.amount]

    @classmethod
    def from_config(cls, raw) -> "ModSlot":
        raw = list(raw or [])
        raw += ["none", "none", 0.0][len(raw):]
        return cls(source=str(raw[0]), dest=str(raw[1]),
                   amount=float(raw[2])).normalised()


def default_slots() -> tuple:
    return (ModSlot("xy_x", "cutoff", 0.7),
            ModSlot("xy_y", "timbre", 0.8),
            ModSlot("mod_wheel", "cutoff", 0.3),
            ModSlot("velocity", "cutoff", 0.2))


def resolve(slots, sources: dict) -> dict:
    """Sum each destination's offsets; sources are −1..1 (bipolar) or 0..1
    (unipolar) — the caller decides what each means at the destination."""
    offsets: dict[str, float] = {}
    for slot in slots:
        if slot.dest == "none" or slot.source == "none":
            continue
        value = sources.get(slot.source, 0.0)
        offsets[slot.dest] = offsets.get(slot.dest, 0.0) \
            + value * slot.amount
    return offsets
