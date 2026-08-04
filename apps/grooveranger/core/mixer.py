"""Mixer + master-bus state, engine-side.

The engine is the authority on these numbers (they live in the project and
the snapshot); the sampler's copy is kept true by the internal CC contract —
every change here is also emitted as a CC through the ``internal`` endpoint
(CC 7 per pad channel; CC 74/85/91/7 on the master channel 15), which is the
same one-way street every other engine→instrument fact travels.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from core.steps import PADS

LEVEL_MAX = 1.27                 # CC 7 value 127 / 100


def _unity() -> tuple:
    return tuple(1.0 for _ in range(PADS))


@dataclass(frozen=True, slots=True)
class Mixer:
    levels: tuple = field(default_factory=_unity)
    master: float = 1.0
    filter: float = 0.5          # one-knob: 0.5 = open
    delay_div: int = 2
    reverb: float = 0.3
    damp: float = 0.0            # reverb damping; 0 = the original tail
    duck: float = 0.0            # sidechain depth on the returns

    def normalised(self) -> "Mixer":
        levels = tuple(max(0.0, min(LEVEL_MAX, float(v)))
                       for v in self.levels[:PADS])
        levels += tuple(1.0 for _ in range(PADS - len(levels)))
        return replace(
            self, levels=levels,
            master=max(0.0, min(LEVEL_MAX, float(self.master))),
            filter=max(0.0, min(1.0, float(self.filter))),
            delay_div=max(0, min(3, int(self.delay_div))),
            reverb=max(0.0, min(1.0, float(self.reverb))),
            damp=max(0.0, min(1.0, float(self.damp))),
            duck=max(0.0, min(1.0, float(self.duck))))

    def with_level(self, pad: int, value: float) -> "Mixer":
        levels = list(self.levels)
        levels[pad] = value
        return replace(self, levels=tuple(levels)).normalised()

    def to_config(self) -> dict:
        return {"levels": list(self.levels), "master": self.master,
                "filter": self.filter, "delay_div": self.delay_div,
                "reverb": self.reverb, "damp": self.damp,
                "duck": self.duck}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Mixer":
        raw = raw or {}
        return cls(levels=tuple(float(v) for v in
                                raw.get("levels", _unity())),
                   master=float(raw.get("master", 1.0)),
                   filter=float(raw.get("filter", 0.5)),
                   delay_div=int(raw.get("delay_div", 2)),
                   reverb=float(raw.get("reverb", 0.3)),
                   damp=float(raw.get("damp", 0.0)),
                   duck=float(raw.get("duck", 0.0))).normalised()
