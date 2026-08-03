"""The MidiRanger engine: the matrix, the rack, and the clock.

Built on ``rangerkit.enginebase``. What this subclass adds:

* the thru path — an incoming note is quantized, harmonized, FX-processed
  and routed the moment it is drained from the queue (<5 ms in→out is a
  drain-latency property, not a tick-latency one);
* four arps that *consume* matching input and emit on the tick grid;
* a schedule heap for everything that happens later — echoes, ratchet hits,
  humanize delays — so future notes are data, not timers;
* the CC LFO bank;
* scenes with morph.

Note ownership is unchanged from the family rule: every note-on goes out
through ``send_note`` with its off-tick booked. Thru notes are booked with a
long safety length and released early when the player's note-off arrives —
a dead input device can strand a note for bars, not forever, and panic
clears everything regardless.

The engine is FREE_RUN: echoes and humanize delays must fire with the
transport stopped (a MIDI FX box that goes dead on stop is broken). The
transport gates the *musical* clocks — arps, LFOs, MIDI clock out.
"""
from __future__ import annotations

import heapq
import logging
import random
from dataclasses import asdict, replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, MidiEvent, TICKS_PER_BAR
from rangerkit.routing import RoutingMatrix

from core import commands as cmd
from core.arp import Arp, ArpParams, ArpView
from core.cclfo import CcLfo, LfoParams
from core.harmonizer import HarmonizerParams, harmonize
from core.notefx import FxParams, process as fx_process
from core.quantizer import QuantizerParams, quantize
from core.scene import SceneStore, blend

log = logging.getLogger("midiranger.engine")

ARP_COUNT = 4
LFO_COUNT = 4
# Thru notes are held by the player, not by a length. This is the safety net
# for an input that dies mid-note: 16 bars, then the book releases it.
THRU_SAFETY_TICKS = TICKS_PER_BAR * 16


