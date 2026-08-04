"""The sampler and the FX bus, offline: deterministic numpy renders, no
audio device anywhere. The hanging-voices ledger mirrors midi.hanging()."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from core.fxbus import DELAY_DIVISIONS, FxBus
from core.kit import load_kit
from core.sampler import (CC_FILTER, CC_LEVEL, CC_PAN, CC_TUNE,
                          MASTER_CHANNEL, MAX_VOICES, Sampler, load_wav)

KIT_DIR = Path(__file__).resolve().parent.parent / "data" / "kits" / "rk909"
SR = 48000


def make_sampler() -> Sampler:
    return Sampler(load_kit(KIT_DIR))


def render_all(sampler: Sampler, blocks: int = 20) -> np.ndarray:
    return np.concatenate([sampler.render(256) for _ in range(blocks)])


def rms(buffer: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(buffer))))


# --- samples -------------------------------------------------------------------

def test_kit_loads_and_wavs_decode():
    kit = load_kit(KIT_DIR)
    assert kit.name == "rk909" and kit.dest == "internal"
    assert all(pad.layers for pad in kit.pads)
    data = load_wav(KIT_DIR / "kick.wav")
    assert data.dtype == np.float32 and len(data) > SR // 10
    assert float(np.max(np.abs(data))) <= 1.0


def test_resampling_keeps_duration(tmp_path):
    import wave
    tone = (np.sin(np.arange(4410) / 4410 * 2 * np.pi * 100)
            * 32000).astype("<i2")
    with wave.open(str(tmp_path / "t.wav"), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(tone.tobytes())
    data = load_wav(tmp_path / "t.wav")
    assert abs(len(data) - 4800) <= 2                # 0.1 s at 48 k


# --- voices --------------------------------------------------------------------

def test_silence_then_a_kick_then_silence():
    sampler = make_sampler()
    assert rms(sampler.render(256)) == 0.0
    sampler.note_on(0, 36, 110)
    assert sampler.hanging_voices() == {(0, 36)}
    loud = rms(render_all(sampler, 10))
    assert loud > 0.01
    sampler.note_off(0, 36)
    assert not sampler.hanging_voices()
    render_all(sampler, 200)                         # play out fully
    assert rms(sampler.render(256)) == 0.0


def test_note_off_does_not_cut_a_one_shot():
    a, b = make_sampler(), make_sampler()
    a.note_on(0, 36, 110)
    b.note_on(0, 36, 110)
    a.render(256)
    b.render(256)
    b.note_off(0, 36)                                # off right after the hit
    tail_a = rms(render_all(a, 8))
    tail_b = rms(render_all(b, 8))
    assert tail_b > 0.005 and abs(tail_a - tail_b) < 1e-6


def test_rendering_is_deterministic():
    a, b = make_sampler(), make_sampler()
    for sampler in (a, b):
        sampler.control(4, CC_TUNE, 96)
        sampler.note_on(0, 36, 110)
        sampler.note_on(4, 42, 90)
    assert np.array_equal(render_all(a, 30), render_all(b, 30))


def test_velocity_layers_pick_different_samples():
    soft, hard = make_sampler(), make_sampler()
    soft.note_on(1, 38, 60)
    hard.note_on(1, 38, 127)
    a = render_all(soft, 5)
    b = render_all(hard, 5)
    # Different files, not just different gains: no scalar relates them.
    ratio = rms(b) / max(rms(a), 1e-9)
    assert not np.allclose(a * ratio, b, atol=1e-4)


def test_choke_group_cuts_the_open_hat():
    ringing, choked = make_sampler(), make_sampler()
    for sampler in (ringing, choked):
        sampler.note_on(5, 46, 120)                  # OHAT, choke group 1
        sampler.render(256)
        sampler.note_off(5, 46)
    choked.note_on(4, 42, 100)                       # CHAT chokes it
    later_ringing = render_all(ringing, 40)[-2560:]
    later_choked = render_all(choked, 40)[-2560:]
    assert rms(later_ringing) > rms(later_choked) * 3
    choked.note_off(4, 42)
    assert not choked.hanging_voices() and not ringing.hanging_voices()


def test_plock_ccs_are_consumed_by_the_next_hit_only():
    locked, plain = make_sampler(), make_sampler()
    locked.control(0, CC_TUNE, 127)                  # +12 semis, one hit
    locked.note_on(0, 36, 110)
    plain.note_on(0, 36, 110)
    assert not np.array_equal(render_all(locked, 10),
                              render_all(plain, 10))
    locked.note_off(0, 36)
    plain.note_off(0, 36)
    render_all(locked, 200)
    render_all(plain, 200)
    locked.note_on(0, 36, 110)                       # lock is spent
    plain.note_on(0, 36, 110)
    assert np.array_equal(render_all(locked, 10), render_all(plain, 10))
    for sampler in (locked, plain):
        sampler.all_off()
    assert not locked.hanging_voices()


def test_pan_and_filter_locks_shape_the_voice():
    panned = make_sampler()
    panned.control(0, CC_PAN, 127)                   # hard right
    panned.note_on(0, 36, 110)
    block = render_all(panned, 10)
    assert rms(block[:, 1]) > rms(block[:, 0]) * 5
    dark = make_sampler()
    dark.control(4, CC_FILTER, 8)
    dark.note_on(4, 42, 110)
    bright = make_sampler()
    bright.note_on(4, 42, 110)
    dark_hf = np.abs(np.diff(render_all(dark, 5)[:, 0]))
    bright_hf = np.abs(np.diff(render_all(bright, 5)[:, 0]))
    assert float(bright_hf.mean()) > float(dark_hf.mean()) * 2


def test_mixer_level_cc_scales_a_pad():
    quiet = make_sampler()
    quiet.control(0, CC_LEVEL, 25)                   # 0.25 × unity
    loud = make_sampler()
    for sampler in (quiet, loud):
        sampler.note_on(0, 36, 110)
    assert rms(render_all(loud, 8)) > rms(render_all(quiet, 8)) * 3


def test_master_bus_ccs_reach_the_fx():
    sampler = make_sampler()
    sampler.control(MASTER_CHANNEL, CC_LEVEL, 0)     # master mute
    sampler.note_on(0, 36, 110)
    assert rms(render_all(sampler, 8)) == 0.0
    sampler.control(MASTER_CHANNEL, CC_FILTER, 0)    # full LP still finite
    sampler.control(MASTER_CHANNEL, CC_LEVEL, 100)
    assert np.all(np.isfinite(render_all(sampler, 8)))


def test_voice_stealing_keeps_the_cap():
    sampler = make_sampler()
    for round_ in range(6):
        for pad in range(12):
            sampler.note_on(pad, sampler.kit.pads[pad].note, 100)
            sampler.render(64)
    alive = len(sampler._voices) + len(sampler._finished)
    assert alive <= MAX_VOICES
    sampler.all_off()
    assert not sampler.hanging_voices()
    assert np.all(np.isfinite(sampler.render(256)))


def test_sample_less_pad_is_midi_only():
    sampler = Sampler()                              # fallback kit, no files
    sampler.note_on(0, 36, 100)
    assert not sampler.hanging_voices()              # no voice, nothing owed
    assert rms(sampler.render(256)) == 0.0


# --- the bus -------------------------------------------------------------------

def test_fxbus_neutral_is_passthrough_and_delay_echoes():
    fx = FxBus(SR)
    fx.set_reverb(0.0)
    dry = np.zeros((256, 2), dtype=np.float32)
    dry[10, 0] = dry[10, 1] = 0.5
    out = fx.process(dry, np.zeros(256, dtype=np.float32),
                     np.zeros(256, dtype=np.float32))
    assert np.array_equal(out, dry)                  # bit-exact at neutral
    fx.set_tempo(120.0)
    fx.set_delay_division(0)                         # half a beat = 0.25 s
    send = np.zeros(256, dtype=np.float32)
    send[0] = 1.0
    fx.process(np.zeros((256, 2), dtype=np.float32), send,
               np.zeros(256, dtype=np.float32))
    echo_at = int(DELAY_DIVISIONS[0] * 0.5 * SR)     # samples until echo
    heard = []
    for block in range(1, echo_at // 256 + 2):
        out = fx.process(np.zeros((256, 2), dtype=np.float32),
                         np.zeros(256, dtype=np.float32),
                         np.zeros(256, dtype=np.float32))
        if float(np.max(np.abs(out))) > 0.0:
            heard.append(block * 256)
    assert heard and abs(heard[0] - echo_at) <= 512


def test_fxbus_filter_ends_stay_finite_and_shape():
    fx = FxBus(SR)
    fx.set_reverb(0.0)
    rng = np.random.RandomState(7)
    noise = rng.uniform(-0.5, 0.5, (256, 2)).astype(np.float32)
    silence = np.zeros(256, dtype=np.float32)
    fx.set_filter(0.0)                               # darkest LP
    low = fx.process(noise.copy(), silence, silence)
    fx.set_filter(1.0)                               # thinnest HP
    high = fx.process(noise.copy(), silence, silence)
    assert np.all(np.isfinite(low)) and np.all(np.isfinite(high))
    assert float(np.abs(np.diff(low[:, 0])).mean()) \
        < float(np.abs(np.diff(high[:, 0])).mean())


def test_reverb_damping_darkens_the_tail_and_zero_is_bit_exact():
    from core.fxbus import FxBus

    def tail(damp: float) -> np.ndarray:
        fx = FxBus(SR)
        fx.set_reverb(1.0)
        fx.set_damp(damp)
        silence = np.zeros(256, dtype=np.float32)
        send = np.zeros(256, dtype=np.float32)
        send[0] = 1.0
        fx.process(np.zeros((256, 2), dtype=np.float32), silence, send)
        blocks = [fx.process(np.zeros((256, 2), dtype=np.float32),
                             silence, silence) for _ in range(40)]
        return np.concatenate(blocks)[-4096:, 0]

    bright, dark = tail(0.0), tail(1.0)
    assert np.all(np.isfinite(dark))
    hf = lambda x: float(np.abs(np.diff(x)).mean())  # noqa: E731
    assert hf(bright) > hf(dark) * 1.5
    assert np.array_equal(tail(0.0), bright)         # damp 0 = identical


def test_damp_cc_reaches_the_bus():
    sampler = make_sampler()
    assert sampler.fx.damp == 0.0
    sampler.control(MASTER_CHANNEL, 92, 127)
    assert sampler.fx.damp == 1.0
