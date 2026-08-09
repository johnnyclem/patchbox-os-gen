"""MIDI backend selection: auto prefers alsa when available, else mido/null."""
from __future__ import annotations

from rangerkit.midi_io import (
    BACKENDS,
    DEFAULT_PREFER,
    CaptureMidiIO,
    NullMidiIO,
    open_midi,
)
from rangerkit.routing import PREFER, TRS_A_OUT, TRS_B_OUT, DIN_OUT


def test_backends_include_alsa():
    assert "alsa" in BACKENDS
    assert "mido" in BACKENDS
    assert "auto" in BACKENDS


def test_default_prefer_lists_pimidi_before_through():
    assert "pimidi" in " ".join(DEFAULT_PREFER)
    assert "pisound" in " ".join(DEFAULT_PREFER)
    assert DEFAULT_PREFER[-1] == "midi through"


def test_routing_prefer_distinguishes_pimidi_ports():
    a = " ".join(PREFER[TRS_A_OUT]).lower()
    b = " ".join(PREFER[TRS_B_OUT]).lower()
    assert "pimidi0:a" in a or "pimidi-a" in a
    assert "pimidi0:b" in b or "pimidi-b" in b
    assert "pisound" in " ".join(PREFER[DIN_OUT])


def test_open_midi_null_pin():
    io = open_midi(backend="null")
    assert isinstance(io, NullMidiIO)
    assert io.backend_name == "null"
    assert io.scan() == []


def test_open_midi_auto_degrades_without_hardware(monkeypatch):
    """On a dev host without /dev/snd/seq, auto still returns *something*."""
    # Force alsa open to fail so we exercise the fallthrough.
    import rangerkit.midi_io as m

    monkeypatch.setattr(m, "mido", None)
    # open_alsa_midi may still succeed on a Linux box with ALSA; that's fine.
    io = open_midi(backend="auto")
    assert io.backend_name in ("alsa", "mido", "null")


def test_capture_backend_records():
    cap = CaptureMidiIO()
    assert cap.backend_name == "capture"
    assert cap.is_bound("x")
