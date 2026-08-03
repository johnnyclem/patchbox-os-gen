"""Internal audio drones — wired (RANGER-SUITE-PLAN Phase 4).

There is no drone engine here, and that is the design: a drone layer is an
ordinary layer whose destination is ``internal``. ``main.build_rig`` wraps
the MIDI backend in ``rangerkit.audio.bridge.SynthMidiBridge`` with a small
organ-patch synth on the DAC, so ``dest = "internal"`` (one tap on the
LAYERS screen) is all it takes — the engine renders, books and releases
those notes exactly like DIN notes, and CI exercises the same path with the
synth behind a CaptureMidiIO.
"""
from __future__ import annotations

AUDIO_AVAILABLE = True          # the internal endpoint answers
