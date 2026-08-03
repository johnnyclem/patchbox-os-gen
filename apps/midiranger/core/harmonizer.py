"""Harmonizer — adds intervals above what the player holds.

Theory-aware: "third" and "triad" walk *scale degrees*, not fixed semitones,
so the added voices stay diatonic the way a real harmony pedal's smart mode
does. A note outside the scale is first treated as its nearest scale tone
for the purpose of finding the degree — the harmony must never be more wrong
than the note it decorates.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.theory import scale_for, snap_to_scale

MODES = ("off", "octave", "power", "third", "triad")


@dataclass(frozen=True, slots=True)
class HarmonizerParams:
    mode: str = "off"
    root: int = 0                   # pitch class of the key
    scale: str = "major"
    velocity_scale: float = 0.8     # added voices sit under the played note

    def normalised(self) -> "HarmonizerParams":
        return replace(self, mode=self.mode if self.mode in MODES else "off",
                       root=int(self.root) % 12,
                       velocity_scale=max(0.1, min(1.0,
                                                   self.velocity_scale)))


def _degree_step(note: int, params: HarmonizerParams, steps: int) -> int:
    """The scale tone ``steps`` degrees above ``note``, in MIDI space."""
    scale = scale_for(params.scale)
    snapped = snap_to_scale(note, params.root, scale)
    offsets = sorted(scale.degrees)
    octave, rest = divmod(snapped - params.root, 12)
    index = offsets.index(rest) if rest in offsets else 0
    index += steps
    octave += index // len(offsets)
    return params.root + octave * 12 + offsets[index % len(offsets)]


def harmonize(note: int, velocity: int,
              params: HarmonizerParams) -> tuple[tuple[int, int], ...]:
    """Added voices for one input note: ``((note, velocity), ...)``.

    The played note itself is not in the result — the caller already owns it.
    """
    if params.mode == "off":
        return ()
    added_velocity = max(1, min(127, round(velocity *
                                           params.velocity_scale)))
    if params.mode == "octave":
        notes = (note + 12,)
    elif params.mode == "power":
        notes = (note + 7,)
    elif params.mode == "third":
        notes = (_degree_step(note, params, 2),)
    else:                           # triad
        notes = (_degree_step(note, params, 2),
                 _degree_step(note, params, 4))
    return tuple((n, added_velocity) for n in notes
                 if 0 <= n <= 127 and n != note)
