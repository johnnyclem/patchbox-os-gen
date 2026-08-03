"""The PhraseRanger engine: eight loops, one recorder, and the book.

Built on ``rangerkit.enginebase``. What this subclass adds:

* per-track loop playback — each tick, every unmuted track's phrase is
  consulted at its own loop position (free-length tracks polyrhythm against
  the locked ones), notes emitted through ``send_note`` with probability
  and humanize applied from the project's seeded rng at emit time;
* the record path — input notes from any bound endpoint land in the armed
  track's phrase, with monitor thru to that track's output so the player
  hears the take as it goes down; the take boundary (disarm) pushes undo
  history and applies one feedback decay generation;
* the slicer — pad fires schedule a window of the source phrase from *now*
  (FREE_RUN: pads must fire with the transport stopped, like pads do);
* scenes of complete track states.

The invariant is the family's: every note-on is booked with its off-tick,
and every engine test ends ``assert not midi.hanging()``.
"""
from __future__ import annotations

import heapq
import logging
import random
from dataclasses import replace

from rangerkit import enginebase as base
from rangerkit.events import EventKind, TICKS_PER_BAR

from core import commands as cmd
from core.history import History
from core.phrase import Phrase
from core.recorder import Recorder, humanized
from core.scene import SceneStore
from core.slicer import MODES, PAD_COUNT, pad_caption, pad_phrase, \
    velocity_scale
from core.track import TRACK_COUNT, TrackParams, TrackView, \
    track_from_config, track_to_config

log = logging.getLogger("phraseranger.engine")

# Monitor-thru notes are held by the player; same safety net as MidiRanger.
THRU_SAFETY_TICKS = TICKS_PER_BAR * 16


class _Track:
    """Runtime state for one track. Only the engine thread touches it."""

    __slots__ = ("params", "phrase", "last_wrap")

    def __init__(self, params: TrackParams, phrase: Phrase) -> None:
        self.params = params
        self.phrase = phrase
        self.last_wrap = 0


