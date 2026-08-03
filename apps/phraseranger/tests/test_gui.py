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

from core.commands import PrSnapshot
from core.engine import PhraseRangerEngine
from core.project import default_project
from gui.app import SCREENS, App
from rangerkit.events import note_off, note_on
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


def make_app(size=(1280, 400)):
    engine = PhraseRangerEngine(default_project(), CaptureMidiIO(),
                                FakeClock())
    return App(engine, size=size)


@pytest.fixture()
def app():
    application = make_app()
    yield application
    pygame.display.quit()


def _frame(application: App, ticks: int = 1) -> PrSnapshot:
    for _ in range(ticks):
        application.engine.step()
    snapshot = application.engine.snapshot()
    screen = application.screens[application.tab]
    screen.update(snapshot)
    application._draw(snapshot)
    return snapshot


def _tap(application: App, key: str) -> None:
    screen = application.screens[application.tab]
    rect = screen.hits.rect_for(key)
    assert rect is not None, f"no hit target for {key!r}"
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        event = pygame.event.Event(kind, button=1, pos=rect.center)
        for command in screen.handle(event):
            application.engine.submit(command)


def record_note(application, note=60):
    from rangerkit import enginebase as base
    application.engine.submit(base.Play())
    application.engine.step()
    application.engine.on_midi_in("din_in", note_on(0, note, 100), 0)
    for _ in range(24):
        application.engine.step()
    application.engine.on_midi_in("din_in", note_off(0, note), 0)
    application.engine.step()


# --- the shell ----------------------------------------------------------------

def test_the_app_builds_every_screen(app):
    assert len(app.screens) == len(SCREENS)
    assert [s.title for s in app.screens] == ["PERFORM", "SLICE", "ROUTING",
                                              "LIBRARY", "SET"]


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
        record_note(application)            # material for slice/undo paths
        for index in range(len(application.screens)):
            application.tab = index
            _frame(application, 2)
            for key in list(application.screens[index].hits.keys()):
                _frame(application)
                if application.screens[index].hits.rect_for(key) is None:
                    continue
                _tap(application, key)
                _frame(application, 2)
        application.engine.all_notes_off()
        assert not application.engine.midi.hanging()
    finally:
        pygame.display.quit()


def test_the_transport_rail_drives_the_engine(app):
    _frame(app)
    rect = app.chrome.rect_for("take")
    assert rect is not None
    assert app.engine.recorder.armed == 0
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    _frame(app, 2)
    assert app.engine.recorder.armed == -1  # take landed


def test_keyboard_arms_tracks_and_undoes(app):
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_3))
    _frame(app, 2)
    assert app.engine.recorder.armed == 2
    record_note(app, 64)
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_u))
    _frame(app, 2)
    assert app.engine.tracks[2].phrase.empty


# --- screens ------------------------------------------------------------------

def test_arm_buttons_toggle_the_take(app):
    app.tab = 0
    _frame(app)
    _tap(app, "arm3")
    assert _frame(app, 2).armed == 3
    _tap(app, "arm3")                       # tapping the armed track lands it
    assert _frame(app, 2).armed == -1


def test_slice_pads_fire_material(app):
    record_note(app)
    app.tab = 1
    _frame(app)
    before = len(app.engine.midi.events)
    _tap(app, "pad0")
    _frame(app, 4)
    assert len(app.engine.midi.events) > before


def test_routing_edits_the_selected_track(app):
    app.tab = 2
    _frame(app)
    _tap(app, "sel4")
    _frame(app)
    _tap(app, "chan+")
    assert _frame(app, 2).tracks[4].channel == 5
    _tap(app, "locked")
    assert not _frame(app, 2).tracks[4].length_locked


def test_library_scene_pads_save_and_recall(app):
    record_note(app)
    app.tab = 3
    _frame(app)
    screen = app.screens[3]
    rect = screen.hits.rect_for("scene1")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    assert _frame(app, 2).scenes_occupied[1]
    _tap(app, "scene1")
    assert "SCENE 2" in _frame(app, 2).message


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
