"""Internal audio drones — the suite Phase 4 hook.

P0 ships the *role* only: a layer with role "drone" renders long overlapping
notes to its MIDI destination like any other layer (``note_length =
"drone"`` holds a note for a full cycle). When ``rangerkit.audio`` lands
(RANGER-SUITE-PLAN Phase 4), this module grows a small additive/organ patch
that doubles the drone layer on the DAC — nothing else in the app will need
to change, which is the point of writing the hook down now.
"""
from __future__ import annotations

AUDIO_AVAILABLE = False         # flipped by the Phase 4 wiring
