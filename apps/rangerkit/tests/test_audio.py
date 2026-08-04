"""The audio kit, offline: the synth invariant, the bridge, null degradation.

No device anywhere in this file — ``render_blocks`` is the callback, run by
hand, which is exactly what CI has. Every synth test ends with
``assert not synth.hanging_voices()``.
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("numpy")

from rangerkit.audio import BLOCK_FRAMES, SAMPLE_RATE
from rangerkit.audio.bridge import SynthMidiBridge
from rangerkit.audio.engine import NullAudioOut, open_audio
from rangerkit.audio.render import peak, render_blocks, rms
from rangerkit.audio.synth import MAX_VOICES, SimpleSynth
from rangerkit.events import EventKind, MidiEvent, note_off, note_on
from rangerkit.midi_io import CaptureMidiIO
from rangerkit.routing import INTERNAL

RELEASE_BLOCKS = 40                 # comfortably past the 120 ms release


def silence_after_release(synth) -> None:
    synth.all_off()
    tail = render_blocks(synth, RELEASE_BLOCKS)
    assert peak(tail[-BLOCK_FRAMES:]) == 0.0
    assert not synth.hanging_voices()


# --- the synth -----------------------------------------------------------------

def test_silence_when_nothing_plays():
    synth = SimpleSynth()
    buffer = render_blocks(synth, 4)
    assert buffer.shape == (4 * BLOCK_FRAMES, 2)
    assert peak(buffer) == 0.0
    assert not synth.hanging_voices()


def test_a_note_sounds_and_note_off_ends_it():
    synth = SimpleSynth("sine")
    synth.note_on(0, 60, 100)
    body = render_blocks(synth, 8)
    assert rms(body) > 0.01
    assert synth.hanging_voices() == {(0, 60)}
    synth.note_off(0, 60)
    assert not synth.hanging_voices()   # releasing is not hanging
    tail = render_blocks(synth, RELEASE_BLOCKS)
    assert peak(tail[-BLOCK_FRAMES:]) == 0.0
    assert synth.sounding() == 0        # the voice was reaped


def test_rendering_is_deterministic():
    def run():
        synth = SimpleSynth("organ")
        synth.note_on(0, 57, 96)
        first = render_blocks(synth, 4)
        synth.note_on(0, 64, 80)
        second = render_blocks(synth, 4)
        synth.all_off()
        return np.concatenate([first, second, render_blocks(synth, 8)])

    a, b = run(), run()
    assert np.array_equal(a, b)


def test_attack_ramps_no_click():
    synth = SimpleSynth("sine")
    synth.note_on(0, 60, 127)
    first = synth.render(BLOCK_FRAMES)
    assert abs(first[0][0]) < 0.01      # starts from silence, not a step
    silence_after_release(synth)


def test_voice_stealing_keeps_the_cap():
    synth = SimpleSynth()
    for index in range(MAX_VOICES + 6):
        synth.note_on(0, 40 + index, 100)
        synth.render(BLOCK_FRAMES)
    assert synth.sounding() <= MAX_VOICES
    silence_after_release(synth)


def test_every_patch_renders_finite_audio():
    for patch in ("sine", "organ", "soft"):
        synth = SimpleSynth(patch)
        for note in (36, 60, 96):
            synth.note_on(0, note, 110)
        buffer = render_blocks(synth, 8)
        assert peak(buffer) <= 1.0      # clipped into range, never NaN
        silence_after_release(synth)


def test_retrigger_replaces_the_voice():
    synth = SimpleSynth()
    synth.note_on(0, 60, 100)
    synth.render(BLOCK_FRAMES)
    synth.note_on(0, 60, 60)            # same key: one voice, not two
    assert synth.sounding() == 1
    silence_after_release(synth)


# --- the bridge ----------------------------------------------------------------

def bridged():
    synth = SimpleSynth("sine")
    capture = CaptureMidiIO()
    return SynthMidiBridge(capture, synth), capture, synth


def test_internal_events_drive_the_synth_only():
    bridge, capture, synth = bridged()
    bridge.send(INTERNAL, note_on(0, 60, 100))
    bridge.send("din_out", note_on(0, 62, 100))
    assert synth.hanging_voices() == {(0, 60)}
    assert [e.data1 for _ep, e in capture.events] == [62]
    bridge.send(INTERNAL, note_off(0, 60))
    bridge.send("din_out", note_off(0, 62))
    assert not synth.hanging_voices()
    assert not capture.hanging()


def test_cc123_reaches_the_synth_as_all_off():
    bridge, _capture, synth = bridged()
    bridge.send(INTERNAL, note_on(3, 60, 100))
    bridge.send(INTERNAL, note_on(3, 64, 100))
    bridge.send(INTERNAL, MidiEvent(EventKind.CC, 0, 3, 123, 0))
    assert not synth.hanging_voices()


def test_internal_is_always_bound_and_capture_helpers_pass_through():
    bridge, capture, _synth = bridged()
    assert bridge.is_bound(INTERNAL)
    assert bridge.bind_output(INTERNAL, "anything")
    assert "+synth" in bridge.backend_name
    bridge.send("usb_out", note_on(0, 60, 90))
    assert bridge.hanging() == {(0, 60)}    # CaptureMidiIO's method, bridged
    bridge.send("usb_out", note_off(0, 60))
    assert not capture.hanging()


def test_realtime_to_internal_is_swallowed():
    bridge, capture, _synth = bridged()
    bridge.send_realtime(INTERNAL, 0xF8)
    bridge.send_realtime("din_out", 0xF8)
    assert capture.realtime == [("din_out", 0xF8, 0)]


# --- the device layer ----------------------------------------------------------

def test_open_audio_degrades_to_null_without_a_stack():
    synth = SimpleSynth()
    out = open_audio(synth, config=None)
    assert isinstance(out, NullAudioOut)
    assert out.backend_name == "null"
    assert out.start() is False
    out.stop()                          # a no-op, not a crash


def test_null_backend_is_forced_by_config():
    class Audio:
        backend = "null"

    class Config:
        audio = Audio()

    out = open_audio(SimpleSynth(), config=Config())
    assert isinstance(out, NullAudioOut)


def test_render_blocks_rejects_non_finite():
    class Broken:
        def render(self, frames):
            return np.full((frames, 2), np.nan, dtype=np.float32)

    with pytest.raises(ValueError):
        render_blocks(Broken(), 1)


def test_sample_rate_contract():
    assert SAMPLE_RATE == 48000 and BLOCK_FRAMES == 256


def test_cc_reaches_an_instrument_that_speaks_control():
    class Ears:
        def __init__(self):
            self.heard = []

        def note_on(self, *a):
            pass

        def note_off(self, *a):
            pass

        def all_off(self, channel=None):
            self.heard.append(("all_off", channel))

        def control(self, channel, number, value):
            self.heard.append((channel, number, value))

    ears = Ears()
    bridge = SynthMidiBridge(CaptureMidiIO(), ears)
    bridge.send(INTERNAL, MidiEvent(EventKind.CC, 0, 3, 74, 90))
    bridge.send(INTERNAL, MidiEvent(EventKind.CC, 0, 3, 123, 0))
    assert ears.heard == [(3, 74, 90), ("all_off", 3)]
    # The simple synth has no ``control`` — the same CC is a quiet no-op.
    synth = SimpleSynth()
    SynthMidiBridge(CaptureMidiIO(), synth).send(
        INTERNAL, MidiEvent(EventKind.CC, 0, 3, 74, 90))


def test_shared_one_pole_matches_the_recurrence_and_carries_state():
    from rangerkit.audio.dsp import OnePole
    rng = np.random.RandomState(11)
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
    whole = OnePole().process(x, 0.9)
    split = OnePole()
    joined = np.concatenate([split.process(x[:128], 0.9),
                             split.process(x[128:], 0.9)])
    assert np.allclose(whole, joined, atol=1e-5)
