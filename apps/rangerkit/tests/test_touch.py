"""Touch input: finger→pointer translation for the capacitive bar panel.

The bug these guard against: the kiosk unit pins SDL_TOUCH_MOUSE_EVENTS=0
and every Ranger GUI only listened for MOUSEBUTTON*. Capacitive HID panels
(ElecLab 1280×400) emit FINGER* only, so the panel rendered perfectly and
every tap was silently dropped — including RangerDeck tile launches.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame                                        # noqa: E402

from rangerkit.gui import touch                      # noqa: E402

PANEL = (1280, 400)


@pytest.fixture
def translator() -> touch.TouchTranslator:
    return touch.TouchTranslator(PANEL)


def finger(kind: int, x: float, y: float, finger_id: int = 1
           ) -> pygame.event.Event:
    return pygame.event.Event(kind, touch_id=1, finger_id=finger_id,
                              x=x, y=y, dx=0.0, dy=0.0)


# --- the hint ----------------------------------------------------------------------

def test_configure_pins_the_sdl_hint_off_by_default(monkeypatch):
    monkeypatch.delenv(touch.MODE_ENV, raising=False)
    monkeypatch.delenv(touch.HINT_TOUCH_MOUSE, raising=False)
    assert touch.configure() == "native"
    # 0, not merely unset: the default flips between SDL builds, and the app
    # now owns the translation.
    assert os.environ[touch.HINT_TOUCH_MOUSE] == "0"


def test_configure_can_hand_the_job_back_to_sdl(monkeypatch):
    monkeypatch.setenv(touch.MODE_ENV, "sdl")
    assert touch.configure() == "sdl"
    assert os.environ[touch.HINT_TOUCH_MOUSE] == "1"


def test_configure_ignores_a_typo_rather_than_dying(monkeypatch):
    monkeypatch.setenv(touch.MODE_ENV, "yes-please")
    assert touch.configure() == "native"


# --- translation -------------------------------------------------------------------

def test_tap_becomes_a_left_click_in_pixels(translator):
    down = translator.translate(finger(pygame.FINGERDOWN, 0.5, 0.25))
    assert down.type == pygame.MOUSEBUTTONDOWN
    assert down.button == 1
    assert down.pos == (640, 100)
    up = translator.translate(finger(pygame.FINGERUP, 0.5, 0.25))
    assert up.type == pygame.MOUSEBUTTONUP
    assert up.pos == (640, 100)
    assert translator.taps == 1


def test_the_far_corner_stays_inside_the_surface(translator):
    down = translator.translate(finger(pygame.FINGERDOWN, 1.0, 1.0))
    assert down.pos == (PANEL[0] - 1, PANEL[1] - 1)


def test_out_of_range_axes_clamp_instead_of_flying_off(translator):
    # A panel with a wrong evdev axis range: an edge tap should still land on
    # the edge button rather than off the surface.
    down = translator.translate(finger(pygame.FINGERDOWN, 1.4, -0.3))
    assert down.pos == (PANEL[0] - 1, 0)


def test_drag_reports_motion_with_the_button_held(translator):
    translator.translate(finger(pygame.FINGERDOWN, 0.0, 0.0))
    motion = translator.translate(finger(pygame.FINGERMOTION, 0.5, 0.5))
    assert motion.type == pygame.MOUSEMOTION
    assert motion.buttons == (1, 0, 0)
    assert motion.pos == (640, 200)
    assert motion.rel == (640, 200)


def test_a_second_contact_cannot_steal_the_press(translator):
    """A palm on a bar panel must not interleave presses on a UI that only
    understands one."""
    assert translator.translate(finger(pygame.FINGERDOWN, 0.1, 0.5, 1))
    assert translator.translate(finger(pygame.FINGERDOWN, 0.9, 0.5, 2)) is None
    assert translator.translate(
        finger(pygame.FINGERMOTION, 0.8, 0.5, 2)) is None
    assert translator.translate(finger(pygame.FINGERUP, 0.9, 0.5, 2)) is None
    assert translator.taps == 1
    assert translator.dropped == 1
    # …and the real finger still gets its release.
    up = translator.translate(finger(pygame.FINGERUP, 0.1, 0.5, 1))
    assert up.type == pygame.MOUSEBUTTONUP


def test_a_lost_release_does_not_latch_the_pointer(translator):
    """Same finger id down twice means we missed a FINGERUP. Re-press —
    latching would eat every tap for the rest of the session."""
    translator.translate(finger(pygame.FINGERDOWN, 0.1, 0.5, 1))
    again = translator.translate(finger(pygame.FINGERDOWN, 0.2, 0.5, 1))
    assert again is not None
    assert again.type == pygame.MOUSEBUTTONDOWN
    assert translator.taps == 2


def test_sdl_synthesised_mouse_events_are_dropped(translator):
    """Belt and braces: the hint is off, but if some SDL build synthesises
    anyway, one tap must not be acted on twice."""
    synthetic = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=(10, 10), touch=True)
    assert translator.translate(synthetic) is None


def test_a_real_mouse_still_works(translator):
    """X11 pointer-emulated touch and a plugged-in mouse both arrive as
    ordinary events, and must pass straight through."""
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 10))
    assert translator.translate(event) is event


def test_unrelated_events_pass_through(translator):
    event = pygame.event.Event(pygame.QUIT)
    assert translator.translate(event) is event


def test_sdl_mode_translates_nothing():
    translator = touch.TouchTranslator(PANEL, mode="sdl")
    synthetic = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=(10, 10), touch=True)
    assert translator.translate(synthetic) is synthetic
    down = finger(pygame.FINGERDOWN, 0.5, 0.5)
    assert translator.translate(down) is down


def test_status_reports_devices_and_taps(translator):
    assert "taps" in translator.status()
    translator.translate(finger(pygame.FINGERDOWN, 0.5, 0.5))
    assert "1 taps" in translator.status()


def test_resize_updates_pixel_math(translator):
    translator.resize((640, 200))
    down = translator.translate(finger(pygame.FINGERDOWN, 0.5, 0.5))
    assert down.pos == (320, 100)
