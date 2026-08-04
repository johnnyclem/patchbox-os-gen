"""One pad of the kit — what it plays and how it is shaped.

A ``PadDef`` is sound-source description, not sequencer material: the sample
layers (picked by velocity), the choke group, and the continuous voice
parameters the KIT screen edits. Values are normalized where the DSP wants
normals and semitones where a musician wants semitones. Immutable, like all
material in the family; the kit swaps whole pads.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

CHOKE_GROUPS = 4                 # 0 = none, 1..4 chokeable families
MUTE_GROUPS = 4                  # 0 = none, 1..4 perform-mute families
TUNE_RANGE = 12.0                # ± semitones


@dataclass(frozen=True, slots=True)
class PadDef:
    name: str = "PAD"
    note: int = 36               # emitted MIDI note (external dest)
    #: velocity layers: sorted (min_velocity, wav_filename); the sampler
    #: plays the highest layer whose floor the velocity reaches.
    layers: tuple = ()
    choke: int = 0               # 0 = none; same group chokes each other
    group: int = 0               # perform mute group, 0 = none
    tune: float = 0.0            # semitones
    filter: float = 1.0          # 0..1 low-pass cutoff (1 = open)
    amp: float = 1.0             # 0..2 voice gain before the mixer
    pan: float = 0.0             # -1..+1
    delay_send: float = 0.0      # 0..1
    reverb_send: float = 0.0     # 0..1
    duck_key: bool = False       # this pad pumps the bus (see fxbus duck)

    def normalised(self) -> "PadDef":
        layers = tuple(sorted(
            (max(0, min(127, int(floor))), str(name))
            for floor, name in self.layers))
        return replace(
            self, name=str(self.name)[:8].upper() or "PAD",
            note=max(0, min(127, int(self.note))), layers=layers,
            choke=max(0, min(CHOKE_GROUPS, int(self.choke))),
            group=max(0, min(MUTE_GROUPS, int(self.group))),
            tune=max(-TUNE_RANGE, min(TUNE_RANGE, float(self.tune))),
            filter=max(0.0, min(1.0, float(self.filter))),
            amp=max(0.0, min(2.0, float(self.amp))),
            pan=max(-1.0, min(1.0, float(self.pan))),
            delay_send=max(0.0, min(1.0, float(self.delay_send))),
            reverb_send=max(0.0, min(1.0, float(self.reverb_send))),
            duck_key=bool(self.duck_key))

    def layer_for(self, velocity: int) -> str | None:
        """The sample file this velocity plays, or None for an empty pad."""
        chosen = None
        for floor, name in self.layers:
            if velocity >= floor:
                chosen = name
        return chosen

    def to_config(self) -> dict:
        return {"name": self.name, "note": self.note,
                "layers": [list(layer) for layer in self.layers],
                "choke": self.choke, "group": self.group, "tune": self.tune,
                "filter": self.filter, "amp": self.amp, "pan": self.pan,
                "delay_send": self.delay_send,
                "reverb_send": self.reverb_send,
                "duck_key": self.duck_key}

    @classmethod
    def from_config(cls, raw: dict | None) -> "PadDef":
        raw = raw or {}
        return cls(
            name=str(raw.get("name", "PAD")), note=int(raw.get("note", 36)),
            layers=tuple((int(f), str(n))
                         for f, n in raw.get("layers", [])),
            choke=int(raw.get("choke", 0)), group=int(raw.get("group", 0)),
            tune=float(raw.get("tune", 0.0)),
            filter=float(raw.get("filter", 1.0)),
            amp=float(raw.get("amp", 1.0)), pan=float(raw.get("pan", 0.0)),
            delay_send=float(raw.get("delay_send", 0.0)),
            reverb_send=float(raw.get("reverb_send", 0.0)),
            duck_key=bool(raw.get("duck_key", False))).normalised()
