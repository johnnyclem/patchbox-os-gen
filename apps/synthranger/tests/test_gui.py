"""The panel, on SDL's dummy video driver: every drawn control is a hit
target, and pressing all of them at every shipped geometry leaves nothing
hanging — MIDI bookings or synth voices.
"""
from __future__ import annotations

import pygame
import pytest

from core.commands import SySnapshot
from core.engine import SynthRangerEngine
from core.project import default_project
from core.voices import Synth
from gui.app import SCREENS, App
from rangerkit.audio.bridge import SynthMidiBridge
from rangerkit.gui import theme
from rangerkit.testkit import CaptureMidiIO, FakeClock, GEOMETRIES


def make_app(size=(1280, 400)):
    capture = CaptureMidiIO()
    synth = Synth()
    engine = SynthRangerEngine(default_project(),
                               SynthMidiBridge(capture, synth),
                               FakeClock())
    app = App(engine, size=size, synth=synth)
    return app, capture, synth


@pytest.fixture()
def app():
    application, _capture, _synth = make_app()
    yield application
    pygame.display.quit()


def _frame(application: App, ticks: int = 1) -> SySnapshot:
    for _ in range(ticks):
        application.engine.step()
    snapshot = application.engine.snapshot()
    application._sync_synth(snapshot)
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
    assert [s.title for s in app.screens] == ["PERFORM", "EDIT",
                                              "BROWSER", "MIX", "SET"]


def test_every_screen_draws_without_raising(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 4)


@pytest.mark.parametrize("size", GEOMETRIES)
def test_pressing_every_control_on_every_screen_is_safe(size):
    application, capture, synth = make_app(size)
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
        _frame(application, 2)
        assert not capture.hanging()
        assert not synth.hanging_voices()
    finally:
        pygame.display.quit()


def test_a_key_press_sounds_and_the_lift_releases(app):
    app.tab = 0
    _frame(app)
    screen = app.screens[0]
    rect = screen.hits.rect_for("k0")
    for kind in (pygame.MOUSEBUTTONDOWN,):
        for command in screen.handle(pygame.event.Event(
                kind, button=1, pos=rect.center)):
            app.engine.submit(command)
    _frame(app, 2)
    assert app.engine.snapshot().held_notes
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONUP, button=1, pos=rect.center)):
        app.engine.submit(command)
    _frame(app, 2)
    assert not app.engine.snapshot().held_notes
    assert not app.engine.midi.hanging()


def test_xy_drag_streams_positions(app):
    app.tab = 0
    _frame(app)
    screen = app.screens[0]
    pad = screen.hits.rect_for("xy")
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                              pos=pad.center)
    for command in screen.handle(down):
        app.engine.submit(command)
    move = pygame.event.Event(pygame.MOUSEMOTION, pos=pad.topright)
    for command in screen.handle(move):
        app.engine.submit(command)
    snapshot = _frame(app, 2)
    assert snapshot.xy[0] > 0.9 and snapshot.xy[1] > 0.9
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                     pos=pad.topright))


def test_browser_loads_a_preset_into_part_a(app):
    app.tab = 2
    _frame(app)
    assert app.presets()
    _tap(app, "pre0")
    snapshot = _frame(app, 2)
    assert snapshot.parts[0].name != "INIT"
    assert app.synth.parts[0].patch.name != "INIT"   # synced via rev


def test_edit_screen_changes_the_engine(app):
    app.tab = 1
    _frame(app)
    _tap(app, "engine")
    snapshot = _frame(app, 2)
    assert snapshot.parts[0].engine == "fm"          # cycled va → fm
    _tap(app, "cut-")
    assert _frame(app, 2).parts[0].patch["cutoff"] == 0.75


def test_mix_screen_routes_the_matrix(app):
    app.tab = 3
    _frame(app)
    _tap(app, "src0")
    snapshot = _frame(app, 2)
    assert snapshot.parts[0].mods[0].source != "xy_x"    # cycled
    _tap(app, "mute1")
    assert _frame(app, 2).parts[1].muted


def test_theme_tokens_hold_on_every_colourway(app):
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT,
                     theme.DANGER):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)
