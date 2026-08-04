"""The step sequencer — a schedule, not a walker.

An immutable ``Pattern`` plus a swing amount compiles to a *schedule*: a
dict from pattern-local tick to the hits due there, ratchets unrolled and
micro-timing already leaned. The engine's tick loop then only looks itself
up — no per-tick arithmetic over 192 steps, and the compile happens on
edits, never on the audio path's clock.

What stays runtime state here: which pattern is playing, which is queued
(switches land at pass end, like every groovebox since the 909), the fill
flag (queued for one full pass), pass counting for ``a:b`` conditions,
swing, and the perform mutes/solos. Probability is *not* resolved here —
the engine draws from the project's seeded rng at fire time so two engines
from one project stay tick-identical.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import TICKS_PER_BAR

from core.steps import PADS, Pattern, STEPS

PATTERNS = 8
STEP_TICKS = TICKS_PER_BAR // STEPS      # 24: one 16th at 96 PPQN
SWING_MIN, SWING_MAX = 0.5, 0.75


@dataclass(frozen=True, slots=True)
class Hit:
    """One scheduled trigger: which pad, from which step, which sub-hit."""

    pad: int
    step: int
    ratchet_index: int
    ratchet_of: int
    vel: int
    prob: float
    cond: str
    plocks: tuple


def swing_ticks(swing: float) -> int:
    """How far the off-16ths lean, in ticks (0 at 50%, 12 at 75%)."""
    swing = max(SWING_MIN, min(SWING_MAX, float(swing)))
    return round((swing - 0.5) * 2 * STEP_TICKS)


def build_schedule(pattern: Pattern, swing: float) -> dict:
    """tick -> tuple of Hits, over one pass of ``pattern``."""
    length_ticks = pattern.length * STEP_TICKS
    lean = swing_ticks(swing)
    schedule: dict[int, list] = {}
    for pad in range(PADS):
        row = pattern.rows[pad]
        for index in range(pattern.length):
            step = row[index]
            if not step.on:
                continue
            base = index * STEP_TICKS + step.micro
            if index % 2 == 1:
                base += lean
            gap = STEP_TICKS // step.ratchet
            for sub in range(step.ratchet):
                tick = (base + sub * gap) % length_ticks
                schedule.setdefault(tick, []).append(Hit(
                    pad=pad, step=index, ratchet_index=sub,
                    ratchet_of=step.ratchet, vel=step.vel, prob=step.prob,
                    cond=step.cond, plocks=step.plocks))
    return {tick: tuple(hits) for tick, hits in schedule.items()}


class Sequencer:
    """Patterns, the playing/queued pair, fills, mutes — and the compiled
    schedule for whatever is current."""

    def __init__(self) -> None:
        self.patterns: list[Pattern] = [Pattern() for _ in range(PATTERNS)]
        self.current = 0
        self.queued: int | None = None
        self.swing = 0.5
        self.fill = False            # active for the pass now playing
        self.fill_queued = False
        self.loop = 0                # 0-based pass count for a:b conditions
        self.mutes: set[int] = set()
        self.solos: set[int] = set()
        self._schedule: dict = {}
        self._compiled_for: tuple | None = None

    # --- material ------------------------------------------------------------
    def pattern(self) -> Pattern:
        return self.patterns[self.current]

    def put(self, index: int, pattern: Pattern) -> None:
        self.patterns[index] = pattern.normalised()
        self._compiled_for = None

    def edit(self, pattern: Pattern) -> None:
        self.put(self.current, pattern)

    def set_swing(self, swing: float) -> None:
        self.swing = max(SWING_MIN, min(SWING_MAX, float(swing)))
        self._compiled_for = None

    # --- transport-facing ----------------------------------------------------
    def pattern_ticks(self) -> int:
        return self.pattern().length * STEP_TICKS

    def schedule(self) -> dict:
        key = (self.current, round(self.swing, 4))
        if self._compiled_for != key:
            self._schedule = build_schedule(self.pattern(), self.swing)
            self._compiled_for = key
        return self._schedule

    def hits_at(self, local_tick: int) -> tuple:
        return self.schedule().get(local_tick, ())

    def queue_pattern(self, index: int) -> None:
        if 0 <= index < PATTERNS:
            self.queued = None if index == self.current else index

    def switch_now(self, index: int) -> None:
        """Immediate switch — the stopped-transport spelling."""
        if 0 <= index < PATTERNS:
            self.current = index
            self.queued = None
            self.loop = 0
            self._compiled_for = None

    def queue_fill(self) -> None:
        self.fill_queued = True

    def on_pass_end(self) -> None:
        """The bar line of this machine: patterns switch, fills land and
        expire, the pass counter walks."""
        self.loop += 1
        if self.queued is not None:
            self.current = self.queued
            self.queued = None
            self.loop = 0
            self._compiled_for = None
        self.fill = self.fill_queued
        self.fill_queued = False

    def reset(self) -> None:
        self.loop = 0
        self.fill = self.fill_queued = False
        self.queued = None

    # --- perform mutes -------------------------------------------------------
    def audible(self, pad: int) -> bool:
        if self.solos:
            return pad in self.solos
        return pad not in self.mutes

    # --- recording -----------------------------------------------------------
    def record_hit(self, local_tick: int, pad: int, vel: int) -> None:
        """Quantize a live hit to the nearest step of the current pattern
        and write it in (velocity included) — classic drum-machine record."""
        pattern = self.pattern()
        index = round(local_tick / STEP_TICKS) % pattern.length
        step = pattern.step(pad, index)
        self.edit(pattern.with_step(
            pad, index, replace(step, on=True, vel=vel)))

    # --- state ---------------------------------------------------------------
    def to_config(self) -> dict:
        return {"patterns": [p.to_config() for p in self.patterns],
                "current": self.current, "swing": self.swing,
                "mutes": sorted(self.mutes), "solos": sorted(self.solos)}

    def from_config(self, raw: dict | None) -> None:
        raw = raw or {}
        patterns = raw.get("patterns") or []
        self.patterns = [
            Pattern.from_config(patterns[i] if i < len(patterns) else None)
            for i in range(PATTERNS)]
        self.current = max(0, min(PATTERNS - 1, int(raw.get("current", 0))))
        self.swing = max(SWING_MIN, min(SWING_MAX,
                                        float(raw.get("swing", 0.5))))
        self.mutes = {int(p) for p in raw.get("mutes", [])
                      if 0 <= int(p) < PADS}
        self.solos = {int(p) for p in raw.get("solos", [])
                      if 0 <= int(p) < PADS}
        self.queued = None
        self.reset()
        self._compiled_for = None
