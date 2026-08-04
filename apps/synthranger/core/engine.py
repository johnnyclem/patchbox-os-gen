"""The SynthRanger engine: a router in front of an instrument.

Built on ``rangerkit.enginebase``. The synth itself lives behind the
``internal`` endpoint (``core.voices.Synth`` + the shared bridge); this
subclass owns everything that is *state*, not sound:

* note routing — an incoming note on a part's listen channel (or a touch
  key on the selected part) is booked through the release book onto the
  internal endpoint, channel = part index. Note-offs release the booking.
  Stop, panic and part mutes therefore release synth voices through the
  very same machinery that releases external gear — the engine holds no
  reference to the synth, ever;
* the immutable parts tuple and its ``parts_rev`` (the App swaps the
  synth's copy when it moves); continuous performance values (XY, mod
  wheel, cutoff pot) go out immediately as the internal CC contract;
* the project state tree.

``FREE_RUN`` is on — a synthesizer with a stopped "transport" still
sounds; the transport only matters to clock out and the delay's tempo.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, MidiEvent, TICKS_PER_BAR
from rangerkit.routing import INTERNAL

from core import commands as cmd
from core.modmatrix import MOD_DESTS, MOD_SOURCES, ModSlot, SLOTS
from core.parts import PARTS, Part, default_parts
from core.patch import Patch

log = logging.getLogger("synthranger.engine")

THRU_SAFETY_TICKS = TICKS_PER_BAR * 16
CC_MOD_WHEEL, CC_CUTOFF, CC_XY_X, CC_XY_Y = 1, 74, 16, 17


class SynthRangerEngine(base.RangerEngine):
    """Post commands, feed it MIDI, read snapshots; the synth listens on
    ``internal``."""

    THREAD_NAME = "sy-engine"
    FREE_RUN = True

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.parts: tuple = default_parts()
        self.parts_rev = 0
        self.selected_part = 0
        self.xy = (0.5, 0.5)
        self.apply_state(project.params)

    # --- the state tree --------------------------------------------------------
    def capture_state(self) -> dict:
        return {"parts": [part.to_config() for part in self.parts],
                "selected_part": self.selected_part}

    def apply_state(self, state: dict) -> None:
        state = state or {}
        raw = state.get("parts") or []
        parts = [Part.from_config(raw[i]) if i < len(raw)
                 else replace(Part(), channel=i).normalised()
                 for i in range(PARTS)]
        self.parts = tuple(parts)
        self.selected_part = max(0, min(PARTS - 1,
                                        int(state.get("selected_part",
                                                      0))))
        self.parts_rev += 1

    def capture(self):
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_state())

    # --- routing ---------------------------------------------------------------
    def _part_for_channel(self, channel: int) -> int:
        for index, part in enumerate(self.parts):
            if part.channel == channel:
                return index
        return -1

    def _key_on(self, part_index: int, note: int, velocity: int) -> None:
        if self.parts[part_index].muted:
            return
        self.send_note(part_index, note, velocity, THRU_SAFETY_TICKS,
                       endpoint=INTERNAL)

    def _key_off(self, part_index: int, note: int) -> None:
        self.release_note(part_index, note, endpoint=INTERNAL)

    def on_midi_in_event(self, endpoint_id: str, event) -> None:
        kind = event.kind
        if kind is EventKind.NOTE_ON and event.data2 > 0:
            part = self._part_for_channel(event.channel)
            if part >= 0:
                self._key_on(part, event.data1, event.data2)
        elif kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            part = self._part_for_channel(event.channel)
            if part >= 0:
                self._key_off(part, event.data1)
        elif kind is EventKind.CC and event.data1 in (CC_MOD_WHEEL,
                                                      CC_CUTOFF):
            part = self._part_for_channel(event.channel)
            if part >= 0:
                self._cc(part, event.data1, event.data2)

    def _cc(self, channel: int, number: int, value: int) -> None:
        self.midi.send(INTERNAL, MidiEvent(
            EventKind.CC, 0, channel, number,
            max(0, min(127, int(value)))))

    # --- pots ------------------------------------------------------------------
    POT_TARGETS = ("cutoff", "morph", "level", "nothing")
    DEFAULT_POT_MAP = {"POT_A": "cutoff", "POT_B": "morph"}

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
        part = self.selected_part
        if target == "cutoff":
            self._cc(part, CC_CUTOFF, int(round(value * 127)))
        elif target == "morph":
            self._set_part(part, "morph", value)
        elif target == "level":
            self._set_part(part, "level", value * 1.27)

    def _set_part(self, index: int, name: str, value) -> None:
        parts = list(self.parts)
        parts[index] = replace(parts[index], **{name: value}).normalised()
        self.parts = tuple(parts)
        self.parts_rev += 1

    # --- snapshot --------------------------------------------------------------
    def build_snapshot(self):
        b = super().build_snapshot()
        sounding: dict[int, int] = {}
        held = []
        for endpoint, channel, note in self._release:
            if endpoint == INTERNAL:
                sounding[channel] = sounding.get(channel, 0) + 1
                if channel == self.selected_part:
                    held.append(note)
        views = tuple(
            cmd.PartView(
                name=part.patch.name, name_b=part.patch_b.name,
                engine=part.effective().engine, morph=part.morph,
                channel=part.channel, level=part.level, pan=part.pan,
                poly=part.poly, muted=part.muted,
                sounding=sounding.get(index, 0),
                patch=part.effective().to_config(),
                mods=tuple(cmd.ModSlotView(slot.source, slot.dest,
                                           slot.amount)
                           for slot in part.mods))
            for index, part in enumerate(self.parts))
        return cmd.SySnapshot(
            playing=b.playing, recording=b.recording, bpm=b.bpm,
            tick=b.tick, bar=b.bar, beat=b.beat, clock_out=b.clock_out,
            backend=b.backend, voices=b.voices, message=b.message,
            parts=views, parts_rev=self.parts_rev,
            selected_part=self.selected_part, xy=self.xy,
            held_notes=tuple(sorted(held)),
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))


# --- handlers ------------------------------------------------------------------

def _part_ok(index: int) -> bool:
    return 0 <= index < PARTS


def _h_key_down(engine, c: cmd.KeyDown) -> None:
    engine._key_on(engine.selected_part,
                   max(0, min(127, int(c.note))),
                   max(1, min(127, int(c.velocity))))


def _h_key_up(engine, c: cmd.KeyUp) -> None:
    engine._key_off(engine.selected_part, max(0, min(127, int(c.note))))


def _h_xy(engine, c: cmd.SetXY) -> None:
    x = max(0.0, min(1.0, float(c.x)))
    y = max(0.0, min(1.0, float(c.y)))
    engine.xy = (x, y)
    engine._cc(engine.selected_part, CC_XY_X, int(round(x * 127)))
    engine._cc(engine.selected_part, CC_XY_Y, int(round(y * 127)))


def _h_select(engine, c: cmd.SelectPart) -> None:
    if _part_ok(c.part):
        engine.selected_part = c.part


def _h_patch_field(engine, c: cmd.SetPatchField) -> None:
    if not _part_ok(c.part):
        return
    if c.name not in Patch.__dataclass_fields__:
        log.warning("unknown patch field %r — ignored", c.name)
        return
    part = engine.parts[c.part]
    engine._set_part(c.part, "patch",
                     replace(part.patch, **{c.name: c.value}))


_PART_FIELDS = ("morph", "channel", "level", "pan", "poly", "muted")


def _h_part_field(engine, c: cmd.SetPartField) -> None:
    if not _part_ok(c.part):
        return
    if c.name not in _PART_FIELDS:
        log.warning("unknown part field %r — ignored", c.name)
        return
    was = engine.parts[c.part]
    engine._set_part(c.part, c.name, c.value)
    now = engine.parts[c.part]
    if (c.name == "muted" and now.muted) or c.name == "channel":
        engine.release_channel(c.part, endpoint=INTERNAL)
    del was


def _h_mod_slot(engine, c: cmd.SetModSlot) -> None:
    if not (_part_ok(c.part) and 0 <= c.slot < SLOTS):
        return
    if c.source not in MOD_SOURCES or c.dest not in MOD_DESTS:
        log.warning("unknown mod route %r→%r — ignored", c.source,
                    c.dest)
        return
    part = engine.parts[c.part]
    mods = list(part.mods)
    mods[c.slot] = ModSlot(c.source, c.dest, c.amount).normalised()
    engine._set_part(c.part, "mods", tuple(mods))


def _h_patch_state(engine, c: cmd.SetPatchState) -> None:
    if not _part_ok(c.part):
        return
    patch = Patch.from_config(dict(c.params))
    engine._set_part(c.part, "patch_b" if c.slot_b else "patch", patch)
    engine.message = f"{'B' if c.slot_b else 'A'} ▸ {patch.name.upper()}"


def _h_copy_a_to_b(engine, c: cmd.CopyAToB) -> None:
    if not _part_ok(c.part):
        return
    part = engine.parts[c.part]
    engine._set_part(c.part, "patch_b", part.effective())
    engine._set_part(c.part, "morph", 0.0)
    engine.message = "B = CURRENT SOUND"


def _h_project_state(engine, c: cmd.RecallProjectState) -> None:
    engine.all_notes_off()
    engine.apply_state(dict(c.params))


SynthRangerEngine.HANDLERS = {
    cmd.KeyDown: _h_key_down,
    cmd.KeyUp: _h_key_up,
    cmd.SetXY: _h_xy,
    cmd.SelectPart: _h_select,
    cmd.SetPatchField: _h_patch_field,
    cmd.SetPartField: _h_part_field,
    cmd.SetModSlot: _h_mod_slot,
    cmd.SetPatchState: _h_patch_state,
    cmd.CopyAToB: _h_copy_a_to_b,
    cmd.RecallProjectState: _h_project_state,
}
