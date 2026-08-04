"""The four oscillator engines — every one a pure function of a phase ramp.

A voice hands each engine the same thing: a float64 phase array in cycles
(the accumulator lives in the voice, so retriggers and pitch bends are the
caller's business) and the patch's engine parameters. Everything here is
stateless and vectorized, which is what makes the engines swappable under a
sounding voice and byte-deterministic in tests.

* ``va`` — band-limited saw/square/triangle/sine from the mip tables.
* ``fm`` — two operators, carrier phase-modulated by the modulator
  (ratio + index, DX-style but one pair; no feedback, so no serial math).
* ``wavetable`` — a morph scan across sine → triangle → saw → square;
  ``position`` sweeps the bank with linear crossfades.
* ``pd`` — Casio-CZ phase distortion: the ramp is bent at a movable
  breakpoint and read against a cosine, ``warp`` sweeping mellow → nasal.
"""
from __future__ import annotations

import numpy as np

from core.dsp import tables

ENGINES = ("va", "fm", "wavetable", "pd")
_WT_BANK = ("sine", "triangle", "saw", "square")


def va(phases: np.ndarray, freq: float, shape: str) -> np.ndarray:
    return tables.read(tables.table(shape, freq), phases)


def fm(phases: np.ndarray, freq: float, ratio: float,
       index: float) -> np.ndarray:
    modulator = tables.read(tables.SINE, phases * max(0.25, ratio))
    return tables.read(tables.SINE, phases + modulator * index)


def wavetable(phases: np.ndarray, freq: float,
              position: float) -> np.ndarray:
    position = min(1.0, max(0.0, position)) * (len(_WT_BANK) - 1)
    low = int(position)
    high = min(low + 1, len(_WT_BANK) - 1)
    blend = position - low
    a = tables.read(tables.table(_WT_BANK[low], freq), phases)
    if high == low or blend == 0.0:
        return a
    b = tables.read(tables.table(_WT_BANK[high], freq), phases)
    return a * (1.0 - blend) + b * blend


def pd(phases: np.ndarray, freq: float, warp: float) -> np.ndarray:
    # Breakpoint walks from 0.5 (pure cosine) toward 0.05 (buzzy).
    d = 0.5 - min(1.0, max(0.0, warp)) * 0.45
    p = phases % 1.0
    bent = np.where(p < d, p * (0.5 / d),
                    0.5 + (p - d) * (0.5 / (1.0 - d)))
    return -tables.read(tables.COSINE, bent)


def render(engine: str, phases: np.ndarray, freq: float,
           params) -> np.ndarray:
    """Dispatch on the patch's engine name; unknown names fall back to a
    sine rather than raising under a sounding voice."""
    if engine == "va":
        return va(phases, freq, params.shape)
    if engine == "fm":
        return fm(phases, freq, params.fm_ratio, params.fm_index)
    if engine == "wavetable":
        return wavetable(phases, freq, params.wt_position)
    if engine == "pd":
        return pd(phases, freq, params.pd_warp)
    return tables.read(tables.SINE, phases)
