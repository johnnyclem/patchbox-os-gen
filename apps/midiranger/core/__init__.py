"""MidiRanger engine core.

Nothing in this package imports pygame or opens a device at import time, so
the whole processing model — matrix, arps, quantizer, harmonizer, note FX,
CC LFOs, scenes, the engine — is importable and testable on a host with no
display, no audio and no MIDI. That property is load-bearing for CI and it
is easy to lose: keep GUI and hardware imports inside functions.
"""

__all__ = ["arp", "cclfo", "commands", "config", "engine", "harmonizer",
           "notefx", "project", "quantizer", "scene", "version"]
