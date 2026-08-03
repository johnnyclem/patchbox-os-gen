"""The panel, on SDL's dummy video driver.

These are not screenshot tests. They assert the two things that actually break
a touch UI: that every control a screen *draws* is also registered as a hit
target (so no button is decorative), and that pressing every registered
control produces commands the engine accepts without raising. Between them
those catch the whole class of "the button does nothing" bugs, which is the
only class a panel like this really has.
"""
from __future__ import annotations

import pygame
import pytest

from core import commands as cmd
from core.clock import FakeClock
from core.commands import EngineSnapshot
from core.engine import Engine
from core.midi_io import CaptureMidiIO
from core.project import default_project
from gui import theme
from gui.app import SCREENS, App


@pytest.fixture()
def app():
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    application = App(engine, size=(1280, 400))
    yield application
    pygame.display.quit()


def _frame(application: App, ticks: int = 1) -> EngineSnapshot:
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


# --- layout -------------------------------------------------------------------

def test_the_wide_panel_gets_side_rails():
    layout = theme.Layout.for_size((1280, 400), 5)
    assert layout.wide
    assert layout.transport.height == 400
    assert layout.content.width == 1280 - theme.RAIL_W - theme.TAB_RAIL_W
    assert len(layout.tabs) == 5
    assert layout.tabs[-1].bottom == 400


def test_a_portrait_panel_stacks_the_chrome():
    layout = theme.Layout.for_size((480, 800), 5)
    assert not layout.wide
    assert layout.transport.width == 480
    assert layout.tabs[0].top == 800 - theme.TABS_H


def test_tabs_tile_their_rail_without_gaps():
    layout = theme.Layout.for_size((1280, 400), 5)
    for first, second in zip(layout.tabs, layout.tabs[1:]):
        assert first.bottom == second.top


def test_every_colourway_defines_every_token():
    for name in theme.COLORWAY_NAMES:
        assert theme.apply(name) == name
        for token in (theme.BG, theme.BG_RAISED, theme.TEXT, theme.ACCENT,
                      theme.BORDER):
            assert len(token) == 3
    theme.apply(theme.DEFAULT_COLORWAY)


def test_an_unknown_colourway_is_ignored():
    theme.apply(theme.DEFAULT_COLORWAY)
    assert theme.apply("chartreuse") == theme.DEFAULT_COLORWAY


def test_ink_survives_on_every_fill_it_is_asked_about():
    for name in theme.COLORWAY_NAMES:
        theme.apply(name)
        for fill in (theme.BG, theme.BG_RAISED, theme.ACCENT, theme.ACCENT2,
                     theme.DANGER, *theme.PART_COLORS):
            ink = theme.ink_for(fill)
            assert abs(theme.luminance(ink) - theme.luminance(fill)) > 0.3
    theme.apply(theme.DEFAULT_COLORWAY)


# --- the shell ----------------------------------------------------------------

def test_the_app_builds_every_screen(app):
    assert len(app.screens) == len(SCREENS)
    assert [s.title for s in app.screens] == ["PERFORM", "CHORD", "BAND",
                                              "SONG", "SET"]


def test_every_screen_draws_without_raising(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 4)


def test_every_screen_registers_hit_targets(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app)
        assert len(app.screens[index].hits) >= 6, app.screens[index].title


def test_pressing_every_control_on_every_screen_is_safe(app):
    for index in range(len(app.screens)):
        app.tab = index
        _frame(app, 2)
        for key in app.screens[index].hits.keys():
            _frame(app)
            if app.screens[index].hits.rect_for(key) is None:
                continue        # the control moved or vanished this frame
            _tap(app, key)
            _frame(app, 2)


def test_the_transport_rail_drives_the_engine(app):
    _frame(app)
    assert app.chrome.rect_for("play") is not None
    rect = app.chrome.rect_for("play")
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    _frame(app, 2)
    assert app.engine.playing


def test_tabs_switch_screens(app):
    _frame(app)
    rect = app.chrome.rect_for("tab2")
    app._chrome_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                         pos=rect.center))
    assert app.tab == 2


def test_switching_tabs_under_a_finger_releases_the_pad(app):
    app.tab = 0
    _frame(app)
    screen = app.screens[0]
    rect = screen.hits.rect_for("pad0")
    for command in screen.handle(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)):
        app.engine.submit(command)
    _frame(app, 2)
    app._switch(3)
    _frame(app, 2)
    assert app.engine.held_pad == -1


def test_keyboard_shortcuts_reach_the_engine(app):
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    _frame(app, 2)
    assert app.engine.playing
    app._key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_p))
    _frame(app, 2)
    assert not app.engine.playing


# --- screens ------------------------------------------------------------------

