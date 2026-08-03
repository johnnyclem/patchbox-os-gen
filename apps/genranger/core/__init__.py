"""GenRanger engine core.

Nothing in this package imports pygame or opens a device at import time, so
the whole generative model — layers, the five generators, mutation, cruise,
seeds, the timeline, the engine — is importable and testable on a host with
no display, no audio and no MIDI. That property is load-bearing for CI and
it is easy to lose: keep GUI and hardware imports inside functions.
"""

__all__ = ["cellular", "commands", "config", "cruise", "drones", "engine",
           "euclidgen", "layers", "macros", "markov", "mutate", "probgrid",
           "project", "randomgen", "seeds", "timeline", "version"]
