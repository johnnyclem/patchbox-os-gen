"""SynthRanger's command vocabulary and the snapshot the panel reads."""
from __future__ import annotations

from dataclasses import dataclass, field


# --- playing -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class KeyDown:
    """A touch-keyboard key on the selected part."""

    note: int
    velocity: int = 100


@dataclass(frozen=True, slots=True)
class KeyUp:
    note: int


@dataclass(frozen=True, slots=True)
class SetXY:
    """The XY pad — mod sources xy_x / xy_y on the selected part."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class SelectPart:
    part: int


# --- editing -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SetPatchField:
    """A field on the selected part's A patch (name/engine/…)."""

    part: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetPartField:
    """morph / channel / level / pan / poly / muted on a part."""

    part: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetModSlot:
    part: int
    slot: int
    source: str
    dest: str
    amount: float


@dataclass(frozen=True, slots=True)
class SetPatchState:
    """A whole patch (parsed preset) onto a part's A or B slot."""

    part: int
    params: dict = field(default_factory=dict)
    slot_b: bool = False


@dataclass(frozen=True, slots=True)
class CopyAToB:
    """Freeze the current sound as morph target B."""

    part: int


@dataclass(frozen=True, slots=True)
class RecallProjectState:
    params: dict = field(default_factory=dict)


# --- snapshot views ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ModSlotView:
    source: str
    dest: str
    amount: float


@dataclass(frozen=True, slots=True)
class PartView:
    name: str                    # A patch name
    name_b: str
    engine: str
    morph: float
    channel: int
    level: float
    pan: float
    poly: int
    muted: bool
    sounding: int
    patch: dict                  # effective patch, config-shaped
    mods: tuple


@dataclass(frozen=True, slots=True)
class SySnapshot:
    playing: bool
    recording: bool
    bpm: float
    tick: int
    bar: int
    beat: int
    clock_out: bool
    backend: str
    voices: int
    message: str
    parts: tuple
    parts_rev: int
    selected_part: int
    xy: tuple
    held_notes: tuple
    project_name: str
    pots_map: dict
