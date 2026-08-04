"""The GrooveRanger engine: patterns compiled to schedules, hits booked
through the release book, and the internal CC contract.

Built on ``rangerkit.enginebase``. What this subclass adds:

* the sequencer tick: look up this tick in the compiled schedule, gate each
  hit on mutes, its condition (pass counter / fill flag) and probability
  (the project's seeded rng), then emit;
* the emission contract: to an external destination a pad is (kit channel,
  pad note); to ``internal`` each pad speaks on its *own channel* (the pad
  index), and a hit's parameter locks travel as CC 16/74/10 immediately
  before its note-on — MIDI-observable, and exactly what the sampler
  consumes;
* pattern switching and fills at pass end, the song chain pressing pattern
  buttons on schedule, live pad hits with quantized record;
* the mixer as engine state, kept true in the sampler by emitting CCs.

``FREE_RUN`` is on: a stopped groovebox still auditions pads, and the tick
must advance for their booked note-offs to come due. Sequencer playback is
gated on the transport. Every engine test ends ``assert not
midi.hanging()``.
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, MidiEvent
from rangerkit.routing import INTERNAL

from core import commands as cmd
from core.kit import Kit, default_kit
from core.mixer import Mixer
from core.pad import TUNE_RANGE
from core.phrasechain import Chain
from core.sequencer import PATTERNS, STEP_TICKS, Sequencer
from core.steps import PADS, Pattern, STEPS, cond_passes

log = logging.getLogger("grooveranger.engine")

CC_TUNE, CC_PAN, CC_FILTER = 16, 10, 74
CC_LEVEL, CC_DELAY_DIV, CC_REVERB, CC_DAMP, CC_DUCK = 7, 85, 91, 92, 93
MASTER_CHANNEL = 15


def _cc7(value: float) -> int:
    return max(0, min(127, int(round(value * 100))))


class GrooveRangerEngine(base.RangerEngine):
    """Post commands, read snapshots; the sampler listens on ``internal``."""

    THREAD_NAME = "gr-engine"
    FREE_RUN = True

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.rng = random.Random(project.seed)
        self.seq = Sequencer()
        self.chain = Chain()
        self.kit = default_kit(config)
        self.mixer = Mixer()
        self.kit_rev = 0
        self.selected_pad = 0
        self.pos = 0                # pattern-local tick
        self._view_for: Pattern | None = None
        self._view: tuple = ()
        self.apply_state(project.params)

    # --- the state tree --------------------------------------------------------
    def capture_state(self) -> dict:
        return {"sequencer": self.seq.to_config(),
                "kit": self.kit.to_config(),
                "mixer": self.mixer.to_config(),
                "chain": self.chain.to_config(),
                "selected_pad": self.selected_pad}

    def apply_state(self, state: dict) -> None:
        state = state or {}
        self.seq.from_config(state.get("sequencer"))
        if state.get("kit"):
            self.kit = Kit.from_config(state.get("kit"))
        self.mixer = Mixer.from_config(state.get("mixer"))
        self.chain = Chain.from_config(state.get("chain"))
        self.selected_pad = max(0, min(PADS - 1,
                                       int(state.get("selected_pad", 0))))
        self.kit_rev += 1
        self.pos = 0
        self._sync_mixer()

    def capture(self):
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_state())

    def _sync_mixer(self) -> None:
        """Restate the whole mixer to the internal instrument as CCs — run
        after any state recall, so the sampler never plays yesterday's
        levels under today's project."""
        for pad in range(PADS):
            self._cc(pad, CC_LEVEL, _cc7(self.mixer.levels[pad]))
        self._cc(MASTER_CHANNEL, CC_LEVEL, _cc7(self.mixer.master))
        self._cc(MASTER_CHANNEL, CC_FILTER,
                 int(round(self.mixer.filter * 127)))
        self._cc(MASTER_CHANNEL, CC_DELAY_DIV, self.mixer.delay_div)
        self._cc(MASTER_CHANNEL, CC_REVERB,
                 int(round(self.mixer.reverb * 127)))
        self._cc(MASTER_CHANNEL, CC_DAMP,
                 int(round(self.mixer.damp * 127)))
        self._cc(MASTER_CHANNEL, CC_DUCK,
                 int(round(self.mixer.duck * 127)))

    def _cc(self, channel: int, number: int, value: int) -> None:
        self.midi.send(INTERNAL, MidiEvent(
            EventKind.CC, 0, channel, number,
            max(0, min(127, int(value)))))

    # --- the tick --------------------------------------------------------------
    def on_tick(self, tick: int) -> None:
        if not self.playing:
            return
        for hit in self.seq.hits_at(self.pos):
            self._fire(hit)
        self.pos += 1
        if self.pos >= self.seq.pattern_ticks():
            self.pos = 0
            follow = self.chain.on_pass_end()
            if follow is not None:
                self.seq.queue_pattern(follow)
            self.seq.on_pass_end()

    def _fire(self, hit) -> None:
        if not self.seq.audible(hit.pad):
            return
        if not cond_passes(hit.cond, self.seq.loop, self.seq.fill):
            return
        if hit.prob < 1.0 and self.rng.random() >= hit.prob:
            return
        length = max(1, (STEP_TICKS // hit.ratchet_of) // 2)
        self._emit(hit.pad, hit.vel, length, dict(hit.plocks))

    def _emit(self, pad_index: int, vel: int, length: int,
              locks: dict | None = None) -> None:
        pad = self.kit.pads[pad_index]
        if self.kit.dest == INTERNAL:
            for name, value in (locks or {}).items():
                if name == "tune":
                    self._cc(pad_index, CC_TUNE,
                             round(64 + value / TUNE_RANGE * 63))
                elif name == "filter":
                    self._cc(pad_index, CC_FILTER, round(value * 127))
                elif name == "pan":
                    self._cc(pad_index, CC_PAN, round(64 + value * 63))
            self.send_note(pad_index, pad.note, vel, length,
                           endpoint=INTERNAL)
        else:
            # A shared external channel can't take per-hit CCs without
            # bending every other pad on it; velocity still carries.
            self.send_note(self.kit.channel, pad.note, vel, length,
                           endpoint=self.kit.dest)

    def _release_pad(self, pad_index: int) -> None:
        pad = self.kit.pads[pad_index]
        if self.kit.dest == INTERNAL:
            self.release_channel(pad_index, endpoint=INTERNAL)
        else:
            self.release_note(self.kit.channel, pad.note,
                              endpoint=self.kit.dest)

    def _pad_hit(self, pad_index: int, vel: int) -> None:
        self._emit(pad_index, vel, STEP_TICKS // 2)
        if self.recording and self.playing:
            self.seq.record_hit(self.pos, pad_index, vel)

    # --- transport -------------------------------------------------------------
    def on_play(self) -> None:
        self.pos = 0
        self.seq.reset()
        if self.chain.on:
            first = self.chain.start()
            if first is not None:
                self.seq.switch_now(first)

    def on_stop(self) -> None:
        self.pos = 0

    # --- MIDI in ---------------------------------------------------------------
    def on_midi_in_event(self, endpoint_id: str, event) -> None:
        """An external pad controller: its notes play our pads (and record
        like a finger). Offs are ignored — drums are one-shots."""
        if event.kind is EventKind.NOTE_ON and event.data2 > 0:
            pad = self.kit.pad_for_note(event.data1)
            if pad >= 0:
                self._pad_hit(pad, event.data2)

    # --- pots ------------------------------------------------------------------
    POT_TARGETS = ("master_filter", "swing", "level", "nothing")
    DEFAULT_POT_MAP = {"POT_A": "master_filter", "POT_B": "swing"}

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
        if target == "master_filter":
            self.mixer = replace(self.mixer, filter=value).normalised()
            self._cc(MASTER_CHANNEL, CC_FILTER, int(round(value * 127)))
        elif target == "swing":
            self.seq.set_swing(0.5 + value * 0.25)
        elif target == "level":
            self.mixer = replace(self.mixer, master=value * 1.27) \
                .normalised()
            self._cc(MASTER_CHANNEL, CC_LEVEL, _cc7(self.mixer.master))

    # --- snapshot --------------------------------------------------------------
    def _pattern_view(self) -> tuple:
        pattern = self.seq.pattern()
        if pattern is not self._view_for:
            self._view = tuple(
                tuple(cmd.StepView(on=s.on, vel=s.vel, prob=s.prob,
                                   ratchet=s.ratchet, cond=s.cond,
                                   micro=s.micro, locks=s.plocks)
                      for s in row)
                for row in pattern.rows)
            self._view_for = pattern
        return self._view

    def build_snapshot(self):
        b = super().build_snapshot()
        is_bound = getattr(self.midi, "is_bound", lambda _e: False)
        sounding: dict[int, int] = {}
        for endpoint, channel, note in self._release:
            if endpoint == INTERNAL:
                sounding[channel] = sounding.get(channel, 0) + 1
            elif endpoint == self.kit.dest:
                pad = self.kit.pad_for_note(note)
                if pad >= 0:
                    sounding[pad] = sounding.get(pad, 0) + 1
        pads = tuple(
            cmd.PadView(
                name=pad.name, note=pad.note,
                muted=index in self.seq.mutes,
                soloed=index in self.seq.solos,
                choke=pad.choke, group=pad.group,
                level=self.mixer.levels[index], tune=pad.tune,
                filter=pad.filter, amp=pad.amp, pan=pad.pan,
                delay_send=pad.delay_send, reverb_send=pad.reverb_send,
                duck_key=pad.duck_key,
                has_samples=bool(pad.layers),
                sounding=sounding.get(index, 0))
            for index, pad in enumerate(self.kit.pads))
        pattern = self.seq.pattern()
        return cmd.GrSnapshot(
            playing=b.playing, recording=self.recording, bpm=b.bpm,
            tick=b.tick, bar=b.bar, beat=b.beat, clock_out=b.clock_out,
            backend=b.backend, voices=b.voices, message=b.message,
            pattern=self._pattern_view(),
            pattern_index=self.seq.current,
            queued=-1 if self.seq.queued is None else self.seq.queued,
            patterns_used=tuple(p.used() > 0 for p in self.seq.patterns),
            length=pattern.length, swing=self.seq.swing,
            fill=self.seq.fill, fill_queued=self.seq.fill_queued,
            loop=self.seq.loop,
            step_pos=(self.pos // STEP_TICKS) if self.playing else -1,
            selected_pad=self.selected_pad, pads=pads,
            kit_name=self.kit.name, kit_rev=self.kit_rev,
            dest=self.kit.dest, channel=self.kit.channel,
            dest_bound=bool(is_bound(self.kit.dest)),
            mixer=cmd.MixerView(master=self.mixer.master,
                                filter=self.mixer.filter,
                                delay_div=self.mixer.delay_div,
                                reverb=self.mixer.reverb,
                                damp=self.mixer.damp,
                                duck=self.mixer.duck),
            chain=tuple(tuple(entry) for entry in self.chain.entries),
            chain_on=self.chain.on, chain_position=self.chain.position,
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))


# --- handlers ------------------------------------------------------------------

def _pad_ok(pad: int) -> bool:
    return 0 <= pad < PADS


def _step_ok(step: int) -> bool:
    return 0 <= step < STEPS


def _h_toggle_step(engine, c: cmd.ToggleStep) -> None:
    if _pad_ok(c.pad) and _step_ok(c.step):
        engine.seq.edit(engine.seq.pattern().toggle(c.pad, c.step))


_STEP_FIELDS = ("vel", "prob", "ratchet", "cond", "micro")


def _h_step_field(engine, c: cmd.SetStepField) -> None:
    if not (_pad_ok(c.pad) and _step_ok(c.step)):
        return
    if c.name not in _STEP_FIELDS:
        log.warning("unknown step field %r — ignored", c.name)
        return
    pattern = engine.seq.pattern()
    step = replace(pattern.step(c.pad, c.step), **{c.name: c.value})
    engine.seq.edit(pattern.with_step(c.pad, c.step, step))


def _h_step_lock(engine, c: cmd.SetStepLock) -> None:
    if not (_pad_ok(c.pad) and _step_ok(c.step)):
        return
    pattern = engine.seq.pattern()
    step = pattern.step(c.pad, c.step).lock(c.name, c.value)
    engine.seq.edit(pattern.with_step(c.pad, c.step, step))


def _h_clear_row(engine, c: cmd.ClearRow) -> None:
    if _pad_ok(c.pad):
        engine.seq.edit(engine.seq.pattern().clear_row(c.pad))


def _h_euclid(engine, c: cmd.ApplyEuclid) -> None:
    if _pad_ok(c.pad):
        engine.seq.edit(engine.seq.pattern().euclid_row(
            c.pad, c.pulses, c.rotate))


def _h_length(engine, c: cmd.SetPatternLength) -> None:
    engine.seq.edit(replace(engine.seq.pattern(),
                            length=c.steps).normalised())


def _h_select_pattern(engine, c: cmd.SelectPattern) -> None:
    if not 0 <= c.index < PATTERNS:
        return
    if engine.playing:
        engine.seq.queue_pattern(c.index)
    else:
        engine.seq.switch_now(c.index)


def _h_copy_pattern(engine, c: cmd.CopyPattern) -> None:
    if 0 <= c.src < PATTERNS and 0 <= c.dst < PATTERNS and c.src != c.dst:
        engine.seq.put(c.dst, engine.seq.patterns[c.src])
        engine.message = f"P{c.src + 1} ▸ P{c.dst + 1}"


def _h_swing(engine, c: cmd.SetSwing) -> None:
    engine.seq.set_swing(c.value)


def _h_fill(engine, _c) -> None:
    engine.seq.queue_fill()


def _h_pad_hit(engine, c: cmd.PadHit) -> None:
    if _pad_ok(c.pad):
        engine._pad_hit(c.pad, max(1, min(127, int(c.vel))))


def _h_select_pad(engine, c: cmd.SelectPad) -> None:
    if _pad_ok(c.pad):
        engine.selected_pad = c.pad


def _h_mute(engine, c: cmd.ToggleMute) -> None:
    if not _pad_ok(c.pad):
        return
    if c.pad in engine.seq.mutes:
        engine.seq.mutes.discard(c.pad)
    else:
        engine.seq.mutes.add(c.pad)
        engine._release_pad(c.pad)


def _h_solo(engine, c: cmd.ToggleSolo) -> None:
    if not _pad_ok(c.pad):
        return
    if c.pad in engine.seq.solos:
        engine.seq.solos.discard(c.pad)
    else:
        engine.seq.solos.add(c.pad)
    for pad in range(PADS):
        if not engine.seq.audible(pad):
            engine._release_pad(pad)


def _h_mute_group(engine, c: cmd.MuteGroup) -> None:
    members = [index for index, pad in enumerate(engine.kit.pads)
               if pad.group == c.group and c.group > 0]
    if not members:
        return
    # One press mutes the group; the next lifts it. All-muted = lift.
    lifting = all(pad in engine.seq.mutes for pad in members)
    for pad in members:
        if lifting:
            engine.seq.mutes.discard(pad)
        else:
            engine.seq.mutes.add(pad)
            engine._release_pad(pad)


_PAD_FIELDS = ("name", "note", "choke", "group", "tune", "filter", "amp",
               "pan", "delay_send", "reverb_send", "duck_key")


def _h_pad_field(engine, c: cmd.SetPadField) -> None:
    if not _pad_ok(c.pad):
        return
    if c.name not in _PAD_FIELDS:
        log.warning("unknown pad field %r — ignored", c.name)
        return
    pad = replace(engine.kit.pads[c.pad], **{c.name: c.value})
    engine.kit = engine.kit.with_pad(c.pad, pad)
    engine.kit_rev += 1


def _h_kit_field(engine, c: cmd.SetKitField) -> None:
    if c.name not in ("dest", "channel", "name"):
        log.warning("unknown kit field %r — ignored", c.name)
        return
    engine.all_notes_off()      # the old plumbing keeps nothing sounding
    engine.kit = replace(engine.kit, **{c.name: c.value}).normalised()
    engine.kit_rev += 1


def _h_load_kit(engine, c: cmd.LoadKitState) -> None:
    engine.all_notes_off()
    engine.kit = Kit.from_config(dict(c.params))
    engine.kit_rev += 1
    engine.message = f"KIT {engine.kit.name.upper()}"


def _h_mixer_level(engine, c: cmd.SetMixerLevel) -> None:
    if not _pad_ok(c.pad):
        return
    engine.mixer = engine.mixer.with_level(c.pad, c.value)
    engine._cc(c.pad, CC_LEVEL, _cc7(engine.mixer.levels[c.pad]))


def _h_master_field(engine, c: cmd.SetMasterField) -> None:
    if c.name not in ("master", "filter", "delay_div", "reverb", "damp",
                      "duck"):
        log.warning("unknown master field %r — ignored", c.name)
        return
    engine.mixer = replace(engine.mixer, **{c.name: c.value}).normalised()
    if c.name == "master":
        engine._cc(MASTER_CHANNEL, CC_LEVEL, _cc7(engine.mixer.master))
    elif c.name == "filter":
        engine._cc(MASTER_CHANNEL, CC_FILTER,
                   int(round(engine.mixer.filter * 127)))
    elif c.name == "delay_div":
        engine._cc(MASTER_CHANNEL, CC_DELAY_DIV, engine.mixer.delay_div)
    elif c.name == "reverb":
        engine._cc(MASTER_CHANNEL, CC_REVERB,
                   int(round(engine.mixer.reverb * 127)))
    elif c.name == "damp":
        engine._cc(MASTER_CHANNEL, CC_DAMP,
                   int(round(engine.mixer.damp * 127)))
    elif c.name == "duck":
        engine._cc(MASTER_CHANNEL, CC_DUCK,
                   int(round(engine.mixer.duck * 127)))


def _h_chain_append(engine, c: cmd.ChainAppend) -> None:
    if 0 <= c.pattern < PATTERNS:
        engine.chain.append(c.pattern, c.passes)


def _h_chain_remove(engine, c: cmd.ChainRemove) -> None:
    engine.chain.remove(c.position)


def _h_chain_clear(engine, _c) -> None:
    engine.chain.clear()


def _h_chain_on(engine, c: cmd.SetChainOn) -> None:
    if not c.on:
        engine.chain.stop()
        return
    first = engine.chain.start()
    if first is None:
        engine.message = "CHAIN IS EMPTY"
        return
    if engine.playing:
        engine.seq.queue_pattern(first)
    else:
        engine.seq.switch_now(first)


def _h_project_state(engine, c: cmd.RecallProjectState) -> None:
    engine.all_notes_off()
    engine.apply_state(dict(c.params))


GrooveRangerEngine.HANDLERS = {
    cmd.ToggleStep: _h_toggle_step,
    cmd.SetStepField: _h_step_field,
    cmd.SetStepLock: _h_step_lock,
    cmd.ClearRow: _h_clear_row,
    cmd.ApplyEuclid: _h_euclid,
    cmd.SetPatternLength: _h_length,
    cmd.SelectPattern: _h_select_pattern,
    cmd.CopyPattern: _h_copy_pattern,
    cmd.SetSwing: _h_swing,
    cmd.QueueFill: _h_fill,
    cmd.PadHit: _h_pad_hit,
    cmd.SelectPad: _h_select_pad,
    cmd.ToggleMute: _h_mute,
    cmd.ToggleSolo: _h_solo,
    cmd.MuteGroup: _h_mute_group,
    cmd.SetPadField: _h_pad_field,
    cmd.SetKitField: _h_kit_field,
    cmd.LoadKitState: _h_load_kit,
    cmd.SetMixerLevel: _h_mixer_level,
    cmd.SetMasterField: _h_master_field,
    cmd.ChainAppend: _h_chain_append,
    cmd.ChainRemove: _h_chain_remove,
    cmd.ChainClear: _h_chain_clear,
    cmd.SetChainOn: _h_chain_on,
    cmd.RecallProjectState: _h_project_state,
}
