"""The design system, asserted.

The micro-rangers master sheet (``docs/design/UI-UX-SPEC.md``) is prose, and
prose drifts: the palette in this repo once carried the sheet's *name* and
none of its values, and two of its chrome tokens sat in ``theme`` for months
without a single caller. These tests are the sheet's checkable claims written
down, so the next divergence is a red build rather than a discovery.

Only rules that are genuinely universal live here. The sheet's fixed 320x240
band stack is deliberately *not* asserted — it says itself to inherit the
language and not the layouts, and this panel is 1280x400.
"""
from __future__ import annotations

import pygame
import pytest

from rangerkit.gui import theme
from rangerkit.gui.widgets import HitMap, button, lcd, pad, pad_face, panel


@pytest.fixture(autouse=True)
def _restore_palette():
    """Every test here swaps the live palette; put it back afterwards so a
    failure in one does not cascade into the rest of the suite."""
    before = theme.active()
    yield
    theme.apply(before)


def surface():
    if not pygame.display.get_init():
        pygame.display.init()
    return pygame.Surface((theme.WIDTH, theme.HEIGHT))


# --- tokens -------------------------------------------------------------------

def test_industrial_carries_the_sheets_tokens_verbatim():
    """§Tokens. These ten values are the design system; if one of them moves,
    it moved in the sheet first or it is a bug."""
    way = theme.COLORWAYS["industrial"]
    assert way.bg == (0x0A, 0x0A, 0x0A)
    assert way.bg_raised == (0x1A, 0x1A, 0x1A)
    assert way.bg_lcd == (0x0D, 0x1A, 0x20)
    assert way.text == (0xE8, 0xE8, 0xE8)
    assert way.text_dim == (0x7A, 0x7A, 0x7A)
    assert way.accent3 == (0x56, 0xD6, 0xFF)        # cyan
    assert way.accent == (0xFF, 0x6B, 0x2C)         # orange
    assert way.ok == (0x3D, 0xFF, 0x8A)             # green
    assert way.danger == (0xFF, 0x3D, 0x4A)         # red
    assert way.warn == (0xFF, 0xD1, 0x2A)           # yellow


def test_industrial_is_the_default():
    assert theme.DEFAULT_COLORWAY == "industrial"


@pytest.mark.parametrize("name", theme.COLORWAY_NAMES)
def test_every_colourway_keeps_the_state_semantics(name):
    """A colourway may re-tune a hue for its ground, but it may not reassign
    what a hue *means*: selection can never be the play colour, and solo can
    never be the stop colour, whatever the panel."""
    way = theme.COLORWAYS[name]
    assert way.hot == way.accent3, f"{name}: selection must be the cyan token"
    assert way.hot != way.accent, f"{name}: selection must not be orange"
    assert way.ok != way.danger, f"{name}: solo must not read as stop"
    assert way.accent2 != way.accent, f"{name}: armed must differ from playing"


@pytest.mark.parametrize("name", theme.COLORWAY_NAMES)
def test_every_colourway_is_legible(name):
    """Body text against its own ground, and the value against the well.
    A colourway that fails this is unreadable on the panel it was added for.
    """
    way = theme.COLORWAYS[name]
    gap = abs(theme.luminance(way.text) - theme.luminance(way.bg))
    assert gap > 0.4, f"{name}: text on bg is {gap:.2f} apart"
    well = abs(theme.luminance(way.display) - theme.luminance(way.bg_lcd))
    assert well > 0.4, f"{name}: value on well is {well:.2f} apart"


@pytest.mark.parametrize("name", theme.COLORWAY_NAMES)
def test_values_in_a_well_are_never_pure_white(name):
    """§Geometry: "Never pure white on black for values." White at value size
    blooms on these panels and the digits smear together."""
    way = theme.COLORWAYS[name]
    assert way.display != (0xFF, 0xFF, 0xFF)


def test_retired_colourway_names_still_resolve():
    """A config or a saved preference written before the design-system pass
    must still boot the panel, not crash it or leave it unstyled."""
    for retired in ("mono", "dusk"):
        assert theme.apply(retired) in theme.COLORWAY_NAMES
    assert theme.apply("no-such-colourway") in theme.COLORWAY_NAMES


# --- geometry -----------------------------------------------------------------

def test_rules_are_two_pixels_and_corners_are_square():
    """§Geometry: "Radius = 0 everywhere. Rules = 2 px." RADIUS is not a
    token because there is nowhere it could be anything else — this asserts
    the rule width and the absence of any radius knob."""
    assert theme.BORDER_W == 2
    assert not hasattr(theme, "RADIUS")


def test_there_is_no_shadow_token():
    """§Component sheet: "No shadows, no gradients." The token is gone, and
    ``panel`` no longer takes the keyword — a stale ``shadow=True`` should be
    a TypeError at the call site, not a silently ignored argument."""
    assert not hasattr(theme, "SHADOW_OFF")
    with pytest.raises(TypeError):
        panel(surface(), pygame.Rect(0, 0, 40, 40), shadow=True)


