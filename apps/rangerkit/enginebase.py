"""The shared engine skeleton: one RT thread, commands in, snapshots out.

Every Ranger app's engine has the same spine, extracted here from
ChordRanger's:

1. drain the command queue (GUI, button, pots, MIDI-in — all one queue);
2. if playing, do the app's musical work for this tick (``on_tick``);
3. release every note whose length has run out;
4. emit MIDI clock if it is on;
5. publish an immutable snapshot for the panel.

The invariant that keeps the family honest: **the engine owns every note it
has sent.** Subclasses emit note-ons only through ``send_note``, which books
the off-tick into the release book at the moment the note goes out. A stop, a
mute, a scene change and a panic all work by consulting that book — which is
why none of them can strand a note. Every engine test ends with
``assert not midi.hanging()``.

The base knows nothing about chords, clips, kits or phrases. It knows about
time, notes it has sent, transport, external clock, and the snapshot
handshake. Apps subclass ``RangerEngine`` and implement ``on_tick`` plus a
``HANDLERS`` table for their own commands.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass

from rangerkit.clock import ExternalClock, RealClock, tick_ns
from rangerkit.events import (EventKind, MidiEvent, PPQN, TICKS_PER_BAR,
                              note_off, note_on)

log = logging.getLogger("ranger.engine")

OUT = "out"                     # the default single-output endpoint id
CLOCK_STATUS, START_STATUS, CONTINUE_STATUS, STOP_STATUS = (0xF8, 0xFA, 0xFB,
                                                            0xFC)
# One MIDI clock every four engine ticks: 96 PPQN / 24 PPQ.
CLOCK_DIVISOR = PPQN // 24
COMMAND_QUEUE_MAX = 512
BPM_MIN, BPM_MAX = 20.0, 300.0


# --- base commands -------------------------------------------------------------
# The transport vocabulary every app shares. Apps add their own command
# dataclasses and handlers; these are dispatched by the base so a button
# bridge or a pots service can drive any Ranger without knowing which.

@dataclass(frozen=True, slots=True)
class Play:
    pass


@dataclass(frozen=True, slots=True)
class Stop:
    pass


@dataclass(frozen=True, slots=True)
class TogglePlay:
    pass


@dataclass(frozen=True, slots=True)
class Panic:
    pass


@dataclass(frozen=True, slots=True)
class SetTempo:
    bpm: float


@dataclass(frozen=True, slots=True)
class NudgeTempo:
    delta: float


@dataclass(frozen=True, slots=True)
class SetRecord:
    on: bool


@dataclass(frozen=True, slots=True)
class SetClockOut:
    on: bool


@dataclass(frozen=True, slots=True)
class BindOutput:
    endpoint_id: str
    port_name: str


@dataclass(frozen=True, slots=True)
class BindInput:
    endpoint_id: str
    port_name: str


@dataclass(frozen=True, slots=True)
class UnbindEndpoint:
    endpoint_id: str


@dataclass(frozen=True, slots=True)
class PotMove:
    """A normalized pot position, whatever the hardware behind it was."""

    index: int                  # 0 = pot A, 1 = pot B
    value: float                # 0.0 … 1.0


@dataclass(frozen=True, slots=True)
class BaseSnapshot:
    """The fields every panel needs. Apps define their own richer snapshot;
    this one exists so the base can publish something meaningful before a
    subclass overrides ``build_snapshot``."""

    playing: bool = False
    recording: bool = False
    bpm: float = 120.0
    tick: int = 0
    bar: int = 0
    beat: int = 0
    clock_out: bool = False
    backend: str = "null"
    voices: int = 0
    message: str = ""


class RangerEngine:
    """Start it, post commands, read snapshots. Subclasses implement
    ``on_tick`` (the music) and extend ``HANDLERS`` (the vocabulary)."""

    #: Subclasses replace/extend: ``{CommandType: callable(engine, command)}``
    HANDLERS: dict = {}
    #: Thread name shown in ``ps`` — override per app ("mr-engine", …).
    THREAD_NAME = "rk-engine"

    def __init__(self, midi, clock=None, config=None,
                 bpm: float = 120.0) -> None:
        self.midi = midi
        self.clock = clock if clock is not None else RealClock()
        self.config = config
        self.bpm = float(bpm)
        self.playing = False
        self.recording = False
        self.clock_out = bool(getattr(getattr(config, "midi", None),
                                      "clock_out", False))
        self.tick = 0               # absolute transport tick
        self.message = ""
        self.pots = [0.0, 0.0]      # last normalized pot positions

        self._queue: deque = deque(maxlen=COMMAND_QUEUE_MAX)
        # (endpoint, channel, note) -> absolute off-tick. The book.
        self._release: dict[tuple[str, int, int], int] = {}
        self._channels_used: set[tuple[str, int]] = set()
        self._snapshot = BaseSnapshot()
        self._snapshot_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._external = (ExternalClock(PPQN)
                          if getattr(config, "clock", None) is not None
                          and config.clock.source != "internal" else None)
        self._external_credit = 0

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        """Start the tick thread. The transport is *not* started — the engine
        ticks whether or not it is playing, so a stopped instrument still
        answers the button and still publishes snapshots for the panel."""
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run,
                                        name=self.THREAD_NAME, daemon=True)
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

    def snapshot(self):
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
            # Not fatal, and not silent: an appliance that quietly lost its
            # RT priority sounds subtly worse and nobody knows why.
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
            self._releases()
            self._publish()
            return                  # waiting on the next external pulse
        if self.playing:
            self._external_credit = max(0, self._external_credit - 1)
            self.on_tick(self.tick)
        # on_tick may stop the transport (song end). Re-check rather than
        # emitting clock for a tick that no longer exists.
        if self.playing:
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

    # --- what subclasses implement -------------------------------------------
    def on_tick(self, tick: int) -> None:
        """Do this tick's musical work. Emit notes only via ``send_note``."""

    def on_play(self) -> None:
        """Transport is about to start (tick already positioned)."""

    def on_stop(self) -> None:
        """Transport has stopped and the release book has been emptied."""

    def on_midi_in_event(self, endpoint_id: str, event: MidiEvent) -> None:
        """A channel event arrived (already on the tick thread)."""

    def on_pot(self, index: int, value: float) -> None:
        """A pot moved (already on the tick thread), value normalized 0…1."""

    def build_snapshot(self):
        """Return the immutable snapshot the panel reads. Subclasses build
        their own dataclass; the base publishes transport basics."""
        bar, rest = divmod(self.tick, TICKS_PER_BAR)
        return BaseSnapshot(
            playing=self.playing, recording=self.recording, bpm=self.bpm,
            tick=self.tick, bar=bar, beat=rest // PPQN,
            clock_out=self.clock_out,
            backend=getattr(self.midi, "backend_name", "null"),
            voices=len(self._release), message=self.message)

    # --- transport -----------------------------------------------------------
    def play(self) -> None:
        if self.playing:
            return
        self.on_play()
        self.playing = True
        self.clock.resync()
        if self.clock_out:
            self.midi.send_realtime(OUT, START_STATUS)

    def stop(self) -> None:
        if not self.playing:
            # Second press of stop = return to the top. Cheap, and it is what
            # every transport since tape has done.
            self.tick = 0
            return
        self.playing = False
        self.all_notes_off()
        if self.clock_out:
            self.midi.send_realtime(OUT, STOP_STATUS)
        self.on_stop()

    def panic(self) -> None:
        self.playing = False
        self.all_notes_off()
        self.message = "PANIC"

    # --- the release book ----------------------------------------------------
    def send_note(self, channel: int, note: int, velocity: int,
                  length_ticks: int, endpoint: str = OUT) -> None:
        """The only way a note-on leaves the engine. Books its off-tick."""
        key = (endpoint, channel, note)
        if key in self._release:
            # Retrigger: release first so the receiving synth sees a new
            # attack rather than a stray note-off arriving mid-note later.
            self.midi.send(endpoint, note_off(channel, note))
        self.midi.send(endpoint, note_on(channel, note, velocity))
        self._release[key] = self.tick + max(1, length_ticks)
        self._channels_used.add((endpoint, channel))

    def _releases(self) -> None:
        if not self._release:
            return
        due = [key for key, off in self._release.items() if off <= self.tick]
        for key in due:
            endpoint, channel, note = key
            self.midi.send(endpoint, note_off(channel, note))
            del self._release[key]

    def release_channel(self, channel: int, endpoint: str = OUT) -> None:
        """Kill one channel's notes — what muting a part has to do, since its
        source simply stops producing note-ons and nothing else would ever
        release what is already sounding."""
        for key in [k for k in self._release
                    if k[0] == endpoint and k[1] == channel]:
            self.midi.send(endpoint, note_off(key[1], key[2]))
            del self._release[key]

    def all_notes_off(self) -> None:
        """Release everything the engine is holding, then belt-and-braces
        every (endpoint, channel) it has ever used with CC 123."""
        for (endpoint, channel, note) in tuple(self._release):
            self.midi.send(endpoint, note_off(channel, note))
        self._release.clear()
        for endpoint, channel in sorted(self._channels_used):
            self.midi.send(endpoint,
                           MidiEvent(EventKind.CC, 0, channel, 123, 0))

    def sounding(self) -> int:
        return len(self._release)

    # --- MIDI in -------------------------------------------------------------
    def on_midi_in(self, endpoint_id: str, event: MidiEvent,
                   ts_ns: int) -> None:
        """Called from the backend's callback thread — enqueue only. The
        subclass sees the event on the tick thread via
        ``on_midi_in_event``."""
        self.submit(("midi_in", endpoint_id, event))

    def on_realtime_in(self, endpoint_id: str, status: int, data: int,
                       ts_ns: int) -> None:
        self.submit(("realtime_in", status, data, ts_ns))

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

    def _clock_tick(self) -> None:
        if self.clock_out and self.tick % CLOCK_DIVISOR == 0:
            self.midi.send_realtime(OUT, CLOCK_STATUS)

    # --- command dispatch ----------------------------------------------------
    def _apply(self, command) -> None:
        if isinstance(command, tuple):          # internal MIDI-in envelopes
            if command[0] == "midi_in":
                self.on_midi_in_event(command[1], command[2])
            elif command[0] == "realtime_in":
                self._handle_realtime(*command[1:])
            return
        handler = self.HANDLERS.get(type(command)) \
            or _BASE_HANDLERS.get(type(command))
        if handler is None:
            log.debug("ignoring unknown command %r", command)
            return
        handler(self, command)

    def _publish(self) -> None:
        snapshot = self.build_snapshot()
        with self._snapshot_lock:
            self._snapshot = snapshot


