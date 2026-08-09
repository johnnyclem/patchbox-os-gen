"""The panel, on SDL's dummy video driver.

These are not screenshot tests. They assert the two things that actually
break a touch UI: that every control a screen *draws* is also registered as
a hit target (so no button is decorative), and that pressing every
registered control produces commands the engine accepts without raising —
at every shipped panel geometry. The 12×8 grid additionally asserts the
44 px touch floor on the wide bar.
"""
from __future__ import annotations

import pygame
import pytest

from core.clip import Clip, ClipNote
from core.commands import ScSnapshot
from core.engine import SceneRangerEngine
from core.project import default_project
from gui.app import SCREENS, App
from rangerkit.events import PPQN, TICKS_PER_BAR
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


def make_clip(*pitches, **fields):
    clip = Clip(**fields).normalised()
    for index, pitch in enumerate(pitches):
        clip = clip.with_note(ClipNote(tick=index * PPQN, note=pitch,
                                       velocity=100, length_ticks=24))
    return clip


def make_app(size=(1280, 400)):
    engine = SceneRangerEngine(default_project(), CaptureMidiIO(),
                               FakeClock())
    engine.grid.put(0, 0, make_clip(60, follow="next"))
    engine.grid.put(1, 0, make_clip(64))
    engine.grid.put(0, 1, make_clip(72))
    return App(engine, size=size)


@pytest.fixture()
def app():
    application = make_app()
    yield application
    pygame.display.quit()


def _frame(application: App, ticks: int = 1) -> ScSnapshot:
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


# --- the shell ----------------------------------------------------------------

def test_the_app_builds_every_screen(app):
    assert len(app.screens) == len(SCREENS)
    assert [s.title for s in app.screens] == ["PERFORM", "ROUTING",
                                              "ARRANGE", "LIBRARY"]


def test_every_screen_draws_without_raising(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 4)


def test_grid_cells_hold_the_touch_floor_on_the_bar(app):
    """A clip is a direct-action target: it fires on press, so it takes the
    design system's larger floor (40x36). The floor is deliberately not
    square — the bar is 400 px tall and a clip grid is wide by nature, so
    demanding 40 in *both* axes would cost a row of scenes to buy width
    nothing needs."""
    app.tab = 0
    _frame(app)
    cell = app.screens[0].hits.rect_for("c:0:0")
    assert cell is not None
    assert theme.touch_ok(cell), f"clip cell {cell.size} is below the floor"


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
                    continue
                _tap(application, key)
                _frame(application, 2)
        application.engine.all_notes_off()
        assert not application.engine.midi.hanging()
    finally:
        pygame.display.quit()


def test_keyboard_launches_scenes(app):
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_1))
    _frame(app, 2)
    assert app.engine.playing
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s))
    _frame(app, TICKS_PER_BAR)
    assert all(l.active < 0 for l in app.engine.launchers)
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    _frame(app, 2)
    assert not app.engine.playing


# --- screens ------------------------------------------------------------------

def test_cell_tap_launches_and_second_tap_stops(app):
    app.tab = 0
    _frame(app)
    _tap(app, "c:0:0")
    snapshot = _frame(app, 2)
    assert snapshot.playing
    assert snapshot.slots[0][0].playing or snapshot.slots[0][0].queued
    _frame(app, TICKS_PER_BAR)
    _tap(app, "c:0:0")                      # playing now: queues the stop
    _frame(app, TICKS_PER_BAR + 2)
    assert app.engine.launchers[0].active < 0


def test_empty_cell_arms_on_hold(app):
    app.tab = 0
    _frame(app)
    screen = app.screens[0]
    rect = screen.hits.rect_for("c:5:5")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    snapshot = _frame(app, 2)
    assert snapshot.armed == (5, 5)


def test_scene_column_fires_the_row(app):
    app.tab = 0
    _frame(app)
    _tap(app, "sc0")
    _frame(app, TICKS_PER_BAR + 2)
    assert app.engine.launchers[0].active == 0
    assert app.engine.launchers[1].active == 0


def test_routing_inspector_edits_the_clip(app):
    app.tab = 1
    _frame(app)
    _tap(app, "follow")
    snapshot = _frame(app, 2)
    assert snapshot.slots[0][0].follow != "next"    # cycled
    _tap(app, "trans+")
    assert _frame(app, 2).slots[0][0].transpose == 1


def test_arrange_builds_and_runs_a_chain(app):
    app.tab = 2
    _frame(app)
    _tap(app, "add0")
    _tap(app, "add1")
    snapshot = _frame(app, 2)
    assert snapshot.chain == ((0, 4), (1, 4))
    _tap(app, "chain")
    assert _frame(app, 2).chain_on
    _tap(app, "ent1")
    assert _frame(app, 2).chain == ((0, 4),)


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
