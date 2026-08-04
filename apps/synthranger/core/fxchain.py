"""Per-part effects chain: drive into chorus, in that order — saturation
into a modulated tap sounds like a synth channel; the other way around
sounds like a broken chorus. The master delay lives in the Synth (it is a
send bus, shared and tempo-synced)."""
from __future__ import annotations

import numpy as np

from core.dsp.effects import Chorus, drive


class PartFx:
    __slots__ = ("_chorus",)

    def __init__(self, sample_rate: int) -> None:
        self._chorus = Chorus(sample_rate)

    def process(self, x: np.ndarray, patch) -> np.ndarray:
        return self._chorus.process(drive(x, patch.drive), patch.chorus)
