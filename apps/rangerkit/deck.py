"""Display handover between the RangerDeck launcher and a Ranger app.

One panel, one DRM master. The launcher and the apps therefore never hold
the display at the same time: whoever is about to stop drawing closes its
SDL display *first*, then tells the other side to open its own. This module
is both halves of that conversation.

An app started with ``--deck-socket PATH`` builds its whole rig (engine,
MIDI, button, pots) exactly as it would standalone, but the GUI becomes a
guest: it opens only when the deck says ``SHOW`` and the ✕ in the top-left
corner closes only the *picture*. The engine keeps ticking through every
hide — clock, transport, arps, recording and playback do not notice the
panel changing hands. That is the whole point: "closing the window stops
the picture, not the routing" was already the family's contract, and the
deck merely exercises it on purpose.

Same idiom as the button bridge on purpose — a Unix stream socket, one line
in, one line out, debuggable with ``socat`` from the field:

    deck -> app   SHOW | QUIT | PING
    app  -> deck  EVENT SHOWN | EVENT HIDDEN | EVENT QUIT | PONG

The connection is persistent (the app pushes unsolicited EVENT lines), and
the app survives the deck disappearing: an EOF just sends the link back to
``accept``, playing all the while.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time
from pathlib import Path

log = logging.getLogger("ranger.deck")

RECV_MAX = 256
BACKLOG = 2
SOCKET_SUFFIX = ".sock"

# Events an app emits; the deck treats anything else as noise.
EVENT_SHOWN = "SHOWN"
EVENT_HIDDEN = "HIDDEN"
EVENT_QUIT = "QUIT"
# The client-side sentinel for "the process hung up" — never sent on the
# wire, but delivered through the same queue so the deck's wait loop has one
# place to look.
EVENT_GONE = "GONE"


class DeckLink:
    """The app half: bind, accept the deck, queue its commands.

    Commands arrive on a reader thread and are consumed from the session
    loop with :meth:`wait`; events go back with :meth:`notify`. Exactly one
    deck connection is served at a time — a second connect replaces the
    first, which is the behaviour that makes a restarted deck Just Work.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._sock: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._commands: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> bool:
        """Bind and serve. False when the socket cannot be created — the rig
        must still play, it just cannot be summoned back onto the panel."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self.path))
            sock.listen(BACKLOG)
            sock.settimeout(0.5)
        except OSError as exc:
            log.warning("deck socket %s unavailable: %s", self.path, exc)
            return False
        self._sock = sock
        self._running.set()
        self._thread = threading.Thread(target=self._serve, name="deck-link",
                                        daemon=True)
        self._thread.start()
        log.info("deck link listening on %s", self.path)
        return True

    def stop(self) -> None:
        self._running.clear()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)
        for sock in (self._conn, self._sock):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        self._conn = self._sock = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    # --- session API ---------------------------------------------------------
    def wait(self, timeout: float | None = None) -> str | None:
        """Next command from the deck, or None on timeout."""
        try:
            return self._commands.get(timeout=timeout)
        except queue.Empty:
            return None

    def notify(self, event: str) -> None:
        """Send ``EVENT <event>``. A missing deck is not an error — the rig
        outlives its launcher by design."""
        with self._send_lock:
            conn = self._conn
            if conn is None:
                log.debug("deck gone — dropped EVENT %s", event)
                return
            try:
                conn.sendall(f"EVENT {event}\n".encode())
            except OSError as exc:
                log.debug("deck notify failed: %s", exc)

    # --- serving -------------------------------------------------------------
    def _serve(self) -> None:
        while self._running.is_set() and self._sock is not None:
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self._send_lock:
                old, self._conn = self._conn, conn
            if old is not None:
                try:
                    old.close()
                except OSError:
                    pass
            self._read_lines(conn)

    def _read_lines(self, conn: socket.socket) -> None:
        conn.settimeout(0.5)
        buffer = b""
        while self._running.is_set() and conn is self._conn:
            try:
                chunk = conn.recv(RECV_MAX)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                self._dispatch(line.decode("utf-8", "replace").strip().upper())
        with self._send_lock:
            if conn is self._conn:
                self._conn = None
        try:
            conn.close()
        except OSError:
            pass

    def _dispatch(self, command: str) -> None:
        if not command:
            return
        if command == "PING":
            with self._send_lock:
                conn = self._conn
                if conn is not None:
                    try:
                        conn.sendall(b"PONG\n")
                    except OSError:
                        pass
            return
        self._commands.put(command)


class DeckClient:
    """The launcher half: connect to an app's link and talk to it.

    A reader thread turns inbound lines into a queue of event words
    (``SHOWN`` / ``HIDDEN`` / ``QUIT`` / ``PONG``); when the far side hangs
    up, :data:`EVENT_GONE` is queued so the deck's wait loop has a single
    thing to select on.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self.events: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self, timeout: float = 15.0, poll: float = 0.1) -> bool:
        """Retry until the app has bound its socket — it is busy building a
        rig when the deck first asks after it."""
        deadline = time.monotonic() + timeout
        while True:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(self.path))
            except OSError:
                sock.close()
                if time.monotonic() >= deadline:
                    return False
                time.sleep(poll)
                continue
            sock.settimeout(0.5)
            self._sock = sock
            self._running.set()
            self._thread = threading.Thread(
                target=self._read, name="deck-client", daemon=True)
            self._thread.start()
            return True

    def close(self) -> None:
        self._running.clear()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)

    # --- talking -------------------------------------------------------------
    def send(self, command: str) -> bool:
        with self._send_lock:
            sock = self._sock
            if sock is None:
                return False
            try:
                sock.sendall((command.strip().upper() + "\n").encode())
                return True
            except OSError as exc:
                log.debug("deck send %s failed: %s", command, exc)
                return False

    def wait_event(self, timeout: float | None = None) -> str | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list[str]:
        drained = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained

    # --- reading -------------------------------------------------------------
    def _read(self) -> None:
        buffer = b""
        while self._running.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                chunk = sock.recv(RECV_MAX)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                word = line.decode("utf-8", "replace").strip().upper()
                if word.startswith("EVENT "):
                    word = word.split(None, 1)[1]
                if word:
                    self.events.put(word)
        # Deliberately after the loop, whatever ended it: the deck's state
        # machine treats a hangup exactly like an app that said QUIT.
        self.events.put(EVENT_GONE)


