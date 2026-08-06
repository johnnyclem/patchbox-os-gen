"""Deck mode: the ✕ hides the picture and leaves the rig alone."""
from __future__ import annotations

import pygame
import pytest

from core.clock import FakeClock
from core.engine import Engine
from core.midi_io import CaptureMidiIO
from core.project import default_project
from gui import theme
from gui.app import App

GEOMETRIES = ((1280, 400), (800, 480), (480, 800))


def make_app(size=(1280, 400), deck=True):
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    return App(engine, size=size, deck=deck)


# --- layout -------------------------------------------------------------------

@pytest.mark.parametrize("size", GEOMETRIES)
def test_deck_mode_reserves_a_close_corner(size):
    layout = theme.Layout.for_size(size, tab_count=5, close_button=True)
    assert layout.close is not None
    # Top-left, big enough to hit with a thumb, and carved out of the
    # transport chrome rather than floating over it.
    assert layout.close.topleft == (0, 0)
    assert layout.close.width >= theme.TOUCH_MIN
    assert layout.close.height >= theme.TOUCH_MIN
    assert not layout.close.colliderect(layout.transport)
    assert not layout.close.colliderect(layout.content)


@pytest.mark.parametrize("size", GEOMETRIES)
def test_standalone_layout_has_no_close_corner(size):
    assert theme.Layout.for_size(size, tab_count=5).close is None


# --- the shell ----------------------------------------------------------------

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
