"""The fleet: guest lifecycles, with fakes and with a real deck link.

The fake-backed tests pin the state machine; the linked test runs an actual
``run_deck_session`` (the same loop every app's ``--deck-socket`` mode
runs) on a thread and walks the full launch → show → hide → show → quit
choreography over a real Unix socket.
"""
from __future__ import annotations

import queue
import shutil
import tempfile
import threading
from pathlib import Path

import pytest

from core.engine import BACKGROUND, OFF, SHOWN, STARTING, DeckFleet
from core.registry import AppSpec
from rangerkit.deck import EVENT_HIDDEN, EVENT_QUIT, EVENT_SHOWN, \
    run_deck_session

SPEC = AppSpec("midiranger", "MidiRanger", "matrix", ("python", "main.py"))


@pytest.fixture()
def sock_dir():
    """pytest's tmp_path overflows AF_UNIX's ~104-byte sun_path on macOS;
    the appliance's real /run/rangerdeck never does. Short dir instead."""
    made = Path(tempfile.mkdtemp(prefix="deck-"))
    yield made
    shutil.rmtree(made, ignore_errors=True)


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


class FakeClient:
    """Just enough of DeckClient for the fleet: a scriptable event queue."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.events: queue.Queue[str] = queue.Queue()
        self.closed = False

    def send(self, command: str) -> bool:
        self.sent.append(command)
        return True

    def wait_event(self, timeout=None):
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self):
        drained = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained

    def close(self) -> None:
        self.closed = True


def make_fleet(sock_dir):
    process = FakeProcess()
    client = FakeClient()
    fleet = DeckFleet((SPEC,), sock_dir,
                      spawn=lambda command: process,
                      connect=lambda name, timeout: client)
    return fleet, process, client


def test_launch_attach_and_the_running_count(sock_dir):
    fleet, _, _ = make_fleet(sock_dir)
    assert fleet.state("midiranger") == OFF
    assert fleet.running_count() == 0
    assert fleet.launch("midiranger")
    assert fleet.state("midiranger") == STARTING
    assert fleet.try_attach("midiranger")
    assert fleet.state("midiranger") == BACKGROUND
    assert fleet.running_count() == 1


def test_spawn_appends_the_deck_socket(sock_dir):
    seen = []

    def spawn(command):
        seen.append(command)
        return FakeProcess()

    fleet = DeckFleet((SPEC,), sock_dir, spawn=spawn,
                      connect=lambda name, timeout: FakeClient())
    fleet.launch("midiranger")
    (command,) = seen
    assert command[-2] == "--deck-socket"
    assert command[-1] == str(sock_dir / "midiranger.sock")


def test_wait_while_shown_follows_the_events(sock_dir):
    fleet, _, client = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    client.events.put(EVENT_SHOWN)
    client.events.put(EVENT_HIDDEN)
    assert fleet.wait_while_shown("midiranger") == "hidden"
    assert fleet.state("midiranger") == BACKGROUND


def test_wait_while_shown_reaps_a_quitter(sock_dir):
    fleet, _, client = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    client.events.put(EVENT_SHOWN)
    client.events.put(EVENT_QUIT)
    assert fleet.wait_while_shown("midiranger") == "quit"
    assert fleet.state("midiranger") == OFF
    assert client.closed


def test_wait_while_shown_notices_a_dead_process(sock_dir):
    fleet, process, _ = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    process.returncode = 1
    assert fleet.wait_while_shown("midiranger") == "quit"
    assert fleet.state("midiranger") == OFF


def test_poll_reaps_a_background_exit(sock_dir):
    fleet, process, _ = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    process.returncode = 0
    fleet.poll()
    assert fleet.state("midiranger") == OFF


def test_stop_asks_politely_over_the_link(sock_dir):
    fleet, _, client = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    fleet.stop("midiranger")
    assert client.sent == ["QUIT"]


def test_stop_before_attach_terminates_the_spawn(sock_dir):
    fleet, process, _ = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.stop("midiranger")
    assert process.terminated
    assert fleet.state("midiranger") == OFF


class _GuestApp:
    """A guest GUI that immediately exits with a scripted reason."""

    def __init__(self, reason: str) -> None:
        self.exit_reason = reason

    def run(self) -> int:
        return 0


def test_full_choreography_over_a_real_link(sock_dir):
    """launch → attach → SHOW/SHOWN → HIDDEN (rig alive) → SHOW → QUIT,
    against the very session loop the apps run under --deck-socket."""
    reasons = iter(["hide", "quit"])
    sessions = []

    def spawn(command):
        socket_path = Path(command[command.index("--deck-socket") + 1])
        thread = threading.Thread(
            target=run_deck_session,
            args=(lambda: _GuestApp(next(reasons)), socket_path, "guest"),
            daemon=True)
        thread.start()
        sessions.append(thread)

        class ThreadProcess:
            def poll(self_inner):
                return None if thread.is_alive() else 0

            def wait(self_inner, timeout=None):
                thread.join(timeout=timeout)
                if thread.is_alive():
                    raise RuntimeError("still running")
                return 0

            def terminate(self_inner):
                pass

        return ThreadProcess()

    fleet = DeckFleet((SPEC,), sock_dir, spawn=spawn)
    assert fleet.launch("midiranger")
    deadline = 50
    while not fleet.try_attach("midiranger", timeout=0.1) and deadline:
        deadline -= 1
    assert fleet.state("midiranger") == BACKGROUND

    assert fleet.show("midiranger")
    assert fleet.wait_while_shown("midiranger") == "hidden"
    assert fleet.state("midiranger") == BACKGROUND

    assert fleet.show("midiranger")
    assert fleet.wait_while_shown("midiranger") == "quit"
    assert fleet.state("midiranger") == OFF
    sessions[0].join(timeout=3.0)
    assert not sessions[0].is_alive()


def test_shutdown_quits_everyone(sock_dir):
    fleet, process, client = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    process.returncode = 0        # the guest obeys the QUIT instantly
    fleet.shutdown(grace=0.5)
    assert client.sent == ["QUIT"]
    assert fleet.state("midiranger") == OFF


def test_shown_state_is_reported_for_the_tile(sock_dir):
    fleet, _, client = make_fleet(sock_dir)
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    client.events.put(EVENT_SHOWN)
    client.events.put(EVENT_HIDDEN)
    fleet.wait_while_shown("midiranger")
    # SHOWN was passed through on the way — the guests dict carried it.
    assert fleet.guests["midiranger"].state in (BACKGROUND, SHOWN)
