"""GenRanger's command vocabulary and snapshot.

Transport, tempo and pot commands come from ``rangerkit.enginebase``;
everything here is this instrument's own. Per-layer field updates follow
MidiRanger's ``Set*Field`` shape — validated against the params dataclass,
so a typo'd field costs a log line, not a crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rangerkit.enginebase import BaseSnapshot

from core.layers import LayerView


@dataclass(frozen=True, slots=True)
class SetLayerField:
    index: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetGridCell:
    """MAP lattice edit: one probability cell of a grid layer."""

    index: int
    step: int
    row: int
    value: float


@dataclass(frozen=True, slots=True)
class SetCaSeedCell:
    """MAP CA edit: toggle one bit of the seed row."""

    index: int
    cell: int


@dataclass(frozen=True, slots=True)
class SetLockRange:
    index: int
    start: int
    end: int                    # end < start clears the range


@dataclass(frozen=True, slots=True)
class ToggleLayerMute:
    index: int


@dataclass(frozen=True, slots=True)
class ToggleLayerLock:
    index: int


@dataclass(frozen=True, slots=True)
class LockAll:
    """Toggle: everything locked <-> everything free."""


@dataclass(frozen=True, slots=True)
class MutateNow:
    index: int = -1             # -1 = one unlocked layer, engine's pick


@dataclass(frozen=True, slots=True)
class Reseed:
    index: int = -1             # -1 = every unlocked layer


@dataclass(frozen=True, slots=True)
class SetCruise:
    on: bool


@dataclass(frozen=True, slots=True)
class SetCruiseField:
    name: str                   # "speed" | "chaos"
    value: float


@dataclass(frozen=True, slots=True)
class SetMacro:
    name: str                   # "density" | "complexity"
    value: float


@dataclass(frozen=True, slots=True)
class SetKey:
    root: int
    scale: str = ""


@dataclass(frozen=True, slots=True)
class CaptureSeed:
    slot: int


@dataclass(frozen=True, slots=True)
class RecallSeed:
    slot: int


@dataclass(frozen=True, slots=True)
class TimelineStep:
    delta: int


@dataclass(frozen=True, slots=True)
class TimelineLive:
    pass


@dataclass(frozen=True, slots=True)
class RecallProjectState:
    """Apply a whole project-shaped state tree (new/load project)."""

    params: dict


@dataclass(frozen=True, slots=True)
class GvSnapshot(BaseSnapshot):
    root: int = 0
    scale: str = "minor"
    cruise_on: bool = True
    cruise_speed: float = 0.5
    chaos: float = 0.35
    macro_density: float = 0.5
    macro_complexity: float = 0.5
    all_locked: bool = False
    layers: tuple[LayerView, ...] = ()
    timeline_len: int = 0
    timeline_pos: int = -1      # -1 = live
    timeline_bars: tuple = ()
    seeds_occupied: tuple[bool, ...] = (False,) * 8
    outputs_bound: tuple = ()
    activity_out: tuple = ()
    project_name: str = "untitled"
    pots_map: dict = field(default_factory=dict)
