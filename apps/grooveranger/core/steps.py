"""Steps and patterns — the sequencer's material, immutable.

A ``Step`` is everything one cell of the grid knows: whether it fires, how
hard, how likely, how many ratchet sub-hits, under what condition, how far
off the grid it leans (micro-timing), and its parameter locks. A ``Pattern``
is twelve rows of sixteen of them plus a length. Every edit returns a new
``Pattern`` — the engine can hand the current one to the schedule builder or
the project file without wondering who else is holding it.

Conditions follow the trackers: ``a:b`` fires on pass ``a`` of every ``b``
pattern passes (1-based), ``fill``/``not_fill`` gate on the fill flag, and
``always`` is what it says. Probability is on top of (not instead of) the
condition, drawn from the project's seeded rng at fire time.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

PADS = 12
STEPS = 16                       # grid columns; ``length`` may use fewer
RATCHET_MAX = 4
MICRO_RANGE = 11                 # ± ticks a step may lean (< one 16th of 24)
CONDITIONS = ("always", "1:2", "2:2", "1:4", "2:4", "3:4", "4:4",
              "fill", "not_fill")
#: The parameters a step may lock. ``vel`` is a native field; these three
#: travel to the internal sampler as CCs (see ``engine._PLOCK_CCS``).
PLOCK_NAMES = ("tune", "filter", "pan")


def cond_passes(cond: str, loop: int, fill: bool) -> bool:
    if cond == "always" or cond not in CONDITIONS:
        return True
    if cond == "fill":
        return fill
    if cond == "not_fill":
        return not fill
    a, _, b = cond.partition(":")
    return loop % int(b) == int(a) - 1


@dataclass(frozen=True, slots=True)
class Step:
    on: bool = False
    vel: int = 100
    prob: float = 1.0
    ratchet: int = 1
    cond: str = "always"
    micro: int = 0
    #: sorted tuple of (name, value) pairs — hashable, JSON-able.
    plocks: tuple = ()

    def normalised(self) -> "Step":
        locks = tuple(sorted((str(k), float(v)) for k, v in self.plocks
                             if str(k) in PLOCK_NAMES))
        return replace(
            self, vel=max(1, min(127, int(self.vel))),
            prob=max(0.0, min(1.0, float(self.prob))),
            ratchet=max(1, min(RATCHET_MAX, int(self.ratchet))),
            cond=self.cond if self.cond in CONDITIONS else "always",
            micro=max(-MICRO_RANGE, min(MICRO_RANGE, int(self.micro))),
            plocks=locks)

    def lock(self, name: str, value: float | None) -> "Step":
        """A new step with one lock set (or cleared when value is None)."""
        kept = tuple((k, v) for k, v in self.plocks if k != name)
        if value is not None and name in PLOCK_NAMES:
            kept = kept + ((name, float(value)),)
        return replace(self, plocks=tuple(sorted(kept))).normalised()

    def locked(self, name: str):
        for key, value in self.plocks:
            if key == name:
                return value
        return None

    def passes(self, loop: int, fill: bool) -> bool:
        """Does the condition let pass number ``loop`` (0-based) through?"""
        return cond_passes(self.cond, loop, fill)

    def to_config(self) -> dict:
        return {"on": self.on, "vel": self.vel, "prob": self.prob,
                "ratchet": self.ratchet, "cond": self.cond,
                "micro": self.micro, "plocks": [list(p) for p in self.plocks]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Step":
        raw = raw or {}
        return cls(
            on=bool(raw.get("on", False)), vel=int(raw.get("vel", 100)),
            prob=float(raw.get("prob", 1.0)),
            ratchet=int(raw.get("ratchet", 1)),
            cond=str(raw.get("cond", "always")),
            micro=int(raw.get("micro", 0)),
            plocks=tuple((str(k), float(v))
                         for k, v in raw.get("plocks", []))).normalised()


def _empty_rows() -> tuple:
    return tuple(tuple(Step() for _ in range(STEPS)) for _ in range(PADS))


@dataclass(frozen=True, slots=True)
class Pattern:
    """Twelve rows of sixteen steps and a playable length in steps."""

    rows: tuple = field(default_factory=_empty_rows)
    length: int = STEPS

    def normalised(self) -> "Pattern":
        return replace(self, length=max(1, min(STEPS, int(self.length))))

    def step(self, pad: int, index: int) -> Step:
        return self.rows[pad][index]

    def with_step(self, pad: int, index: int, step: Step) -> "Pattern":
        row = list(self.rows[pad])
        row[index] = step.normalised()
        rows = list(self.rows)
        rows[pad] = tuple(row)
        return replace(self, rows=tuple(rows))

    def toggle(self, pad: int, index: int) -> "Pattern":
        step = self.rows[pad][index]
        return self.with_step(pad, index, replace(step, on=not step.on))

    def clear_row(self, pad: int) -> "Pattern":
        rows = list(self.rows)
        rows[pad] = tuple(Step() for _ in range(STEPS))
        return replace(self, rows=tuple(rows))

    def euclid_row(self, pad: int, pulses: int, rotate: int = 0,
                   vel: int = 100) -> "Pattern":
        """Distribute ``pulses`` hits over the playable length, evenly the
        way rangerkit.euclid does, leaving steps beyond the length alone."""
        from rangerkit.euclid import euclidean
        mask = euclidean(self.length, pulses, rotate)
        row = list(self.rows[pad])
        for index in range(self.length):
            row[index] = replace(row[index], on=mask[index],
                                 vel=vel).normalised()
        rows = list(self.rows)
        rows[pad] = tuple(row)
        return replace(self, rows=tuple(rows))

    def used(self) -> int:
        return sum(1 for row in self.rows
                   for step in row[:self.length] if step.on)

    def to_config(self) -> dict:
        return {"length": self.length,
                "rows": [[step.to_config() for step in row]
                         for row in self.rows]}

    @classmethod
    def from_config(cls, raw: dict | None) -> "Pattern":
        raw = raw or {}
        rows = raw.get("rows") or []
        built = []
        for pad in range(PADS):
            row = rows[pad] if pad < len(rows) else []
            built.append(tuple(
                Step.from_config(row[i] if i < len(row) else None)
                for i in range(STEPS)))
        return cls(rows=tuple(built),
                   length=int(raw.get("length", STEPS))).normalised()
