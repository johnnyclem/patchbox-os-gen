"""Markov layer generator — an order-N walk over scale degrees.

Transition tables are built procedurally from interval-preference curves
rather than stored matrices: a *style* is a function ``weight(interval) ->
float`` over the signed degree interval, so every register and scale gets a
sensible table for free and a mutation can nudge ``temperature`` (blending
toward uniform) without any table surgery.

P0 keeps orders 1 and 2: order 2 biases against immediately re-reversing,
which is most of what a longer memory audibly buys. Learning tables from
played input is deferred (RANGER-SUITE-PLAN Phase 7 territory).
"""
from __future__ import annotations

import math

from core.layers import LayerParams, Pattern, ScaleContext, Step

# Style → preference over the signed interval (in scale degrees).
_STYLES = {
    # Stepwise motion, the walking-bass feel.
    "walk": lambda iv: 1.0 / (1.0 + (abs(iv) - 1) ** 2) if iv else 0.05,
    # Chord-tone leaps: thirds and fifths (degree intervals 2 and 4).
    "arpy": lambda iv: {2: 1.0, -2: 0.9, 4: 0.7, -4: 0.6, 0: 0.2,
                        7: 0.3, -7: 0.3}.get(iv, 0.02),
    # Root/fifth gravity with long dwells.
    "drone": lambda iv: 1.5 if iv == 0 else (0.6 if abs(iv) == 4 else 0.05),
    # Near-uniform wandering.
    "wander": lambda iv: 1.0 / (1.0 + 0.1 * abs(iv)),
}


def _weights(here: int, span: int, params: LayerParams) -> list[float]:
    style = _STYLES[params.style]
    # Temperature blends the style toward uniform: 0 = strict, 1 = anything.
    t = params.temperature
    return [(1.0 - t) * style(target - here) + t * 1.0
            for target in range(span)]


def _choose(rng, weights: list[float]) -> int:
    total = math.fsum(weights)
    if total <= 0:
        return 0
    mark = rng.random() * total
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if running >= mark:
            return index
    return len(weights) - 1


def render(params: LayerParams, rng, ctx: ScaleContext,
           generation: int = 0) -> Pattern:
    span = ctx.degrees_span()
    here = rng.randrange(span)
    previous_move = 0
    steps = []
    for index in range(params.step_count):
        if rng.random() >= params.density:
            continue                    # a rest; the walk holds its place
        weights = _weights(here, span, params)
        if params.order >= 2 and previous_move:
            # Order 2, cheaply: discourage immediately undoing the last
            # move, which is what turns a walk into a wobble.
            undo = here - previous_move
            if 0 <= undo < span:
                weights[undo] *= 0.25
        target = _choose(rng, weights)
        previous_move = target - here
        here = target
        steps.append(Step(index=index, note=ctx.degree_to_midi(here),
                          velocity=params.velocity,
                          length_ticks=params.length_ticks()))
    return Pattern(steps=tuple(steps), step_count=params.step_count)
