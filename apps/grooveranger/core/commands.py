"""GrooveRanger's command vocabulary and the snapshot the panel reads.

Commands are immutable dataclasses posted from any thread; the snapshot is
what the engine publishes each tick. Both follow the family conventions in
rangerkit's CONVENTIONS.md: the GUI owns no musical state, and everything a
screen draws is in the snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# --- pattern / step editing ----------------------------------------------------

@dataclass(frozen=True, slots=True)
class ToggleStep:
    pad: int
    step: int


@dataclass(frozen=True, slots=True)
class SetStepField:
    """vel / prob / ratchet / cond / micro on one step."""

    pad: int
    step: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetStepLock:
    """A parameter lock (tune / filter / pan); value None clears it."""

    pad: int
    step: int
    name: str
    value: float | None


@dataclass(frozen=True, slots=True)
class ClearRow:
    pad: int


@dataclass(frozen=True, slots=True)
class ApplyEuclid:
    pad: int
    pulses: int
    rotate: int = 0


@dataclass(frozen=True, slots=True)
class SetPatternLength:
    steps: int


@dataclass(frozen=True, slots=True)
class SelectPattern:
    """Queued at pass end while playing; immediate when stopped."""

    index: int


@dataclass(frozen=True, slots=True)
class CopyPattern:
    src: int
    dst: int


@dataclass(frozen=True, slots=True)
class SetSwing:
    value: float


@dataclass(frozen=True, slots=True)
class QueueFill:
    pass


# --- performing ----------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PadHit:
    """A finger on a pad: sound it now; write it in when recording."""

    pad: int
    vel: int = 110


@dataclass(frozen=True, slots=True)
class SelectPad:
    pad: int


@dataclass(frozen=True, slots=True)
class ToggleMute:
    pad: int


@dataclass(frozen=True, slots=True)
class ToggleSolo:
    pad: int


@dataclass(frozen=True, slots=True)
class MuteGroup:
    """Toggle every pad in a kit mute group at once."""

    group: int


# --- kit / mixer ---------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SetPadField:
    pad: int
    name: str
    value: object


@dataclass(frozen=True, slots=True)
class SetKitField:
    """dest / channel / name on the kit itself."""

    name: str
    value: object


@dataclass(frozen=True, slots=True)
class LoadKitState:
    """A whole kit, as its config dict (the App loads kit.json files)."""

    params: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SetMixerLevel:
    pad: int
    value: float


@dataclass(frozen=True, slots=True)
class SetMasterField:
    """master / filter / delay_div / reverb on the bus."""

    name: str
    value: float


# --- song ----------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChainAppend:
    pattern: int
    passes: int = 4


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
    params: dict = field(default_factory=dict)


# --- snapshot views ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class StepView:
    on: bool
    vel: int
    prob: float
    ratchet: int
    cond: str
    micro: int
    locks: tuple


@dataclass(frozen=True, slots=True)
class PadView:
    name: str
    note: int
    muted: bool
    soloed: bool
    choke: int
    group: int
    level: float
    tune: float
    filter: float
    amp: float
    pan: float
    delay_send: float
    reverb_send: float
    has_samples: bool
    sounding: int


@dataclass(frozen=True, slots=True)
class MixerView:
    master: float
    filter: float
    delay_div: int
    reverb: float
    damp: float


@dataclass(frozen=True, slots=True)
class GrSnapshot:
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
    #: 12 rows × 16 StepViews of the *current* pattern
    pattern: tuple
    pattern_index: int
    queued: int
    patterns_used: tuple
    length: int
    swing: float
    fill: bool
    fill_queued: bool
    loop: int
    step_pos: int
    selected_pad: int
    pads: tuple
    kit_name: str
    kit_rev: int
    dest: str
    channel: int
    dest_bound: bool
    mixer: MixerView
    chain: tuple
    chain_on: bool
    chain_position: int
    project_name: str
    pots_map: dict