class PhraseRangerEngine(base.RangerEngine):
    """Post commands, feed it MIDI, read snapshots."""

    THREAD_NAME = "pr-engine"
    FREE_RUN = True             # slice pads and monitor thru outlive stop

    def __init__(self, project, midi, clock=None, config=None) -> None:
        super().__init__(midi, clock, config, bpm=project.bpm)
        self.project = project
        self.rng = random.Random(project.seed)
        self.tracks: list[_Track] = [
            _Track(TrackParams(channel=i).normalised(), Phrase())
            for i in range(TRACK_COUNT)]
        self.global_bars = 1
        self.recorder = Recorder()
        self.history = History()
        self.scenes = SceneStore(project.scenes)
        self.last_touched = 0
        self.slice_source = 0
        self.slice_mode = "slice"
        self._schedule: list = []
        self._sequence = 0
        self._thru: dict[tuple, tuple] = {}
        self._activity_out: dict[str, int] = {}
        self.apply_state(project.params)
        # Play-and-it-records is the first gesture: track 1 is armed from
        # boot, with its pre-take state on the undo stack like any arm.
        self.history.push(0, self.tracks[0].phrase)
        self.recorder.arm(0)

    # --- the state tree --------------------------------------------------------
    def capture_state(self) -> dict:
        return {"tracks": [track_to_config(t.params, t.phrase)
                           for t in self.tracks],
                "global_bars": self.global_bars}

    def apply_state(self, state: dict) -> None:
        state = state or {}
        raw_tracks = state.get("tracks") or []
        for index, track in enumerate(self.tracks):
            if index < len(raw_tracks):
                track.params, track.phrase = track_from_config(
                    raw_tracks[index])
            else:
                track.params = TrackParams(channel=index).normalised()
                track.phrase = Phrase()
        self.global_bars = max(1, int(state.get("global_bars", 1)))
        for track in self.tracks:
            track.phrase = track.phrase.with_length(self._bars_for(track))

    def capture(self):
        return replace(self.project, bpm=self.bpm,
                       params=self.capture_state(),
                       scenes=self.scenes.to_config())

    def _bars_for(self, track: _Track) -> int:
        return self.global_bars if track.params.length_locked \
            else track.params.bars

    # --- MIDI in (the record path) ---------------------------------------------
    def on_midi_in_event(self, endpoint_id: str, event) -> None:
        kind = event.kind
        if kind is EventKind.NOTE_ON and event.data2 > 0:
            self._input_on(event.data1, event.data2)
        elif kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            self._input_off(event.data1)

    def _armed(self) -> _Track | None:
        index = self.recorder.armed
        return self.tracks[index] if 0 <= index < len(self.tracks) else None

    def _loop_tick(self, track: _Track) -> int:
        return self.tick % track.phrase.length_ticks

    def _input_on(self, note: int, velocity: int) -> None:
        track = self._armed()
        if track is None:
            return
        if self.playing:
            self.recorder.note_on(self._loop_tick(track), note, velocity)
        # Monitor thru: the player hears the take on the take's output.
        params = track.params
        self.send_note(params.channel, note, velocity, THRU_SAFETY_TICKS,
                       endpoint=params.dest)
        self._thru[(note,)] = ((params.dest, params.channel, note),)

    def _input_off(self, note: int) -> None:
        track = self._armed()
        if track is not None and self.playing:
            index = self.recorder.armed
            track.phrase = self.recorder.note_off(self._loop_tick(track),
                                                  note, track.phrase)
            self.last_touched = index
        for dst, channel, out_note in self._thru.pop((note,), ()):
            self.release_note(channel, out_note, endpoint=dst)

    # --- the tick --------------------------------------------------------------
    def on_tick(self, tick: int) -> None:
        while self._schedule and self._schedule[0][0] <= tick:
            _due, _seq, dst, channel, note, velocity, length = \
                heapq.heappop(self._schedule)
            self.send_note(channel, note, velocity, length, endpoint=dst)
        if not self.playing:
            return
        for index, track in enumerate(self.tracks):
            params = track.params
            phrase = track.phrase
            position = tick % phrase.length_ticks
            if position == 0 and tick > track.last_wrap:
                track.last_wrap = tick
                self._on_wrap(index, track)
            if params.muted or phrase.empty:
                continue
            for note in phrase.notes_at(position):
                if params.probability < 1.0 \
                        and self.rng.random() >= params.probability:
                    continue
                shaped = humanized(note, self.rng, params.humanize_timing,
                                   params.humanize_velocity)
                offset = shaped.tick - note.tick
                if offset <= 0:
                    self._emit(params, shaped.note, shaped.velocity,
                               shaped.length_ticks)
                else:
                    self._book(offset, params.dest, params.channel,
                               shaped.note, shaped.velocity,
                               shaped.length_ticks)

    def _on_wrap(self, index: int, track: _Track) -> None:
        """A loop boundary on one track. While its take is open and feedback
        is below unity, the old material loses a tape generation."""
        if self.recorder.armed == index and track.params.feedback < 1.0 \
                and self.recorder.overdubbed:
            track.phrase = track.phrase.decayed(track.params.feedback)

    def _emit(self, params: TrackParams, note: int, velocity: int,
              length: int) -> None:
        self._activity_out[params.dest] = \
            self._activity_out.get(params.dest, 0) + 1
        self.send_note(params.channel, note, velocity, length,
                       endpoint=params.dest)

    def _book(self, offset: int, dst: str, channel: int, note: int,
              velocity: int, length: int) -> None:
        self._sequence += 1
        heapq.heappush(self._schedule,
                       (self.tick + offset, self._sequence, dst, channel,
                        note, velocity, length))

    # --- take boundaries -------------------------------------------------------
    def _land_take(self) -> None:
        """Disarm: close open notes into the phrase and push the undo point
        *under* the take (the pre-take phrase was pushed at arm time)."""
        track = self._armed()
        if track is None:
            return
        track.phrase = self.recorder.close_open_notes(
            self._loop_tick(track), track.phrase)
        self.recorder.disarm()

    # --- sweeping the decks ----------------------------------------------------
    def panic(self) -> None:
        self._schedule.clear()
        self._thru.clear()
        self._land_take()
        super().panic()

    def on_stop(self) -> None:
        self._schedule.clear()
        self._thru.clear()
        track = self._armed()
        if track is not None:
            track.phrase = self.recorder.close_open_notes(
                self._loop_tick(track), track.phrase)

    # --- pots ------------------------------------------------------------------
    POT_TARGETS = ("feedback", "density", "humanize", "nothing")
    DEFAULT_POT_MAP = {"POT_A": "feedback", "POT_B": "density"}

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
        focus = self.recorder.armed if self.recorder.armed >= 0 \
            else self.last_touched
        if not 0 <= focus < len(self.tracks):
            return
        track = self.tracks[focus]
        if target == "feedback":
            track.params = replace(track.params,
                                   feedback=value).normalised()
        elif target == "density":
            track.params = replace(track.params,
                                   probability=value).normalised()
        elif target == "humanize":
            track.params = replace(
                track.params,
                humanize_timing=round(value * 12),
                humanize_velocity=round(value * 24)).normalised()

    # --- snapshot --------------------------------------------------------------
    def build_snapshot(self):
        b = super().build_snapshot()
        is_bound = getattr(self.midi, "is_bound", lambda _e: False)
        views = []
        for index, track in enumerate(self.tracks):
            params = track.params
            phrase = track.phrase
            views.append(TrackView(
                dest=params.dest, channel=params.channel, muted=params.muted,
                armed=index == self.recorder.armed,
                probability=params.probability,
                humanize_timing=params.humanize_timing,
                humanize_velocity=params.humanize_velocity,
                length_locked=params.length_locked,
                bars=phrase.bars, feedback=params.feedback,
                notes=len(phrase.notes),
                position=(self.tick % phrase.length_ticks)
                / phrase.length_ticks,
                undo_depth=self.history.depth(index),
                hits=tuple(sorted({round(n.tick / phrase.length_ticks, 3)
                                   for n in phrase.notes}))[:64],
                sounding=sum(1 for (endpoint, channel, _n) in self._release
                             if endpoint == params.dest
                             and channel == params.channel)))
        source = self.tracks[self.slice_source] \
            if 0 <= self.slice_source < len(self.tracks) else self.tracks[0]
        captions = tuple(pad_caption(source.phrase, self.slice_mode, pad)
                         for pad in range(PAD_COUNT))
        filled = tuple(not pad_phrase(source.phrase, self.slice_mode,
                                      pad).empty
                       for pad in range(PAD_COUNT))
        destinations = sorted({t.params.dest for t in self.tracks})
        return cmd.PrSnapshot(
            playing=b.playing, recording=self.recorder.recording, bpm=b.bpm,
            tick=b.tick, bar=b.bar, beat=b.beat, clock_out=b.clock_out,
            backend=b.backend, voices=b.voices, message=b.message,
            tracks=tuple(views), armed=self.recorder.armed,
            quantize=self.recorder.quantize, global_bars=self.global_bars,
            slice_source=self.slice_source, slice_mode=self.slice_mode,
            slice_captions=captions, slice_filled=filled,
            scenes_occupied=self.scenes.occupied(),
            open_notes=self.recorder.open_notes(),
            outputs_bound=tuple((d, bool(is_bound(d)))
                                for d in destinations),
            activity_out=tuple((d, self._activity_out.get(d, 0))
                               for d in destinations),
            project_name=self.project.name,
            pots_map=dict(getattr(getattr(self.config, "pots", None),
                                  "map", {}) or {}))


