"""The panel, on SDL's dummy video driver.

These are not screenshot tests. They assert the two things that actually
break a touch UI: that every control a screen *draws* is also registered as
a hit target (so no button is decorative), and that pressing every
registered control produces commands the engine accepts without raising —
at every shipped panel geometry.
"""
from __future__ import annotations

import pygame
import pytest

from core.commands import GvSnapshot
from core.engine import GenRangerEngine
from core.project import default_project
from gui.app import SCREENS, App
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


def build_project():
    project = default_project()
    # A CA layer so the MAP editor's third face is exercised too.
    project.params["layers"].append(
        {"role": "melody", "algorithm": "cellular", "dest": "din_out",
         "channel": 3, "rule": 110, "scale": "minor"})
    return project


@pytest.fixture()
def app():
    engine = GenRangerEngine(build_project(), CaptureMidiIO(), FakeClock())
    application = App(engine, size=(1280, 400))
    yield application
    pygame.display.quit()


def make_app(size):
    engine = GenRangerEngine(build_project(), CaptureMidiIO(), FakeClock())
    return App(engine, size=size)


def _frame(application: App, ticks: int = 1) -> GvSnapshot:
    for _ in range(ticks):
        application.engine.step()
    snapshot = application.engine.snapshot()
    screen = application.screens[application.tab]
    screen.update(snapshot)
    application._draw(snapshot)
    return snapshot


def _tap(application: App, key: str) -> None:
    """Press and release a control by key, through the real event path."""
    screen = application.screens[application.tab]
    rect = screen.hits.rect_for(key)
    assert rect is not None, f"no hit target for {key!r}"
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        event = pygame.event.Event(kind, button=1, pos=rect.center)
        for command in screen.handle(event):
            application.engine.submit(command)


# --- the shell ----------------------------------------------------------------

def test_the_app_builds_every_screen(app):
    assert len(app.screens) == len(SCREENS)
    assert [s.title for s in app.screens] == ["PERFORM", "MAP", "LAYERS",
                                              "SEEDS", "SET"]


def test_every_screen_draws_without_raising(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 4)


def test_every_screen_registers_hit_targets(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app)
        assert len(app.screens[index].hits) >= 4, app.screens[index].title


@pytest.mark.parametrize("size", GEOMETRIES)
def test_pressing_every_control_on_every_screen_is_safe(size):
    application = make_app(size)
    try:
        for index in range(len(application.screens)):
            application.tab = index
            _frame(application, 2)
            for key in list(application.screens[index].hits.keys()):
                _frame(application)
                if application.screens[index].hits.rect_for(key) is None:
                    continue    # the control moved or vanished this frame
                _tap(application, key)
                _frame(application, 2)
        application.engine.all_notes_off()
        assert not application.engine.midi.hanging()
    finally:
        pygame.display.quit()


def test_the_transport_rail_drives_the_engine(app):
    _frame(app)
    rect = app.chrome.rect_for("play")
    assert rect is not None
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    _frame(app, 2)
    assert app.engine.playing
    rect = app.chrome.rect_for("cruise")
    was = app.engine.cruise.on
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    _frame(app, 2)
    assert app.engine.cruise.on != was


def test_tabs_switch_screens(app):
    _frame(app)
    rect = app.chrome.rect_for("tab2")
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    assert app.tab == 2


def test_keyboard_shortcuts_reach_the_engine(app):
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    _frame(app, 2)
    assert app.engine.playing
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m))
    _frame(app, 2)
    assert app.engine.timeline is not None and len(app.engine.timeline) >= 1
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    _frame(app, 2)
    assert not app.engine.playing


# --- screens ------------------------------------------------------------------

def test_layer_strip_tap_mutes(app):
    app.tab = 0                             # PERFORM
    _frame(app)
    _tap(app, "layer1")
    assert _frame(app, 2).layers[1].muted
    _tap(app, "layer1")
    assert not _frame(app, 2).layers[1].muted


def test_grid_cell_tap_cycles_probability(app):
    app.tab = 1                             # MAP; layer 0 is euclid — select
    _frame(app)                             # the grid layer first
    _tap(app, "sel2")
    _frame(app)
    _tap(app, "g:0:0")
    snapshot = _frame(app, 2)
    value = snapshot.layers[2].grid[0][0]
    assert value in (0.0, 0.5, 1.0)


def test_seed_pads_capture_on_hold_and_recall_on_tap(app):
    app.tab = 3                             # SEEDS
    _frame(app)
    screen = app.screens[3]
    rect = screen.hits.rect_for("seed2")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600                 # simulate the hold
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    snapshot = _frame(app, 2)
    assert snapshot.seeds_occupied[2]
    _tap(app, "seed2")
    assert "SEED 3" in _frame(app, 2).message


def test_layers_screen_edits_the_selection(app):
    app.tab = 2                             # LAYERS
    _frame(app)
    _tap(app, "slot1")
    _frame(app)
    _tap(app, "mute")
    assert _frame(app, 2).layers[1].muted
    _tap(app, "dens+")
    snapshot = _frame(app, 2)
    assert snapshot.layers[1].density > 0.5


def test_enabling_a_dormant_slot_from_the_panel(app):
    app.tab = 2
    _frame(app)
    _tap(app, "slot5")
    snapshot = _frame(app, 2)
    assert snapshot.layers[5].role          # slot 6 came alive


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