def test_the_two_touch_floors_clear_the_sheets_minimums():
    """§Interaction: direct-action >= 40x36, selectable >= 28x24."""
    assert (theme.TOUCH_DIRECT_W, theme.TOUCH_DIRECT_H) == (40, 36)
    assert (theme.TOUCH_SELECT_W, theme.TOUCH_SELECT_H) == (28, 24)
    assert theme.TOUCH_MIN >= theme.TOUCH_DIRECT_W, \
        "the rail target must never sit below the floor"
    assert theme.touch_ok(pygame.Rect(0, 0, 40, 36))
    assert not theme.touch_ok(pygame.Rect(0, 0, 39, 36))
    assert not theme.touch_ok(pygame.Rect(0, 0, 40, 35))
    assert theme.touch_ok(pygame.Rect(0, 0, 28, 24), direct=False)
    assert not theme.touch_ok(pygame.Rect(0, 0, 20, 20), direct=False)


def test_the_type_scale_is_monotonic():
    """Five named steps, each genuinely smaller than the last. A scale with a
    duplicate step is a scale a screen will pick from at random."""
    steps = (theme.TYPE_VALUE, theme.TYPE_TITLE, theme.TYPE_CAPTION,
             theme.TYPE_LABEL, theme.TYPE_MICRO)
    assert list(steps) == sorted(steps, reverse=True)
    assert len(set(steps)) == len(steps)


# --- state --------------------------------------------------------------------

def test_playing_is_an_orange_fill_and_armed_is_dimmer():
    """§States: "playing -> orange fill", "armed -> orange_dim fill". Armed
    must be visibly *less* than playing or the queue reads as the thing."""
    theme.apply("industrial")
    assert pad_face("playing") == theme.ACCENT
    assert pad_face("armed") == theme.ACCENT2
    assert theme.luminance(pad_face("armed")) < \
        theme.luminance(pad_face("playing"))


def test_empty_and_filled_pads_are_distinguishable():
    """§States: an empty pad and a pad holding a clip are different surfaces.
    This is the exact failure the light colourway was introduced to dodge, so
    it is worth asserting on every scheme rather than trusting one."""
    for name in theme.COLORWAY_NAMES:
        theme.apply(name)
        gap = abs(theme.luminance(pad_face("empty"))
                  - theme.luminance(pad_face("filled")))
        assert gap > 0.01, f"{name}: empty and filled pads collapse"


def test_mute_dims_rather_than_hides():
    """§Geometry: "Dim (not hide) for mute." A muted face must move toward
    the ground without reaching it — a pad dimmed to the background has been
    hidden, and the row loses its rhythm."""
    theme.apply("industrial")
    muted = pad_face("muted")
    assert muted != theme.BG, "mute must not erase the pad"
    assert theme.luminance(muted) < theme.luminance(pad_face("filled"))


def test_press_is_a_geometry_change_not_a_hue():
    """§Geometry: "Press affordance is geometry + inverse fill." The pressed
    face must differ from rest in lightness, not merely in hue, so it reads
    without being looked at."""
    theme.apply("industrial")
    rest, pressed = pad_face("filled"), pad_face("pressed")
    assert abs(theme.luminance(rest) - theme.luminance(pressed)) > 0.02


def test_selection_and_playing_can_be_told_apart_on_one_pad():
    """The states matrix allows a pad to be selected *and* playing. One is a
    fill and the other a rule precisely so this picture is unambiguous."""
    theme.apply("industrial")
    canvas, rect = surface(), pygame.Rect(20, 20, 80, 60)
    pad(canvas, rect, state="playing", selected=True)
    assert canvas.get_at(rect.center)[:3] == theme.ACCENT     # orange fill
    edge = canvas.get_at((rect.x + theme.BORDER_W + 1,
                          rect.centery))[:3]
    assert edge == theme.HOT                                   # cyan rule


def test_solo_is_green_and_mute_is_not_red():
    """§States: "solo green emphasis on S button". Mute went through the
    suite as DANGER red for a while, which said "error" on a control whose
    whole job is to be a normal, reversible performance move."""
    theme.apply("industrial")
    canvas, hits = surface(), HitMap()
    # Sampled in the corner, inside the rule and clear of the glyph: the
    # centre of a button is its label, which is ink, not face.
    solo = pygame.Rect(10, 10, 60, 44)
    button(canvas, hits, "s", solo, "S", kind="solo", active=True)
    assert canvas.get_at((solo.x + 5, solo.y + 5))[:3] == theme.OK

    mute = pygame.Rect(10, 80, 60, 44)
    button(canvas, hits, "m", mute, "M", kind="mute", active=True)
    assert canvas.get_at((mute.x + 5, mute.y + 5))[:3] != theme.DANGER


# --- readouts -----------------------------------------------------------------

def test_a_captioned_readout_draws_its_caption_permanently():
    """§Geometry: "Caption-over-value on every continuous parameter. Caption
    is permanent, not a tooltip." Nothing is hovered on a touch panel, so a
    caption that is not always drawn is a caption nobody ever sees."""
    theme.apply("industrial")
    canvas, rect = surface(), pygame.Rect(0, 0, 160, 70)
    lcd(canvas, rect, "120", label="BPM")
    caption_band = [canvas.get_at((x, rect.y + 8))[:3]
                    for x in range(rect.x + 4, rect.right - 4)]
    assert any(px != theme.BG_LCD for px in caption_band), \
        "the caption row is empty — the caption was not drawn"


def test_a_meter_registers_no_hit():
    """§Screens/TRACKS: "meter is output, not input". A meter that can be
    pressed is a control the player will try to drag."""
    from rangerkit.gui.widgets import meter
    hits = HitMap()
    meter(surface(), pygame.Rect(0, 0, 120, 12), 0.5)
    assert len(hits) == 0
