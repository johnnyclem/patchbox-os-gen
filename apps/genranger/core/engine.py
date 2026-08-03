"""The GenRanger engine: layers on the grid, cruise on the bar line.

Built on ``rangerkit.enginebase``. The whole musical loop:

* each layer holds an immutable rendered ``Pattern``; ``on_tick`` reads it —
  at each step boundary the step's note goes out through ``send_note`` (the
  base books the off-tick, which is what makes mute/stop/panic mid-note
  free);
* at each pattern-cycle boundary the layer's ``generation`` increments and
  the pattern re-renders from ``Random(mix(seed, index, generation))`` —
  stochastic layers evolve loop to loop, deterministically;
* cruise fires on its own bar-multiple clock, mutating one unlocked layer's
  *(params, seed)* per firing from a dedicated rng, and pushes the state to
  the timeline.

Not FREE_RUN: a generative sequencer is transport-bound. Stop is silence
(the base releases everything), and the appliance auto-plays at boot so the
factory piece sounds immediately.
"""
from __future__ import annotations

import logging
import random
from dataclasses import asdict, replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, MidiEvent, TICKS_PER_BAR

from core import commands as cmd
from core.cellular import row_at
from core.cruise import Cruise
from core.layers import (GRID_ROWS, LAYER_COUNT, LayerParams, LayerView,
                         Pattern, render_layer)
from core.macros import apply_macros
from core.mutate import mutate
from core.probgrid import grid_for
from core.seeds import SeedStore, mix
from core.timeline import Timeline

log = logging.getLogger("genranger.engine")

CC_SUBSTEP = 4                  # cc layers emit at quarter-step resolution


class _Layer:
    """Runtime state for one layer: params + seed salt + generation + the
    rendered pattern. Plain mutable object — only the engine thread touches
    it."""

    __slots__ = ("params", "seed", "generation", "pattern", "current_step",
                 "last_cc")

    def __init__(self, params: LayerParams, seed: int) -> None:
        self.params = params
        self.seed = seed
        self.generation = 0
        self.pattern = Pattern(step_count=params.step_count)
        self.current_step = 0
        self.last_cc: int | None = None


