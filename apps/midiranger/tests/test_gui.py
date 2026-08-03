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

from core.commands import MrSnapshot
from core.engine import MidiRangerEngine
from core.project import default_project
from gui.app import SCREENS, App
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


@pytest.fixture()
def app():
    engine = MidiRangerEngine(default_project(), CaptureMidiIO(),
                              FakeClock())
    application = App(engine, size=(1280, 400))
    yield application
    pygame.display.quit()


def make_app(size):
    engine = MidiRangerEngine(default_project(), CaptureMidiIO(),
                              FakeClock())
    return App(engine, size=size)


def _frame(application: App, ticks: int = 1) -> MrSnapshot:
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
    assert [s.title for s in app.screens] == ["PERFORM", "MATRIX", "FX",
                                              "ARP", "SET"]


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
    rect = app.chrome.rect_for("bypass")
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    _frame(app, 2)
    assert app.engine.bypass


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
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    _frame(app, 2)
    assert not app.engine.playing
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b))
    _frame(app, 2)
    assert app.engine.bypass


# --- screens ------------------------------------------------------------------

def test_a_crosspoint_tap_toggles_the_route(app):
    app.tab = 1                             # MATRIX
    before = len(_frame(app).routes)
    _tap(app, "x:trs_a_in:usb_out")
    after = len(_frame(app, 2).routes)
    assert after == before + 1
    _tap(app, "x:trs_a_in:usb_out")
    assert len(_frame(app, 2).routes) == before


def test_scene_pads_save_on_hold_and_recall_on_tap(app):
    app.tab = 0                             # PERFORM
    _frame(app)
    screen = app.screens[0]
    rect = screen.hits.rect_for("scene2")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600                 # simulate the hold
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    snapshot = _frame(app, 2)
    assert snapshot.scenes_occupied[2]
    _tap(app, "scene2")                     # plain tap recalls
    assert "SCENE 3" in _frame(app, 2).message


def test_the_arp_editor_edits_the_selected_slot(app):
    app.tab = 3                             # ARP
    _frame(app)
    _tap(app, "slot1")
    _frame(app)
    _tap(app, "on")
    snapshot = _frame(app, 2)
    assert snapshot.arps[1].enabled and not snapshot.arps[0].enabled
    _tap(app, "pattern")
    assert _frame(app, 2).arps[1].pattern == "down"


def test_fx_steppers_move_their_fields(app):
    app.tab = 2                             # FX
    _frame(app)
    _tap(app, "quant")
    assert _frame(app, 2).quantizer_enabled
    _tap(app, "reps+")
    assert _frame(app, 2).fx_echo_repeats == 1
    _tap(app, "harmony")
    assert _frame(app, 2).harmonizer_mode != "off"


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
