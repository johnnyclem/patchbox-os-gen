"""One phrase track: the loop, its routing, and its feel.

Eight of these make the instrument. Params are the deployment-stable
choices (where it plays, how it feels); the phrase is the material; history
(``core.history``) remembers old material. The engine owns playback.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import PPQN
from rangerkit.routing import OUTPUTS

from core.phrase import MAX_BARS, Phrase

TRACK_COUNT = 8


@dataclass(frozen=True, slots=True)
class TrackParams:
    dest: str = "din_out"
    channel: int = 0
    muted: bool = False
    # Playback feel — applied at emit time, never written into the phrase,
    # so they are reversible the way a macro is.
    probability: float = 1.0    # chance a note fires this pass
    humanize_timing: int = 0    # max delay, ticks (0..12)
    humanize_velocity: int = 0  # ± velocity
    # Loop length: locked tracks follow the global bar count; free tracks
    # keep their own (that is the polyrhythm feature).
    length_locked: bool = True
    bars: int = 1
    # Overdub feedback: 1.0 = layers pile up forever; below it, each pass
    # while recording multiplies the old material (tape generations).
    feedback: float = 1.0

    def normalised(self) -> "TrackParams":
        return replace(
            self,
            dest=self.dest if self.dest in OUTPUTS else "din_out",
            channel=max(0, min(15, int(self.channel))),
            probability=max(0.0, min(1.0, float(self.probability))),
            humanize_timing=max(0, min(PPQN // 8,
                                       int(self.humanize_timing))),
            humanize_velocity=max(0, min(32, int(self.humanize_velocity))),
            bars=max(1, min(MAX_BARS, int(self.bars))),
            feedback=max(0.3, min(1.0, float(self.feedback))))


@dataclass(frozen=True, slots=True)
class TrackView:
    """What the panel shows for one track."""

    dest: str = "din_out"
    channel: int = 0
    muted: bool = False
    armed: bool = False
    probability: float = 1.0
    humanize_timing: int = 0
    humanize_velocity: int = 0
    length_locked: bool = True
    bars: int = 1
    feedback: float = 1.0
    notes: int = 0
    position: float = 0.0       # 0..1 through the loop, for the progress bar
    undo_depth: int = 0
    hits: tuple = ()            # note onsets as 0..1 fractions, for the strip
    sounding: int = 0


def track_to_config(params: TrackParams, phrase: Phrase) -> dict:
    return {"params": {f: getattr(params, f)
                       for f in params.__dataclass_fields__},
            "phrase": phrase.to_config()}


def track_from_config(raw: dict | None) -> tuple[TrackParams, Phrase]:
    raw = raw or {}
    fields = TrackParams.__dataclass_fields__
    params = TrackParams(**{k: v for k, v in (raw.get("params") or {}).items()
                            if k in fields}).normalised()
    return params, Phrase.from_config(raw.get("phrase"))
