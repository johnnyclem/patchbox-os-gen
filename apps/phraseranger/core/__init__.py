"""PhraseRanger engine core.

Nothing in this package imports pygame or opens a device at import time, so
the whole looper model — phrases, tracks, the recorder, history, the slicer,
scenes, the engine — is importable and testable on a host with no display,
no audio and no MIDI. That property is load-bearing for CI and it is easy to
lose: keep GUI and hardware imports inside functions.
"""

__all__ = ["commands", "config", "engine", "history", "phrase", "project",
           "recorder", "scene", "slicer", "track", "version"]
