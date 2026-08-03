"""rangerkit — the shared engine kit for the Ranger appliance apps.

Everything the Ranger family shares by *design* rather than by accident lives
here: music theory and chords, the tick clock, the MIDI I/O stack, the
multi-port routing model, the RT engine skeleton (commands in, immutable
snapshots out, a release book so nothing is ever left sounding), the PiSound
button bridge, the pots abstraction, the shared config.toml sections, and the
panel geometry/theme/widget layer.

Two rules, both load-bearing:

* Nothing outside ``rangerkit.gui`` (and, later, ``rangerkit.audio.engine``)
  may import pygame or open a device at import time. CI enforces this with a
  poisoned-import check.
* Every engine owns every note it has sent. The release book in
  ``rangerkit.enginebase`` is the single mechanism; every engine test ends
  with ``assert not midi.hanging()``.

Deployment note: each app ships its *own* copy of this package under
``/opt/<app>/rangerkit`` (vendored by the install stage), so one app can be
updated or rolled back without moving the ground under its siblings. In the
repo there is exactly one copy: ``apps/rangerkit``.
"""

__all__ = ["button", "chords", "clock", "configbase", "enginebase", "euclid",
           "events", "midi_io", "pots", "routing", "theory", "version"]
