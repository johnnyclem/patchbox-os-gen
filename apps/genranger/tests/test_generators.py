"""The five generators as pure functions, plus the state machinery."""
from __future__ import annotations

import random

from core.cellular import render as ca_render, row_at, step_row
from core.euclidgen import render as euclid_render
from core.layers import (GRID_ROWS, LayerParams, ScaleContext, render_layer)
from core.macros import apply_macros
from core.markov import render as markov_render
from core.mutate import mutate
from core.probgrid import default_grid, render as grid_render
from core.randomgen import render as random_render
from core.seeds import SeedStore, mix
from core.timeline import CAPACITY, Timeline
from rangerkit.theory import scale_for


def rng(seed=1):
    return random.Random(seed)


CTX = ScaleContext(root=0, scale="minor", octave_low=3, octave_high=5)


def in_scale(note: int, ctx=CTX) -> bool:
    return scale_for(ctx.scale).contains(note, ctx.root)


def in_register(note: int, ctx=CTX) -> bool:
    low = (ctx.octave_low + 1) * 12
    high = (ctx.octave_high + 2) * 12
    return low <= note < high


# --- shared properties ---------------------------------------------------------

def every_generator(params):
    yield euclid_render(params, rng(), CTX)
    yield markov_render(params, rng(), CTX)
    yield grid_render(params, rng(), CTX)
    yield ca_render(params, rng(), CTX)
    yield random_render(params, rng(), CTX)


def test_patterns_are_well_formed():
    params = LayerParams(density=0.8).normalised()
    for pattern in every_generator(params):
        assert pattern.step_count == params.step_count
        for step in pattern.steps:
            assert 0 <= step.index < pattern.step_count
            assert 0 <= step.note <= 127
            assert 1 <= step.velocity <= 127
            assert step.length_ticks >= 1


def test_same_rng_same_pattern():
    params = LayerParams(density=0.7).normalised()
    for render in (markov_render, grid_render, random_render):
        assert render(params, rng(7), CTX) == render(params, rng(7), CTX)
        assert render(params, rng(7), CTX) != render(params, rng(8), CTX) \
            or render is None       # astronomically unlikely to collide


# --- euclid --------------------------------------------------------------------

def test_euclid_ignores_the_rng_and_scales_with_density():
    params = LayerParams(algorithm="euclid", pulses=4,
                         density=0.5).normalised()
    assert euclid_render(params, rng(1), CTX) == \
        euclid_render(params, rng(99), CTX)
    thin = LayerParams(algorithm="euclid", pulses=8, density=0.1).normalised()
    thick = LayerParams(algorithm="euclid", pulses=8,
                        density=1.0).normalised()
    assert len(euclid_render(thin, rng(), CTX).steps) < \
        len(euclid_render(thick, rng(), CTX).steps)


# --- markov --------------------------------------------------------------------

def test_markov_stays_in_scale_and_register():
    params = LayerParams(algorithm="markov", density=1.0,
                         style="wander").normalised()
    pattern = markov_render(params, rng(), CTX)
    assert pattern.steps
    for step in pattern.steps:
        assert in_scale(step.note) and in_register(step.note)


def test_markov_walk_is_mostly_stepwise():
    params = LayerParams(algorithm="markov", density=1.0, style="walk",
                         temperature=0.0, step_count=32).normalised()
    pattern = markov_render(params, rng(3), CTX)
    notes = [s.note for s in pattern.steps]
    scale = scale_for("minor")
    degrees = []
    for note in notes:
        octave, rest = divmod(note - 48, 12)
        degrees.append(octave * len(scale)
                       + sorted(scale.degrees).index(rest))
    moves = [abs(b - a) for a, b in zip(degrees, degrees[1:])]
    assert sum(1 for m in moves if m <= 1) / len(moves) > 0.6


# --- cellular ------------------------------------------------------------------

def test_rule_90_is_xor_of_neighbours():
    row = (False, True, False, False, True, False, False, False)
    stepped = step_row(90, row)
    for i in range(len(row)):
        assert stepped[i] == (row[(i - 1) % 8] ^ row[(i + 1) % 8])


def test_row_at_is_iterated_step_row():
    seed = 0b0000000010000000
    row = row_at(110, seed, 0)
    for generation in range(1, 5):
        row = step_row(110, row)
        assert row_at(110, seed, generation) == row


def test_dead_seed_row_is_revived():
    assert any(row_at(90, 0, 0))


# --- probability grid ----------------------------------------------------------

