"""MIDI output and input, behind one small protocol.

Three backends satisfy ``MidiIO``: mido/python-rtmidi (the ALSA sequencer on
the appliance and on any dev box), a capture backend the tests use to assert
on exact bytes, and a null backend that drops everything.

Degrading to null is deliberate and load-bearing. An appliance whose MIDI
package failed to install should boot, draw its panel, and *say* on the
Settings screen that it has no output — not refuse to start. A silent
instrument you can diagnose beats a black screen every time.

Sends are queued and written by a separate thread. A wedged USB gadget or a
full ALSA pool blocks whoever calls into it, and the one caller that must
never block is the tick thread: a stall there does not drop one note, it bends
the tempo of everything that follows.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from rangerkit.events import EventKind, MidiEvent

log = logging.getLogger("ranger.midi")

try:                                    # pragma: no cover - host dependent
    import mido
except ImportError:
    mido = None                         # type: ignore[assignment]

BACKENDS = ("auto", "mido", "null")
# rtmidi's ALSA names carry " client:port" numbers that change across a
# replug, so ports are matched on the name with those stripped.
_PORT_NUMBERS = re.compile(r"\s\d+:\d+$")
OUTBOX_CAP = 4096
# Note-offs and CC 123 get in even when the queue is over its cap: dropping a
# note-on loses a note, dropping a note-off loses the instrument.
_CRITICAL_CC = (120, 123)


@dataclass(frozen=True, slots=True)
class PortInfo:
    name: str                   # stripped, stable across replug
    raw_name: str               # what the backend wants to open
    is_input: bool = False

    @property
    def client(self) -> str:
        return self.name.partition(":")[0]


def strip_port_numbers(raw: str) -> str:
    return _PORT_NUMBERS.sub("", raw)


@runtime_checkable
class MidiIO(Protocol):
    """What the engine may ask of a backend. Nothing here may block."""

    backend_name: str

    def scan(self) -> list[PortInfo]: ...
    def bind_output(self, endpoint_id: str, port_name: str) -> bool: ...
    def bind_input(self, endpoint_id: str, port_name: str) -> bool: ...
    def unbind(self, endpoint_id: str) -> None: ...
    def is_bound(self, endpoint_id: str) -> bool: ...
    def send(self, endpoint_id: str, event: MidiEvent) -> None: ...
    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None: ...
    def close_all(self) -> None: ...


# --- encoding -----------------------------------------------------------------

def event_to_bytes(event: MidiEvent) -> bytes:
    """Wire encoding, used by the capture backend and by anything that wants
    to assert on what was actually sent rather than on a mido object."""
    channel = event.channel & 0x0F
    if event.kind is EventKind.NOTE_ON:
        return bytes((0x90 | channel, event.data1 & 0x7F, event.data2 & 0x7F))
    if event.kind is EventKind.NOTE_OFF:
        return bytes((0x80 | channel, event.data1 & 0x7F, 0))
    if event.kind is EventKind.CC:
        return bytes((0xB0 | channel, event.data1 & 0x7F, event.data2 & 0x7F))
    if event.kind is EventKind.PROGRAM:
        return bytes((0xC0 | channel, event.data1 & 0x7F))
    if event.kind is EventKind.PITCH_BEND:
        return bytes((0xE0 | channel, event.data1 & 0x7F, event.data2 & 0x7F))
    raise ValueError(f"{event.kind} has no wire encoding")


def event_to_message(event: MidiEvent):     # pragma: no cover - needs mido
    kind = event.kind
    if kind is EventKind.NOTE_ON:
        return mido.Message("note_on", channel=event.channel,
                            note=event.data1, velocity=event.data2)
    if kind is EventKind.NOTE_OFF:
        return mido.Message("note_off", channel=event.channel,
                            note=event.data1, velocity=0)
    if kind is EventKind.CC:
        return mido.Message("control_change", channel=event.channel,
                            control=event.data1, value=event.data2)
    if kind is EventKind.PROGRAM:
        return mido.Message("program_change", channel=event.channel,
                            program=event.data1)
    if kind is EventKind.PITCH_BEND:
        value = ((event.data2 << 7) | event.data1) - 8192
        return mido.Message("pitchwheel", channel=event.channel, pitch=value)
    raise ValueError(f"{kind} has no wire encoding")


def message_to_event(msg) -> MidiEvent | None:   # pragma: no cover
    if msg.type == "note_on":
        return MidiEvent(EventKind.NOTE_ON, 0, msg.channel, msg.note,
                         msg.velocity)
    if msg.type == "note_off":
        return MidiEvent(EventKind.NOTE_OFF, 0, msg.channel, msg.note, 0)
    if msg.type == "control_change":
        return MidiEvent(EventKind.CC, 0, msg.channel, msg.control, msg.value)
    if msg.type == "program_change":
        return MidiEvent(EventKind.PROGRAM, 0, msg.channel, msg.program)
    return None


def is_critical(event: MidiEvent) -> bool:
    """Would dropping this leave the rig in a wrong state, rather than merely
    missing a note?"""
    return (event.kind is EventKind.NOTE_OFF
            or (event.kind is EventKind.CC and event.data1 in _CRITICAL_CC))


# --- backends -----------------------------------------------------------------

class NullMidiIO:
    """Drops everything. The rig is silent and every screen can say so."""

    backend_name = "null"

    def scan(self) -> list[PortInfo]:
        return []

    def bind_output(self, endpoint_id: str, port_name: str) -> bool:
        return False

    def bind_input(self, endpoint_id: str, port_name: str) -> bool:
        return False

    def unbind(self, endpoint_id: str) -> None:
        pass

    def is_bound(self, endpoint_id: str) -> bool:
        return False

    def send(self, endpoint_id: str, event: MidiEvent) -> None:
        pass

    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None:
        pass

    def close_all(self) -> None:
        pass


class CaptureMidiIO(NullMidiIO):
    """Records everything sent. The tests' ears.

    Kept in the production module rather than the test tree because the bench
    scripts and the diagnostics CLI use it too, and because a capture backend
    that drifts from the real encoder is worse than no capture at all.
    """

    backend_name = "capture"

    def __init__(self) -> None:
        self.events: list[tuple[str, MidiEvent]] = []
        self.realtime: list[tuple[str, int, int]] = []

    def send(self, endpoint_id: str, event: MidiEvent) -> None:
        self.events.append((endpoint_id, event))

    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None:
        self.realtime.append((endpoint_id, status, data))

    def is_bound(self, endpoint_id: str) -> bool:
        return True

    # --- assertions the tests read -------------------------------------------
    def notes_on(self, channel: int | None = None) -> list[MidiEvent]:
        return [e for _id, e in self.events
                if e.kind is EventKind.NOTE_ON
                and (channel is None or e.channel == channel)]

    def notes_off(self, channel: int | None = None) -> list[MidiEvent]:
        return [e for _id, e in self.events
                if e.kind is EventKind.NOTE_OFF
                and (channel is None or e.channel == channel)]

    def hanging(self) -> set[tuple[int, int]]:
        """Notes turned on and never turned off — the assertion every engine
        test ends with."""
        held: set[tuple[int, int]] = set()
        for _id, event in self.events:
            key = (event.channel, event.data1)
            if event.kind is EventKind.NOTE_ON:
                held.add(key)
            elif event.kind is EventKind.NOTE_OFF:
                held.discard(key)
            elif event.kind is EventKind.CC and event.data1 in _CRITICAL_CC:
                held = {k for k in held if k[0] != event.channel}
        return held

    def clear(self) -> None:
        self.events.clear()
        self.realtime.clear()


class MidoMidiIO:                       # pragma: no cover - needs a host port
    """mido / python-rtmidi. One instance owns every open port."""

    backend_name = "mido"

    def __init__(self, on_input: Callable[[str, MidiEvent, int], None] | None
                 = None,
                 on_realtime: Callable[[str, int, int, int], None] | None
                 = None) -> None:
        if mido is None:
            raise RuntimeError("mido is not installed")
        self._on_input = on_input
        self._on_realtime = on_realtime
        self._outputs: dict[str, object] = {}
        self._inputs: dict[str, object] = {}
        self._outbox: deque = deque()
        self._wake = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self._writer = threading.Thread(target=self._write_loop,
                                        name="rk-midi-out", daemon=True)
        self._writer.start()

    # --- ports ---------------------------------------------------------------
    def scan(self) -> list[PortInfo]:
        out = [PortInfo(strip_port_numbers(raw), raw, False)
               for raw in mido.get_output_names()]
        out += [PortInfo(strip_port_numbers(raw), raw, True)
                for raw in mido.get_input_names()]
        return out

    def _find(self, port_name: str, inputs: bool) -> str | None:
        names = mido.get_input_names() if inputs else mido.get_output_names()
        wanted = port_name.lower()
        for raw in names:
            if wanted in strip_port_numbers(raw).lower():
                return raw
        return None

    def bind_output(self, endpoint_id: str, port_name: str) -> bool:
        raw = self._find(port_name, inputs=False)
        if raw is None:
            log.warning("no output port matching %r", port_name)
            return False
        self.unbind(endpoint_id)
        try:
            self._outputs[endpoint_id] = mido.open_output(raw)
        except (OSError, IOError) as exc:
            log.warning("cannot open %r: %s", raw, exc)
            return False
        log.info("output %s -> %s", endpoint_id, raw)
        return True

    def bind_input(self, endpoint_id: str, port_name: str) -> bool:
        raw = self._find(port_name, inputs=True)
        if raw is None:
            return False
        self.unbind(endpoint_id)

        def callback(msg, endpoint=endpoint_id):
            import time
            now = time.monotonic_ns()
            if msg.type in ("clock", "start", "stop", "continue"):
                if self._on_realtime is not None:
                    status = {"clock": 0xF8, "start": 0xFA, "continue": 0xFB,
                              "stop": 0xFC}[msg.type]
                    self._on_realtime(endpoint, status, 0, now)
                return
            event = message_to_event(msg)
            if event is not None and self._on_input is not None:
                self._on_input(endpoint, event, now)

        try:
            self._inputs[endpoint_id] = mido.open_input(raw,
                                                        callback=callback)
        except (OSError, IOError) as exc:
            log.warning("cannot open input %r: %s", raw, exc)
            return False
        return True

    def unbind(self, endpoint_id: str) -> None:
        for table in (self._outputs, self._inputs):
            port = table.pop(endpoint_id, None)
            if port is not None:
                try:
                    port.close()
                except Exception:
                    log.debug("close failed for %s", endpoint_id)

    def is_bound(self, endpoint_id: str) -> bool:
        return endpoint_id in self._outputs

    # --- sending -------------------------------------------------------------
    def send(self, endpoint_id: str, event: MidiEvent) -> None:
        if len(self._outbox) >= OUTBOX_CAP and not is_critical(event):
            return
        self._outbox.append((endpoint_id, event, 0, 0))
        self._wake.set()

    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None:
        if len(self._outbox) >= OUTBOX_CAP:
            return
        self._outbox.append((endpoint_id, None, status, data))
        self._wake.set()

    def _write_loop(self) -> None:
        while self._running.is_set():
            if not self._outbox:
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            endpoint_id, event, status, _data = self._outbox.popleft()
            port = self._outputs.get(endpoint_id)
            if port is None:
                continue
            try:
                if event is not None:
                    port.send(event_to_message(event))
                elif status:
                    port.send(mido.Message.from_bytes([status]))
            except Exception:
                log.debug("send failed on %s", endpoint_id)

    def close_all(self) -> None:
        self._running.clear()
        self._wake.set()
        for endpoint_id in list(self._outputs) + list(self._inputs):
            self.unbind(endpoint_id)


def open_midi(on_input: Callable[[str, MidiEvent, int], None] | None = None,
              on_realtime: Callable[[str, int, int, int], None] | None = None,
              backend: str = "auto") -> MidiIO:
    """Open the configured backend, degrading toward null rather than raising."""
    if backend not in BACKENDS:
        log.warning("unknown backend %r; using auto", backend)
        backend = "auto"
    if backend in ("auto", "mido") and mido is not None:
        try:
            return MidoMidiIO(on_input, on_realtime)
        except Exception as exc:        # pragma: no cover
            log.warning("mido backend failed (%s); falling back to null", exc)
    elif backend == "mido":             # pragma: no cover
        log.warning("mido is not installed; falling back to null")
    return NullMidiIO()


def autobind_output(midi: MidiIO, endpoint_id: str,
                    prefer: tuple[str, ...] = ("pisound", "f_midi",
                                               "midi through")) -> str:
    """Bind the first output port matching a preference, in order.

    "pisound" first because on this appliance that is the DIN socket and the
    reason the hardware exists. "Midi Through" is last precisely because it is
    always present and would otherwise win every time and play to nobody.
    """
    ports = [p for p in midi.scan() if not p.is_input]
    for wanted in prefer:
        for port in ports:
            if wanted.lower() in port.name.lower():
                if midi.bind_output(endpoint_id, port.name):
                    return port.name
    for port in ports:
        if midi.bind_output(endpoint_id, port.name):
            return port.name
    return ""
