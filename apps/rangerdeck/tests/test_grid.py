"""The grid, on SDL's dummy video driver.

Same contract as every panel's GUI tests: everything drawn as tappable is
registered as a hit target, taps travel the real event path, and it all
holds at every shipped geometry.
"""
from __future__ import annotations

import pygame
import pytest

from core.engine import BACKGROUND, OFF, DeckFleet
from core.registry import AppSpec
from gui.app import App
from rangerkit.testkit import GEOMETRIES

SPECS = (
    AppSpec("chordranger", "ChordRanger", "chord pads", ("py", "m")),
    AppSpec("midiranger", "MidiRanger", "matrix", ("py", "m")),
    AppSpec("genranger", "GenRanger", "generative", ("py", "m")),
    AppSpec("phraseranger", "PhraseRanger", "looper", ("py", "m")),
    AppSpec("sceneranger", "SceneRanger", "scenes", ("py", "m")),
    AppSpec("grooveranger", "GrooveRanger", "groovebox", ("py", "m")),
    AppSpec("synthranger", "SynthRanger", "synth", ("py", "m")),
)


class IdleClient:
    def send(self, command):
        return True

    def wait_event(self, timeout=None):
        return None

    def drain(self):
        return []

    def close(self):
        pass


class IdleProcess:
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass


def make_app(size=(1280, 400), sock_dir=None, tmp_path=None):
    fleet = DeckFleet(SPECS, sock_dir or tmp_path,
                      spawn=lambda command: IdleProcess(),
                      connect=lambda name, timeout: IdleClient())
    return App(fleet, size=size)


@pytest.mark.parametrize("size", GEOMETRIES)
def test_every_tile_is_a_hit_target(size, tmp_path):
    app = make_app(size=size, tmp_path=tmp_path)
    try:
        app._draw()
        for spec in SPECS:
            rect = app.chrome.rect_for(f"app:{spec.name}")
            assert rect is not None, spec.name
            assert rect.width >= 44 and rect.height >= 44, spec.name
    finally:
        pygame.display.quit()


def test_running_tiles_grow_a_stop_control(tmp_path):
    app = make_app(tmp_path=tmp_path)
    try:
        app._draw()
        assert app.chrome.rect_for("stop:midiranger") is None
        app.fleet.launch("midiranger")
        app.fleet.try_attach("midiranger")
        assert app.fleet.state("midiranger") == BACKGROUND
        app._draw()
        assert app.chrome.rect_for("stop:midiranger") is not None
    finally:
        pygame.display.quit()


def test_the_stop_control_wins_over_the_tile_beneath_it(tmp_path):
    app = make_app(tmp_path=tmp_path)
    try:
        app.fleet.launch("midiranger")
        app.fleet.try_attach("midiranger")
        app._draw()
        stop = app.chrome.rect_for("stop:midiranger")
        assert app.chrome.hit(stop.center) == "stop:midiranger"
    finally:
        pygame.display.quit()


def test_tapping_stop_travels_the_real_event_path(tmp_path):
    app = make_app(tmp_path=tmp_path)
    try:
        app.fleet.launch("midiranger")
        app.fleet.try_attach("midiranger")
        app._draw()
        stop = app.chrome.rect_for("stop:midiranger")
        pygame.event.post(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=stop.center))
        app._events()
        # The polite QUIT went out; with the fake guest never exiting the
        # tile stays visible, which is exactly what the panel should show.
        assert app.fleet.guests["midiranger"].note == "STOPPING"
    finally:
        pygame.display.quit()


def test_header_counts_the_running(tmp_path):
    app = make_app(tmp_path=tmp_path)
    try:
        assert app.fleet.running_count() == 0
        app.fleet.launch("midiranger")
        app.fleet.try_attach("midiranger")
        app.fleet.launch("genranger")
        app.fleet.try_attach("genranger")
        assert app.fleet.running_count() == 2
        app._draw()          # and drawing with running guests must not raise
    finally:
        pygame.display.quit()


def test_states_render_without_raising(tmp_path):
    app = make_app(tmp_path=tmp_path)
    try:
        guest = app.fleet.guests["midiranger"]
        for state in (OFF, "starting", BACKGROUND, "shown"):
            guest.state = state
            app._draw()
    finally:
        pygame.display.quit()
