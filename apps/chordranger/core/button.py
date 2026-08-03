"""The PiSound button, over a Unix socket.

``pisound-btn`` runs its action scripts as root under the system Python. The
app runs as its own user inside a venv, so the two cannot share a process —
the bridge is a socket the app listens on and a stdlib client the scripts
call. This is the same shape RK-00pi uses, deliberately: an operator who has
learned one of these two appliances should not have to learn the other's
button plumbing.

Gestures map to actions in ``[button.map]``. An unknown action name is dropped
with a log line rather than raising: the map is hand-written config, and a
typo must cost you one gesture, not the instrument.

The socket protocol is one line in, one line out, so ``socat`` and a shell
loop are enough to debug it in the field:

    $ echo PING | nc -U /run/chordranger/button.sock
    PONG
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from pathlib import Path

from core import commands as cmd

log = logging.getLogger("chordranger.button")

# Gesture → action. The defaults mirror RK-00pi's so a rig that swaps apps
# keeps the same muscle memory: one click plays, two records, a hold saves,
# a long hold panics.
DEFAULT_MAP: dict[str, str] = {
    "CLICK_1": "play_stop",
    "CLICK_2": "record_toggle",
    "CLICK_3": "next_section",
    "HOLD_1S": "save_project",
    "HOLD_3S": "next_style",
    "HOLD_5S": "panic",
}

ACTIONS = ("play_stop", "record_toggle", "next_section", "prev_section",
           "save_project", "next_style", "next_chordset", "panic",
           "metronome", "nothing")

SOCKET_NAME = "button.sock"
BACKLOG = 4
RECV_MAX = 128


def normalise_map(raw: dict[str, str]) -> dict[str, str]:
    """Merge a config map over the defaults, dropping unknown actions."""
    merged = dict(DEFAULT_MAP)
    for gesture, action in (raw or {}).items():
        name = str(action).strip().lower()
        if name not in ACTIONS:
            log.warning("button: unknown action %r for %s — ignored", action,
                        gesture)
            continue
        merged[str(gesture).upper()] = name
    return merged


HOLD_STEPS = (1, 3, 5)          # the thresholds pisound.conf itself uses


def _gesture_from_words(words: list[str]) -> str:
    """``["CLICK", "2"] -> "CLICK_2"``; ``["HOLD", "1", "4"] -> "HOLD_3S"``.

    A hold rounds *down* to the threshold it passed: releasing at 4 s means
    you got past 3 s and not past 5 s, and binding that to the 5 s action
    would fire panic on a hold the player meant as a save.
    """
    verb = words[0].upper()
    if verb == "CLICK":
        count = int(words[1]) if len(words) > 1 and words[1].isdigit() else 1
        return f"CLICK_{count}" if count <= 3 else "CLICK_OTHER"
    seconds = int(words[2]) if len(words) > 2 and words[2].isdigit() else 0
    held = max((s for s in HOLD_STEPS if s <= seconds), default=None)
    return f"HOLD_{held}S" if held else "HOLD_OTHER"


def socket_path(config) -> Path:
    """``[button] socket`` if set, else ``<data_dir>/button.sock``.

    The appliance points this at /run/chordranger, which the unit's
    RuntimeDirectory= creates and removes — so a crash cannot leave a stale
    socket node behind to block the next bind.
    """
    configured = getattr(config.button, "socket", "")
    if configured:
        return Path(configured)
    return Path(config.paths.data_dir) / SOCKET_NAME


class ButtonServer:
    """Listens for gesture lines and turns them into engine commands."""

    def __init__(self, engine, config) -> None:
        self.engine = engine
        self.config = config
        self.map = normalise_map(getattr(config.button, "map", {}))
        self.path = socket_path(config)
        self.on_message = None          # set by the App to print on the panel
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()

    # --- lifecycle -----------------------------------------------------------
    def start(self) -> bool:
        """Bind and serve. Returns False when the socket cannot be created —
        a headless unit with no button still has to play."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists():
                self.path.unlink()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self.path))
            sock.listen(BACKLOG)
            sock.settimeout(0.5)
            # The daemon runs as root and the app does not, so the socket has
            # to be writable by anyone who can reach the directory. The
            # directory is the access control, not this mode.
            os.chmod(self.path, 0o666)
        except OSError as exc:
            log.warning("button socket %s unavailable: %s", self.path, exc)
            return False
        self._sock = sock
        self._running.set()
        self._thread = threading.Thread(target=self._serve, name="cr-button",
                                        daemon=True)
        self._thread.start()
        log.info("button socket listening on %s", self.path)
        return True

    def stop(self) -> None:
        self._running.clear()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.5)
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    # --- serving -------------------------------------------------------------
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
                    payload = connection.recv(RECV_MAX).decode(
                        "utf-8", "replace").strip()
                    reply = self.handle(payload)
                    connection.sendall((reply + "\n").encode())
                except (OSError, UnicodeError) as exc:
                    log.debug("button client failed: %s", exc)

    def handle(self, line: str) -> str:
        """One request line → one reply line. Public so the tests can drive
        the protocol without a socket."""
        request = line.strip().upper()
        if not request:
            return "ERR empty"
        if request == "PING":
            return "PONG"
        if request == "MAP":
            return " ".join(f"{g}={a}" for g, a in sorted(self.map.items()))
        if request == "ACTIONS":
            return " ".join(ACTIONS)
        if request.startswith("ACTION "):
            # Run an action by name, ignoring the map. This is the escape
            # hatch for scripting and for testing a binding before you commit
            # it to config.
            name = request.split(None, 1)[1].strip().lower()
            if name not in ACTIONS:
                return f"ERR unknown action {name}"
            return self.act(name)
        if request.startswith(("CLICK ", "HOLD ")):
            # The wrapper normally sends a gesture id, but pisound-btn's own
            # argument shape (verb + counts) is accepted too so a hand-rolled
            # script does not have to know the id spelling.
            request = _gesture_from_words(request.split())
        action = self.map.get(request)
        if action is None:
            return f"ERR unmapped {request}"
        return self.act(action)

    def act(self, action: str) -> str:
        """Run one action by name. Returns the reply line."""
        engine = self.engine
        if action == "nothing":
            return "OK nothing"
        if action == "play_stop":
            engine.submit(cmd.TogglePlay())
        elif action == "record_toggle":
            engine.submit(cmd.SetRecord(not engine.snapshot().recording))
        elif action == "panic":
            engine.submit(cmd.Panic())
        elif action == "metronome":
            engine.submit(cmd.SetMetronome(not engine.snapshot().metronome))
        elif action in ("next_section", "prev_section"):
            engine.submit(cmd.RequestSection(
                self._adjacent_section(+1 if action == "next_section"
                                       else -1)))
        elif action == "next_style":
            from data.styles import factory_styles
            styles = factory_styles()
            names = [s.name for s in styles]
            here = names.index(engine.style.name) \
                if engine.style.name in names else -1
            engine.submit(cmd.SetStyle(styles[(here + 1) % len(styles)]))
        elif action == "next_chordset":
            from core.chordset import factory_chordsets
            sets = factory_chordsets()
            names = [c.name for c in sets]
            here = names.index(engine.chordset.name) \
                if engine.chordset.name in names else -1
            engine.submit(cmd.SetChordset(sets[(here + 1) % len(sets)]))
        elif action == "save_project":
            # Saving touches the filesystem, so it is handed to the GUI/host
            # rather than done on this thread — and a headless unit says so
            # instead of pretending it saved.
            if self.on_message is not None:
                self.on_message("BUTTON: SAVE")
            self._request_save()
        else:
            return f"ERR unknown {action}"
        if self.on_message is not None and action != "save_project":
            self.on_message(f"BUTTON: {action.replace('_', ' ').upper()}")
        return f"OK {action}"

    def _adjacent_section(self, step: int) -> str:
        """The next section the *current style actually has*, wrapping.

        Walking the canonical order and skipping what the style lacks means a
        cut-down style still cycles sensibly rather than hitting a dead
        button every third press.
        """
        from core.style import SECTION_ORDER
        available = [name for name in SECTION_ORDER
                     if self.engine.style.has(name)]
        if not available:
            return ""
        here = self.engine.arranger.section
        index = available.index(here) if here in available else 0
        return available[(index + step) % len(available)]

    def _request_save(self) -> None:
        saver = getattr(self, "on_save", None)
        if saver is not None:
            saver()
            return
        # Headless: write beside the data dir under the project's own name.
        from core.project import EXTENSION
        try:
            project = self.engine.capture()
            directory = Path(self.config.paths.projects_dir)
            project.save(directory / f"{project.name.lower()}{EXTENSION}")
            log.info("button: saved %s", project.name)
        except OSError as exc:
            log.warning("button: save failed: %s", exc)


def send(path: Path, request: str, timeout: float = 1.0) -> str:
    """Client half — used by the shell wrappers and the diagnostics CLI.

    Stdlib only and no imports from the app, because it runs under the system
    Python as root, outside the venv.
    """
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(path))
        sock.sendall((request.strip() + "\n").encode())
        return sock.recv(RECV_MAX).decode("utf-8", "replace").strip()
