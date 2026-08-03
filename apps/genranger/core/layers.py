"""Layers, patterns, and the generator table.

A **layer** is one voice of the evolving piece: a role (rhythm, bass,
melody, harmony, drone, cc), a generator algorithm, a MIDI destination, and
the constraints the generator works inside. A **pattern** is what a
generator renders: a fixed grid of steps covering ``step_count`` steps of
``step_ticks`` ticks each.

The contract that makes the whole app deterministic: a generator is a *pure
function* ``render(params, rng, ctx) -> Pattern``. All randomness comes from
the ``rng`` argument, which the engine seeds as
``Random(mix(seed, layer_index, generation))`` — so the same project at the
same generation renders the same pattern, on any box, forever. Cruise and
mutation change *(params, seed)*, never notes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from rangerkit.events import PPQN
from rangerkit.routing import OUTPUTS
from rangerkit.theory import SCALE_NAMES, scale_for

ROLES = ("rhythm", "bass", "melody", "harmony", "drone", "cc")
ALGORITHMS = ("euclid", "markov", "grid", "cellular", "random")
NOTE_LENGTHS = ("gate", "legato", "drone")
STEP_COUNTS = (8, 16, 32)
STEP_TICKS = PPQN // 4          # a sixteenth at 96 PPQN
LAYER_COUNT = 6
GRID_ROWS = 7                   # scale degrees the MAP lattice edits
CA_RULES = (30, 90, 110, 150, 182)
MARKOV_STYLES = ("walk", "arpy", "drone", "wander")


@dataclass(frozen=True, slots=True)
class Step:
    """One cell of a rendered pattern. ``note`` is a MIDI note, already
    inside the layer's register — generators speak degrees internally and
    convert on the way out, so the engine never touches theory."""

    index: int
    note: int
    velocity: int
    length_ticks: int


@dataclass(frozen=True, slots=True)
class Pattern:
    """What a generator renders. Immutable: mutation replaces patterns, the
    engine only reads them. ``cc_curve`` is the cc-role alternative — one
    0–127 value per step, no notes."""

    steps: tuple[Step, ...] = ()
    step_count: int = 16
    step_ticks: int = STEP_TICKS
    cc_curve: tuple[int, ...] = ()

    @property
    def ticks(self) -> int:
        return self.step_count * self.step_ticks

    def step_at(self, index: int) -> Step | None:
        for step in self.steps:
            if step.index == index:
                return step
        return None


@dataclass(frozen=True, slots=True)
class ScaleContext:
    """The key, as generators see it. ``degree_to_midi`` is the one door
    between degree-space and note-space, mirroring theory's ``pc()`` rule."""

    root: int = 0
    scale: str = "minor"
    octave_low: int = 3         # MIDI octave: C3 = 48
    octave_high: int = 5

    def degrees_span(self) -> int:
        """How many scale degrees the register holds."""
        return len(scale_for(self.scale)) * (self.octave_high
                                             - self.octave_low + 1)

    def degree_to_midi(self, degree: int) -> int:
        """Degree 0 = the root at octave_low; negative and past-the-top
        degrees clamp into the register rather than raising — a mutation
        that walks off the end must pin, not crash."""
        offsets = scale_for(self.scale).degrees
        degree = max(0, min(self.degrees_span() - 1, int(degree)))
        octave, position = divmod(degree, len(offsets))
        note = (self.octave_low + 1) * 12 + self.root \
            + octave * 12 + offsets[position]
        return max(0, min(127, note))


