"""Scale quantizer — the front of the thru chain.

Snaps incoming notes into a key using the shared theory module. The register
is preserved (``snap_to_scale`` never moves a note more than a whole step),
so a player leaning on wrong notes hears corrections, not jumps.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.theory import SCALE_NAMES, scale_for, snap_to_scale


@dataclass(frozen=True, slots=True)
class QuantizerParams:
    enabled: bool = False
    root: int = 0                   # pitch class, C = 0
    scale: str = "major"

    def normalised(self) -> "QuantizerParams":
        return replace(self, root=int(self.root) % 12,
                       scale=self.scale if self.scale in SCALE_NAMES
                       else "major")


def quantize(note: int, params: QuantizerParams) -> int:
    if not params.enabled:
        return note
    return snap_to_scale(note, params.root, scale_for(params.scale))
