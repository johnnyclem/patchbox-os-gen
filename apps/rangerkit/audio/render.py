"""Offline rendering — audio without a device, for CI and bouncing.

Drives any renderer block by block exactly the way the PortAudio callback
would, and returns the concatenated buffer. Deterministic by construction:
the same note calls interleaved with the same block counts produce the same
samples, which is what lets the tests assert on audio numerically instead
of listening.
"""
from __future__ import annotations

import numpy as np

from rangerkit.audio import BLOCK_FRAMES


def render_blocks(renderer, blocks: int,
                  frames: int = BLOCK_FRAMES) -> np.ndarray:
    """``blocks`` consecutive blocks from the renderer, stitched."""
    parts = [renderer.render(frames) for _ in range(blocks)]
    out = np.concatenate(parts, axis=0)
    if not np.all(np.isfinite(out)):
        raise ValueError("renderer produced non-finite samples")
    return out


def peak(buffer: np.ndarray) -> float:
    return float(np.max(np.abs(buffer))) if buffer.size else 0.0


def rms(buffer: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(buffer)))) if buffer.size else 0.0
