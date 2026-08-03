"""Mutation — the vocabulary of small changes evolution is made of.

A mutation is a pure function from one ``LayerParams`` to another, drawing
every random number from the rng it is handed (the engine's dedicated
cruise rng — nothing else may consume from it, or determinism dies). Chaos
scales both how bold each op is and how many ops land per firing.

Locks are vetoed *here* for whole layers (a locked layer's params never
change) and in ``render_layer`` for step ranges (the mutation lands, the
locked steps are copied back).
"""
from __future__ import annotations

from dataclasses import replace

from core.layers import CA_RULES, LayerParams, MARKOV_STYLES


def _nudge_density(params: LayerParams, rng, chaos: float) -> LayerParams:
    span = 0.05 + 0.25 * chaos
    return replace(params, density=params.density
                   + rng.uniform(-span, span))


def _rotate(params: LayerParams, rng, chaos: float) -> LayerParams:
    return replace(params, rotate=params.rotate + rng.choice((-1, 1)))


def _reseed(params: LayerParams, rng, chaos: float) -> LayerParams:
    """Handled specially by the engine: the op marks itself by returning the
    params unchanged; the engine reseeds the layer's seed salt from the same
    rng. Kept in the table so its *probability* lives with the others."""
    return params


def _octave_shift(params: LayerParams, rng, chaos: float) -> LayerParams:
    step = rng.choice((-1, 1))
    return replace(params, octave_low=params.octave_low + step,
                   octave_high=params.octave_high + step)


def _velocity_tilt(params: LayerParams, rng, chaos: float) -> LayerParams:
    return replace(params, velocity=params.velocity
                   + rng.randint(-12, 12))


def _style_nudge(params: LayerParams, rng, chaos: float) -> LayerParams:
    if params.algorithm == "markov":
        if rng.random() < 0.5:
            return replace(params, temperature=params.temperature
                           + rng.uniform(-0.15, 0.15 + 0.2 * chaos))
        return replace(params, style=rng.choice(MARKOV_STYLES))
    if params.algorithm == "cellular":
        here = CA_RULES.index(params.rule) if params.rule in CA_RULES else 0
        return replace(params,
                       rule=CA_RULES[(here + rng.choice((-1, 1)))
                                     % len(CA_RULES)])
    if params.algorithm == "euclid":
        return replace(params, pulses=params.pulses + rng.choice((-1, 1)))
    if params.algorithm == "grid":
        grid = [list(row) for row in params.grid] if params.grid else None
        if grid:
            row = rng.randrange(len(grid))
            step = rng.randrange(len(grid[row]))
            grid[row][step] = round(max(0.0, min(
                1.0, grid[row][step] + rng.uniform(-0.4, 0.4))), 3)
            return replace(params, grid=tuple(tuple(r) for r in grid))
        return params
    return replace(params, max_interval=params.max_interval
                   + rng.choice((-1, 1)))


# (op, base weight). reseed is rare at low chaos — it is the biggest jump.
_OPS = ((_nudge_density, 1.0), (_style_nudge, 1.0), (_rotate, 0.6),
        (_velocity_tilt, 0.5), (_octave_shift, 0.3), (_reseed, 0.25))
RESEED_OP = _reseed


def pick_ops(rng, chaos: float) -> list:
    """Which ops fire this mutation: 1 at chaos 0, up to 3 at chaos 1, each
    chosen by weight with reseed's weight growing with chaos."""
    count = 1 + (1 if rng.random() < chaos else 0) \
        + (1 if rng.random() < chaos * 0.5 else 0)
    ops = []
    for _ in range(count):
        weights = [w * (1.0 + 3.0 * chaos if op is _reseed else 1.0)
                   for op, w in _OPS]
        mark = rng.random() * sum(weights)
        running = 0.0
        for (op, _w), weight in zip(_OPS, weights):
            running += weight
            if running >= mark:
                ops.append(op)
                break
    return ops


def mutate(params: LayerParams, rng, chaos: float) -> tuple[LayerParams, bool]:
    """One mutation firing. Returns (new params, reseed_requested).

    A locked layer is returned untouched — the veto lives here so every
    caller (cruise, mutate-now, macros) gets it for free.
    """
    if params.locked:
        return params, False
    reseed = False
    for op in pick_ops(rng, chaos):
        if op is _reseed:
            reseed = True
            continue
        params = op(params, rng, chaos).normalised()
    return params, reseed
