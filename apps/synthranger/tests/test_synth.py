"""The Synth as an instrument: voices, parts, morphing, presets — and the
perf canary that keeps the 48 kHz / 8-voice floor honest in CI.
"""
from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from core.modmatrix import ModSlot
from core.morph import morphed
from core.parts import MAX_PART_VOICES, Part, default_parts
from core.patch import Patch
from core.preset import (factory_dir, list_presets, load_preset,
                         save_preset)
from core.voices import CC_CUTOFF, CC_XY_X, MASTER_CHANNEL, Synth

SR = 48000


def rms(buffer: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(buffer))))


def render(synth: Synth, blocks: int = 20) -> np.ndarray:
    return np.concatenate([synth.render(256) for _ in range(blocks)])


# --- voices --------------------------------------------------------------------

def test_silence_then_a_note_then_silence():
    synth = Synth()
    assert rms(synth.render(256)) == 0.0
    synth.note_on(0, 60, 100)
    assert synth.hanging_voices() == {(0, 60)}
    assert rms(render(synth, 10)) > 0.005
    synth.note_off(0, 60)
    assert not synth.hanging_voices()
    render(synth, 400)                               # release tail dies
    assert synth.sounding() == 0
    assert rms(synth.render(256)) == 0.0


def test_rendering_is_deterministic():
    a, b = Synth(seed=5), Synth(seed=5)
    for synth in (a, b):
        synth.note_on(0, 48, 90)
        synth.note_on(1, 64, 110)
        synth.control(0, CC_XY_X, 96)
    assert np.array_equal(render(a, 30), render(b, 30))


def test_every_engine_sounds_through_a_voice():
    for engine in ("va", "fm", "wavetable", "pd"):
        parts = list(default_parts())
        parts[0] = replace(parts[0], patch=replace(
            parts[0].patch, engine=engine)).normalised()
        synth = Synth(parts)
        synth.note_on(0, 57, 100)
        block = render(synth, 8)
        assert np.all(np.isfinite(block)), engine
        assert rms(block) > 0.003, engine
        synth.all_off()


def test_poly_cap_steals_the_oldest():
    synth = Synth()
    for index, note in enumerate(range(40, 40 + MAX_PART_VOICES + 3)):
        synth.note_on(0, note, 100)
        synth.render(64)
    alive = [v for v in synth._all() if v.part_index == 0]
    assert len(alive) <= MAX_PART_VOICES
    assert (0, 40) not in synth.hanging_voices()     # oldest stolen
    synth.all_off()
    assert not synth.hanging_voices()


def test_parts_are_isolated_and_mutable_under_sound():
    synth = Synth()
    synth.note_on(0, 60, 100)
    synth.note_on(1, 60, 100)
    parts = list(synth.parts)
    parts[1] = replace(parts[1], muted=True).normalised()
    synth.set_parts(parts)
    block = render(synth, 6)
    assert rms(block) > 0.001                        # part 0 still sounds
    synth.all_off()
    assert not synth.hanging_voices()


def test_master_level_cc_and_channel_bounds():
    synth = Synth()
    synth.control(MASTER_CHANNEL, 7, 0)
    synth.note_on(0, 60, 110)
    assert rms(render(synth, 8)) == 0.0
    synth.note_on(9, 60, 110)                        # no such part: no-op
    assert synth.hanging_voices() == {(0, 60)}
    synth.all_off()


def test_cutoff_cc_darkens_a_sounding_voice():
    bright, dark = Synth(), Synth()
    dark.control(0, CC_CUTOFF, 0)                    # −0.5 cutoff offset
    for synth in (bright, dark):
        synth.control(0, CC_XY_X, 0)                 # park the pad
        synth.note_on(0, 45, 110)
    # Compare after the mod envelope has decayed to sustain, where the
    # two cutoffs are no longer both clipped against the top.
    tail_bright = render(bright, 120)[-2560:, 0]
    tail_dark = render(dark, 120)[-2560:, 0]
    hf_bright = np.abs(np.diff(tail_bright)).mean()
    hf_dark = np.abs(np.diff(tail_dark)).mean()
    assert float(hf_bright) > float(hf_dark) * 1.5


# --- morphing / matrix ---------------------------------------------------------

def test_morph_interpolates_numbers_and_snaps_names():
    a = Patch(cutoff=0.2, drive=0.0, engine="va").normalised()
    b = Patch(cutoff=0.8, drive=1.0, engine="pd").normalised()
    mid = morphed(a, b, 0.5)
    assert abs(mid.cutoff - 0.5) < 1e-9
    assert abs(mid.drive - 0.5) < 1e-9
    assert mid.engine == "pd"                        # snaps at midpoint
    assert morphed(a, b, 0.0) == a
    assert morphed(a, b, 1.0) == b
    assert a.cutoff == 0.2                           # lens rule: no writes


def test_mod_matrix_reaches_the_sound():
    parts = list(default_parts())
    parts[0] = replace(parts[0], mods=(
        ModSlot("xy_x", "cutoff", -0.9), ModSlot(), ModSlot(),
        ModSlot())).normalised()
    open_, closed = Synth(parts), Synth(parts)
    closed.control(0, CC_XY_X, 127)                  # full negative sweep
    open_.control(0, CC_XY_X, 0)
    for synth in (open_, closed):
        synth.note_on(0, 45, 110)
    hf_open = np.abs(np.diff(render(open_, 8)[:, 0])).mean()
    hf_closed = np.abs(np.diff(render(closed, 8)[:, 0])).mean()
    assert float(hf_open) > float(hf_closed) * 1.2


# --- presets -------------------------------------------------------------------

def test_factory_bank_loads_and_round_trips(tmp_path):
    presets = list_presets(config=None)
    assert len(presets) >= 8
    assert all(p.parent == factory_dir() for p in presets)
    for path in presets:
        patch = load_preset(path)
        assert patch.name != "INIT"
        saved = save_preset(tmp_path, patch)
        assert load_preset(saved) == patch


def test_part_config_round_trip():
    part = replace(
        default_parts()[2], morph=0.4,
        patch=load_preset(factory_dir() / "acid-line.synpatch"),
        mods=(ModSlot("lfo", "timbre", 0.5),)).normalised()
    again = Part.from_config(part.to_config())
    assert again == part


# --- the canary ----------------------------------------------------------------

def test_perf_canary_eight_voices_render_faster_than_half_realtime():
    """The documented floor: 8 sounding voices, one second of audio, in
    under two seconds of CPU on the CI runner. A regression here is a
    regression on the Pi."""
    synth = Synth()
    for note in (36, 43, 48, 52, 55, 60, 64, 67):
        synth.note_on(0, note, 100)
    blocks = SR // 256
    start = time.monotonic()
    for _ in range(blocks):
        synth.render(256)
    elapsed = time.monotonic() - start
    assert synth.sounding() >= 8
    assert elapsed < 2.0, f"8 voices took {elapsed:.2f}s for 1s of audio"
    synth.all_off()