class GenRangerEngine(base.RangerEngine):
    """Post commands, read snapshots; the piece evolves on its own."""

    THREAD_NAME = "gv-engine"
    FREE_RUN = False

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.cruise = Cruise()
        self.cruise_rng = random.Random(mix(project.seed, 0xC7015E))
        self.macro_density = 0.5
        self.macro_complexity = 0.5
        self.root = 0
        self.scale = "minor"
        self.layers: list[_Layer] = [
            _Layer(LayerParams(enabled=False), mix(project.seed, i))
            for i in range(LAYER_COUNT)]
        self.seeds = SeedStore(project.seeds)
        self.timeline = Timeline()
        self._activity_out: dict[str, int] = {}
        self.apply_state(project.params)
        self._render_all()

    # --- the state tree (seeds, timeline and the project speak this shape) ----
    def capture_state(self) -> dict:
        return {
            "layers": [asdict(layer.params) for layer in self.layers],
            "layer_seeds": [layer.seed for layer in self.layers],
            "layer_generations": [layer.generation for layer in self.layers],
            "key": {"root": self.root, "scale": self.scale},
            "cruise": {"on": self.cruise.on, "speed": self.cruise.speed,
                       "chaos": self.cruise.chaos},
            "macros": {"density": self.macro_density,
                       "complexity": self.macro_complexity},
        }

    def apply_state(self, state: dict) -> None:
        state = state or {}
        key = state.get("key") or {}
        self.root = int(key.get("root", self.root)) % 12
        self.scale = str(key.get("scale", self.scale))
        raw_layers = state.get("layers") or []
        for index, layer in enumerate(self.layers):
            if index < len(raw_layers):
                params = _build(LayerParams, raw_layers[index])
                layer.params = replace(params, root=self.root,
                                       scale=self.scale).normalised()
            else:
                layer.params = LayerParams(enabled=False)
        for index, seed in enumerate(state.get("layer_seeds") or []):
            if index < len(self.layers):
                self.layers[index].seed = int(seed)
        for index, generation in enumerate(state.get("layer_generations")
                                           or []):
            if index < len(self.layers):
                self.layers[index].generation = int(generation)
        cruise = state.get("cruise") or {}
        self.cruise.on = bool(cruise.get("on", self.cruise.on))
        self.cruise.speed = max(0.0, min(1.0, float(
            cruise.get("speed", self.cruise.speed))))
        self.cruise.chaos = max(0.0, min(1.0, float(
            cruise.get("chaos", self.cruise.chaos))))
        macros = state.get("macros") or {}
        self.macro_density = max(0.0, min(1.0, float(
            macros.get("density", self.macro_density))))
        self.macro_complexity = max(0.0, min(1.0, float(
            macros.get("complexity", self.macro_complexity))))

    def capture(self):
        """Fold live state back into a project value for saving."""
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_state(),
                       seeds=self.seeds.to_config())

    # --- rendering -------------------------------------------------------------
    def _render(self, index: int) -> None:
        layer = self.layers[index]
        if not layer.params.enabled:
            layer.pattern = Pattern(step_count=layer.params.step_count)
            return
        effective = apply_macros(layer.params, self.macro_density,
                                 self.macro_complexity)
        rng = random.Random(mix(layer.seed, index, layer.generation))
        layer.pattern = render_layer(effective, rng,
                                     previous=layer.pattern,
                                     generation=layer.generation)

    def _render_all(self) -> None:
        for index in range(len(self.layers)):
            self._render(index)

    def _restore(self, state: dict | None) -> None:
        """Timeline/seed restore: apply, release, re-render — the sounding
        piece becomes exactly the recorded one."""
        if state is None:
            return
        self.all_notes_off()
        self.apply_state(state)
        self._render_all()

    # --- the tick --------------------------------------------------------------
    def on_tick(self, tick: int) -> None:
        for index, layer in enumerate(self.layers):
            params = layer.params
            if not params.enabled:
                continue
            pattern = layer.pattern
            position = tick % pattern.ticks
            if position == 0 and tick > 0:
                layer.generation += 1
                self._render(index)
                pattern = layer.pattern
            step_index, offset = divmod(position, pattern.step_ticks)
            layer.current_step = step_index
            if params.muted:
                continue
            if params.role == "cc":
                self._cc_tick(layer, step_index, offset)
                continue
            if offset == 0:
                step = pattern.step_at(step_index)
                if step is not None:
                    self._emit(params, step)
        if self.cruise.due(tick):
            self._cruise_fire(tick)

    def _emit(self, params: LayerParams, step) -> None:
        self._activity_out[params.dest] = \
            self._activity_out.get(params.dest, 0) + 1
        self.send_note(params.channel, step.note, step.velocity,
                       step.length_ticks, endpoint=params.dest)

    def _cc_tick(self, layer: _Layer, step_index: int, offset: int) -> None:
        pattern = layer.pattern
        if not pattern.cc_curve or offset % max(
                1, pattern.step_ticks // CC_SUBSTEP):
            return
        here = pattern.cc_curve[step_index % len(pattern.cc_curve)]
        following = pattern.cc_curve[(step_index + 1) % len(pattern.cc_curve)]
        t = offset / pattern.step_ticks
        value = round(here + (following - here) * t)
        if value == layer.last_cc:
            return
        layer.last_cc = value
        params = layer.params
        self._activity_out[params.dest] = \
            self._activity_out.get(params.dest, 0) + 1
        self.midi.send(params.dest, MidiEvent(EventKind.CC, 0,
                                              params.channel, params.cc,
                                              value))

    # --- mutation --------------------------------------------------------------
    def _mutable(self) -> list[int]:
        return [i for i, layer in enumerate(self.layers)
                if layer.params.enabled and not layer.params.locked]

    def _mutate_layer(self, index: int) -> None:
        layer = self.layers[index]
        new_params, reseed = mutate(layer.params, self.cruise_rng,
                                    self.cruise.chaos)
        layer.params = new_params
        if reseed:
            layer.seed = self.cruise_rng.getrandbits(48)
        self._render(index)

    def _cruise_fire(self, tick: int) -> None:
        index = self.cruise.next_layer(self._mutable())
        if index is None:
            return
        self._mutate_layer(index)
        self.timeline.push(tick // TICKS_PER_BAR, self.capture_state())

    # --- snapshot --------------------------------------------------------------
    def build_snapshot(self):
        b = super().build_snapshot()
        is_bound = getattr(self.midi, "is_bound", lambda _e: False)
        views = []
        for layer in self.layers:
            params = layer.params
            if not params.enabled:
                views.append(LayerView(role="", algorithm=""))
                continue
            ca_row = row_at(params.rule, params.ca_seed, layer.generation) \
                if params.algorithm == "cellular" else ()
            views.append(LayerView(
                role=params.role, algorithm=params.algorithm,
                muted=params.muted, locked=params.locked,
                lock_start=params.lock_start, lock_end=params.lock_end,
                dest=params.dest, channel=params.channel,
                step_count=params.step_count, density=params.density,
                note_length=params.note_length,
                octave_low=params.octave_low, octave_high=params.octave_high,
                pulses=params.pulses, rotate=params.rotate,
                order=params.order, style=params.style,
                temperature=params.temperature, rule=params.rule,
                ca_seed=params.ca_seed,
                max_interval=params.max_interval, cc=params.cc,
                current_step=layer.current_step,
                hits=tuple(sorted({s.index for s in layer.pattern.steps})),
                grid=grid_for(params) if params.algorithm == "grid" else (),
                ca_row=ca_row,
                sounding=sum(1 for (endpoint, channel, _n) in self._release
                             if endpoint == params.dest
                             and channel == params.channel),
                generation=layer.generation))
        destinations = sorted({layer.params.dest for layer in self.layers
                               if layer.params.enabled})
        return cmd.GvSnapshot(
            playing=b.playing, recording=b.recording, bpm=b.bpm, tick=b.tick,
            bar=b.bar, beat=b.beat, clock_out=b.clock_out, backend=b.backend,
            voices=b.voices, message=b.message,
            root=self.root, scale=self.scale,
            cruise_on=self.cruise.on, cruise_speed=self.cruise.speed,
            chaos=self.cruise.chaos,
            macro_density=self.macro_density,
            macro_complexity=self.macro_complexity,
            all_locked=bool(self.layers) and not self._mutable(),
            layers=tuple(views),
            timeline_len=len(self.timeline),
            timeline_pos=self.timeline.position,
            timeline_bars=self.timeline.bars(),
            seeds_occupied=self.seeds.occupied(),
            outputs_bound=tuple((d, bool(is_bound(d)))
                                for d in destinations),
            activity_out=tuple((d, self._activity_out.get(d, 0))
                               for d in destinations),
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))

    # --- pots ------------------------------------------------------------------
    POT_TARGETS = ("cruise_speed", "chaos", "density", "complexity",
                   "nothing")
    DEFAULT_POT_MAP = {"POT_A": "cruise_speed", "POT_B": "chaos"}

    def on_pot(self, index: int, value: float) -> None:
        configured = dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {})
        mapping = dict(self.DEFAULT_POT_MAP)
        for gesture, target in configured.items():
            if target in self.POT_TARGETS:
                mapping[str(gesture).upper()] = target
            else:
                log.warning("unknown pot target %r — ignored", target)
        target = mapping.get(("POT_A", "POT_B")[index], "nothing")
        if target == "cruise_speed":
            self.cruise.speed = value
        elif target == "chaos":
            self.cruise.chaos = value
        elif target == "density":
            self.macro_density = value
            self._render_all()
        elif target == "complexity":
            self.macro_complexity = value
            self._render_all()


