"""The deck's engine is a fleet: guest app processes and their deck links.

Where a Ranger app's ``core/engine.py`` keeps musical time, the deck's
keeps *processes*. Each guest is spawned once, handed the panel on demand,
and — this is the whole product — left running when its picture closes.
Clock, transport, arps, recording and playback belong to the guest's own
engine thread inside its own process; the fleet never touches them, it only
decides who is drawing.

States per guest:

    off         not running (or exited, reaped)
    starting    spawned, deck socket not yet answering
    background  rig up, no display — playing, invisible
    shown       rig up and holding the panel

Testable without a single real subprocess: ``spawn`` and ``connect`` are
injectable, and the GUI drives the same public methods the tests do.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rangerkit.deck import (
    EVENT_GONE, EVENT_HIDDEN, EVENT_QUIT, EVENT_SHOWN, DeckClient,
)

from core.registry import AppSpec

log = logging.getLogger("rangerdeck.fleet")

OFF = "off"
STARTING = "starting"
BACKGROUND = "background"
SHOWN = "shown"

SHOW_TIMEOUT = 15.0     # rig is already built; opening a display is quick
QUIT_GRACE = 5.0        # after QUIT, before SIGTERM


def _spawn(command: tuple[str, ...]) -> subprocess.Popen:
    # Guests inherit stdout/stderr, so on the appliance their logs land in
    # the deck unit's journal — one place to read the whole suite.
    return subprocess.Popen(list(command))


@dataclass
class Guest:
    spec: AppSpec
    process: object | None = None
    client: DeckClient | None = None
    state: str = OFF
    note: str = ""              # last human-readable event, for the tile
    _events: list = field(default_factory=list)


class DeckFleet:
    """Spawn, attach, show, and reap the guest apps."""

    def __init__(self, specs, socket_dir: Path, spawn=_spawn,
                 connect=None) -> None:
        self.socket_dir = Path(socket_dir)
        self._spawn = spawn
        self._connect = connect or self._real_connect
        self.guests = {spec.name: Guest(spec) for spec in specs}

    # --- injectables ---------------------------------------------------------
    def socket_for(self, name: str) -> Path:
        return self.socket_dir / f"{name}.sock"

    def _real_connect(self, name: str, timeout: float):
        client = DeckClient(self.socket_for(name))
        return client if client.connect(timeout=timeout) else None

    # --- queries -------------------------------------------------------------
    def state(self, name: str) -> str:
        return self.guests[name].state

    def note(self, name: str) -> str:
        return self.guests[name].note

    def names(self) -> tuple[str, ...]:
        return tuple(self.guests)

    def running_count(self) -> int:
        return sum(g.state in (BACKGROUND, SHOWN) for g in
                   self.guests.values())

    # --- lifecycle -----------------------------------------------------------
    def launch(self, name: str) -> bool:
        """Spawn the guest. Returns False when the spawn itself fails."""
        guest = self.guests[name]
        if guest.state != OFF:
            return True
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        socket_path = self.socket_for(name)
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass
        command = guest.spec.command + ("--deck-socket", str(socket_path))
        try:
            guest.process = self._spawn(command)
        except OSError as exc:
            log.error("%s: spawn failed: %s", name, exc)
            guest.note = "SPAWN FAILED"
            return False
        guest.state = STARTING
        guest.note = "STARTING"
        return True

    def try_attach(self, name: str, timeout: float = 0.2) -> bool:
        """One bounded connect attempt while the guest builds its rig.

        Called from the grid's frame loop so the STARTING tile can animate
        instead of the whole deck freezing on a long import.
        """
        guest = self.guests[name]
        if guest.client is not None:
            return True
        if guest.state != STARTING:
            return False
        client = self._connect(name, timeout)
        if client is None:
            return False
        guest.client = client
        guest.state = BACKGROUND
        guest.note = "RUNNING"
        return True

    def show(self, name: str) -> bool:
        """Ask the guest to take the panel. Call with the deck's own display
        already closed — the whole protocol exists because two DRM masters
        cannot coexist."""
        guest = self.guests[name]
        if guest.client is None:
            return False
        return guest.client.send("SHOW")

    def wait_while_shown(self, name: str) -> str:
        """Block until the panel is ours again.

        Returns "hidden" (guest still playing, invisible), "quit" (guest
        gone), or "failed" (never took the display). Blocking is correct
        here: the deck has no window of its own while a guest holds the
        panel, so there is nothing else for this thread to do.
        """
        guest = self.guests[name]
        client = guest.client
        if client is None:
            return "failed"
        shown = False
        waited = 0.0
        while True:
            event = client.wait_event(timeout=0.5)
            if event == EVENT_SHOWN:
                shown = True
                guest.state = SHOWN
                continue
            if event == EVENT_HIDDEN:
                guest.state = BACKGROUND
                guest.note = "RUNNING"
                return "hidden"
            if event in (EVENT_QUIT, EVENT_GONE):
                self._reap(guest)
                return "quit"
            if event is None:
                process = guest.process
                if process is not None and process.poll() is not None:
                    self._reap(guest)
                    return "quit"
                if not shown:
                    waited += 0.5
                    if waited >= SHOW_TIMEOUT:
                        guest.state = BACKGROUND
                        guest.note = "NO DISPLAY"
                        return "failed"

    def stop(self, name: str) -> None:
        """Ask the guest to shut its rig down for real (the tile's ■)."""
        guest = self.guests[name]
        if guest.client is not None:
            guest.client.send("QUIT")
            guest.note = "STOPPING"
            return
        # Never attached — nothing to ask politely; terminate the spawn.
        if guest.process is not None:
            try:
                guest.process.terminate()
            except OSError:
                pass
            self._reap(guest)

    def poll(self) -> None:
        """Reap exits and fold in stray events; called once per frame."""
        for guest in self.guests.values():
            process = guest.process
            if process is not None and process.poll() is not None:
                self._reap(guest)
                continue
            client = guest.client
            if client is None:
                continue
            for event in client.drain():
                if event in (EVENT_QUIT, EVENT_GONE):
                    self._reap(guest)
                    break
                if event == EVENT_HIDDEN:
                    guest.state = BACKGROUND
                    guest.note = "RUNNING"

    def shutdown(self, grace: float = QUIT_GRACE) -> None:
        """QUIT everyone, wait briefly, then terminate what remains."""
        for guest in self.guests.values():
            if guest.client is not None:
                guest.client.send("QUIT")
        for guest in self.guests.values():
            process = guest.process
            if process is None:
                continue
            try:
                process.wait(timeout=grace)
            except Exception:
                try:
                    process.terminate()
                except OSError:
                    pass
            self._reap(guest)

    # --- internal ------------------------------------------------------------
    def _reap(self, guest: Guest) -> None:
        if guest.client is not None:
            guest.client.close()
            guest.client = None
        process, guest.process = guest.process, None
        if process is not None:
            try:
                process.wait(timeout=1.0)
            except Exception:
                pass
        guest.state = OFF
        guest.note = ""
        try:
            self.socket_for(guest.spec.name).unlink(missing_ok=True)
        except OSError:
            pass
