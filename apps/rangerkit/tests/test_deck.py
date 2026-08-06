"""The deck link — display handover without ever dropping the rig.

Real sockets in a tmp dir, both halves of the conversation, and the session
loop driven exactly the way RangerDeck drives it. pygame stays on the dummy
driver throughout; what these tests protect is the *choreography* — SHOW
before SHOWN, HIDDEN only after the display is gone, and an app that keeps
serving after its launcher dies.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest

from rangerkit.deck import (
    EVENT_GONE, EVENT_HIDDEN, EVENT_QUIT, EVENT_SHOWN,
    DeckClient, DeckLink, run_deck_session,
)


@pytest.fixture()
def sock_dir():
    """pytest's tmp_path overflows AF_UNIX's ~104-byte sun_path on macOS;
    the appliance's real /run/rangerdeck never does. Short dir instead."""
    made = Path(tempfile.mkdtemp(prefix="deck-"))
    yield made
    shutil.rmtree(made, ignore_errors=True)


@pytest.fixture()
def linked(sock_dir):
    path = sock_dir / "app.sock"
    link = DeckLink(path)
    assert link.start()
    client = DeckClient(path)
    assert client.connect(timeout=2.0)
    yield link, client
    client.close()
    link.stop()


def test_commands_flow_down_and_events_flow_up(linked):
    link, client = linked
    assert client.send("SHOW")
    assert link.wait(timeout=2.0) == "SHOW"
    link.notify(EVENT_SHOWN)
    assert client.wait_event(timeout=2.0) == EVENT_SHOWN


def test_ping_answers_without_entering_the_command_queue(linked):
    link, client = linked
    assert client.send("PING")
    assert client.wait_event(timeout=2.0) == "PONG"
    assert link.wait(timeout=0.2) is None


def test_client_hears_gone_when_the_app_hangs_up(linked):
    link, client = linked
    link.stop()
    assert client.wait_event(timeout=2.0) == EVENT_GONE


def test_link_survives_the_deck_disappearing(sock_dir):
    path = sock_dir / "app.sock"
    link = DeckLink(path)
    assert link.start()
    try:
        first = DeckClient(path)
        assert first.connect(timeout=2.0)
        first.close()
        # A restarted deck connects again and is heard — the app never
        # stopped serving while nobody was attached.
        second = DeckClient(path)
        assert second.connect(timeout=2.0)
        assert second.send("SHOW")
        assert link.wait(timeout=2.0) == "SHOW"
        second.close()
    finally:
        link.stop()


class _FakeApp:
    """Stands in for a real App: run() returns at once with a reason."""

    def __init__(self, reason: str) -> None:
        self.exit_reason = reason

    def run(self) -> int:
        return 0


def test_session_hides_and_comes_back_then_quits(sock_dir):
    path = sock_dir / "app.sock"
    reasons = iter(["hide", "quit"])
    built = []

    def make_app():
        app = _FakeApp(next(reasons))
        built.append(app)
        return app

    result = []
    session = threading.Thread(
        target=lambda: result.append(run_deck_session(make_app, path,
                                                      "testapp")),
        daemon=True)
    session.start()

    client = DeckClient(path)
    assert client.connect(timeout=3.0)
    assert client.send("SHOW")
    assert client.wait_event(timeout=3.0) == EVENT_SHOWN
    # First run hides: the session must report HIDDEN and keep serving.
    assert client.wait_event(timeout=3.0) == EVENT_HIDDEN
    assert client.send("SHOW")
    assert client.wait_event(timeout=3.0) == EVENT_SHOWN
    # Second run quits outright: QUIT, then the socket goes away.
    assert client.wait_event(timeout=3.0) == EVENT_QUIT
    session.join(timeout=3.0)
    assert not session.is_alive()
    assert result == [0]
    assert len(built) == 2
    client.close()


def test_session_quit_command_ends_it_without_a_show(sock_dir):
    path = sock_dir / "app.sock"
    result = []
    session = threading.Thread(
        target=lambda: result.append(
            run_deck_session(lambda: _FakeApp("quit"), path, "testapp")),
        daemon=True)
    session.start()
    client = DeckClient(path)
    assert client.connect(timeout=3.0)
    assert client.send("QUIT")
    assert client.wait_event(timeout=3.0) == EVENT_QUIT
    session.join(timeout=3.0)
    assert not session.is_alive()
    assert result == [0]
    client.close()


def test_session_survives_an_app_that_cannot_open_its_display(sock_dir):
    path = sock_dir / "app.sock"

    calls = []

    def exploding_then_fine():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("no display")
        return _FakeApp("quit")

    session = threading.Thread(
        target=lambda: run_deck_session(exploding_then_fine, path, "testapp"),
        daemon=True)
    session.start()
    client = DeckClient(path)
    assert client.connect(timeout=3.0)
    assert client.send("SHOW")
    # The failed open reads as an immediate hide — the deck takes the panel
    # back and the rig is still alive to try again.
    assert client.wait_event(timeout=3.0) == EVENT_HIDDEN
    assert client.send("SHOW")
    assert client.wait_event(timeout=3.0) == EVENT_SHOWN
    assert client.wait_event(timeout=3.0) == EVENT_QUIT
    session.join(timeout=3.0)
    assert not session.is_alive()
    client.close()


def test_wait_times_out_quickly_enough_for_a_poll_loop(linked):
    link, _ = linked
    started = time.monotonic()
    assert link.wait(timeout=0.05) is None
    assert time.monotonic() - started < 1.0
