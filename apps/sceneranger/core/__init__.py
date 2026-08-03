"""SceneRanger engine core.

Nothing in this package imports pygame or opens a device at import time, so
the whole session model — clips, the grid, the launcher, follow actions,
the recorder, scene chains, the engine — is importable and testable on a
host with no display, no audio and no MIDI. That property is load-bearing
for CI and it is easy to lose: keep GUI and hardware imports inside
functions.
"""

__all__ = ["arrange", "clip", "commands", "config", "engine", "grid",
           "launcher", "project", "recorder", "version"]
