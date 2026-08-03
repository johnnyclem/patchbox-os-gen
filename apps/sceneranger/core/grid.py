"""The session grid — 12 tracks × 8 scenes of clip slots.

12 × 8 is what keeps every cell at or above the 44 px touch floor on the
1280×400 bar (the PRD's 16×12 ceiling would put cells under a fingertip);
the portrait panel pages the tracks in halves. A slot is a ``Clip`` or
nothing; tracks own routing (dest + channel + mute), scenes are the rows.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.routing import OUTPUTS

from core.clip import Clip

TRACKS = 12
SCENES = 8


@dataclass(frozen=True, slots=True)
class TrackParams:
    dest: str = "din_out"
    channel: int = 0
    muted: bool = False

    def normalised(self) -> "TrackParams":
        return replace(
            self,
            dest=self.dest if self.dest in OUTPUTS else "din_out",
            channel=max(0, min(15, int(self.channel))))


class Grid:
    """Slots + track params. Mutable holder, engine-thread only; the clips
    inside are immutable values."""

    def __init__(self) -> None:
        self.slots: dict[tuple[int, int], Clip] = {}
        self.tracks: list[TrackParams] = [
            TrackParams(channel=min(15, i)).normalised()
            for i in range(TRACKS)]

    def clip(self, track: int, scene: int) -> Clip | None:
        return self.slots.get((track, scene))

    def put(self, track: int, scene: int, clip: Clip | None) -> None:
        if not (0 <= track < TRACKS and 0 <= scene < SCENES):
            return
        if clip is None or clip.empty:
            self.slots.pop((track, scene), None)
        else:
            self.slots[(track, scene)] = clip

    def scene_slots(self, scene: int) -> list[tuple[int, Clip]]:
        return [(track, clip) for (track, s), clip in sorted(
            self.slots.items()) if s == scene]

    def filled_scenes(self) -> tuple[bool, ...]:
        return tuple(any((t, s) in self.slots for t in range(TRACKS))
                     for s in range(SCENES))

    def to_config(self) -> dict:
        return {
            "tracks": [{f: getattr(p, f)
                        for f in p.__dataclass_fields__}
                       for p in self.tracks],
            "slots": {f"{track}:{scene}": clip.to_config()
                      for (track, scene), clip in sorted(self.slots.items())},
        }

    @classmethod
    def from_config(cls, raw: dict | None) -> "Grid":
        grid = cls()
        raw = raw or {}
        fields = TrackParams.__dataclass_fields__
        for index, params in enumerate(raw.get("tracks") or ()):
            if index < TRACKS:
                grid.tracks[index] = TrackParams(
                    **{k: v for k, v in (params or {}).items()
                       if k in fields}).normalised()
        for key, clip in (raw.get("slots") or {}).items():
            track, _, scene = str(key).partition(":")
            if track.isdigit() and scene.isdigit():
                grid.put(int(track), int(scene), Clip.from_config(clip))
        return grid
