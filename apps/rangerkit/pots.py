"""The two panel pots, behind one hardware-agnostic service.

The control panel lists two potentiometers, but nothing on the current BOM
can read an analog voltage — Pisound has no ADC and Pimidi is MIDI-only. So
the pots must reach the app either as MIDI CC (a pot board with a micro
speaking USB/TRS MIDI) or through a future daemon that owns whatever ADC
eventually appears. This module commits to the *interface* and keeps every
source swappable in config:

``[pots] source`` is one of:

* ``"midi_cc"`` (default) — the app feeds every incoming CC through
  ``PotsService.on_cc``; the configured controller numbers (CC 20/21 by
  default, any channel) become pot A and B. A LEARN mode captures the next
  CC seen, so any pot hardware that speaks MIDI works with zero repo
  knowledge of it.
* ``"socket"`` — a Unix socket at ``/run/<app>/pots.sock`` speaking one line
  per update: ``POT <index> <raw>`` with raw 0…1023 (plus ``PING`` → ``PONG``).
  The same shape as the button socket on purpose; a future ``patchbox-potsd``
  ADC daemon or a shell loop in the field can drive it.
* ``"none"`` — the panel greys its pot widgets.

Whatever the source, the app sees exactly one thing: a ``PotMove(index,
value)`` command in its engine queue, slew-limited and deduplicated here so
a noisy pot cannot flood the tick thread.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from pathlib import Path

from rangerkit.enginebase import PotMove
from rangerkit.events import EventKind, MidiEvent

log = logging.getLogger("ranger.pots")

SOCKET_NAME = "pots.sock"
SOURCES = ("midi_cc", "socket", "none")
RAW_MAX = 1023
# A 7-bit controller only has 128 positions; forward a move only when it
# travels at least half a code, so a jittery ADC parked between two codes
# does not stream commands forever but every real CC step gets through.
_QUANTUM = 0.5 / 127.0


def socket_path(config) -> Path:
    configured = getattr(config.pots, "socket", "")
    if configured:
        return Path(configured)
    return Path(config.paths.data_dir) / SOCKET_NAME


class PotsService:
    """Turns raw pot input into deduplicated ``PotMove`` commands.

    ``submit`` is the engine's queue entry point. The service never touches
    the engine otherwise, so it can run against a FakeClock rig in tests and
    against nothing at all on a potless bench.
    """

    def __init__(self, submit, config=None,
                 thread_name: str = "rk-pots") -> None:
        self.submit = submit
        pots = getattr(config, "pots", None)
        self.source = getattr(pots, "source", "midi_cc")
        if self.source not in SOURCES:
            log.warning("unknown pots source %r; using none", self.source)
            self.source = "none"
        self.cc = [int(getattr(pots, "cc_a", 20)),
                   int(getattr(pots, "cc_b", 21))]
        self.channel = int(getattr(pots, "channel", -1))    # -1 = omni
        self.learning: int | None = None    # pot index armed for LEARN
        self.on_learned = None              # callback(index, cc) for the GUI
        self._last = [-1.0, -1.0]
        self._thread_name = thread_name
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._path: Path | None = None

    # --- MIDI CC source ------------------------------------------------------
    def on_cc(self, event: MidiEvent) -> None:
        """Feed every incoming CC through here; non-pot CCs fall straight
        through (return False) so the app can use them for its own mapping."""
        if self.source != "midi_cc" or event.kind is not EventKind.CC:
            return False
        if self.channel >= 0 and event.channel != self.channel:
            return False
        if self.learning is not None:
            index, self.learning = self.learning, None
            self.cc[index] = event.data1
            log.info("pot %s learned CC %d", "AB"[index], event.data1)
            if self.on_learned is not None:
                self.on_learned(index, event.data1)
            return True
        if event.data1 not in self.cc:
            return False
        self._move(self.cc.index(event.data1), event.data2 / 127.0)
        return True

    def learn(self, index: int) -> None:
        """Arm LEARN: the next CC seen becomes pot ``index``."""
        if index in (0, 1):
            self.learning = index

    # --- socket source -------------------------------------------------------
    def start_socket(self, path: Path) -> bool:
        """Bind and serve ``POT <index> <raw>`` lines. Returns False when the
        socket cannot be created — a rig with no pots daemon still plays."""
        if self.source != "socket":
            return False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(path))
            sock.listen(2)
            sock.settimeout(0.5)
            os.chmod(path, 0o666)
        except OSError as exc:
            log.warning("pots socket %s unavailable: %s", path, exc)
            return False
        self._sock, self._path = sock, path
        self._running.set()
        self._thread = threading.Thread(target=self._serve,
                                        name=self._thread_name, daemon=True)
        self._thread.start()
        log.info("pots socket listening on %s", path)
        return True

    def stop(self) -> None:
        self._running.clear()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                pass

    def _serve(self) -> None:
        while self._running.is_set() and self._sock is not None:
            try:
                connection, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                try:
                    connection.settimeout(0.5)
                    line = connection.recv(64).decode("utf-8",
                                                      "replace").strip()
                    connection.sendall((self.handle(line) + "\n").encode())
                except (OSError, UnicodeError) as exc:
                    log.debug("pots client failed: %s", exc)

    def handle(self, line: str) -> str:
        """One request line → one reply line. Public for the tests."""
        words = line.strip().upper().split()
        if not words:
            return "ERR empty"
        if words[0] == "PING":
            return "PONG"
        if words[0] == "POT" and len(words) >= 3:
            try:
                index, raw = int(words[1]), int(words[2])
            except ValueError:
                return "ERR not a number"
            if index not in (0, 1):
                return "ERR index"
            self._move(index, max(0, min(RAW_MAX, raw)) / RAW_MAX)
            return "OK"
        return "ERR unknown"

    # --- shared path ---------------------------------------------------------
    def _move(self, index: int, value: float) -> None:
        if index not in (0, 1):
            return
        value = max(0.0, min(1.0, value))
        last = self._last[index]
        if last >= 0 and abs(value - last) < _QUANTUM:
            return
        self._last[index] = value
        self.submit(PotMove(index=index, value=value))


class FakePots(PotsService):
    """The test rig's pots: call ``turn`` and the command lands in the queue
    exactly the way a real source's would."""

    def __init__(self, submit) -> None:
        super().__init__(submit, config=None)
        self.source = "midi_cc"

    def turn(self, index: int, value: float) -> None:
        self._move(index, value)
