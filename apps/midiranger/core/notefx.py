"""Note FX — velocity curves, humanize, constrained random, delay/echo.

One processor, applied to every thru note (arps carry their own feel). The
result of ``process`` is plain data — ``(offset_ticks, note, velocity)``
triples, the played note first — so the engine owns every note-on and the
FX never touch MIDI.

Humanize only ever *delays* (0 … timing ticks): the engine cannot send into
the past, and a humanizer that pushed early would need a lookahead buffer
this box does not want between a key and its <5 ms thru path.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import PPQN

CURVES = ("linear", "soft", "hard", "fixed")
MAX_REPEATS = 4
MAX_TIMING = PPQN // 8          # 12 ticks ≈ a 32nd at 96 PPQN


@dataclass(frozen=True, slots=True)
class FxParams:
    # velocity curve
    curve: str = "linear"
    curve_amount: float = 0.5   # softness/hardness; fixed value when "fixed"
    # humanize
    humanize_timing: int = 0    # max delay, ticks
    humanize_velocity: int = 0  # ± velocity
    # constrained randomizer
    drop_probability: float = 0.0
    # delay / echo
    echo_repeats: int = 0
    echo_ticks: int = PPQN // 2
    echo_decay: float = 0.6     # velocity multiplier per repeat

    def normalised(self) -> "FxParams":
        return replace(
            self,
            curve=self.curve if self.curve in CURVES else "linear",
            curve_amount=max(0.0, min(1.0, float(self.curve_amount))),
            humanize_timing=max(0, min(MAX_TIMING,
                                       int(self.humanize_timing))),
            humanize_velocity=max(0, min(64, int(self.humanize_velocity))),
            drop_probability=max(0.0, min(0.9, float(self.drop_probability))),
            echo_repeats=max(0, min(MAX_REPEATS, int(self.echo_repeats))),
            echo_ticks=max(1, min(PPQN * 4, int(self.echo_ticks))),
            echo_decay=max(0.1, min(1.0, float(self.echo_decay))))


def shape_velocity(velocity: int, params: FxParams) -> int:
    """The velocity curve. "soft" compresses toward loud (a light touch still
    speaks), "hard" expands (playing dynamics exaggerated), "fixed" is an
    organ."""
    v = max(1, min(127, velocity)) / 127.0
    amount = params.curve_amount
    if params.curve == "soft":
        shaped = v ** (1.0 - 0.6 * amount)
    elif params.curve == "hard":
        shaped = v ** (1.0 + 1.5 * amount)
    elif params.curve == "fixed":
        shaped = amount if amount > 0 else 0.7
    else:
        shaped = v
    return max(1, min(127, round(shaped * 127)))


def process(note: int, velocity: int, params: FxParams,
            rng) -> list[tuple[int, int, int]]:
    """One input note → ``[(offset, note, velocity), ...]``.

    Empty when the randomizer drops the note. The first entry is the played
    note (possibly delayed by humanize); echoes follow at their offsets.
    """
    if params.drop_probability and rng.random() < params.drop_probability:
        return []
    velocity = shape_velocity(velocity, params)
    if params.humanize_velocity:
        velocity += rng.randint(-params.humanize_velocity,
                                params.humanize_velocity)
        velocity = max(1, min(127, velocity))
    offset = rng.randint(0, params.humanize_timing) \
        if params.humanize_timing else 0
    out = [(offset, note, velocity)]
    level = float(velocity)
    for repeat in range(1, params.echo_repeats + 1):
        level *= params.echo_decay
        echoed = round(level)
        if echoed < 1:
            break
        out.append((offset + repeat * params.echo_ticks, note, echoed))
    return out
