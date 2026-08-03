"""The rack processors as pure functions: quantizer, harmonizer, FX, LFOs."""
from __future__ import annotations

import random

from core.cclfo import CcLfo, LfoParams, RESOLUTION
from core.harmonizer import HarmonizerParams, harmonize
from core.notefx import FxParams, process, shape_velocity
from core.quantizer import QuantizerParams, quantize
from rangerkit.events import PPQN, TICKS_PER_BAR
from rangerkit.theory import scale_for


def rng():
    return random.Random(0xC0FFEE)


# --- quantizer -----------------------------------------------------------------

def test_quantizer_off_is_identity():
    params = QuantizerParams(enabled=False)
    assert all(quantize(n, params) == n for n in range(0, 128, 7))


def test_quantizer_snaps_into_key_and_register():
    params = QuantizerParams(enabled=True, root=0, scale="major")
    scale = scale_for("major")
    for note in range(36, 96):
        snapped = quantize(note, params)
        assert scale.contains(snapped, 0)
        assert abs(snapped - note) <= 1


def test_quantizer_normalise_rejects_unknown_scale():
    params = QuantizerParams(enabled=True, root=14,
                             scale="klingon").normalised()
    assert params.root == 2 and params.scale == "major"


# --- harmonizer ----------------------------------------------------------------

def test_harmonizer_off_adds_nothing():
    assert harmonize(60, 100, HarmonizerParams(mode="off")) == ()


def test_harmonizer_octave_and_power():
    octave = harmonize(60, 100, HarmonizerParams(mode="octave"))
    assert [n for n, _v in octave] == [72]
    power = harmonize(60, 100, HarmonizerParams(mode="power"))
    assert [n for n, _v in power] == [67]


def test_harmonizer_third_is_diatonic():
    params = HarmonizerParams(mode="third", root=0, scale="major")
    # C -> E (major third), D -> F (minor third), E -> G (minor third):
    # the pedal follows the key, not a fixed interval.
    assert harmonize(60, 100, params)[0][0] == 64
    assert harmonize(62, 100, params)[0][0] == 65
    assert harmonize(64, 100, params)[0][0] == 67


def test_harmonizer_triad_stays_in_scale():
    params = HarmonizerParams(mode="triad", root=0, scale="major")
    scale = scale_for("major")
    for note in range(48, 84):
        for added, _velocity in harmonize(note, 100, params):
            assert scale.contains(added, 0)


def test_harmonizer_added_voices_sit_under_the_played_note():
    added = harmonize(60, 100, HarmonizerParams(mode="triad"))
    assert all(v == 80 for _n, v in added)


# --- note FX -------------------------------------------------------------------

def test_velocity_curves():
    soft = FxParams(curve="soft", curve_amount=1.0)
    hard = FxParams(curve="hard", curve_amount=1.0)
    fixed = FxParams(curve="fixed", curve_amount=0.5)
    assert shape_velocity(40, soft) > 40
    assert shape_velocity(40, hard) < 40
    assert shape_velocity(127, soft) == 127
    assert shape_velocity(40, fixed) == shape_velocity(120, fixed) == 64


def test_process_plain_is_one_note_now():
    assert process(60, 100, FxParams(), rng()) == [(0, 60, 100)]


def test_echo_decays_and_spaces():
    params = FxParams(echo_repeats=3, echo_ticks=PPQN, echo_decay=0.5)
    out = process(60, 100, params, rng())
    assert [(o, n) for o, n, _v in out] == \
        [(0, 60), (PPQN, 60), (PPQN * 2, 60), (PPQN * 3, 60)]
    velocities = [v for _o, _n, v in out]
    assert velocities == [100, 50, 25, 12]   # round-half-even


def test_echo_stops_below_audibility():
    params = FxParams(echo_repeats=4, echo_ticks=12, echo_decay=0.1)
    out = process(60, 4, params, rng())
    assert len(out) < 5                     # tail dropped, not sent at v=0


def test_humanize_delays_never_rush():
    params = FxParams(humanize_timing=8, humanize_velocity=10)
    r = rng()
    for _ in range(50):
        out = process(60, 100, params, r)
        offset, _note, velocity = out[0]
        assert 0 <= offset <= 8
        assert 1 <= velocity <= 127


def test_drop_probability_drops_deterministically():
    params = FxParams(drop_probability=0.5)
    r = rng()
    kept = sum(bool(process(60, 100, params, r)) for _ in range(200))
    assert 60 < kept < 140                  # seeded, so this never flakes


# --- CC LFOs -------------------------------------------------------------------

def test_lfo_disabled_emits_nothing():
    lfo = CcLfo(LfoParams(enabled=False))
    assert all(lfo.on_tick(t) is None for t in range(0, TICKS_PER_BAR))


def test_lfo_sine_sweeps_the_range_and_dedups():
    lfo = CcLfo(LfoParams(enabled=True, shape="sine", period=TICKS_PER_BAR,
                          depth=1.0, center=64))
    values = [lfo.on_tick(t) for t in range(0, TICKS_PER_BAR)]
    emitted = [v for v in values if v is not None]
    assert max(emitted) >= 120 and min(emitted) <= 7
    # Off the resolution grid nothing is emitted.
    assert all(values[t] is None for t in range(TICKS_PER_BAR)
               if t % RESOLUTION)


def test_lfo_square_snaps_between_two_levels():
    lfo = CcLfo(LfoParams(enabled=True, shape="square", period=PPQN * 2,
                          depth=1.0, center=64))
    emitted = {lfo.on_tick(t) for t in range(0, PPQN * 4, RESOLUTION)}
    assert emitted - {None} == {0, 127}     # None = deduped repeats


def test_lfo_random_is_deterministic_per_seed():
    a = CcLfo(LfoParams(enabled=True, shape="random"), seed=7)
    b = CcLfo(LfoParams(enabled=True, shape="random"), seed=7)
    c = CcLfo(LfoParams(enabled=True, shape="random"), seed=8)
    ticks = range(0, TICKS_PER_BAR * 2, RESOLUTION)
    series_a = [a.value_at(t) for t in ticks]
    series_b = [b.value_at(t) for t in ticks]
    series_c = [c.value_at(t) for t in ticks]
    assert series_a == series_b
    assert series_a != series_c


def test_lfo_depth_zero_is_flat_center():
    lfo = CcLfo(LfoParams(enabled=True, depth=0.0, center=100))
    values = {lfo.value_at(t) for t in range(0, TICKS_PER_BAR, RESOLUTION)}
    assert values == {100}
