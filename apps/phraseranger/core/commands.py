"""PhraseRanger's command vocabulary and snapshot.

Transport, tempo and pot commands come from ``rangerkit.enginebase``;
everything here is this instrument's own. Per-track field updates follow
the family's ``Set*Field`` shape — validated against the params dataclass,
so a typo'd field costs a log line, not a crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rangerkit.enginebase import BaseSnapshot

from core.track import TrackView


@dataclass(frozen=True, slots=True)
class ArmTrack:
    """Arm one track for record/overdub; index -1 disarms."""

    index: int


@dataclass(frozen=True, slots=True)
class SetQuantize:
    on: bool


@dataclass(frozen=True, slots=True)
class UndoTrack:
    """index -1 = the armed track, else the last-touched one."""

    index: int = -1


@dataclass(frozen=True, slots=True)
class ClearTrack:
    index: int


@dataclass(frozen=True, slots=True)
class ReverseTrack:
    index: int


@dataclass(frozen=True, slots=True)
class StretchTrack:
    index: int
    factor: float               # 0.5 = half-time, 2.0 = double-time


@dataclass(frozen=True, slots=True)
class ToggleTrackMute:
    index: int


@dataclass(frozen=True, slots=True)
class SetTrackField:
    index: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetTrackBars:
    index: int
    bars: int


@dataclass(frozen=True, slots=True)
class SetGlobalBars:
    bars: int


@dataclass(frozen=True, slots=True)
class SelectSliceSource:
    """Which track the SLICE screen chops."""

    index: int


@dataclass(frozen=True, slots=True)
class SetSliceMode:
    mode: str                   # "slice" | "chromatic"


@dataclass(frozen=True, slots=True)
class FireSlice:
    pad: int
    layer: float = 1.0          # velocity layer, 0 soft … 1 full


@dataclass(frozen=True, slots=True)
class SaveScene:
    slot: int


@dataclass(frozen=True, slots=True)
class RecallScene:
    slot: int


@dataclass(frozen=True, slots=True)
class RecallProjectState:
    """Apply a whole project-shaped state tree (new/load project)."""

    params: dict


@dataclass(frozen=True, slots=True)
class PrSnapshot(BaseSnapshot):
    tracks: tuple[TrackView, ...] = ()
    armed: int = -1
    quantize: bool = True
    global_bars: int = 1
    slice_source: int = 0
    slice_mode: str = "slice"
    slice_captions: tuple[str, ...] = ()
    slice_filled: tuple[bool, ...] = ()
    scenes_occupied: tuple[bool, ...] = (False,) * 8
    open_notes: tuple = ()      # keys currently held into the recorder
    outputs_bound: tuple = ()
    activity_out: tuple = ()
    project_name: str = "untitled"
    pots_map: dict = field(default_factory=dict)