# --- handlers ------------------------------------------------------------------

def _valid(engine, index: int) -> bool:
    return 0 <= index < len(engine.tracks)


def _h_arm(engine, command: cmd.ArmTrack) -> None:
    engine._land_take()
    if not _valid(engine, command.index):
        return                              # -1 lands the take and disarms
    engine.history.push(command.index,
                        engine.tracks[command.index].phrase)
    engine.recorder.arm(command.index)
    engine.last_touched = command.index


def _h_quantize(engine, command: cmd.SetQuantize) -> None:
    engine.recorder.quantize = bool(command.on)


def _h_undo(engine, command: cmd.UndoTrack) -> None:
    index = command.index if command.index >= 0 else (
        engine.recorder.armed if engine.recorder.armed >= 0
        else engine.last_touched)
    if not _valid(engine, index):
        return
    previous = engine.history.pop(index)
    if previous is None:
        engine.message = "NOTHING TO UNDO"
        return
    track = engine.tracks[index]
    engine.release_channel(track.params.channel,
                           endpoint=track.params.dest)
    track.phrase = previous
    engine.message = f"UNDO T{index + 1}"


def _h_clear(engine, command: cmd.ClearTrack) -> None:
    if not _valid(engine, command.index):
        return
    track = engine.tracks[command.index]
    if track.phrase.empty:
        return
    engine.history.push(command.index, track.phrase)
    engine.release_channel(track.params.channel,
                           endpoint=track.params.dest)
    track.phrase = Phrase(length_ticks=track.phrase.length_ticks)
    engine.last_touched = command.index
    engine.message = f"CLEARED T{command.index + 1}"


def _h_reverse(engine, command: cmd.ReverseTrack) -> None:
    if not _valid(engine, command.index):
        return
    track = engine.tracks[command.index]
    engine.history.push(command.index, track.phrase)
    track.phrase = track.phrase.reversed()
    engine.last_touched = command.index


