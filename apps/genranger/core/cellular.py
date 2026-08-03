"""Cellular-automaton layer generator — 1-D elementary CA rows as steps.

The layer's seed row evolves one generation per pattern cycle: the piece
literally computes itself forward. A live cell at step *i* fires a note
whose pitch climbs with the density of the neighbourhood around it — Rule 90
gives Sierpinski sparkle, 110 gives lopsided grooves, 30 gives noise that
still rhymes with itself.

Everything here is arithmetic on the rule number and the seed row — the rng
is only consulted for velocity humanization, so a CA layer is *almost*
frozen and mutations change it by changing the rule or the seed row.
"""
from __future__ import annotations

from core.layers import LayerParams, Pattern, ScaleContext, Step

ROW_WIDTH = 16                  # seed rows are 16 bits; wider steps wrap


def step_row(rule: int, row: tuple[bool, ...]) -> tuple[bool, ...]:
    """One CA generation, periodic boundary (the bar is a loop, so is the
    row)."""
    width = len(row)
    out = []
    for i in range(width):
        neighborhood = (row[(i - 1) % width] << 2) | (row[i] << 1) \
            | row[(i + 1) % width]
        out.append(bool((rule >> neighborhood) & 1))
    return tuple(out)


def row_at(rule: int, seed_bits: int, generation: int,
           width: int = ROW_WIDTH) -> tuple[bool, ...]:
    """The row after ``generation`` steps from the seed. Iterative — the
    engine calls this once per cycle with generation increasing by one, so
    there is nothing to cache."""
    row = tuple(bool((seed_bits >> i) & 1) for i in range(width))
    if not any(row):
        row = tuple(i == width // 2 for i in range(width))  # never all-dead
    for _ in range(max(0, generation)):
        row = step_row(rule, row)
    return row


def render(params: LayerParams, rng, ctx: ScaleContext,
           generation: int = 0) -> Pattern:
    row = row_at(params.rule, params.ca_seed, generation)
    steps = []
    span = ctx.degrees_span()
    for index in range(params.step_count):
        cell = row[index % len(row)]
        if not cell:
            continue
        if rng.random() >= 0.35 + 0.65 * params.density:
            continue                    # density thins the living cells
        # Pitch from the neighbourhood: lonely cells sit low, crowded ones
        # climb — structure in the row becomes contour in the line.
        crowd = sum(row[(index + d) % len(row)] for d in (-2, -1, 1, 2))
        degree = round((crowd / 4) * (span - 1))
        velocity = max(1, min(127, params.velocity
                              + rng.randint(-6, 6)))
        steps.append(Step(index=index, note=ctx.degree_to_midi(degree),
                          velocity=velocity,
                          length_ticks=params.length_ticks()))
    return Pattern(steps=tuple(steps), step_count=params.step_count)
