"""Probability-grid layer generator — the Marbles-style lattice.

Rows are scale degrees (bottom row = the register's root), columns are
steps; each cell holds a probability. Rendering coin-flips every cell with
the pattern rng, top row first so at most one note per step wins (highest
probability-weighted voice takes the slot in P0 — chords are the harmony
layer's job, not the lattice's).

The MAP screen edits exactly this grid; an empty grid gets a factory
seeding derived from the density knob so a fresh layer sounds without a
single tap.
"""
from __future__ import annotations

from core.layers import GRID_ROWS, LayerParams, Pattern, ScaleContext, Step


def default_grid(step_count: int, density: float) -> tuple:
    """The factory lattice: root-heavy downbeats, thinning upward — enough
    structure to sound like music the second the layer exists."""
    rows = []
    for row in range(GRID_ROWS):
        cells = []
        for step in range(step_count):
            downbeat = step % 4 == 0
            weight = density * (1.0 - row / (GRID_ROWS + 1))
            cells.append(round(weight * (0.9 if downbeat else 0.35), 3))
        rows.append(tuple(cells))
    return tuple(rows)


def grid_for(params: LayerParams) -> tuple:
    """The stored grid, resized to the layer's step count if it drifted."""
    grid = params.grid
    if (not grid or len(grid) != GRID_ROWS
            or any(len(row) != params.step_count for row in grid)):
        return default_grid(params.step_count, params.density)
    return grid


def render(params: LayerParams, rng, ctx: ScaleContext,
           generation: int = 0) -> Pattern:
    grid = grid_for(params)
    span = ctx.degrees_span()
    steps = []
    for step in range(params.step_count):
        for row in range(GRID_ROWS - 1, -1, -1):    # top voice wins the slot
            if rng.random() < grid[row][step]:
                degree = round(row / max(1, GRID_ROWS - 1) * (span - 1))
                steps.append(Step(index=step,
                                  note=ctx.degree_to_midi(degree),
                                  velocity=params.velocity,
                                  length_ticks=params.length_ticks()))
                break
    return Pattern(steps=tuple(steps), step_count=params.step_count)
