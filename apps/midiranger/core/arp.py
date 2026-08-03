"""One advanced arpeggiator. The engine runs four of them.

Each arp has an input filter (endpoint + channel) and an output (endpoint +
channel). Notes matching the filter are *consumed* — held by the arp instead
of passing thru — and the arp emits its pattern on the tick grid while the
transport runs.

Everything an emission needs is returned as plain data
``(offset_ticks, note, velocity, length_ticks)`` so the engine owns every
note-on and its off-tick booking; the arp never touches MIDI. Randomness
(pattern "random", probability) comes from the caller's seeded ``Random`` —
same seed, same performance, which is what makes the tests exact.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from rangerkit.events import PPQN

PATTERNS = ("up", "down", "updown", "order", "random")
# Rates the panel offers, in ticks: 1/4 … 1/32 at PPQN 96.
RATES = (PPQN, PPQN // 2, PPQN // 3, PPQN // 4, PPQN // 6, PPQN // 8)
MAX_RATCHET = 4
MAX_OCTAVES = 4
ANY_SOURCE = ""                 # match input from any endpoint
OMNI = -1                       # match any channel / keep incoming channel


@dataclass(frozen=True, slots=True)
class ArpParams:
    enabled: bool = False
    source: str = ANY_SOURCE    # input endpoint filter ("" = any)
    channel_in: int = OMNI      # input channel filter (-1 = omni)
    dest: str = "din_out"       # output endpoint
    channel_out: int = 0        # output channel
    rate: int = PPQN // 4       # ticks per step (default 1/16)
    gate: float = 0.6           # fraction of the step a note sounds
    octaves: int = 1
    pattern: str = "up"
    ratchet: int = 1            # hits per step
    probability: float = 1.0    # chance a step fires at all
    hold: bool = False          # latch: keep notes after release

    def normalised(self) -> "ArpParams":
        return replace(
            self,
            rate=self.rate if self.rate in RATES else PPQN // 4,
            gate=max(0.05, min(1.0, float(self.gate))),
            octaves=max(1, min(MAX_OCTAVES, int(self.octaves))),
            pattern=self.pattern if self.pattern in PATTERNS else "up",
            ratchet=max(1, min(MAX_RATCHET, int(self.ratchet))),
            probability=max(0.0, min(1.0, float(self.probability))),
            channel_out=max(0, min(15, int(self.channel_out))))


class Arp:
    """Holds notes, steps a pattern. One instance per panel slot."""

    def __init__(self, params: ArpParams | None = None) -> None:
        self.params = (params or ArpParams()).normalised()
        self._held: list[tuple[int, int]] = []      # (note, velocity), press order
        self._physical: set[int] = set()            # keys actually down
        self._step = 0

    # --- input ---------------------------------------------------------------
    def matches(self, endpoint: str, channel: int) -> bool:
        p = self.params
        if not p.enabled:
            return False
        if p.source not in (ANY_SOURCE, endpoint):
            return False
        return p.channel_in in (OMNI, channel)

    def note_on(self, note: int, velocity: int) -> None:
        if self.params.hold and not self._physical:
            # First key of a new phrase while latched: the old chord yields.
            self._held.clear()
            self._step = 0
        self._physical.add(note)
        if all(n != note for n, _v in self._held):
            self._held.append((note, velocity))

    def note_off(self, note: int) -> None:
        self._physical.discard(note)
        if not self.params.hold:
            self._held = [(n, v) for n, v in self._held if n != note]
            if not self._held:
                self._step = 0

    def clear(self) -> None:
        self._held.clear()
        self._physical.clear()
        self._step = 0

    def set_params(self, params: ArpParams) -> None:
        was_hold = self.params.hold
        self.params = params.normalised()
        if was_hold and not self.params.hold:
            # Dropping latch keeps only what is physically held.
            self._held = [(n, v) for n, v in self._held
                          if n in self._physical]

    # --- pattern -------------------------------------------------------------
    def _cycle(self, rng) -> list[tuple[int, int]]:
        base = list(self._held)
        if not base:
            return []
        p = self.params
        notes = []
        for octave in range(p.octaves):
            notes += [(n + 12 * octave, v) for n, v in base if
                      n + 12 * octave <= 127]
        if p.pattern == "up":
            return sorted(notes)
        if p.pattern == "down":
            return sorted(notes, reverse=True)
        if p.pattern == "updown":
            asc = sorted(notes)
            return asc + asc[-2:0:-1] if len(asc) > 2 else asc
        if p.pattern == "random":
            return [rng.choice(notes)]
        return notes                    # "order": press order, octave-stacked

    def on_tick(self, tick: int, rng) -> list[tuple[int, int, int, int]]:
        """Emissions for this tick: ``(offset, note, velocity, length)``.

        Ratchets subdivide the step into equal hits; the last hit keeps the
        gate so the step never bleeds into the next one.
        """
        p = self.params
        if not p.enabled or not self._held or tick % p.rate:
            return []
        cycle = self._cycle(rng)
        if not cycle:
            return []
        if p.probability < 1.0 and rng.random() >= p.probability:
            self._step += 1             # a skipped step still advances
            return []
        note, velocity = cycle[self._step % len(cycle)]
        self._step += 1
        hit_span = p.rate // p.ratchet
        length = max(1, round(hit_span * p.gate))
        return [(hit * hit_span, note, velocity, length)
                for hit in range(p.ratchet)]

    # --- panel ---------------------------------------------------------------
    def held_notes(self) -> tuple[int, ...]:
        return tuple(n for n, _v in self._held)


@dataclass(frozen=True, slots=True)
class ArpView:
    """What the panel shows for one arp slot."""

    enabled: bool = False
    source: str = ANY_SOURCE
    channel_in: int = OMNI
    dest: str = "din_out"
    channel_out: int = 0
    rate: int = PPQN // 4
    gate: float = 0.6
    octaves: int = 1
    pattern: str = "up"
    ratchet: int = 1
    probability: float = 1.0
    hold: bool = False
    held: tuple[int, ...] = field(default_factory=tuple)
