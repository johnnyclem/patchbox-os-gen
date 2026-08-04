"""The DSP layer, offline: tables, engines, filters, envelopes, effects.
Deterministic numpy renders, no audio device anywhere.
"""
from __future__ import annotations

import numpy as np

from core.dsp import oscillators, tables
from core.dsp.effects import Chorus, Delay, drive
from core.dsp.filters import OnePole, VoiceFilter, pole_for
from core.envelope import Envelope
from core.lfo import Lfo
from core.patch import Patch

SR = 48000


def phases(freq: float, n: int = 1024) -> np.ndarray:
    return (freq / SR) * np.arange(1, n + 1, dtype=np.float64)


def hf_energy(x: np.ndarray) -> float:
    return float(np.abs(np.diff(x)).mean())


# --- tables --------------------------------------------------------------------

def test_tables_are_normal_and_mips_get_duller():
    for shape in tables.SHAPES:
        for mip in range(tables.MIPS):
            wave = tables._BY_SHAPE[shape][mip]
            assert np.all(np.isfinite(wave))
            assert 0.99 <= np.max(np.abs(wave)) <= 1.0
    bright = tables.table("saw", 55.0)
    dull = tables.table("saw", 8000.0)
    assert hf_energy(bright) > hf_energy(dull)


def test_table_read_interpolates_a_full_cycle():
    wave = tables.SINE
    out = tables.read(wave, np.linspace(0, 1, 2048, endpoint=False))
    assert abs(float(out[0])) < 1e-4
    assert abs(float(out[512]) - 1.0) < 1e-2


# --- engines -------------------------------------------------------------------

def test_every_engine_renders_finite_audio():
    patch = Patch().normalised()
    for engine in oscillators.ENGINES:
        out = oscillators.render(engine, phases(220.0), 220.0, patch)
        assert np.all(np.isfinite(out))
        assert 0.05 < float(np.max(np.abs(out))) <= 1.001, engine


def test_engines_are_deterministic():
    patch = Patch().normalised()
    for engine in oscillators.ENGINES:
        a = oscillators.render(engine, phases(330.0), 330.0, patch)
        b = oscillators.render(engine, phases(330.0), 330.0, patch)
        assert np.array_equal(a, b)


def test_fm_index_and_pd_warp_add_harmonics():
    quiet = oscillators.fm(phases(220.0), 220.0, 2.0, 0.0)
    wild = oscillators.fm(phases(220.0), 220.0, 2.0, 3.0)
    assert hf_energy(wild) > hf_energy(quiet)
    mellow = oscillators.pd(phases(220.0), 220.0, 0.0)
    nasal = oscillators.pd(phases(220.0), 220.0, 1.0)
    assert hf_energy(nasal) > hf_energy(mellow)


def test_wavetable_scan_moves_between_shapes():
    a = oscillators.wavetable(phases(220.0), 220.0, 0.0)
    b = oscillators.wavetable(phases(220.0), 220.0, 1.0)
    mid = oscillators.wavetable(phases(220.0), 220.0, 0.5)
    assert hf_energy(b) > hf_energy(a)
    assert not np.array_equal(mid, a) and not np.array_equal(mid, b)


# --- filters -------------------------------------------------------------------

def test_one_pole_matches_the_recurrence():
    rng = np.random.RandomState(3)
    x = rng.uniform(-1, 1, 300).astype(np.float32)
    for a in (0.2, 0.6, 0.95):
        pole = OnePole()
        got = pole.process(x, a)
        want = np.empty_like(x, dtype=np.float64)
        level = 0.0
        for n in range(len(x)):
            level = (1 - a) * x[n] + a * level
            want[n] = level
        assert np.allclose(got, want, atol=2e-4), a


def test_one_pole_state_carries_across_blocks():
    rng = np.random.RandomState(4)
    x = rng.uniform(-1, 1, 512).astype(np.float32)
    whole = OnePole().process(x, 0.9)
    split = OnePole()
    joined = np.concatenate([split.process(x[:256], 0.9),
                             split.process(x[256:], 0.9)])
    assert np.allclose(whole, joined, atol=1e-5)


def test_voice_filter_darkens_and_res_emphasises():
    rng = np.random.RandomState(5)
    x = rng.uniform(-0.5, 0.5, 1024).astype(np.float32)
    dark = VoiceFilter(SR).process(x, 0.15, 0.0)
    bright = VoiceFilter(SR).process(x, 1.0, 0.0)
    assert hf_energy(bright) > hf_energy(dark) * 2
    flat = VoiceFilter(SR).process(x, 0.5, 0.0)
    peaked = VoiceFilter(SR).process(x, 0.5, 1.0)
    assert float(np.abs(peaked).mean()) > float(np.abs(flat).mean())
    hp = VoiceFilter(SR).process(x, 0.5, 0.0, "hp")
    assert np.all(np.isfinite(hp))
    assert 0.0 < pole_for(0.5, SR) < 1.0


# --- envelope / lfo ------------------------------------------------------------

def test_envelope_walks_its_stages_and_releases_to_silence():
    env = Envelope(SR)
    env.gate_on()
    block = env.render(SR // 2, (0.01, 0.05, 0.6, 0.05))
    assert float(block.max()) > 0.9                  # attack peaked
    assert abs(float(block[-1]) - 0.6) < 0.02        # sat at sustain
    env.gate_off()
    tail = env.render(SR, (0.01, 0.05, 0.6, 0.05))
    assert env.idle()
    assert float(tail[-1]) == 0.0
    assert np.all(np.diff(tail[tail > 0]) <= 1e-6)   # strictly decaying


def test_envelope_release_from_mid_attack_never_clicks():
    env = Envelope(SR)
    env.gate_on()
    env.render(32, (0.5, 0.1, 0.8, 0.1))             # barely into attack
    level = env.level
    env.gate_off()
    tail = env.render(256, (0.5, 0.1, 0.8, 0.1))
    assert float(tail[0]) <= level + 1e-6            # no upward jump


def test_lfo_shapes_and_sh_determinism():
    import random
    for shape in ("sine", "triangle", "square", "sh"):
        lfo = Lfo()
        rng = random.Random(7)
        values = [lfo.step(2.0, shape, 256, SR, rng) for _ in range(50)]
        assert all(-1.0 <= v <= 1.0 for v in values), shape
    a, b = Lfo(), Lfo()
    ra, rb = random.Random(9), random.Random(9)
    va = [a.step(3.0, "sh", 256, SR, ra) for _ in range(20)]
    vb = [b.step(3.0, "sh", 256, SR, rb) for _ in range(20)]
    assert va == vb


# --- effects -------------------------------------------------------------------

def test_effects_are_finite_and_do_their_jobs():
    rng = np.random.RandomState(6)
    x = rng.uniform(-0.8, 0.8, 512).astype(np.float32)
    assert np.array_equal(drive(x, 0.0), x)
    hot = drive(x, 1.0)
    assert np.all(np.isfinite(hot)) and float(np.abs(hot).max()) <= 1.0
    chorus = Chorus(SR)
    wet = chorus.process(x[:256], 0.8)
    assert np.all(np.isfinite(wet))
    assert not np.array_equal(wet, x[:256])
    delay = Delay(SR)
    send = np.zeros(256, dtype=np.float32)
    send[0] = 1.0
    delay.process(send, 0.1)
    heard = 0.0
    for _ in range(1, 24):
        block = delay.process(np.zeros(256, dtype=np.float32), 0.1)
        heard = max(heard, float(np.abs(block).max()))
    assert heard > 0.5                               # the echo came back