def run_deck_session(make_app, path: Path, app_name: str = "ranger") -> int:
    """The app-side session loop: wait for SHOW, run the GUI, hand back.

    ``make_app`` builds a fresh App (opening the SDL display in its
    constructor) against the *same* live engine every time — hiding tears
    down pygame's window and nothing else. Returns like ``App.run`` so
    ``main.py`` can keep its shutdown ``finally`` unchanged.

    SIGTERM/SIGINT end the session from either state: hidden (the wait loop
    polls a flag) or shown (a synthetic pygame QUIT unwinds the GUI loop).
    """
    import signal

    import pygame

    stop = threading.Event()

    def _terminate(signum, frame):
        stop.set()
        try:
            if pygame.display.get_init():
                pygame.event.post(pygame.event.Event(pygame.QUIT))
        except pygame.error:
            pass

    # Handlers only exist on the main thread (the tests drive sessions from
    # workers); elsewhere the process-level default is the caller's problem.
    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {sig: signal.signal(sig, _terminate)
                    for sig in (signal.SIGTERM, signal.SIGINT)}
    link = DeckLink(Path(path))
    if not link.start():
        log.error("%s: no deck link — refusing to sit invisible forever",
                  app_name)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        return 1
    try:
        while not stop.is_set():
            command = link.wait(timeout=0.5)
            if command is None:
                continue
            if command == "QUIT":
                break
            if command != "SHOW":
                log.debug("%s: ignoring deck command %r", app_name, command)
                continue
            try:
                app = make_app()
            except Exception:
                # A display that will not open must not kill the rig; tell
                # the deck to take the panel back and keep playing.
                log.exception("%s: GUI failed to open", app_name)
                link.notify(EVENT_HIDDEN)
                continue
            link.notify(EVENT_SHOWN)
            try:
                app.run()
            finally:
                pygame.display.quit()
            if getattr(app, "exit_reason", "quit") == "hide" \
                    and not stop.is_set():
                link.notify(EVENT_HIDDEN)
                continue
            break
        link.notify(EVENT_QUIT)
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        link.stop()
