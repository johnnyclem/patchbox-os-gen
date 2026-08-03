"""Constrained-random layer generator.

Uniform chaos with three leashes: the scale (via degree space), the register
(the context clamps), and the maximum melodic interval — which is the one
that makes random lines singable. For the cc role this renders a smoothed
random curve instead of notes.
"""
from __future__ import annotations

from dataclasses import replace

from core.layers import LayerParams, Pattern, ScaleContext, Step


def render(params: LayerParams, rng, ctx: ScaleContext,
           generation: int = 0) -> Pattern:
    if params.role == "cc":
        return _render_cc(params, rng)
    span = ctx.degrees_span()
    here = rng.randrange(span)
    steps = []
    for index in range(params.step_count):
        if rng.random() >= params.density:
            continue
        low = max(0, here - params.max_interval)
        high = min(span - 1, here + params.max_interval)
        here = rng.randint(low, high)
        velocity = max(1, min(127, params.velocity + rng.randint(-10, 10)))
        steps.append(Step(index=index, note=ctx.degree_to_midi(here),
                          velocity=velocity,
                          length_ticks=params.length_ticks()))
    return Pattern(steps=tuple(steps), step_count=params.step_count)


def _render_cc(params: LayerParams, rng) -> Pattern:
    """A drifting control curve: random targets, linear glide between them.
    Emitted by the engine at quarter-step resolution."""
    low, high = sorted((params.cc_low, params.cc_high))
    anchors = max(2, round(2 + params.density * 6))
    marks = sorted({0, params.step_count - 1}
                   | {rng.randrange(params.step_count)
                      for _ in range(anchors)})
    values = {mark: rng.randint(low, high) for mark in marks}
    curve = []
    points = sorted(values)
    for step in range(params.step_count):
        left = max(p for p in points if p <= step)
        right = min(p for p in points if p >= step)
        if left == right:
            curve.append(values[left])
        else:
            t = (step - left) / (right - left)
            curve.append(round(values[left]
                               + (values[right] - values[left]) * t))
    pattern = Pattern(steps=(), step_count=params.step_count)
    return replace(pattern, cc_curve=tuple(curve))