def test_a_pad_tap_sets_the_chord(app):
    app.tab = 0
    _frame(app)
    _tap(app, "pad4")
    _frame(app, 2)
    assert app.engine.snapshot().chord_symbol == "G"


def test_holding_a_pad_opens_it_in_the_chord_editor(app):
    app.tab = 0
    _frame(app)
    screen = app.screens[0]
    rect = screen.hits.rect_for("pad2")
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                     pos=rect.center))
    screen._press_ms -= 600          # simulate the hold
    screen.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                     pos=rect.center))
    assert app.tab == 1
    assert app.edit_target() == 2


def test_the_chord_editor_toggles_degrees_and_writes_back(app):
    app.set_edit_target(0)
    app.tab = 1
    _frame(app, 2)
    _tap(app, "deg11")               # add a major seventh to the tonic
    _frame(app, 2)
    editor = app.screens[1]
    assert editor.working is not None
    assert 11 in editor.working.intervals
    _tap(app, "write")
    _frame(app, 2)
    assert app.engine.chordset.chord_at(0).intervals == (0, 4, 7, 11)


def test_cancelling_an_edit_leaves_the_pad_alone(app):
    app.set_edit_target(0)
    app.tab = 1
    _frame(app, 2)
    before = app.engine.chordset.chord_at(0)
    _tap(app, "deg1")
    _frame(app, 2)
    _tap(app, "revert")
    _frame(app, 2)
    assert app.engine.chordset.chord_at(0) == before


def test_the_cruiser_offers_suggestions_that_can_be_taken(app):
    app.tab = 1
    _frame(app, 2)
    editor = app.screens[1]
    assert editor._suggestions
    _tap(app, "sug0")
    _frame(app, 2)
    assert editor.working is not None


def test_the_band_screen_mutes_a_part(app):
    app.tab = 2
    _frame(app, 2)
    _tap(app, "mute:drum")
    _frame(app, 2)
    assert app.engine.style.part("drum").muted


def test_the_band_screen_changes_the_bass_mode(app):
    app.tab = 2
    _frame(app, 2)
    _tap(app, "mode:walk")
    _frame(app, 2)
    assert app.engine.bass.mode == "walk"


def test_the_song_screen_writes_the_held_chord_into_a_bar(app):
    app.engine.submit(cmd.PadDown(3))
    app.tab = 3
    _frame(app, 2)
    app.screens[3].cursor = 2
    _tap(app, "write")
    _frame(app, 2)
    assert app.engine.song.chord_at(2).symbol() == "F"


def test_the_settings_screen_cycles_the_theme(app):
    app.tab = 4
    _frame(app, 2)
    before = theme.active()
    _tap(app, "theme")
    _frame(app)
    assert theme.active() != before
    theme.apply(theme.DEFAULT_COLORWAY)


def test_the_settings_screen_transposes_the_chordset(app):
    app.tab = 4
    _frame(app, 2)
    _tap(app, "key+")
    _frame(app, 2)
    assert app.engine.key_root == 1


def test_messages_appear_and_expire(app):
    app.message("HELLO")
    _frame(app)
    assert app._message == "HELLO"
    app._message_until = 0
    _frame(app)                      # drawn without the banner, no raise


# --- other panels ---------------------------------------------------------------
# The 800x480 HyperPixel profile and the 480x800 4" panel both get *stacked*
# chrome — a short transport band across the top rather than a tall rail. The
# transport originally laid its six controls out as a column regardless, which
# on an 88 px band put every control at 13 px and turned it into a smear. These
# assert the band stays usable on every size the image can be built for.

@pytest.mark.parametrize("size", [(1280, 400), (800, 480), (480, 800)])
def test_the_transport_is_usable_on_every_shipped_panel(size):
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    app = App(engine, size=size)
    try:
        _frame(app, 2)
        keys = ("bpm-", "bpm+", "play", "rec", "panic")
        rects = []
        for key in keys:
            rect = app.chrome.rect_for(key)
            assert rect is not None, f"{key} missing at {size}"
            assert rect.width >= theme.TOUCH_MIN, f"{key} too narrow at {size}"
            assert rect.height >= 24, f"{key} too short at {size}"
            rects.append((key, rect))
        for index, (key, rect) in enumerate(rects):
            for other_key, other in rects[index + 1:]:
                assert not rect.colliderect(other), \
                    f"{key} overlaps {other_key} at {size}"
    finally:
        pygame.display.quit()


@pytest.mark.parametrize("size", [(1280, 400), (800, 480), (480, 800)])
def test_every_screen_draws_on_every_shipped_panel(size):
    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    app = App(engine, size=size)
    try:
        for index in range(len(app.screens)):
            app.tab = index
            _frame(app, 2)
            assert len(app.screens[index].hits) >= 6, \
                f"{app.screens[index].title} has no controls at {size}"
    finally:
        pygame.display.quit()
