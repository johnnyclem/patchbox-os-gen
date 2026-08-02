"""The engine: one RT thread, a command queue in, a snapshot out.

Responsibilities, in the order the tick loop does them:

1. drain commands (the GUI, the PiSound button, MIDI-in — all the same queue);
2. if the song is running, look up the chord and section for this tick;
3. ask the arranger for the notes that start on this tick and send them;
4. release anything whose length has run out;
5. emit MIDI clock if it is on;
6. publish a snapshot, at most once per GUI frame.

The invariant that keeps this honest: **the engine owns every note it has
sent.** Nothing else may emit a note-on, and every note-on is booked into
``_release`` with its off-tick at the moment it goes out. A chord change, a
section switch, a style swap and a panic all work by consulting that book —
which is why none of them can strand a note. The failure mode this design
exists to prevent is a MIDI instrument holding a note forever, which on a
stage is indistinguishable from a broken instrument.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace

from core import commands as cmd
from core.arranger import Arranger, NoteOut
from core.bass import BassSpec
from core.chords import Chord, VoicingSpec, detect_chord, voice
from core.chordset import Chordset, PAD_COUNT
from core.clock import ExternalClock, RealClock, tick_ns
from core.commands import EngineSnapshot, PartView
from core.events import (EventKind, MidiEvent, PPQN,
                         TICKS_PER_BAR, note_off, note_on)
from core.song import ChordStep, Song, quantize_position
from core.style import DRUM_CHANNEL, ENDING, MAIN_A, Style

log = logging.getLogger("chordranger.engine")

OUT = "out"                     # the single output endpoint id
METRONOME_CHANNEL = DRUM_CHANNEL
METRONOME_DOWNBEAT, METRONOME_BEAT = 76, 77     # GM claves
CLOCK_STATUS, START_STATUS, CONTINUE_STATUS, STOP_STATUS = (0xF8, 0xFA, 0xFB,
                                                            0xFC)
# One MIDI clock every four engine ticks: 96 PPQN / 24 PPQ.
CLOCK_DIVISOR = PPQN // 24
COMMAND_QUEUE_MAX = 512
# A chord tapped on a pad is auditioned immediately even when the transport is
# stopped: an instrument you cannot hear without pressing play is a sequencer,
# not an instrument.
AUDITION_VELOCITY = 96


class Engine:
    """The instrument. Start it, post commands, read snapshots."""

    def __init__(self, project, midi, clock=None, config=None) -> None:
        self.project = project
        self.midi = midi
        self.clock = clock if clock is not None else RealClock()
        self.config = config
        self.bpm = project.bpm
        self.playing = False
        self.recording = False
        self.tick = 0                   # absolute transport tick
        self.song_mode = project.song_mode
        self.chordset: Chordset = project.chordset
        self.style: Style = project.style
        self.song: Song = project.song
        self.voicing: VoicingSpec = project.voicing
        self.bass: BassSpec = project.bass
        self.strum = project.strum
        self.latch = project.latch
        self.key_root = project.key_root
        self.scale = project.scale
        self.metronome = project.metronome
        self.clock_out = project.clock_out
        self.arranger = Arranger(self.style, project.section_quantize)
        self.chord: Chord | None = None
        self.held_pad = -1
        self.message = ""

        self._queue: deque = deque(maxlen=COMMAND_QUEUE_MAX)
        self._release: dict[tuple[int, int], int] = {}
        self._audition: tuple[int, ...] = ()
        self._input_notes: set[int] = set()
        self._snapshot = EngineSnapshot()
        self._snapshot_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._late = 0
        self._external = (ExternalClock(PPQN)
                          if getattr(config, "clock", None) is not None
                          and config.clock.source != "internal" else None)
        self._external_credit = 0
        self._last_song_step: tuple[int, int] | None = None

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Start the tick thread. The transport is *not* started — the engine
        ticks whether or not it is playing, so a stopped instrument still
        auditions chords, still answers the button, and still publishes
        snapshots for the panel."""
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="cr-engine",
                                        daemon=True)
        self._thread.start()
        self._request_rt_priority()

    def shutdown(self) -> None:
        self._running.clear()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        self.all_notes_off()

    def submit(self, command) -> None:
        """Post a command from any thread. The queue is bounded: a GUI that
        somehow floods it drops its own oldest requests rather than growing
        without limit under the tick thread's feet."""
        self._queue.append(command)

    def snapshot(self) -> EngineSnapshot:
        with self._snapshot_lock:
            return self._snapshot

    def _request_rt_priority(self) -> None:
        priority = getattr(getattr(self.config, "engine", None),
                           "rt_priority", 0) or 0
        if priority <= 0:
            return
        try:
            import os
            os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
            log.info("engine thread at SCHED_FIFO %d", priority)
        except (AttributeError, OSError, PermissionError) as exc:
            # Not fatal, and not silent: an appliance that quietly lost its RT
            # priority sounds subtly worse and nobody knows why.
            log.warning("no RT priority (%s) — running SCHED_OTHER", exc)

    # --- tick loop -----------------------------------------------------------
    def _run(self) -> None:
        while self._running.is_set():
            self.clock.wait_for_tick(tick_ns(self.bpm, PPQN))
            try:
                self.step()
            except Exception:           # pragma: no cover - last-resort net
                # A raise here would take the music with it. Log, kill the
                # sounding notes so nothing is stranded, and keep ticking.
                log.exception("engine tick failed")
                self.all_notes_off()

    def step(self) -> None:
        """One engine tick. Public because the tests drive it directly with a
        FakeClock — the same code path playback uses, never a simulation."""
        self._drain()
        if self._external is not None and self._external_credit <= 0 \
                and self.playing:
            return                      # waiting on the next external pulse
        if self.playing:
            self._external_credit = max(0, self._external_credit - 1)
            self._song_tick()
        # The song track can end the tune from inside _song_tick. Re-check
        # rather than playing one more tick's notes after the transport has
        # already released everything — that is exactly how a stop leaves a
        # chord hanging.
        if self.playing:
            self._play_tick()
            self._metronome_tick()
            self._clock_tick()
            self.tick += 1
        self._releases()
        self._publish()

    def _drain(self) -> None:
        while self._queue:
            try:
                self._apply(self._queue.popleft())
            except Exception:           # pragma: no cover
                log.exception("command failed")

    # --- transport -----------------------------------------------------------
    def play(self, section: str = "") -> None:
        if self.playing:
            return
        self.tick = 0 if not self.song_mode else self.tick
        self.arranger.style = self.style
        self.arranger.start(section)
        if self.song_mode:
            self._last_song_step = None
            marker = self.song.section_at(self.tick // TICKS_PER_BAR)
            if marker:
                self.arranger.start(marker)
            chord = self.song.chord_at(self.tick // TICKS_PER_BAR)
            if chord is not None:
                self.chord = chord
        if self.chord is None:
            self.chord = self.chordset.chord_at(0) or Chord()
        self.playing = True
        self.clock.resync()
        self._stop_audition()
        if self.clock_out:
            self.midi.send_realtime(OUT, START_STATUS)

    def stop(self) -> None:
        if not self.playing:
            # Second press of stop = return to the top. Cheap, and it is what
            # every transport since tape has done.
            self.tick = 0
            self.arranger.start()
            return
        self.playing = False
        self.all_notes_off()
        if self.clock_out:
            self.midi.send_realtime(OUT, STOP_STATUS)

    def all_notes_off(self) -> None:
        """Release everything the engine is holding, then belt-and-braces the
        channels it uses with CC 123."""
        for (channel, note) in tuple(self._release):
            self.midi.send(OUT, note_off(channel, note))
        self._release.clear()
        self._audition = ()
        channels = {p.channel for p in self.style.parts} | {METRONOME_CHANNEL}
        for channel in sorted(channels):
            self.midi.send(OUT, MidiEvent(EventKind.CC, 0, channel, 123, 0))

    # --- playback ------------------------------------------------------------
    def _song_tick(self) -> None:
        """Apply the song's chord and section changes for this tick."""
        if not self.song_mode or self.song.empty:
            return
        bar, rest = divmod(self.tick, TICKS_PER_BAR)
        beat = rest // PPQN
        if rest % PPQN:
            return                      # changes land on beats, not between
        if self.song.loop and bar >= self.song.bars:
            self.tick = 0
            bar, beat = 0, 0
            self._last_song_step = None
        elif bar >= self.song.bars:
            self.stop()
            return
        position = (bar, beat)
        if position == self._last_song_step:
            return
        self._last_song_step = position
        step = self.song.step_at(bar, beat)
        if step is None or (step.bar, step.beat) != position:
            return
        if step.section:
            self.arranger.request(step.section)
        self.chord = step.chord

    def _play_tick(self) -> None:
        if self.chord is None:
            return
        nxt = self._next_chord()
        notes = self.arranger.step(self.chord, nxt, self.voicing, self.bass,
                                   self.scale, self.key_root, self.strum)
        for item in notes:
            self._send_note(item)
        if self.arranger.stopped:
            self.playing = False
            self.all_notes_off()
            if self.clock_out:
                self.midi.send_realtime(OUT, STOP_STATUS)

    def _next_chord(self) -> Chord | None:
        """What the bass should walk toward. In song mode that is written
        down; live it is unknowable, so the walk resolves to the current
        chord's own root and simply does not lead anywhere."""
        if self.song_mode and not self.song.empty:
            bar, rest = divmod(self.tick, TICKS_PER_BAR)
            return self.song.next_chord_after(bar, rest // PPQN)
        return None

    def _send_note(self, item: NoteOut) -> None:
        key = (item.channel, item.note)
        if key in self._release:
            # Retrigger: release first so the receiving synth sees a new
            # attack rather than a note-off arriving mid-note later.
            self.midi.send(OUT, note_off(item.channel, item.note))
        self.midi.send(OUT, note_on(item.channel, item.note, item.velocity))
        self._release[key] = self.tick + max(1, item.length)

    def _release_channel(self, channel: int) -> None:
        """Kill one channel's notes — what muting a part has to do, since its
        phrase simply stops producing note-ons and nothing else would ever
        release what is already sounding."""
        for key in [k for k in self._release if k[0] == channel]:
            self.midi.send(OUT, note_off(*key))
            del self._release[key]

    def _send_programs(self) -> None:
        """Send each part's program change and level. Only for parts that ask:
        ``program`` -1 means the player has dialled their own sound in and
        would not thank us for overwriting it."""
        for part in self.style.parts:
            if part.program >= 0:
                self.midi.send(OUT, MidiEvent(EventKind.PROGRAM, 0,
                                              part.channel, part.program))
            if 0 <= part.level <= 127:
                self.midi.send(OUT, MidiEvent(EventKind.CC, 0, part.channel,
                                              7, part.level))

    def _releases(self) -> None:
        if not self._release:
            return
        due = [key for key, off in self._release.items() if off <= self.tick]
        for key in due:
            channel, note = key
            self.midi.send(OUT, note_off(channel, note))
            del self._release[key]

    def _metronome_tick(self) -> None:
        if not self.metronome:
            return
        rest = self.tick % TICKS_PER_BAR
        if rest % PPQN:
            return
        note = METRONOME_DOWNBEAT if rest == 0 else METRONOME_BEAT
        self.midi.send(OUT, note_on(METRONOME_CHANNEL, note,
                                    110 if rest == 0 else 80))
        self._release[(METRONOME_CHANNEL, note)] = self.tick + PPQN // 8

    def _clock_tick(self) -> None:
        if self.clock_out and self.tick % CLOCK_DIVISOR == 0:
            self.midi.send_realtime(OUT, CLOCK_STATUS)

    # --- chords --------------------------------------------------------------
    def set_chord(self, chord: Chord | None, audition: bool = True) -> None:
        """The current chord changed. When stopped, audition it so the panel
        is an instrument; when playing, the arranger picks it up on the next
        tick and the audition would just double the chord part."""
        self.chord = chord
        if not audition or chord is None:
            return
        if self.playing:
            self._stop_audition()
            return
        self._audition_chord(chord)

    def _audition_chord(self, chord: Chord) -> None:
        part = next((p for p in self.style.parts if p.role == "chord"), None)
        channel = part.channel if part else 0
        notes = voice(chord, self.voicing, self._audition)
        self._stop_audition()
        for note in notes:
            self.midi.send(OUT, note_on(channel, note, AUDITION_VELOCITY))
        self._audition = tuple(notes)
        self._audition_channel = channel

    def _stop_audition(self) -> None:
        channel = getattr(self, "_audition_channel", 0)
        for note in self._audition:
            self.midi.send(OUT, note_off(channel, note))
        self._audition = ()

    def _pad_down(self, index: int) -> None:
        chord = self.chordset.chord_at(index)
        if chord is None:
            return
        self.held_pad = index
        self.set_chord(chord)
        if self.recording and self.playing:
            bar, beat = quantize_position(self.tick)
            self.song = self.song.with_step(
                ChordStep(bar=bar, beat=beat, chord=chord))

    def _pad_up(self, index: int) -> None:
        if self.held_pad != index:
            return
        self.held_pad = -1
        if not self.latch:
            self._stop_audition()
            if not self.playing:
                self.chord = None

    # --- MIDI in -------------------------------------------------------------
    def on_midi_in(self, endpoint_id: str, event: MidiEvent,
                   ts_ns: int) -> None:
        """Called from the backend's callback thread — enqueue only.

        Chord recognition happens on the tick thread because it mutates the
        held-note set, and a keyboard's note-ons arrive on whichever thread
        the driver felt like using.
        """
        self.submit(("midi_in", event))

    def on_realtime_in(self, endpoint_id: str, status: int, data: int,
                       ts_ns: int) -> None:
        self.submit(("realtime_in", status, data, ts_ns))

    def _handle_midi_in(self, event: MidiEvent) -> None:
        if event.kind is EventKind.NOTE_ON and event.data2 > 0:
            self._input_notes.add(event.data1)
        elif event.kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            self._input_notes.discard(event.data1)
        else:
            return
        if len(self._input_notes) >= 2:
            chord = detect_chord(tuple(sorted(self._input_notes)))
            if chord is not None:
                self.set_chord(chord)
        elif not self._input_notes and not self.latch:
            self.set_chord(None)

    def _handle_realtime(self, status: int, data: int, ts_ns: int) -> None:
        if self._external is None:
            return
        if status == CLOCK_STATUS:
            self._external_credit += self._external.on_pulse(ts_ns)
            bpm = self._external.bpm
            if bpm is not None:
                self.bpm = round(bpm, 1)
        elif status in (START_STATUS, CONTINUE_STATUS):
            self._external.reset()
            if status == START_STATUS:
                self.tick = 0
            self.play()
        elif status == STOP_STATUS:
            self.stop()

    # --- command dispatch ----------------------------------------------------
    def _apply(self, command) -> None:
        if isinstance(command, tuple):          # internal MIDI-in envelopes
            if command[0] == "midi_in":
                self._handle_midi_in(command[1])
            elif command[0] == "realtime_in":
                self._handle_realtime(*command[1:])
            return
        handler = _HANDLERS.get(type(command))
        if handler is None:
            log.debug("ignoring unknown command %r", command)
            return
        handler(self, command)

    # --- snapshot ------------------------------------------------------------
    def _publish(self) -> None:
        state = self.arranger.state()
        bar, rest = divmod(self.tick, TICKS_PER_BAR)
        chord = self.chord
        parts = tuple(
            PartView(id=p.id, name=p.name, role=p.role, channel=p.channel,
                     muted=p.muted, velocity=p.velocity, octave=p.octave,
                     active=sum(1 for (channel, _n) in self._release
                                if channel == p.channel))
            for p in self.style.parts)
        nxt = self._next_chord()
        snapshot = EngineSnapshot(
            playing=self.playing, recording=self.recording, bpm=self.bpm,
            tick=self.tick, bar=bar, beat=rest // PPQN,
            section=state.section, next_section=state.next_section,
            section_bar=state.bar, section_bars=state.bars,
            chord_symbol=chord.symbol() if chord else "—", chord=chord,
            next_chord_symbol=nxt.symbol() if nxt else "",
            held_pad=self.held_pad, latch=self.latch,
            key_root=self.key_root, scale=self.scale,
            style_name=self.style.name, chordset_name=self.chordset.name,
            pad_captions=tuple(self.chordset.caption(i)
                               for i in range(PAD_COUNT)),
            pad_numerals=tuple(self.chordset.numeral(i)
                               for i in range(PAD_COUNT)),
            pad_active=tuple(i == self.held_pad for i in range(PAD_COUNT)),
            pad_chords=tuple(self.chordset.chord_at(i)
                             for i in range(PAD_COUNT)),
            parts=parts, voicing=self.voicing, bass=self.bass,
            strum=self.strum, song_mode=self.song_mode,
            song_bar=bar, song_bars=self.song.bars, song_name=self.song.name,
            song_bars_view=self._song_view(),
            chord_notes=voice(chord, self.voicing) if chord else (),
            metronome=self.metronome, clock_out=self.clock_out,
            backend=getattr(self.midi, "backend_name", "null"),
            output_bound=getattr(self.midi, "is_bound", lambda _e: False)(OUT),
            voices=len(self._release), late_ticks=self._late,
            message=self.message)
        with self._snapshot_lock:
            self._snapshot = snapshot

    def _song_view(self) -> tuple:
        """The song flattened to one ``(chord, marker, is_change)`` per bar.

        ``is_change`` is what lets the Song screen distinguish a bar where the
        chord was *written* from a bar that merely inherits it — without which
        a two-chord song looks like sixteen bars of the second chord. Bars
        past the song's length answer ``(None, "", False)``: they are the
        empty space you write the next section into, not more of the tune.

        Bounded to a screenful past the song so a long arrangement does not
        rebuild a thousand-entry tuple every frame.
        """
        span = max(16, min(256, self.song.bars))
        changes = {(s.bar, s.section) for s in self.song.steps}
        starts = {s.bar for s in self.song.steps if s.beat == 0}
        out = []
        for bar in range(span):
            if bar >= self.song.bars:
                out.append((None, "", False))
                continue
            marker = next((section for at, section in changes
                           if at == bar and section), "")
            out.append((self.song.chord_at(bar), marker, bar in starts))
        return tuple(out)

    # --- project -------------------------------------------------------------
    def capture(self):
        """Fold live state back into a project value for saving. The engine is
        the authority while it runs, so the saved file is built from it rather
        than from the project object it booted with."""
        return replace(self.project, bpm=self.bpm, chordset=self.chordset,
                       style=self.style, song=self.song, voicing=self.voicing,
                       bass=self.bass, strum=self.strum, latch=self.latch,
                       key_root=self.key_root, scale=self.scale,
                       song_mode=self.song_mode, metronome=self.metronome,
                       clock_out=self.clock_out)


# --- handlers -----------------------------------------------------------------
# A table rather than a chain of isinstance checks: adding a command should be
# one line here and one dataclass there, and the dispatch cost should not grow
# with the vocabulary.

def _h_play(engine: Engine, command: cmd.Play) -> None:
    engine.play(command.section)


def _h_stop(engine: Engine, _command) -> None:
    engine.stop()


def _h_toggle(engine: Engine, _command) -> None:
    engine.stop() if engine.playing else engine.play()


def _h_panic(engine: Engine, _command) -> None:
    engine.playing = False
    engine.all_notes_off()
    engine.message = "PANIC"


def _h_tempo(engine: Engine, command: cmd.SetTempo) -> None:
    engine.bpm = max(20.0, min(300.0, float(command.bpm)))
    engine.clock.resync()


def _h_nudge(engine: Engine, command: cmd.NudgeTempo) -> None:
    engine.bpm = max(20.0, min(300.0, engine.bpm + command.delta))


def _h_metronome(engine: Engine, command: cmd.SetMetronome) -> None:
    engine.metronome = command.on


def _h_pad_down(engine: Engine, command: cmd.PadDown) -> None:
    engine._pad_down(command.index)


def _h_pad_up(engine: Engine, command: cmd.PadUp) -> None:
    engine._pad_up(command.index)


def _h_set_chord(engine: Engine, command: cmd.SetChord) -> None:
    engine.set_chord(command.chord)


def _h_latch(engine: Engine, command: cmd.SetLatch) -> None:
    engine.latch = command.on
    if not command.on and engine.held_pad < 0 and not engine.playing:
        engine._stop_audition()


def _h_key(engine: Engine, command: cmd.SetKey) -> None:
    engine.key_root = command.root % 12
    if command.scale:
        engine.scale = command.scale


def _h_transpose_set(engine: Engine, command: cmd.TransposeChordset) -> None:
    engine.chordset = engine.chordset.transposed(command.semitones)
    engine.key_root = engine.chordset.root


def _h_chordset(engine: Engine, command: cmd.SetChordset) -> None:
    engine.chordset = command.chordset
    engine.key_root = command.chordset.root
    engine.scale = command.chordset.scale


def _h_set_pad(engine: Engine, command: cmd.SetPad) -> None:
    engine.chordset = engine.chordset.with_chord(command.index, command.chord)


def _h_transpose_pad(engine: Engine, command: cmd.TransposePad) -> None:
    engine.chordset = engine.chordset.transposed_pad(command.index,
                                                     command.semitones)


def _h_section(engine: Engine, command: cmd.RequestSection) -> None:
    if not engine.playing and command.name != ENDING:
        # Asking for a section while stopped starts there — the same button
        # means "go" and "go *there*", which is how the QY behaves and how a
        # player expects one button to work.
        engine.play(command.name)
        return
    engine.arranger.request(command.name)


def _h_style(engine: Engine, command: cmd.SetStyle) -> None:
    engine.style = command.style
    engine.arranger.style = command.style
    engine.arranger._invalidate()
    if not engine.style.has(engine.arranger.section):
        engine.arranger.section = MAIN_A
    # A style swap changes channels and programs under sounding notes.
    engine.all_notes_off()
    engine._send_programs()


def _h_voicing(engine: Engine, command: cmd.SetVoicing) -> None:
    engine.voicing = command.spec
    if not engine.playing and engine.chord is not None:
        engine._audition_chord(engine.chord)


def _h_bass(engine: Engine, command: cmd.SetBass) -> None:
    engine.bass = command.spec.normalised()


def _h_strum(engine: Engine, command: cmd.SetStrum) -> None:
    engine.strum = max(0, min(24, command.ticks))


def _h_part_mute(engine: Engine, command: cmd.SetPartMute) -> None:
    part = engine.style.part(command.part_id)
    if part is None:
        return
    engine.style = engine.style.with_part(replace(part, muted=command.muted))
    engine.arranger.style = engine.style
    engine.arranger._invalidate()
    if command.muted:
        engine._release_channel(part.channel)


def _h_part_field(engine: Engine, command: cmd.SetPartField) -> None:
    part = engine.style.part(command.part_id)
    if part is None or command.field not in ("octave", "velocity", "channel",
                                             "level", "program"):
        return
    limits = {"octave": (-3, 3), "velocity": (1, 127), "channel": (0, 15),
              "level": (0, 127), "program": (-1, 127)}
    low, high = limits[command.field]
    value = max(low, min(high, command.value))
    engine.style = engine.style.with_part(
        replace(part, **{command.field: value}))
    engine.arranger.style = engine.style
    engine.arranger._invalidate()


def _h_song_mode(engine: Engine, command: cmd.SetSongMode) -> None:
    engine.song_mode = command.on
    engine._last_song_step = None


def _h_song(engine: Engine, command: cmd.SetSong) -> None:
    engine.song = command.song
    engine._last_song_step = None


def _h_write_step(engine: Engine, command: cmd.WriteChordStep) -> None:
    engine.song = engine.song.with_step(command.step)
    engine._last_song_step = None


def _h_erase_step(engine: Engine, command: cmd.EraseChordStep) -> None:
    engine.song = engine.song.without_step(command.bar, command.beat)


def _h_record(engine: Engine, command: cmd.SetRecord) -> None:
    engine.recording = command.on


def _h_locate(engine: Engine, command: cmd.Locate) -> None:
    engine.tick = max(0, command.bar) * TICKS_PER_BAR
    engine._last_song_step = None
    engine.all_notes_off()


def _h_bind(engine: Engine, command: cmd.BindOutput) -> None:
    engine.midi.bind_output(command.endpoint_id, command.port_name)


def _h_unbind(engine: Engine, command: cmd.UnbindOutput) -> None:
    engine.midi.unbind(command.endpoint_id)


def _h_clock_out(engine: Engine, command: cmd.SetClockOut) -> None:
    engine.clock_out = command.on


_HANDLERS = {
    cmd.Play: _h_play, cmd.Stop: _h_stop, cmd.TogglePlay: _h_toggle,
    cmd.Panic: _h_panic, cmd.SetTempo: _h_tempo, cmd.NudgeTempo: _h_nudge,
    cmd.SetMetronome: _h_metronome, cmd.PadDown: _h_pad_down,
    cmd.PadUp: _h_pad_up, cmd.SetChord: _h_set_chord, cmd.SetLatch: _h_latch,
    cmd.SetKey: _h_key, cmd.TransposeChordset: _h_transpose_set,
    cmd.SetChordset: _h_chordset, cmd.SetPad: _h_set_pad,
    cmd.TransposePad: _h_transpose_pad, cmd.RequestSection: _h_section,
    cmd.SetStyle: _h_style, cmd.SetVoicing: _h_voicing, cmd.SetBass: _h_bass,
    cmd.SetStrum: _h_strum, cmd.SetPartMute: _h_part_mute,
    cmd.SetPartField: _h_part_field, cmd.SetSongMode: _h_song_mode,
    cmd.SetSong: _h_song, cmd.WriteChordStep: _h_write_step,
    cmd.EraseChordStep: _h_erase_step, cmd.SetRecord: _h_record,
    cmd.Locate: _h_locate, cmd.BindOutput: _h_bind,
    cmd.UnbindOutput: _h_unbind, cmd.SetClockOut: _h_clock_out,
}