class MidiRangerEngine(base.RangerEngine):
    """Post commands, feed it MIDI, read snapshots."""

    THREAD_NAME = "mr-engine"
    FREE_RUN = True

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.rng = random.Random(project.seed)
        self.bypass = False
        self.matrix = RoutingMatrix()
        self.arps = [Arp() for _ in range(ARP_COUNT)]
        self.quantizer = QuantizerParams()
        self.harmonizer = HarmonizerParams()
        self.fx = FxParams()
        self.lfos = [CcLfo(seed=project.seed + i) for i in range(LFO_COUNT)]
        self.scenes = SceneStore(project.scenes)
        self.morph_state: tuple = ()
        # input (endpoint, ch, note) -> emitted ((endpoint, ch, note), ...)
        self._thru: dict[tuple, tuple] = {}
        # (due_tick, sequence, endpoint, ch, note, velocity, length)
        self._schedule: list = []
        self._sequence = 0
        self._activity_in: dict[str, int] = {}
        self._activity_out: dict[str, int] = {}
        self.apply_params(project.params)
        if not self.matrix.routes and config is not None:
            # A project with no routing falls back to the appliance's
            # [routing] table, so a fresh unit passes MIDI out of the box.
            self.matrix = RoutingMatrix.from_config(
                list(getattr(config.routing, "routes", ()) or ()))

    # --- parameter tree (scenes and the project speak this shape) -------------
    def capture_params(self) -> dict:
        return {
            "routes": self.matrix.to_config(),
            "arps": [asdict(a.params) for a in self.arps],
            "quantizer": asdict(self.quantizer),
            "harmonizer": asdict(self.harmonizer),
            "fx": asdict(self.fx),
            "lfos": [asdict(l.params) for l in self.lfos],
        }

    def apply_params(self, params: dict) -> None:
        params = params or {}
        self.matrix = RoutingMatrix.from_config(params.get("routes"))
        for arp, raw in zip(self.arps, params.get("arps") or []):
            arp.set_params(_build(ArpParams, raw))
        if "quantizer" in params:
            self.quantizer = _build(QuantizerParams,
                                    params["quantizer"]).normalised()
        if "harmonizer" in params:
            self.harmonizer = _build(HarmonizerParams,
                                     params["harmonizer"]).normalised()
        if "fx" in params:
            self.fx = _build(FxParams, params["fx"]).normalised()
        for lfo, raw in zip(self.lfos, params.get("lfos") or []):
            lfo.set_params(_build(LfoParams, raw))

    def capture(self):
        """Fold live state back into a project value for saving."""
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_params(),
                       scenes=self.scenes.to_config())

    # --- MIDI in ---------------------------------------------------------------
    def on_midi_in_event(self, endpoint_id: str, event: MidiEvent) -> None:
        self._activity_in[endpoint_id] = \
            self._activity_in.get(endpoint_id, 0) + 1
        kind = event.kind
        if kind is EventKind.NOTE_ON and event.data2 > 0:
            self._note_on(endpoint_id, event.channel, event.data1,
                          event.data2)
        elif kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            self._note_off(endpoint_id, event.channel, event.data1)
        else:
            # CC / program / pitch bend: straight through the matrix. The
            # rack is a *note* rack; a mod wheel must arrive now, untouched.
            for dst, channel in self.matrix.targets(endpoint_id,
                                                   event.channel):
                self._send_raw(dst, replace(event, channel=channel))

    def _note_on(self, endpoint: str, channel: int, note: int,
                 velocity: int) -> None:
        if not self.bypass:
            consumed = False
            for arp in self.arps:
                if arp.matches(endpoint, channel):
                    arp.note_on(note, velocity)
                    consumed = True
            if consumed:
                return
        targets = self.matrix.targets(endpoint, channel)
        if not targets:
            return
        if self.bypass:
            emitted = []
            for dst, out_channel in targets:
                self.send_note(out_channel, note, velocity,
                               THRU_SAFETY_TICKS, endpoint=dst)
                emitted.append((dst, out_channel, note))
            self._thru[(endpoint, channel, note)] = tuple(emitted)
            return
        played = quantize(note, self.quantizer)
        voices = [(played, velocity)]
        voices += list(harmonize(played, velocity, self.harmonizer))
        emitted = []
        for voice_note, voice_velocity in voices:
            for offset, out_note, out_velocity in \
                    fx_process(voice_note, voice_velocity, self.fx, self.rng):
                for dst, out_channel in targets:
                    if offset == 0:
                        self.send_note(out_channel, out_note, out_velocity,
                                       THRU_SAFETY_TICKS, endpoint=dst)
                        emitted.append((dst, out_channel, out_note))
                    else:
                        # Echoes and humanize delays are not held by the
                        # player; they get a real length instead of a
                        # release entry.
                        self._book(offset, dst, out_channel, out_note,
                                   out_velocity,
                                   max(1, self.fx.echo_ticks // 2))
        if emitted:
            self._thru[(endpoint, channel, note)] = tuple(emitted)

    def _note_off(self, endpoint: str, channel: int, note: int) -> None:
        for arp in self.arps:
            if arp.matches(endpoint, channel):
                arp.note_off(note)
        emitted = self._thru.pop((endpoint, channel, note), ())
        for dst, out_channel, out_note in emitted:
            self.release_note(out_channel, out_note, endpoint=dst)

    # --- the tick --------------------------------------------------------------
    def on_tick(self, tick: int) -> None:
        while self._schedule and self._schedule[0][0] <= tick:
            _due, _seq, dst, channel, note, velocity, length = \
                heapq.heappop(self._schedule)
            self.send_note(channel, note, velocity, length, endpoint=dst)
        if not self.playing:
            return                  # arps and LFOs are transport-bound
        for arp in self.arps:
            for offset, note, velocity, length in arp.on_tick(tick, self.rng):
                if offset == 0:
                    self.send_note(arp.params.channel_out, note, velocity,
                                   length, endpoint=arp.params.dest)
                else:
                    self._book(offset, arp.params.dest,
                               arp.params.channel_out, note, velocity,
                               length)
        for lfo in self.lfos:
            value = lfo.on_tick(tick)
            if value is not None:
                self._send_raw(lfo.params.dest,
                               MidiEvent(EventKind.CC, 0, lfo.params.channel,
                                         lfo.params.cc, value))

    def _book(self, offset: int, dst: str, channel: int, note: int,
              velocity: int, length: int) -> None:
        self._sequence += 1
        heapq.heappush(self._schedule,
                       (self.tick + offset, self._sequence, dst, channel,
                        note, velocity, length))

    def _send_raw(self, endpoint: str, event: MidiEvent) -> None:
        self._activity_out[endpoint] = \
            self._activity_out.get(endpoint, 0) + 1
        self.midi.send(endpoint, event)

    def send_note(self, channel, note, velocity, length_ticks,
                  endpoint=base.OUT):
        self._activity_out[endpoint] = \
            self._activity_out.get(endpoint, 0) + 1
        super().send_note(channel, note, velocity, length_ticks,
                          endpoint=endpoint)

    # --- pots ------------------------------------------------------------------
    # [pots.map] names → what the knob actually turns. "Two assignable hot
    # params" from the PRD; unknown names cost a log line, like every other
    # hand-written map in the family.
    POT_TARGETS = ("arp_probability", "arp_gate", "humanize", "echo_decay",
                   "morph", "nothing")
    DEFAULT_POT_MAP = {"POT_A": "arp_probability", "POT_B": "humanize"}

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
        if target == "arp_probability":
            for arp in self.arps:
                arp.set_params(replace(arp.params, probability=value))
        elif target == "arp_gate":
            for arp in self.arps:
                arp.set_params(replace(arp.params,
                                       gate=max(0.05, value)))
        elif target == "humanize":
            from core.notefx import MAX_TIMING
            self.fx = replace(self.fx,
                              humanize_timing=round(value * MAX_TIMING),
                              humanize_velocity=round(value * 24)
                              ).normalised()
        elif target == "echo_decay":
            self.fx = replace(self.fx,
                              echo_decay=max(0.1, value)).normalised()
        elif target == "morph" and len(self.morph_state) == 3:
            self.submit(cmd.Morph(slot_a=self.morph_state[0],
                                  slot_b=self.morph_state[1], t=value))

    # --- sweeping the decks ----------------------------------------------------
    def panic(self) -> None:
        self._schedule.clear()
        self._thru.clear()
        for arp in self.arps:
            arp.clear()
        super().panic()

    def on_stop(self) -> None:
        # Stop is musical: pending echoes die, held thru notes were already
        # released by all_notes_off, arps keep their held keys (the player's
        # hands have not moved).
        self._schedule.clear()
        self._thru.clear()

    # --- snapshot --------------------------------------------------------------
    def build_snapshot(self):
        b = super().build_snapshot()
        is_bound = getattr(self.midi, "is_bound", lambda _e: False)
        endpoints_in = sorted({r.src for r in self.matrix.routes}
                              | set(self._activity_in))
        endpoints_out = sorted({r.dst for r in self.matrix.routes}
                               | set(self._activity_out))
        return cmd.MrSnapshot(
            playing=b.playing, recording=b.recording, bpm=b.bpm, tick=b.tick,
            bar=b.bar, beat=b.beat, clock_out=b.clock_out, backend=b.backend,
            voices=b.voices, message=b.message,
            bypass=self.bypass,
            routes=tuple(sorted(self.matrix.routes,
                                key=lambda r: (r.src, r.dst, r.channel))),
            arps=tuple(ArpView(**asdict(a.params),
                               held=a.held_notes()) for a in self.arps),
            quantizer_enabled=self.quantizer.enabled,
            quantizer_root=self.quantizer.root,
            quantizer_scale=self.quantizer.scale,
            harmonizer_mode=self.harmonizer.mode,
            fx_curve=self.fx.curve, fx_curve_amount=self.fx.curve_amount,
            fx_humanize_timing=self.fx.humanize_timing,
            fx_humanize_velocity=self.fx.humanize_velocity,
            fx_drop_probability=self.fx.drop_probability,
            fx_echo_repeats=self.fx.echo_repeats,
            fx_echo_ticks=self.fx.echo_ticks,
            fx_echo_decay=self.fx.echo_decay,
            lfos=tuple(cmd.LfoView(**asdict(l.params),
                                   value=l.value_at(self.tick))
                       for l in self.lfos),
            scenes_occupied=self.scenes.occupied(),
            morph=self.morph_state,
            activity_in=tuple((e, self._activity_in.get(e, 0))
                              for e in endpoints_in),
            activity_out=tuple((e, self._activity_out.get(e, 0))
                               for e in endpoints_out),
            inputs_bound=tuple((e, bool(is_bound(e))) for e in endpoints_in),
            outputs_bound=tuple((e, bool(is_bound(e)))
                                for e in endpoints_out),
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))


def _build(cls, raw: dict):
    """Params dataclass from a stored dict, unknown keys dropped — the same
    forgiveness the config loader shows."""
    fields = cls.__dataclass_fields__
    return cls(**{k: v for k, v in (raw or {}).items() if k in fields})


# --- handlers ------------------------------------------------------------------

def _field_update(engine, params, name, value, kinds):
    """Shared shape of every Set*Field: replace one field if it exists and
    normalise. Unknown names cost a log line, not a crash."""
    if name not in kinds.__dataclass_fields__:
        log.warning("unknown %s field %r — ignored", kinds.__name__, name)
        return None
    return replace(params, **{name: value}).normalised()


def _h_toggle_route(engine, command: cmd.ToggleRoute) -> None:
    before = engine.matrix
    engine.matrix = engine.matrix.toggled(command.route)
    if command.route in before.routes:
        # Removing a route must not strand what traveled it: release every
        # thru note that was emitted for that destination.
        for key, emitted in list(engine._thru.items()):
            kept = tuple(e for e in emitted if e[0] != command.route.dst)
            for dst, channel, note in emitted:
                if dst == command.route.dst:
                    engine.release_note(channel, note, endpoint=dst)
            if kept:
                engine._thru[key] = kept
            else:
                engine._thru.pop(key, None)


def _h_clear_routes(engine, _command) -> None:
    engine.matrix = RoutingMatrix()
    for key, emitted in list(engine._thru.items()):
        for dst, channel, note in emitted:
            engine.release_note(channel, note, endpoint=dst)
    engine._thru.clear()


def _h_bypass(engine, command: cmd.SetBypass) -> None:
    engine.bypass = bool(command.on)
    if engine.bypass:
        # Engaging bypass kills the rack's product (arps, echoes); raw thru
        # notes keep sounding — the player is still holding them.
        engine._schedule.clear()
        for arp in engine.arps:
            arp.clear()


def _h_arp_field(engine, command: cmd.SetArpField) -> None:
    if not 0 <= command.index < len(engine.arps):
        return
    arp = engine.arps[command.index]
    updated = _field_update(engine, arp.params, command.name, command.value,
                            ArpParams)
    if updated is not None:
        arp.set_params(updated)


def _h_arp_clear(engine, command: cmd.ClearArp) -> None:
    if 0 <= command.index < len(engine.arps):
        engine.arps[command.index].clear()


def _h_quantizer(engine, command: cmd.SetQuantizerField) -> None:
    updated = _field_update(engine, engine.quantizer, command.name,
                            command.value, QuantizerParams)
    if updated is not None:
        engine.quantizer = updated


def _h_harmonizer(engine, command: cmd.SetHarmonizerField) -> None:
    updated = _field_update(engine, engine.harmonizer, command.name,
                            command.value, HarmonizerParams)
    if updated is not None:
        engine.harmonizer = updated


def _h_fx(engine, command: cmd.SetFxField) -> None:
    updated = _field_update(engine, engine.fx, command.name, command.value,
                            FxParams)
    if updated is not None:
        engine.fx = updated


def _h_lfo_field(engine, command: cmd.SetLfoField) -> None:
    if not 0 <= command.index < len(engine.lfos):
        return
    lfo = engine.lfos[command.index]
    updated = _field_update(engine, lfo.params, command.name, command.value,
                            LfoParams)
    if updated is not None:
        lfo.set_params(updated)


def _h_save_scene(engine, command: cmd.SaveScene) -> None:
    if engine.scenes.save(command.slot, engine.capture_params()):
        engine.message = f"SCENE {command.slot + 1} SAVED"


def _h_recall_scene(engine, command: cmd.RecallScene) -> None:
    scene = engine.scenes.get(command.slot)
    if scene is None:
        engine.message = f"SCENE {command.slot + 1} EMPTY"
        return
    engine.all_notes_off()
    engine._schedule.clear()
    engine._thru.clear()
    engine.apply_params(scene)
    engine.morph_state = ()
    engine.message = f"SCENE {command.slot + 1}"


def _h_morph(engine, command: cmd.Morph) -> None:
    a = engine.scenes.get(command.slot_a)
    b = engine.scenes.get(command.slot_b)
    if a is None or b is None:
        engine.message = "MORPH NEEDS TWO SAVED SCENES"
        return
    engine.apply_params(blend(a, b, command.t))
    engine.morph_state = (command.slot_a, command.slot_b,
                          max(0.0, min(1.0, float(command.t))))


MidiRangerEngine.HANDLERS = {
    cmd.ToggleRoute: _h_toggle_route,
    cmd.ClearRoutes: _h_clear_routes,
    cmd.SetBypass: _h_bypass,
    cmd.SetArpField: _h_arp_field,
    cmd.ClearArp: _h_arp_clear,
    cmd.SetQuantizerField: _h_quantizer,
    cmd.SetHarmonizerField: _h_harmonizer,
    cmd.SetFxField: _h_fx,
    cmd.SetLfoField: _h_lfo_field,
    cmd.SaveScene: _h_save_scene,
    cmd.RecallScene: _h_recall_scene,
    cmd.Morph: _h_morph,
}
