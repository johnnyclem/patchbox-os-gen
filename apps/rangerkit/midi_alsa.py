"""ALSA sequencer MidiIO backend for the Ranger suite.

Same architecture as RK-00pi ``core.midi_alsa`` (ADR-0006): three sequencer
clients so no libasound handle is shared across threads, name-matched binds,
and amidiauto-friendly subscribe (busy/exists treated as success).

Rangerkit's ``MidiIO`` protocol binds by *port name string* (substring match),
not by a structured PortInfo — this module keeps that surface so engines and
routing.autobind need no API change.

``open_alsa_midi()`` returns None when the package or ``/dev/snd/seq`` is
missing; ``open_midi(backend="auto")`` then falls through to mido/rtmidi.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable

from rangerkit.events import EventKind, MidiEvent
from rangerkit.midi_io import OUTBOX_CAP, PortInfo, is_critical, strip_port_numbers

try:                                    # pragma: no cover - host dependent
    import alsa_midi
except ImportError:                     # pragma: no cover
    alsa_midi = None                    # type: ignore[assignment]

log = logging.getLogger("ranger.midi.alsa")

READ_TIMEOUT_S = 0.25
CLIENT_PREFIX = "ranger"                # shown in aconnect -l


def open_alsa_midi(
        on_input: Callable[[str, MidiEvent, int], None] | None = None,
        on_realtime: Callable[[str, int, int, int], None] | None = None,
) -> "AlsaSeqMidiIO | None":
    """AlsaSeqMidiIO, or None when alsa-midi / the sequencer is unavailable."""
    if alsa_midi is None:
        return None
    try:
        return AlsaSeqMidiIO(on_input, on_realtime)
    except Exception as exc:            # no /dev/snd/seq (CI, macOS, …)
        log.info("alsa backend unavailable: %s", exc)
        return None


# --- MidiEvent ↔ alsa_midi ----------------------------------------------------

def event_to_alsa(event: MidiEvent):
    k = event.kind
    if k is EventKind.NOTE_ON:
        return alsa_midi.NoteOnEvent(note=event.data1, channel=event.channel,
                                     velocity=event.data2)
    if k is EventKind.NOTE_OFF:
        return alsa_midi.NoteOffEvent(note=event.data1, channel=event.channel,
                                      velocity=0)
    if k is EventKind.CC:
        return alsa_midi.ControlChangeEvent(channel=event.channel,
                                            param=event.data1,
                                            value=event.data2)
    if k is EventKind.PROGRAM:
        return alsa_midi.ProgramChangeEvent(channel=event.channel,
                                            value=event.data1)
    if k is EventKind.PITCH_BEND:
        value = ((event.data2 << 7) | event.data1) - 8192
        return alsa_midi.PitchBendEvent(channel=event.channel, value=value)
    raise ValueError(f"{k} has no ALSA encoding")


def alsa_to_event(ev) -> MidiEvent | None:
    t = type(ev)
    if t is alsa_midi.NoteOnEvent:
        return MidiEvent(EventKind.NOTE_ON, 0, ev.channel, ev.note, ev.velocity)
    if t is alsa_midi.NoteOffEvent:
        return MidiEvent(EventKind.NOTE_OFF, 0, ev.channel, ev.note, 0)
    if t is alsa_midi.ControlChangeEvent:
        return MidiEvent(EventKind.CC, 0, ev.channel, ev.param, ev.value)
    if t is alsa_midi.ProgramChangeEvent:
        return MidiEvent(EventKind.PROGRAM, 0, ev.channel, ev.value)
    if t is alsa_midi.PitchBendEvent:
        value = ev.value + 8192
        return MidiEvent(EventKind.PITCH_BEND, 0, ev.channel,
                         value & 0x7F, value >> 7)
    return None


def realtime_status(ev) -> tuple[int, int] | None:
    t = type(ev)
    if t is alsa_midi.ClockEvent:
        return 0xF8, 0
    if t is alsa_midi.StartEvent:
        return 0xFA, 0
    if t is alsa_midi.ContinueEvent:
        return 0xFB, 0
    if t is alsa_midi.StopEvent:
        return 0xFC, 0
    if t is alsa_midi.SongPositionPointerEvent:
        return 0xF2, ev.value
    return None


def _parse_addr(raw_name: str) -> tuple[int, int]:
    client, _, port = raw_name.partition(":")
    return int(client), int(port)


def _display_name(client_name: str, port_name: str) -> str:
    """Stable label for matching: ``pimidi0:a``, ``pisound:pisound MIDI PS``."""
    client = strip_port_numbers(client_name).strip()
    port = strip_port_numbers(port_name).strip()
    if port and port.lower() != client.lower():
        return f"{client}:{port}"
    return client or port


class AlsaSeqMidiIO:
    """Three ALSA seq clients; duck-typed to rangerkit.midi_io.MidiIO."""

    backend_name = "alsa"

    def __init__(self,
                 on_input: Callable[[str, MidiEvent, int], None] | None = None,
                 on_realtime: Callable[[str, int, int, int], None] | None
                 = None) -> None:
        if alsa_midi is None:
            raise RuntimeError("alsa_midi is not installed")
        A = alsa_midi
        self._on_input = on_input
        self._on_realtime = on_realtime
        self._in_client = A.SequencerClient(f"{CLIENT_PREFIX}-in")
        self._in_port = self._in_client.create_port(
            "in", caps=A.PortCaps.WRITE | A.PortCaps.SUBS_WRITE,
            type=A.PortType.MIDI_GENERIC | A.PortType.APPLICATION)
        self._out_client = A.SequencerClient(f"{CLIENT_PREFIX}-out")
        self._out_port = self._out_client.create_port(
            "out", caps=A.PortCaps.READ | A.PortCaps.SUBS_READ,
            type=A.PortType.MIDI_GENERIC | A.PortType.APPLICATION)
        self._ctl = A.SequencerClient(f"{CLIENT_PREFIX}-ctl")
        self._own_clients = {self._in_client.client_id,
                             self._out_client.client_id,
                             self._ctl.client_id}
        self._in_addr = (self._in_client.client_id, self._in_port.port_id)
        self._out_addr = (self._out_client.client_id, self._out_port.port_id)
        self._in_client.subscribe_port(A.SYSTEM_ANNOUNCE, self._in_port)
        self._graph_events = frozenset({
            A.EventType.CLIENT_START, A.EventType.CLIENT_EXIT,
            A.EventType.PORT_START, A.EventType.PORT_EXIT,
            A.EventType.PORT_CHANGE})
        self._lock = threading.Lock()
        self._in_subs: dict[str, tuple[int, int]] = {}
        self._out_addrs: dict[str, tuple[int, int]] = {}
        self._by_src: dict[tuple[int, int], frozenset[str]] = {}
        self._by_dest: dict[tuple[int, int], frozenset[str]] = {}
        # name (display) → raw "client:port" id for the last scan
        self._raw_by_name: dict[str, str] = {}
        self._stop = threading.Event()
        self._outbox: deque = deque()
        self._wake = threading.Event()
        self._running = threading.Event()
        self._running.set()
        self._writer = threading.Thread(target=self._write_loop,
                                        name="rk-alsaout", daemon=True)
        self._reader = threading.Thread(target=self._read_loop,
                                        name="rk-alsain", daemon=True)
        self._writer.start()
        self._reader.start()

    # --- scan / match --------------------------------------------------------
    def scan(self) -> list[PortInfo]:
        with self._lock:
            try:
                ins = self._ctl.list_ports(input=True, include_no_export=False)
                outs = self._ctl.list_ports(output=True,
                                            include_no_export=False)
            except (alsa_midi.Error, OSError):
                return []
            ports: list[PortInfo] = []
            raw_map: dict[str, str] = {}
            for alsa_ports, is_input in ((ins, True), (outs, False)):
                for p in alsa_ports:
                    if p.client_id in self._own_clients:
                        continue
                    name = _display_name(p.client_name, p.name)
                    raw = f"{p.client_id}:{p.port_id}"
                    raw_map[name.lower()] = raw
                    ports.append(PortInfo(name=name, raw_name=raw,
                                          is_input=is_input))
            self._raw_by_name = raw_map
            return ports

    def _resolve(self, port_name: str, inputs: bool) -> str | None:
        """Substring match → raw ``client_id:port_id``."""
        # Fresh scan so hotplug is visible without a PortScanner.
        ports = [p for p in self.scan() if p.is_input is inputs]
        wanted = port_name.lower()
        for port in ports:
            if wanted in port.name.lower():
                return port.raw_name
        # Fall back to last scan map (exact key)
        return self._raw_by_name.get(wanted)

    def bind_output(self, endpoint_id: str, port_name: str) -> bool:
        raw = self._resolve(port_name, inputs=False)
        if raw is None:
            log.warning("alsa: no output matching %r", port_name)
            return False
        addr = _parse_addr(raw)
        with self._lock:
            self._unbind_locked(endpoint_id)
            if addr not in self._by_dest:
                try:
                    self._ctl.subscribe_port(self._out_addr, addr)
                except (alsa_midi.Error, OSError) as exc:
                    err = str(exc).lower()
                    if "busy" not in err and "exist" not in err:
                        log.warning("alsa: cannot subscribe out → %s: %s",
                                    raw, exc)
                        return False
            peers = self._by_dest.get(addr, frozenset())
            self._by_dest[addr] = peers | {endpoint_id}
            self._out_addrs[endpoint_id] = addr
        log.info("alsa output %s → %s (%s)", endpoint_id, port_name, raw)
        return True

    def bind_input(self, endpoint_id: str, port_name: str) -> bool:
        raw = self._resolve(port_name, inputs=True)
        if raw is None:
            log.warning("alsa: no input matching %r", port_name)
            return False
        addr = _parse_addr(raw)
        with self._lock:
            self._unbind_locked(endpoint_id)
            if addr not in self._by_src:
                try:
                    self._ctl.subscribe_port(addr, self._in_addr)
                except (alsa_midi.Error, OSError) as exc:
                    err = str(exc).lower()
                    if "busy" not in err and "exist" not in err:
                        log.warning("alsa: cannot subscribe %s → in: %s",
                                    raw, exc)
                        return False
            peers = self._by_src.get(addr, frozenset())
            self._by_src[addr] = peers | {endpoint_id}
            self._in_subs[endpoint_id] = addr
        log.info("alsa input %s → %s (%s)", endpoint_id, port_name, raw)
        return True

    def unbind(self, endpoint_id: str) -> None:
        with self._lock:
            self._unbind_locked(endpoint_id)

    def _unbind_locked(self, endpoint_id: str) -> None:
        dest = self._out_addrs.pop(endpoint_id, None)
        if dest is not None:
            peers = self._by_dest.get(dest, frozenset()) - {endpoint_id}
            if peers:
                self._by_dest[dest] = peers
            else:
                self._by_dest.pop(dest, None)
                try:
                    self._ctl.unsubscribe_port(self._out_addr, dest)
                except (alsa_midi.Error, OSError):
                    pass
        addr = self._in_subs.pop(endpoint_id, None)
        if addr is None:
            return
        peers = self._by_src.get(addr, frozenset()) - {endpoint_id}
        if peers:
            self._by_src[addr] = peers
            return
        self._by_src.pop(addr, None)
        try:
            self._ctl.unsubscribe_port(addr, self._in_addr)
        except (alsa_midi.Error, OSError):
            pass

    def is_bound(self, endpoint_id: str) -> bool:
        return endpoint_id in self._out_addrs

    # --- send ----------------------------------------------------------------
    def send(self, endpoint_id: str, event: MidiEvent) -> None:
        if endpoint_id not in self._out_addrs:
            return
        if len(self._outbox) >= OUTBOX_CAP and not is_critical(event):
            return
        self._outbox.append((endpoint_id, event, 0))
        self._wake.set()

    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None:
        if endpoint_id not in self._out_addrs:
            return
        if len(self._outbox) >= OUTBOX_CAP:
            return
        self._outbox.append((endpoint_id, None, status))
        self._wake.set()

    def _write_loop(self) -> None:
        while self._running.is_set():
            if not self._outbox:
                self._wake.wait(0.05)
                self._wake.clear()
                continue
            endpoint_id, event, status = self._outbox.popleft()
            addr = self._out_addrs.get(endpoint_id)
            if addr is None:
                continue
            try:
                if event is not None:
                    self._out_client.event_output_direct(
                        event_to_alsa(event), port=self._out_port, dest=addr)
                elif status:
                    cls = {0xF8: alsa_midi.ClockEvent,
                           0xFA: alsa_midi.StartEvent,
                           0xFB: alsa_midi.ContinueEvent,
                           0xFC: alsa_midi.StopEvent}.get(status)
                    if cls is not None:
                        self._out_client.event_output_direct(
                            cls(), port=self._out_port, dest=addr)
            except (alsa_midi.Error, OSError):
                log.debug("alsa send failed on %s", endpoint_id)

    def close_all(self) -> None:
        self._running.clear()
        self._wake.set()
        self._stop.set()
        self._reader.join(timeout=2 * READ_TIMEOUT_S + 1.0)
        clients = [self._ctl, self._out_client]
        if self._reader.is_alive():
            log.warning("ALSA reader did not stop; leaving in-client open")
        else:
            clients.append(self._in_client)
        with self._lock:
            for endpoint_id in list(self._out_addrs) + list(self._in_subs):
                self._unbind_locked(endpoint_id)
            for client in clients:
                try:
                    client.close()
                except Exception:
                    pass

    # --- reader --------------------------------------------------------------
    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                ev = self._in_client.event_input(timeout=READ_TIMEOUT_S)
            except Exception:
                if self._stop.is_set():
                    return
                time.sleep(0.05)
                continue
            if ev is None:
                continue
            try:
                self._dispatch(ev, time.monotonic_ns())
            except Exception:
                pass

    def _dispatch(self, ev, ts_ns: int) -> None:
        if getattr(ev, "type", None) in self._graph_events:
            return
        source = getattr(ev, "source", None)
        if source is None:
            return
        endpoints = self._by_src.get((source.client_id, source.port_id))
        if not endpoints:
            return
        rt = realtime_status(ev)
        if rt is not None:
            if self._on_realtime is not None:
                status, data = rt
                for endpoint_id in endpoints:
                    self._on_realtime(endpoint_id, status, data, ts_ns)
            return
        event = alsa_to_event(ev)
        if event is None or self._on_input is None:
            return
        for endpoint_id in endpoints:
            self._on_input(endpoint_id, event, ts_ns)
