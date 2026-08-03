"""Euclidean layer generator — rangerkit's algorithm, given a pitch.

Deterministic even across generations: the euclidean lattice ignores the
rng entirely, so an un-mutated euclid layer repeats exactly — it is the
skeleton the stochastic layers evolve around. Density scales the pulse
count; the pitch is the register's root (rhythm layers point this at a drum
channel where pitch picks the pad).
"""
from __future__ import annotations

from rangerkit.euclid import euclidean, pulse_positions

from core.layers import LayerParams, Pattern, ScaleContext, Step


def render(params: LayerParams, rng, ctx: ScaleContext,
           generation: int = 0) -> Pattern:
    # Density folds over the stored pulse count: the knob thins or thickens
    # the lattice without forgetting what "full" meant.
    pulses = round(params.pulses * (0.25 + 1.5 * params.density))
    pulses = max(0, min(params.step_count, pulses))
    lattice = euclidean(params.step_count, pulses, params.rotate)
    note = ctx.degree_to_midi(0)
    steps = tuple(Step(index=index, note=note, velocity=params.velocity,
                       length_ticks=params.length_ticks())
                  for index in pulse_positions(lattice))
    return Pattern(steps=steps, step_count=params.step_count)
