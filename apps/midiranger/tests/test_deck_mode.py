"""Deck mode: the ✕ hides the picture and leaves the rig alone."""
from __future__ import annotations

import pygame
import pytest

from core.engine import MidiRangerEngine
from core.project import default_project
from gui.app import App
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


def make_app(size=(1280, 400), deck=True):
    engine = MidiRangerEngine(default_project(), CaptureMidiIO(), FakeClock())
    return App(engine, size=size, deck=deck)


@pytest.mark.parametrize("size", GEOMETRIES)
def test_deck_mode_draws_the_close_control_top_left(size):
    app = make_app(size)
    try:
        app.engine.step()
        app._draw(app.engine.snapshot())
        rect = app.chrome.rect_for("deck-close")
        assert rect is not None
        assert rect.x < 60 and rect.y < 60
    finally:
        pygame.display.quit()


def test_the_close_control_hides_rather_than_quits():
    app = make_app()
    try:
        app.running = True
        app.engine.step()
        app._draw(app.engine.snapshot())
        rect = app.chrome.rect_for("deck-close")
        handled = app._chrome_event(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center))
        assert handled
        assert app.running is False
        assert app.exit_reason == "hide"
        # The engine did not notice: the tick loop still steps and no notes
        # were cut — hiding is a GUI event, not a transport one.
        app.engine.step()
    finally:
        pygame.display.quit()


def test_standalone_mode_has_no_close_control_and_quits_normally():
    app = make_app(deck=False)
    try:
        app.engine.step()
        app._draw(app.engine.snapshot())
        assert app.chrome.rect_for("deck-close") is None
        assert app.exit_reason == "quit"
    finally:
        pygame.display.quit()