def _build(cls, raw: dict):
    """Params dataclass from a stored dict, unknown keys dropped — the same
    forgiveness the config loader shows. Lists (the grid) become tuples so
    params stay hashable-by-value."""
    fields = cls.__dataclass_fields__
    kwargs = {}
    for key, value in (raw or {}).items():
        if key not in fields:
            continue
        if key == "grid" and value:
            value = tuple(tuple(row) for row in value)
        kwargs[key] = value
    return cls(**kwargs)


# --- handlers ------------------------------------------------------------------

def _valid_index(engine, index: int) -> bool:
    return 0 <= index < len(engine.layers) \
        and engine.layers[index].params.enabled


def _h_layer_field(engine, command: cmd.SetLayerField) -> None:
    # "enabled" is the one field a *dormant* slot answers to — it is how the
    # panel adds layer 5 and 6.
    if command.name == "enabled" \
            and 0 <= command.index < len(engine.layers):
        layer = engine.layers[command.index]
        was = layer.params
        layer.params = replace(was, enabled=bool(command.value),
                               root=engine.root,
                               scale=engine.scale).normalised()
        if was.enabled and not layer.params.enabled:
            engine.release_channel(was.channel, endpoint=was.dest)
        engine._render(command.index)
        return
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    if command.name not in LayerParams.__dataclass_fields__:
        log.warning("unknown layer field %r — ignored", command.name)
        return
    value = command.value
    if command.name == "grid" and value:
        value = tuple(tuple(row) for row in value)
    was_muted = layer.params.muted
    layer.params = replace(layer.params,
                           **{command.name: value}).normalised()
    if command.name == "muted" and layer.params.muted and not was_muted:
        engine.release_channel(layer.params.channel,
                               endpoint=layer.params.dest)
    if command.name not in ("muted", "locked"):
        engine._render(command.index)


