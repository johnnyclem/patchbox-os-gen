"""The two global macros — density and complexity — as a pure fold.

Layers keep their own settings; the macros are applied at render time as a
bias, not written back into the layers. Turning the density macro down and
back up therefore returns exactly the piece you had — a macro is a lens,
not an edit.
"""
from __future__ import annotations

from dataclasses import replace

from core.layers import LayerParams


def apply_macros(params: LayerParams, density: float,
                 complexity: float) -> LayerParams:
    """Bias one layer's params by the global macros (both 0..1, 0.5 = flat).

    Density scales note-probability; complexity leans on the parameters
    that add event-variety (markov temperature, random interval, euclid
    pulses) without touching pitch material.
    """
    density_bias = 2.0 * (max(0.0, min(1.0, density)) - 0.5)
    complexity_bias = 2.0 * (max(0.0, min(1.0, complexity)) - 0.5)
    return replace(
        params,
        density=params.density + 0.5 * density_bias,
        temperature=params.temperature + 0.3 * complexity_bias,
        max_interval=params.max_interval + round(4 * complexity_bias),
        pulses=params.pulses + round(2 * complexity_bias),
    ).normalised()
