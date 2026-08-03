"""The SceneRanger engine: the grid, the queues, and the boundaries.

Built on ``rangerkit.enginebase``. What this subclass adds:

* per-track clip playback through per-track launchers — a launch is a
  *queue*, resolved at the launch-quantize boundary ("off" resolves on the
  next drain, which is the <5–10 ms command-to-MIDI path);
* follow actions, evaluated when the active clip completes its loop count,
  drawing probability from the project's seeded rng;
* the slot recorder — input notes land in the armed slot with monitor thru
  to its track's output;
* the scene chain (ARRANGE), stepping on bar lines;
* clock master (the base's 24 ppq out) / slave (external clock source).

Every note-on is booked with its off-tick; clip switches and stops release
the outgoing clip's channel through the book — legato by arithmetic, not
luck. Every engine test ends ``assert not midi.hanging()``.
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, TICKS_PER_BAR

from core import commands as cmd
from core.arrange import Chain
from core.clip import Clip
from core.grid import Grid, SCENES, TRACKS, TrackParams
from core.launcher import NOTHING, QUANTIZE_MODES, TrackLauncher, \
    boundary
from core.recorder import SlotRecorder

log = logging.getLogger("sceneranger.engine")

THRU_SAFETY_TICKS = TICKS_PER_BAR * 16


class SceneRangerEngine(base.RangerEngine):
    """Post commands, feed it MIDI, read snapshots."""

    THREAD_NAME = "sc-engine"
    FREE_RUN = False            # a session player is transport-bound

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.rng = random.Random(project.seed)
        self.grid = Grid()
        self.launchers = [TrackLauncher() for _ in range(TRACKS)]
        self.chain = Chain()
        self.recorder = SlotRecorder()
        self.quantize = "bar"
        self.intensity = 1.0
        self._thru: dict[tuple, tuple] = {}
        self._activity_out: dict[str, int] = {}
        self.apply_state(project.params)

    # --- the state tree --------------------------------------------------------
    def capture_state(self) -> dict:
        return {"grid": self.grid.to_config(),
                "chain": self.chain.to_config(),
                "quantize": self.quantize}

    def apply_state(self, state: dict) -> None:
        state = state or {}
        self.grid = Grid.from_config(state.get("grid"))
        self.chain = Chain.from_config(state.get("chain"))
        mode = str(state.get("quantize", "bar"))
        self.quantize = mode if mode in QUANTIZE_MODES else "bar"
        for launcher in self.launchers:
            launcher.active = launcher.queued = NOTHING

    def capture(self):
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_state())

    # --- MIDI in (the record path) ---------------------------------------------
    def on_midi_in_event(self, endpoint_id: str, event) -> None:
        kind = event.kind
        if kind is EventKind.NOTE_ON and event.data2 > 0:
            self._input_on(event.data1, event.data2)
        elif kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            self._input_off(event.data1)

    def _input_on(self, note: int, velocity: int) -> None:
        if not self.recorder.recording:
            return
        if self.playing:
            self.recorder.note_on(self.tick, note, velocity)
        params = self.grid.tracks[self.recorder.track]
        self.send_note(params.channel, note, velocity, THRU_SAFETY_TICKS,
                       endpoint=params.dest)
        self._thru[(note,)] = ((params.dest, params.channel, note),)

    def _input_off(self, note: int) -> None:
        if self.recorder.recording and self.playing:
            self.recorder.note_off(self.tick, note)
        for dst, channel, out_note in self._thru.pop((note,), ()):
            self.release_note(channel, out_note, endpoint=dst)

    # --- the tick --------------------------------------------------------------
    def on_tick(self, tick: int) -> None:
        at_boundary = boundary(tick, self.quantize)
        if tick > 0 and tick % TICKS_PER_BAR == 0:
            next_scene = self.chain.on_bar()
            if next_scene is not None:
                self._queue_scene(next_scene)
        for track_index, launcher in enumerate(self.launchers):
            params = self.grid.tracks[track_index]
            if at_boundary:
                resolved = launcher.resolve(tick)
                if resolved is not None:
                    # In or out, the previous clip's voice ends here.
                    self.release_channel(params.channel,
                                         endpoint=params.dest)
            slot = launcher.active
            if slot == NOTHING:
                continue
            clip = self.grid.clip(track_index, slot)
            if clip is None:
                launcher.active = NOTHING
                continue
            if launcher.wrapped(tick, clip.length_ticks):
                launcher.loops += 1
                self._follow(track_index, launcher, clip)
                if launcher.active == NOTHING or launcher.queued != NOTHING:
                    continue
            if params.muted:
                continue
            position = launcher.position(tick, clip.length_ticks)
            for note in clip.notes_at(position):
                pitch, velocity = clip.shaped(note, self.intensity)
                self._emit(params, pitch, velocity, note.length_ticks)

    def _follow(self, track_index: int, launcher: TrackLauncher,
                clip: Clip) -> None:
        if clip.follow == "none" or launcher.loops < clip.follow_loops:
            return
        launcher.loops = 0
        if clip.follow_probability < 1.0 \
                and self.rng.random() >= clip.follow_probability:
            return                      # the dice said play on
        slot = launcher.active
        if clip.follow == "again":
            launcher.queue(slot)
        elif clip.follow == "stop":
            launcher.queue_stop()
        elif clip.follow in ("next", "prev"):
            step = 1 if clip.follow == "next" else -1
            for hop in range(1, SCENES):
                candidate = (slot + step * hop) % SCENES
                if self.grid.clip(track_index, candidate) is not None:
                    launcher.queue(candidate)
                    return
        elif clip.follow == "random":
            filled = [s for s in range(SCENES)
                      if self.grid.clip(track_index, s) is not None]
            if filled:
                launcher.queue(self.rng.choice(filled))

    def _queue_scene(self, scene: int) -> None:
        """A scene launch: every filled slot in the row queues; tracks with
        nothing in the row queue a stop — a scene is a *state*, not a
        delta, which is what makes scene 4 sound like scene 4 regardless of
        what was playing."""
        for track_index in range(TRACKS):
            if self.grid.clip(track_index, scene) is not None:
                self.launchers[track_index].queue(scene)
            else:
                self.launchers[track_index].queue_stop()

    def _emit(self, params: TrackParams, pitch: int, velocity: int,
              length: int) -> None:
        self._activity_out[params.dest] = \
            self._activity_out.get(params.dest, 0) + 1
        self.send_note(params.channel, pitch, velocity, length,
                       endpoint=params.dest)

    # --- take boundaries / hygiene ---------------------------------------------
    def _land_take(self) -> None:
        track, scene, clip = self.recorder.land(self.tick)
        if track >= 0:
            self.grid.put(track, scene, clip)

    def panic(self) -> None:
        self._thru.clear()
        self._land_take()
        for launcher in self.launchers:
            launcher.active = launcher.queued = NOTHING
        self.chain.stop()
        super().panic()

    def on_stop(self) -> None:
        self._thru.clear()
        self._land_take()

    # --- pots ------------------------------------------------------------------
    POT_TARGETS = ("quantize", "intensity", "nothing")
    DEFAULT_POT_MAP = {"POT_A": "quantize", "POT_B": "intensity"}

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
        if target == "quantize":
            # The pot sweeps the strength: loose → beat → bar.
            self.quantize = QUANTIZE_MODES[min(
                len(QUANTIZE_MODES) - 1,
                int(value * len(QUANTIZE_MODES)))]
        elif target == "intensity":
            self.intensity = max(0.1, min(1.0, value))

    # --- snapshot --------------------------------------------------------------
    def build_snapshot(self):
        b = super().build_snapshot()
        is_bound = getattr(self.midi, "is_bound", lambda _e: False)
        rows = []
        strips = []
        for track_index in range(TRACKS):
            launcher = self.launchers[track_index]
            params = self.grid.tracks[track_index]
            cells = []
            for scene in range(SCENES):
                clip = self.grid.clip(track_index, scene)
                cells.append(cmd.SlotView(
                    filled=clip is not None,
                    playing=launcher.active == scene,
                    queued=launcher.queued == scene,
                    armed=(self.recorder.track == track_index
                           and self.recorder.scene == scene),
                    bars=clip.bars if clip else 1,
                    follow=clip.follow if clip else "none",
                    follow_loops=clip.follow_loops if clip else 1,
                    follow_probability=(clip.follow_probability
                                        if clip else 1.0),
                    velocity_scale=clip.velocity_scale if clip else 1.0,
                    transpose=clip.transpose if clip else 0,
                    notes=len(clip.notes) if clip else 0))
            rows.append(tuple(cells))
            active_clip = self.grid.clip(track_index, launcher.active) \
                if launcher.active != NOTHING else None
            strips.append(cmd.TrackStripView(
                dest=params.dest, channel=params.channel, muted=params.muted,
                active=launcher.active,
                position=(launcher.position(self.tick,
                                            active_clip.length_ticks)
                          / active_clip.length_ticks)
                if active_clip else 0.0,
                sounding=sum(1 for (endpoint, channel, _n) in self._release
                             if endpoint == params.dest
                             and channel == params.channel)))
        destinations = sorted({p.dest for p in self.grid.tracks})
        return cmd.ScSnapshot(
            playing=b.playing, recording=self.recorder.recording, bpm=b.bpm,
            tick=b.tick, bar=b.bar, beat=b.beat, clock_out=b.clock_out,
            backend=b.backend, voices=b.voices, message=b.message,
            slots=tuple(rows), tracks=tuple(strips),
            scenes_filled=self.grid.filled_scenes(),
            quantize=self.quantize, intensity=self.intensity,
            armed=((self.recorder.track, self.recorder.scene)
                   if self.recorder.recording else ()),
            open_notes=self.recorder.open_notes(),
            chain=tuple((scene, bars) for scene, bars in self.chain.entries),
            chain_on=self.chain.on, chain_position=self.chain.position,
            outputs_bound=tuple((d, bool(is_bound(d)))
                                for d in destinations),
            activity_out=tuple((d, self._activity_out.get(d, 0))
                               for d in destinations),
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))


# --- handlers ------------------------------------------------------------------

def _h_launch_clip(engine, command: cmd.LaunchClip) -> None:
    if not (0 <= command.track < TRACKS and 0 <= command.scene < SCENES):
        return
    if engine.grid.clip(command.track, command.scene) is None:
        return                      # an empty pad is a no-op, not a stop
    engine.launchers[command.track].queue(command.scene)
    if not engine.playing:
        engine.play()               # a launched clip starts the session


def _h_launch_scene(engine, command: cmd.LaunchScene) -> None:
    if not 0 <= command.scene < SCENES:
        return
    engine._queue_scene(command.scene)
    if not engine.playing:
        engine.play()


def _h_stop_track(engine, command: cmd.StopTrack) -> None:
    if 0 <= command.track < TRACKS:
        engine.launchers[command.track].queue_stop()


def _h_stop_all(engine, _command) -> None:
    for launcher in engine.launchers:
        launcher.queue_stop()
    engine.chain.stop()


def _h_quantize(engine, command: cmd.SetLaunchQuantize) -> None:
    if command.mode in QUANTIZE_MODES:
        engine.quantize = command.mode


def _h_intensity(engine, command: cmd.SetIntensity) -> None:
    engine.intensity = max(0.1, min(1.0, float(command.value)))


def _h_arm(engine, command: cmd.ArmSlot) -> None:
    engine._land_take()
    if not (0 <= command.track < TRACKS and 0 <= command.scene < SCENES):
        return
    engine.recorder.arm(command.track, command.scene,
                        engine.grid.clip(command.track, command.scene),
                        engine.tick)
    # Recording wants to be heard: launch the slot too if it has material.
    if engine.grid.clip(command.track, command.scene) is not None:
        engine.launchers[command.track].queue(command.scene)
    if not engine.playing:
        engine.play()


def _h_disarm(engine, _command) -> None:
    engine._land_take()


def _h_clear(engine, command: cmd.ClearClip) -> None:
    params = engine.grid.tracks[command.track] \
        if 0 <= command.track < TRACKS else None
    if params is None:
        return
    if engine.launchers[command.track].active == command.scene:
        engine.launchers[command.track].active = NOTHING
        engine.release_channel(params.channel, endpoint=params.dest)
    engine.grid.put(command.track, command.scene, None)


def _h_clip_field(engine, command: cmd.SetClipField) -> None:
    clip = engine.grid.clip(command.track, command.scene)
    if clip is None:
        return
    if command.name not in Clip.__dataclass_fields__ \
            or command.name in ("notes",):
        log.warning("unknown clip field %r — ignored", command.name)
        return
    engine.grid.put(command.track, command.scene,
                    replace(clip, **{command.name: command.value})
                    .normalised())


def _h_track_field(engine, command: cmd.SetTrackField) -> None:
    if not 0 <= command.track < TRACKS:
        return
    if command.name not in TrackParams.__dataclass_fields__:
        log.warning("unknown track field %r — ignored", command.name)
        return
    was = engine.grid.tracks[command.track]
    updated = replace(was, **{command.name: command.value}).normalised()
    engine.grid.tracks[command.track] = updated
    if command.name in ("dest", "channel") or updated.muted:
        engine.release_channel(was.channel, endpoint=was.dest)


def _h_chain_append(engine, command: cmd.ChainAppend) -> None:
    if 0 <= command.scene < SCENES:
        engine.chain.append(command.scene, command.bars)


def _h_chain_remove(engine, command: cmd.ChainRemove) -> None:
    engine.chain.remove(command.position)


def _h_chain_clear(engine, _command) -> None:
    engine.chain.clear()


def _h_chain_on(engine, command: cmd.SetChainOn) -> None:
    if not command.on:
        engine.chain.stop()
        return
    first = engine.chain.start()
    if first is None:
        engine.message = "CHAIN IS EMPTY"
        return
    engine._queue_scene(first)
    if not engine.playing:
        engine.play()


def _h_project_state(engine, command: cmd.RecallProjectState) -> None:
    engine._land_take()
    engine.all_notes_off()
    engine._thru.clear()
    engine.apply_state(dict(command.params))


SceneRangerEngine.HANDLERS = {
    cmd.LaunchClip: _h_launch_clip,
    cmd.LaunchScene: _h_launch_scene,
    cmd.StopTrack: _h_stop_track,
    cmd.StopAll: _h_stop_all,
    cmd.SetLaunchQuantize: _h_quantize,
    cmd.SetIntensity: _h_intensity,
    cmd.ArmSlot: _h_arm,
    cmd.Disarm: _h_disarm,
    cmd.ClearClip: _h_clear,
    cmd.SetClipField: _h_clip_field,
    cmd.SetTrackField: _h_track_field,
    cmd.ChainAppend: _h_chain_append,
    cmd.ChainRemove: _h_chain_remove,
    cmd.ChainClear: _h_chain_clear,
    cmd.SetChainOn: _h_chain_on,
    cmd.RecallProjectState: _h_project_state,
}