def _h_grid_cell(engine, command: cmd.SetGridCell) -> None:
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    grid = [list(row) for row in grid_for(layer.params)]
    if not (0 <= command.row < GRID_ROWS
            and 0 <= command.step < layer.params.step_count):
        return
    grid[command.row][command.step] = max(0.0, min(1.0,
                                                   float(command.value)))
    layer.params = replace(layer.params,
                           grid=tuple(tuple(r) for r in grid))
    engine._render(command.index)


def _h_ca_cell(engine, command: cmd.SetCaSeedCell) -> None:
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    if not 0 <= command.cell < 16:
        return
    layer.params = replace(layer.params,
                           ca_seed=layer.params.ca_seed
                           ^ (1 << command.cell)).normalised()
    layer.generation = 0            # a new seed row starts its own history
    engine._render(command.index)


def _h_lock_range(engine, command: cmd.SetLockRange) -> None:
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    layer.params = replace(layer.params, lock_start=command.start,
                           lock_end=command.end).normalised()


def _h_mute(engine, command: cmd.ToggleLayerMute) -> None:
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    layer.params = replace(layer.params, muted=not layer.params.muted)
    if layer.params.muted:
        # A muted layer's phrase stops producing note-ons; what is already
        # sounding on its channel must be released here or never.
        engine.release_channel(layer.params.channel,
                               endpoint=layer.params.dest)


def _h_lock(engine, command: cmd.ToggleLayerLock) -> None:
    if not _valid_index(engine, command.index):
        return
    layer = engine.layers[command.index]
    layer.params = replace(layer.params, locked=not layer.params.locked)


def _h_lock_all(engine, _command) -> None:
    if engine._mutable():
        for layer in engine.layers:
            if layer.params.enabled:
                layer.params = replace(layer.params, locked=True)
        engine.message = "ALL LOCKED"
    else:
        for layer in engine.layers:
            if layer.params.enabled:
                layer.params = replace(layer.params, locked=False)
        engine.message = "ALL FREE"


