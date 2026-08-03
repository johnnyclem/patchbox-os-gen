"""ChordRanger engine core.

Nothing in this package imports pygame or opens a device at import time, so
the whole music model — theory, chords, voicings, styles, the arranger, the
engine — is importable and testable on a host with no display, no audio and
no MIDI. That property is load-bearing for CI and for the bench scripts, and
it is easy to lose: keep GUI and hardware imports inside functions.
"""

__all__ = ["arranger", "bass", "chords", "chordset", "clock", "commands",
           "config", "cruiser", "engine", "events", "midi_io", "project",
           "song", "style", "theory"]