@dataclass(frozen=True, slots=True)
class LayerParams:
    """Everything a mutation may change and a project stores, per layer."""

    role: str = "melody"
    algorithm: str = "random"
    enabled: bool = True
    muted: bool = False
    locked: bool = False
    lock_start: int = -1        # locked step range; -1/-1 = none
    lock_end: int = -1
    dest: str = "din_out"
    channel: int = 0
    step_count: int = 16
    density: float = 0.5        # 0..1 — how busy
    velocity: int = 96
    note_length: str = "gate"
    octave_low: int = 3
    octave_high: int = 5
    root: int = 0               # folded in from the project key by the engine
    scale: str = "minor"
    # per-algorithm extras
    pulses: int = 4             # euclid
    rotate: int = 0             # euclid
    order: int = 1              # markov: 1 | 2
    style: str = "walk"         # markov
    temperature: float = 0.5    # markov: how adventurous
    rule: int = 90              # cellular
    ca_seed: int = 0b0000000010000000  # cellular seed row bits (16 wide)
    grid: tuple = ()            # probability lattice rows×steps, row-major
    max_interval: int = 5       # random: widest jump, in degrees
    cc: int = 74                # cc role: controller number
    cc_low: int = 20
    cc_high: int = 100

    def normalised(self) -> "LayerParams":
        low = max(0, min(8, int(self.octave_low)))
        high = max(low, min(8, int(self.octave_high)))
        lock_start, lock_end = int(self.lock_start), int(self.lock_end)
        if lock_end < lock_start:
            lock_start = lock_end = -1
        return replace(
            self,
            role=self.role if self.role in ROLES else "melody",
            algorithm=(self.algorithm if self.algorithm in ALGORITHMS
                       else "random"),
            dest=self.dest if self.dest in OUTPUTS else "din_out",
            channel=max(0, min(15, int(self.channel))),
            step_count=(self.step_count if self.step_count in STEP_COUNTS
                        else 16),
            density=max(0.0, min(1.0, float(self.density))),
            velocity=max(1, min(127, int(self.velocity))),
            note_length=(self.note_length
                         if self.note_length in NOTE_LENGTHS else "gate"),
            octave_low=low, octave_high=high,
            root=int(self.root) % 12,
            scale=self.scale if self.scale in SCALE_NAMES else "minor",
            lock_start=lock_start, lock_end=lock_end,
            pulses=max(0, min(32, int(self.pulses))),
            rotate=int(self.rotate) % max(1, int(self.step_count)),
            order=1 if int(self.order) < 2 else 2,
            style=self.style if self.style in MARKOV_STYLES else "walk",
            temperature=max(0.0, min(1.0, float(self.temperature))),
            rule=self.rule if self.rule in CA_RULES else 90,
            ca_seed=int(self.ca_seed) & 0xFFFFFFFF,
            max_interval=max(1, min(14, int(self.max_interval))),
            cc=max(0, min(119, int(self.cc))),
            cc_low=max(0, min(127, int(self.cc_low))),
            cc_high=max(0, min(127, int(self.cc_high))))

    def context(self) -> ScaleContext:
        return ScaleContext(root=self.root, scale=self.scale,
                            octave_low=self.octave_low,
                            octave_high=self.octave_high)

    def length_ticks(self) -> int:
        """The note length the role's feel calls for."""
        if self.note_length == "drone":
            return STEP_TICKS * self.step_count      # a full cycle
        if self.note_length == "legato":
            return STEP_TICKS
        return max(1, STEP_TICKS // 2)               # gate


def render_layer(params: LayerParams, rng,
                 previous: Pattern | None = None,
                 generation: int = 0) -> Pattern:
    """Dispatch to the algorithm, then merge the locked step range.

    The lock merge is the *last* stage on purpose: a mutation may change
    anything it likes, and the locked steps of the previous pattern are then
    copied back verbatim — deterministic, so determinism survives locking.
    """
    from core import cellular, euclidgen, markov, probgrid, randomgen
    table = {"euclid": euclidgen.render, "markov": markov.render,
             "grid": probgrid.render, "cellular": cellular.render,
             "random": randomgen.render}
    pattern = table[params.algorithm](params, rng, params.context(),
                                      generation)
    if previous is not None and params.lock_start >= 0:
        kept = {s.index: s for s in previous.steps
                if params.lock_start <= s.index <= params.lock_end}
        merged = tuple(sorted(
            [s for s in pattern.steps
             if not params.lock_start <= s.index <= params.lock_end]
            + list(kept.values()), key=lambda s: s.index))
        pattern = replace(pattern, steps=merged)
    return pattern


@dataclass(frozen=True, slots=True)
class LayerView:
    """What the panel shows for one layer — params plus live pattern facts."""

    role: str = "melody"
    algorithm: str = "random"
    muted: bool = False
    locked: bool = False
    lock_start: int = -1
    lock_end: int = -1
    dest: str = "din_out"
    channel: int = 0
    step_count: int = 16
    density: float = 0.5
    note_length: str = "gate"
    octave_low: int = 3
    octave_high: int = 5
    pulses: int = 4
    rotate: int = 0
    order: int = 1
    style: str = "walk"
    temperature: float = 0.5
    rule: int = 90
    ca_seed: int = 0
    max_interval: int = 5
    cc: int = 74
    current_step: int = 0
    hits: tuple[int, ...] = ()
    grid: tuple = ()            # rows × steps of probabilities, for MAP
    ca_row: tuple = ()          # the row currently sounding, for MAP
    sounding: int = 0
    generation: int = 0
