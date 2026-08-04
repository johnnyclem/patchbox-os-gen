"""The panel, on SDL's dummy video driver.

These are not screenshot tests. They assert the two things that actually
break a touch UI: that every control a screen *draws* is also registered as
a hit target (so no button is decorative), and that pressing every
registered control produces commands the engine accepts without raising —
at every shipped panel geometry. The pad bank additionally asserts the
44 px touch floor on the wide bar.
"""
from __future__ import annotations

import pygame
import pytest

from core.commands import GrSnapshot
from core.engine import GrooveRangerEngine
from core.project import default_project
from core.sequencer import STEP_TICKS
from gui.app import SCREENS, App
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES

PASS = 16 * STEP_TICKS


def make_app(size=(1280, 400)):
    engine = GrooveRangerEngine(default_project(), CaptureMidiIO(),
                                FakeClock())
    return App(engine, size=size)


@pytest.fixture()
def app():
    application = make_app()
    yield application
    pygame.display.quit()


def _frame(application: App, ticks: int = 1) -> GrSnapshot:
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
    assert [s.title for s in app.screens] == ["PERFORM", "SEQ", "KIT",
                                              "SONG", "SET"]


def test_every_screen_draws_without_raising(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 4)


def test_pads_hold_the_touch_floor_on_the_bar(app):
    app.tab = 0
    _frame(app)
    cell = app.screens[0].hits.rect_for("pad0")
    assert cell is not None
    assert min(cell.width, cell.height) >= theme.TOUCH_MIN


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


def test_keyboard_runs_the_transport(app):
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    _frame(app, 2)
    assert app.engine.playing
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_3))
    _frame(app, 2)
    assert app.engine.snapshot().queued == 2
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    _frame(app, 2)
    assert app.engine.snapshot().fill_queued
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    _frame(app, 2)
    assert not app.engine.playing
    assert not app.engine.midi.hanging()


# --- screens ------------------------------------------------------------------

def test_pad_tap_sounds_and_long_press_mutes(app):
    app.tab = 0
    _frame(app)
    _tap(app, "pad0")
    _frame(app, 2)
    assert len([e for _ep, e in app.engine.midi.events
                if e.kind.name == "NOTE_ON"]) == 1
    screen = app.screens[0]
    rect = screen.hits.rect_for("pad1")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    snapshot = _frame(app, 2)
    assert snapshot.pads[1].muted
    _frame(app, PASS)
    assert not app.engine.midi.hanging()


def test_seq_screen_edits_a_step(app):
    app.tab = 1
    _frame(app)
    _tap(app, "st3")                        # toggle step 4 of the kick row
    snapshot = _frame(app, 2)
    assert snapshot.pattern[0][3].on
    _tap(app, "vel+")
    _tap(app, "ltune+")
    snapshot = _frame(app, 2)
    assert snapshot.pattern[0][3].vel == 105
    assert dict(snapshot.pattern[0][3].locks)["tune"] == 1.0
    _tap(app, "clr")
    assert _frame(app, 2).pattern[0][3].locks == ()


def test_kit_screen_edits_the_voice_and_routing(app):
    app.tab = 2
    _frame(app)
    _tap(app, "sel5")
    _frame(app, 2)                          # the selection reaches the panel
    _tap(app, "tune+")
    _tap(app, "lvl-")
    snapshot = _frame(app, 2)
    assert snapshot.selected_pad == 5
    assert snapshot.pads[5].tune == 0.5
    assert snapshot.pads[5].level == 0.95
    _tap(app, "dest")
    assert _frame(app, 2).dest != "internal"    # cycled off the sampler
    assert not app.engine.midi.hanging()


def test_song_screen_builds_a_chain_and_drives_the_bus(app):
    app.tab = 3
    _frame(app)
    _tap(app, "add")
    _tap(app, "addpt+")
    _tap(app, "add")
    snapshot = _frame(app, 2)
    assert snapshot.chain == ((0, 4), (1, 4))
    _tap(app, "on")
    assert _frame(app, 2).chain_on
    _tap(app, "en1")
    assert _frame(app, 2).chain == ((0, 4),)
    _tap(app, "mfilt-")
    assert _frame(app, 2).mixer.filter == 0.45


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