def _h_stretch(engine, command: cmd.StretchTrack) -> None:
    if not _valid(engine, command.index):
        return
    factor = float(command.factor)
    if factor not in (0.5, 2.0):
        log.warning("stretch factor %r not offered — ignored", factor)
        return
    track = engine.tracks[command.index]
    engine.history.push(command.index, track.phrase)
    track.phrase = track.phrase.stretched(factor)
    engine.last_touched = command.index


def _h_mute(engine, command: cmd.ToggleTrackMute) -> None:
    if not _valid(engine, command.index):
        return
    track = engine.tracks[command.index]
    track.params = replace(track.params, muted=not track.params.muted)
    if track.params.muted:
        engine.release_channel(track.params.channel,
                               endpoint=track.params.dest)


def _h_track_field(engine, command: cmd.SetTrackField) -> None:
    if not _valid(engine, command.index):
        return
    if command.name not in TrackParams.__dataclass_fields__:
        log.warning("unknown track field %r — ignored", command.name)
        return
    track = engine.tracks[command.index]
    was = track.params
    track.params = replace(was, **{command.name: command.value}).normalised()
    if command.name in ("dest", "channel"):
        # Rerouting mid-note: what sounded on the old plumbing is released
        # there, or its note-offs would chase a jack it no longer owns.
        engine.release_channel(was.channel, endpoint=was.dest)
    if command.name in ("length_locked", "bars"):
        track.phrase = track.phrase.with_length(engine._bars_for(track))


def _h_track_bars(engine, command: cmd.SetTrackBars) -> None:
    if not _valid(engine, command.index):
        return
    track = engine.tracks[command.index]
    engine.history.push(command.index, track.phrase)
    track.params = replace(track.params, bars=command.bars,
                           length_locked=False).normalised()
    track.phrase = track.phrase.with_length(track.params.bars)


def _h_global_bars(engine, command: cmd.SetGlobalBars) -> None:
    engine.global_bars = max(1, min(8, int(command.bars)))
    for track in engine.tracks:
        if track.params.length_locked:
            track.phrase = track.phrase.with_length(engine.global_bars)


def _h_slice_source(engine, command: cmd.SelectSliceSource) -> None:
    if _valid(engine, command.index):
        engine.slice_source = command.index


def _h_slice_mode(engine, command: cmd.SetSliceMode) -> None:
    if command.mode in MODES:
        engine.slice_mode = command.mode


def _h_fire_slice(engine, command: cmd.FireSlice) -> None:
    source = engine.tracks[engine.slice_source]
    piece = pad_phrase(source.phrase, engine.slice_mode, command.pad)
    if piece.empty:
        return
    scale = velocity_scale(command.layer)
    params = source.params
    for note in piece.notes:
        velocity = max(1, min(127, round(note.velocity * scale)))
        if note.tick == 0:
            engine._emit(params, note.note, velocity, note.length_ticks)
        else:
            engine._book(note.tick, params.dest, params.channel, note.note,
                         velocity, note.length_ticks)


def _h_save_scene(engine, command: cmd.SaveScene) -> None:
    if engine.scenes.save(command.slot, engine.capture_state()):
        engine.message = f"SCENE {command.slot + 1} SAVED"


def _h_recall_scene(engine, command: cmd.RecallScene) -> None:
    state = engine.scenes.get(command.slot)
    if state is None:
        engine.message = f"SCENE {command.slot + 1} EMPTY"
        return
    engine._land_take()
    engine.all_notes_off()
    engine._schedule.clear()
    engine._thru.clear()
    engine.apply_state(state)
    engine.history.clear()
    engine.message = f"SCENE {command.slot + 1}"


def _h_project_state(engine, command: cmd.RecallProjectState) -> None:
    engine._land_take()
    engine.all_notes_off()
    engine._schedule.clear()
    engine._thru.clear()
    engine.apply_state(dict(command.params))
    engine.history.clear()


PhraseRangerEngine.HANDLERS = {
    cmd.ArmTrack: _h_arm,
    cmd.SetQuantize: _h_quantize,
    cmd.UndoTrack: _h_undo,
    cmd.ClearTrack: _h_clear,
    cmd.ReverseTrack: _h_reverse,
    cmd.StretchTrack: _h_stretch,
    cmd.ToggleTrackMute: _h_mute,
    cmd.SetTrackField: _h_track_field,
    cmd.SetTrackBars: _h_track_bars,
    cmd.SetGlobalBars: _h_global_bars,
    cmd.SelectSliceSource: _h_slice_source,
    cmd.SetSliceMode: _h_slice_mode,
    cmd.FireSlice: _h_fire_slice,
    cmd.SaveScene: _h_save_scene,
    cmd.RecallScene: _h_recall_scene,
    cmd.RecallProjectState: _h_project_state,
}
