"""Shared test rig pieces, importable by every app's suite.

Not a pytest plugin — just values and helpers, so a test file reads the same
whether it lives in rangerkit or in an app. The conventions these encode:

* engines are driven tick-by-tick through ``step()`` with a ``FakeClock``,
  the same code path playback uses, never a simulation;
* MIDI is captured, and **every engine test ends with**
  ``assert not midi.hanging()``;
* panel tests run at all three shipped geometries, and every drawn control
  must be a registered hit target.
"""
from __future__ import annotations

from rangerkit.clock import FakeClock
from rangerkit.midi_io import CaptureMidiIO
from rangerkit.pots import FakePots

__all__ = ["CaptureMidiIO", "FakeClock", "FakePots", "GEOMETRIES", "drain",
           "run_ticks"]

#: The three panel geometries every app must lay out for: the 1280×400 HDMI
#: bar (Profile A), the 800×480 HyperPixel (Profile B), and 480×800 portrait.
GEOMETRIES = ((1280, 400), (800, 480), (480, 800))


def run_ticks(engine, ticks: int) -> None:
    """Drive an engine the way the transport does, one step per tick."""
    for _ in range(ticks):
        engine.step()


def drain(engine) -> None:
    """Apply everything queued without advancing time — what a stopped
    engine's next tick would do first."""
    engine.step()