# --- base handlers -------------------------------------------------------------
# A table rather than a chain of isinstance checks: adding a command should be
# one line here and one dataclass there, and the dispatch cost should not grow
# with the vocabulary. App tables are consulted first, so an app may override
# any of these (ChordRanger-style sectioned play, say) without monkeypatching.

def _h_pot(engine: RangerEngine, command: PotMove) -> None:
    index = command.index
    if index not in (0, 1):
        return
    value = max(0.0, min(1.0, float(command.value)))
    engine.pots[index] = value
    engine.on_pot(index, value)


_BASE_HANDLERS = {
    Play: lambda e, _c: e.play(),
    Stop: lambda e, _c: e.stop(),
    TogglePlay: lambda e, _c: e.stop() if e.playing else e.play(),
    Panic: lambda e, _c: e.panic(),
    SetTempo: lambda e, c: (setattr(e, "bpm",
                                    max(BPM_MIN, min(BPM_MAX, float(c.bpm)))),
                            e.clock.resync()),
    NudgeTempo: lambda e, c: setattr(e, "bpm",
                                     max(BPM_MIN,
                                         min(BPM_MAX, e.bpm + c.delta))),
    SetRecord: lambda e, c: setattr(e, "recording", bool(c.on)),
    SetClockOut: lambda e, c: setattr(e, "clock_out", bool(c.on)),
    BindOutput: lambda e, c: e.midi.bind_output(c.endpoint_id, c.port_name),
    BindInput: lambda e, c: e.midi.bind_input(c.endpoint_id, c.port_name),
    UnbindEndpoint: lambda e, c: e.midi.unbind(c.endpoint_id),
    PotMove: _h_pot,
}
