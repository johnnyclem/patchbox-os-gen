"""MidiRanger's command vocabulary and snapshot.

Transport, tempo, binding and pot commands come from
``rangerkit.enginebase``; everything here is this instrument's own. Field
updates go through per-module ``Set*Field`` commands with the field name as
data — the alternative is a dataclass per parameter, and this box has dozens.
The engine validates field names against the params dataclass, so a typo'd
field costs a log line, not a crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rangerkit.enginebase import BaseSnapshot
from rangerkit.routing import Route

from core.arp import ArpView


# --- routing -------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ToggleRoute:
    route: Route


@dataclass(frozen=True, slots=True)
class ClearRoutes:
    pass


@dataclass(frozen=True, slots=True)
class SetBypass:
    """True: the whole processing rack steps aside; the matrix still routes."""

    on: bool


# --- processors ----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SetArpField:
    index: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class ClearArp:
    index: int


@dataclass(frozen=True, slots=True)
class SetQuantizerField:
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetHarmonizerField:
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetFxField:
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetLfoField:
    index: int
    name: str
    value: object


# --- scenes --------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SaveScene:
    slot: int


@dataclass(frozen=True, slots=True)
class RecallScene:
    slot: int


@dataclass(frozen=True, slots=True)
class Morph:
    """Blend the live state from scene ``slot_a`` toward ``slot_b``."""

    slot_a: int
    slot_b: int
    t: float


# --- snapshot ------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class LfoView:
    enabled: bool = False
    shape: str = "sine"
    period: int = 384
    depth: float = 1.0
    center: int = 64
    cc: int = 1
    channel: int = 0
    dest: str = "din_out"
    value: int = 64


@dataclass(frozen=True, slots=True)
class MrSnapshot(BaseSnapshot):
    bypass: bool = False
    routes: tuple = ()                      # tuple[Route, ...], sorted
    arps: tuple[ArpView, ...] = ()
    quantizer_enabled: bool = False
    quantizer_root: int = 0
    quantizer_scale: str = "major"
    harmonizer_mode: str = "off"
    fx_curve: str = "linear"
    fx_curve_amount: float = 0.5
    fx_humanize_timing: int = 0
    fx_humanize_velocity: int = 0
    fx_drop_probability: float = 0.0
    fx_echo_repeats: int = 0
    fx_echo_ticks: int = 48
    fx_echo_decay: float = 0.6
    lfos: tuple[LfoView, ...] = ()
    scenes_occupied: tuple[bool, ...] = (False,) * 8
    morph: tuple = ()                       # (slot_a, slot_b, t) or ()
    activity_in: tuple = ()                 # ((endpoint, count), ...)
    activity_out: tuple = ()
    inputs_bound: tuple = ()                # ((endpoint, bool), ...)
    outputs_bound: tuple = ()
    project_name: str = "untitled"
    pots_map: dict = field(default_factory=dict)
