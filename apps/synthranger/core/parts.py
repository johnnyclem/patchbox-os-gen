"""Four parts — the multitimbral frame.

A part is a patch pair (A/B + morph), a listen channel, a level, a pan and
a polyphony cap. Parts are immutable; the engine swaps whole tuples and
the snapshot's ``parts_rev`` tells the App when the synth needs the new
values. The documented floor is 8 voices per part, 4 parts, 48 kHz — see
README for what that means on a Pi 5.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.modmatrix import ModSlot, SLOTS, default_slots
from core.morph import morphed
from core.patch import Patch

PARTS = 4
MAX_PART_VOICES = 8


@dataclass(frozen=True, slots=True)
class Part:
    patch: Patch = field(default_factory=Patch)
    patch_b: Patch = field(default_factory=Patch)
    morph: float = 0.0
    channel: int = 0             # MIDI listen channel (internal = index)
    level: float = 0.85
    pan: float = 0.0
    poly: int = MAX_PART_VOICES
    muted: bool = False
    mods: tuple = field(default_factory=default_slots)

    def normalised(self) -> "Part":
        mods = tuple(slot.normalised() for slot in self.mods[:SLOTS])
        mods += tuple(ModSlot() for _ in range(SLOTS - len(mods)))
        return replace(
            self, patch=self.patch.normalised(),
            patch_b=self.patch_b.normalised(),
            morph=max(0.0, min(1.0, float(self.morph))),
            channel=max(0, min(15, int(self.channel))),
            level=max(0.0, min(1.27, float(self.level))),
            pan=max(-1.0, min(1.0, float(self.pan))),
            poly=max(1, min(MAX_PART_VOICES, int(self.poly))),
            mods=mods)

    def effective(self) -> Patch:
        return morphed(self.patch, self.patch_b, self.morph)

    def to_config(self) -> dict:
        return {"patch": self.patch.to_config(),
                "patch_b": self.patch_b.to_config(),
                "morph": self.morph, "channel": self.channel,
                "level": self.level, "pan": self.pan, "poly": self.poly,
                "muted": self.muted,
                "mods": [slot.to_config() for slot in self.mods]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Part":
        raw = raw or {}
        return cls(patch=Patch.from_config(raw.get("patch")),
                   patch_b=Patch.from_config(raw.get("patch_b")),
                   morph=float(raw.get("morph", 0.0)),
                   channel=int(raw.get("channel", 0)),
                   level=float(raw.get("level", 0.85)),
                   pan=float(raw.get("pan", 0.0)),
                   poly=int(raw.get("poly", MAX_PART_VOICES)),
                   muted=bool(raw.get("muted", False)),
                   mods=tuple(ModSlot.from_config(entry)
                              for entry in raw.get("mods", []))
                   or default_slots()).normalised()


def default_parts() -> tuple:
    return tuple(replace(Part(), channel=index).normalised()
                 for index in range(PARTS))