def test_grid_extremes():
    zero = tuple(tuple(0.0 for _ in range(16)) for _ in range(GRID_ROWS))
    ones = tuple(tuple(1.0 for _ in range(16)) for _ in range(GRID_ROWS))
    silent = LayerParams(algorithm="grid", grid=zero).normalised()
    full = LayerParams(algorithm="grid", grid=ones).normalised()
    assert not grid_render(silent, rng(), CTX).steps
    assert len(grid_render(full, rng(), CTX).steps) == 16


def test_default_grid_favors_downbeats():
    grid = default_grid(16, density=0.8)
    assert grid[0][0] > grid[0][1]


# --- constrained random --------------------------------------------------------

def test_random_honours_the_interval_leash():
    params = LayerParams(algorithm="random", density=1.0, max_interval=2,
                         step_count=32).normalised()
    pattern = random_render(params, rng(5), CTX)
    notes = [s.note for s in pattern.steps]
    for a, b in zip(notes, notes[1:]):
        assert abs(b - a) <= 2 * 4      # 2 degrees ≤ a fifth-ish in semitones


def test_cc_role_renders_a_curve_not_notes():
    params = LayerParams(role="cc", algorithm="random", cc_low=20,
                         cc_high=100, density=0.5).normalised()
    pattern = random_render(params, rng(), CTX)
    assert not pattern.steps
    assert len(pattern.cc_curve) == params.step_count
    assert all(20 <= v <= 100 for v in pattern.cc_curve)


# --- lock-range merge ----------------------------------------------------------

def test_lock_range_keeps_previous_steps_verbatim():
    params = LayerParams(algorithm="random", density=1.0).normalised()
    before = render_layer(params, rng(1))
    locked = params.__class__(**{
        **{f: getattr(params, f)
           for f in params.__dataclass_fields__},
        "lock_start": 4, "lock_end": 9}).normalised()
    after = render_layer(locked, rng(2), previous=before)
    kept = {s.index: s for s in before.steps if 4 <= s.index <= 9}
    got = {s.index: s for s in after.steps if 4 <= s.index <= 9}
    assert got == kept
    outside_changed = [s for s in after.steps if not 4 <= s.index <= 9]
    assert outside_changed != [s for s in before.steps
                               if not 4 <= s.index <= 9]


# --- mutation ------------------------------------------------------------------

def test_locked_layers_never_mutate():
    params = LayerParams(locked=True, density=0.5).normalised()
    for seed in range(20):
        after, reseed = mutate(params, rng(seed), chaos=1.0)
        assert after == params and not reseed


def test_mutation_changes_something_and_stays_normalised():
    params = LayerParams(algorithm="markov", density=0.5).normalised()
    changed = 0
    for seed in range(30):
        after, reseed = mutate(params, rng(seed), chaos=0.6)
        assert after == after.normalised()
        if after != params or reseed:
            changed += 1
    assert changed > 20


def test_mutation_is_deterministic():
    params = LayerParams(algorithm="euclid").normalised()
    assert mutate(params, rng(9), 0.5) == mutate(params, rng(9), 0.5)


# --- macros --------------------------------------------------------------------

def test_macros_are_a_lens_not_an_edit():
    params = LayerParams(density=0.5, pulses=4).normalised()
    biased = apply_macros(params, density=1.0, complexity=1.0)
    assert biased.density > params.density
    assert apply_macros(params, 0.5, 0.5) == params


# --- seeds + timeline ----------------------------------------------------------

def test_mix_is_stable_and_spread():
    assert mix(1, 2, 3) == mix(1, 2, 3)
    assert mix(1, 2, 3) != mix(3, 2, 1)
    assert len({mix(i) for i in range(1000)}) == 1000


def test_seed_store_slots():
    store = SeedStore()
    assert store.save(2, {"a": 1})
    assert not store.save(99, {"a": 1})
    assert store.get(2) == {"a": 1} and store.get(3) is None
    assert store.occupied()[2] and not store.occupied()[3]
    again = SeedStore(store.to_config())
    assert again.get(2) == {"a": 1}


def test_timeline_walks_both_ways_and_wraps():
    timeline = Timeline()
    for bar in range(40):
        timeline.push(bar, {"bar": bar})
    assert len(timeline) == CAPACITY
    assert timeline.step(-1)["bar"] == 38       # one back from the head
    assert timeline.step(-2)["bar"] == 36
    assert timeline.step(+1)["bar"] == 37
    assert timeline.live()["bar"] == 39
    assert timeline.position == -1
    assert timeline.step(-1000)["bar"] == 8     # clamped at the tail


def test_timeline_coalesces_same_bar():
    timeline = Timeline()
    timeline.push(4, {"v": 1})
    timeline.push(4, {"v": 2})
    assert len(timeline) == 1
    assert timeline.step(-1)["v"] == 2