def _h_mutate_now(engine, command: cmd.MutateNow) -> None:
    if command.index >= 0:
        if not _valid_index(engine, command.index):
            return
        if engine.layers[command.index].params.locked:
            engine.message = "LAYER LOCKED"
            return
        index = command.index
    else:
        candidates = engine._mutable()
        if not candidates:
            engine.message = "ALL LOCKED"
            return
        index = candidates[engine.cruise_rng.randrange(len(candidates))]
    engine._mutate_layer(index)
    engine.timeline.push(engine.tick // TICKS_PER_BAR,
                         engine.capture_state())
    engine.message = f"MUTATED L{index + 1}"


def _h_reseed(engine, command: cmd.Reseed) -> None:
    targets = [command.index] if command.index >= 0 else engine._mutable()
    for index in targets:
        if not _valid_index(engine, index) \
                or engine.layers[index].params.locked:
            continue
        engine.layers[index].seed = engine.cruise_rng.getrandbits(48)
        engine.layers[index].generation = 0
        engine._render(index)
    engine.timeline.push(engine.tick // TICKS_PER_BAR,
                         engine.capture_state())
    engine.message = "RESEEDED"


def _h_cruise(engine, command: cmd.SetCruise) -> None:
    engine.cruise.on = bool(command.on)


def _h_cruise_field(engine, command: cmd.SetCruiseField) -> None:
    value = max(0.0, min(1.0, float(command.value)))
    if command.name == "speed":
        engine.cruise.speed = value
    elif command.name == "chaos":
        engine.cruise.chaos = value
    else:
        log.warning("unknown cruise field %r — ignored", command.name)


def _h_macro(engine, command: cmd.SetMacro) -> None:
    value = max(0.0, min(1.0, float(command.value)))
    if command.name == "density":
        engine.macro_density = value
    elif command.name == "complexity":
        engine.macro_complexity = value
    else:
        log.warning("unknown macro %r — ignored", command.name)
        return
    engine._render_all()


def _h_key(engine, command: cmd.SetKey) -> None:
    engine.root = int(command.root) % 12
    if command.scale:
        engine.scale = command.scale
    for index, layer in enumerate(engine.layers):
        if layer.params.enabled:
            layer.params = replace(layer.params, root=engine.root,
                                   scale=engine.scale).normalised()
    engine.all_notes_off()          # old-key notes must not ring into the new
    engine._render_all()


def _h_capture_seed(engine, command: cmd.CaptureSeed) -> None:
    if engine.seeds.save(command.slot, engine.capture_state()):
        engine.message = f"SEED {command.slot + 1} SAVED"


def _h_recall_seed(engine, command: cmd.RecallSeed) -> None:
    state = engine.seeds.get(command.slot)
    if state is None:
        engine.message = f"SEED {command.slot + 1} EMPTY"
        return
    engine._restore(state)
    engine.message = f"SEED {command.slot + 1}"


def _h_timeline_step(engine, command: cmd.TimelineStep) -> None:
    engine._restore(engine.timeline.step(command.delta))


def _h_timeline_live(engine, _command) -> None:
    engine._restore(engine.timeline.live())


def _h_project_state(engine, command: cmd.RecallProjectState) -> None:
    engine._restore(dict(command.params) or None)


GenRangerEngine.HANDLERS = {
    cmd.SetLayerField: _h_layer_field,
    cmd.SetGridCell: _h_grid_cell,
    cmd.SetCaSeedCell: _h_ca_cell,
    cmd.SetLockRange: _h_lock_range,
    cmd.ToggleLayerMute: _h_mute,
    cmd.ToggleLayerLock: _h_lock,
    cmd.LockAll: _h_lock_all,
    cmd.MutateNow: _h_mutate_now,
    cmd.Reseed: _h_reseed,
    cmd.SetCruise: _h_cruise,
    cmd.SetCruiseField: _h_cruise_field,
    cmd.SetMacro: _h_macro,
    cmd.SetKey: _h_key,
    cmd.CaptureSeed: _h_capture_seed,
    cmd.RecallSeed: _h_recall_seed,
    cmd.TimelineStep: _h_timeline_step,
    cmd.TimelineLive: _h_timeline_live,
    cmd.RecallProjectState: _h_project_state,
}
