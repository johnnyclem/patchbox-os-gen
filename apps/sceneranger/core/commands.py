"""SceneRanger's command vocabulary and snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field

from rangerkit.enginebase import BaseSnapshot


@dataclass(frozen=True, slots=True)
class LaunchClip:
    track: int
    scene: int


@dataclass(frozen=True, slots=True)
class LaunchScene:
    scene: int


@dataclass(frozen=True, slots=True)
class StopTrack:
    track: int


@dataclass(frozen=True, slots=True)
class StopAll:
    pass


@dataclass(frozen=True, slots=True)
class SetLaunchQuantize:
    mode: str                   # "off" | "beat" | "bar"


@dataclass(frozen=True, slots=True)
class SetIntensity:
    value: float                # global scene intensity, 0..1 → velocity


@dataclass(frozen=True, slots=True)
class ArmSlot:
    track: int
    scene: int


@dataclass(frozen=True, slots=True)
class Disarm:
    pass


@dataclass(frozen=True, slots=True)
class ClearClip:
    track: int
    scene: int


@dataclass(frozen=True, slots=True)
class SetClipField:
    track: int
    scene: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetTrackField:
    track: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class ChainAppend:
    scene: int
    bars: int = 4


@dataclass(frozen=True, slots=True)
class ChainRemove:
    position: int


@dataclass(frozen=True, slots=True)
class ChainClear:
    pass


@dataclass(frozen=True, slots=True)
class SetChainOn:
    on: bool


@dataclass(frozen=True, slots=True)
class RecallProjectState:
    """Apply a whole project-shaped state tree (new/load project)."""

    params: dict


@dataclass(frozen=True, slots=True)
class SlotView:
    filled: bool = False
    playing: bool = False
    queued: bool = False
    armed: bool = False
    bars: int = 1
    follow: str = "none"
    follow_loops: int = 1
    follow_probability: float = 1.0
    velocity_scale: float = 1.0
    transpose: int = 0
    notes: int = 0


@dataclass(frozen=True, slots=True)
class TrackStripView:
    dest: str = "din_out"
    channel: int = 0
    muted: bool = False
    active: int = -1            # playing slot
    position: float = 0.0       # 0..1 through the active clip
    sounding: int = 0


@dataclass(frozen=True, slots=True)
class ScSnapshot(BaseSnapshot):
    slots: tuple = ()           # tuple[tuple[SlotView, ...], ...] [track][scene]
    tracks: tuple[TrackStripView, ...] = ()
    scenes_filled: tuple[bool, ...] = (False,) * 8
    quantize: str = "bar"
    intensity: float = 1.0
    armed: tuple = ()           # (track, scene) or ()
    open_notes: tuple = ()
    chain: tuple = ()           # ((scene, bars), ...)
    chain_on: bool = False
    chain_position: int = -1
    outputs_bound: tuple = ()
    activity_out: tuple = ()
    project_name: str = "untitled"
    pots_map: dict = field(default_factory=dict)
