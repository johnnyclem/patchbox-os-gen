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

import ast
from pathlib import Path

import pygame
import pytest

from rangerkit.gui import theme
from rangerkit.gui.widgets import HitMap, button, lcd, pad, pad_face, panel

APPS = Path(__file__).resolve().parents[2]


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
    """§States: "empty pad — surface fill", "filled pad — well fill".

    This is the exact failure the light colourway was introduced to dodge, so
    it is worth asserting on every scheme rather than trusting one. Lightness
    alone is not enough of a test: on a near-black ground the surface and the
    well are only a few levels apart and it is the well's blue cast that does
    the separating, so measure the whole distance, not just the grey.

    The bar is deliberately low, because INDUSTRIAL only just clears it: the
    sheet's own #1A1A1A and #0D1A20 are 19 apart, most of that in one channel.
    That is the tightest the design system ever gets, it is a real risk on a
    washed panel, and DAYLIGHT — where the same pair is 537 apart — is the
    documented answer when a given unit cannot hold it. A stricter threshold
    here would fail the sheet rather than the code.
    """
    for name in theme.COLORWAY_NAMES:
        theme.apply(name)
        empty, filled = pad_face("empty"), pad_face("filled")
        assert empty == theme.BG_RAISED and filled == theme.BG_LCD, \
            f"{name}: empty/filled must be surface/well, in that order"
        distance = sum(abs(a - b) for a, b in zip(empty, filled))
        assert distance >= 18, \
            f"{name}: empty and filled pads collapse ({distance} apart)"


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


def test_an_empty_slot_is_a_surface_and_still_pressable():
    """The states matrix distinguishes an empty slot from a filled one by
    *surface*, not by an accent hue — a seed bank where every saved slot
    glowed orange claimed eight things were sounding. And unlike ``disabled``,
    an empty slot must stay pressable: pressing it is how you fill it."""
    theme.apply("industrial")
    canvas, hits = surface(), HitMap()
    empty = pygame.Rect(10, 10, 60, 44)
    button(canvas, hits, "s1", empty, "S1", filled=False)
    assert canvas.get_at((empty.x + 5, empty.y + 5))[:3] == theme.BG_RAISED

    full = pygame.Rect(10, 80, 60, 44)
    button(canvas, hits, "s2", full, "S2", filled=True)
    assert canvas.get_at((full.x + 5, full.y + 5))[:3] == theme.BG_LCD
    assert set(hits.keys()) == {"s1", "s2"}, "an empty slot must stay pressable"

    # The default is "not a slot at all" — an ordinary button must not quietly
    # become a well just because this parameter exists.
    plain = pygame.Rect(10, 150, 60, 44)
    button(canvas, hits, "s3", plain, "GO")
    assert canvas.get_at((plain.x + 5, plain.y + 5))[:3] == theme.BG_RAISED


# --- the suite, read as source ------------------------------------------------

def _button_calls():
    """Every ``button(...)`` call in every app's GUI, as (path, node)."""
    for path in sorted(APPS.glob("*/gui/**/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "button"):
                yield path, node


def test_no_button_passes_a_colour_it_cannot_use():
    """``color`` is the face used *when active*. Passing it with neither
    ``active`` nor ``kind`` does nothing whatsoever, silently.

    This is not hypothetical tidiness. Eighteen destructive controls — PANIC,
    CLEAR, CLEAR ROW, ERASE, REMOVE — passed ``color=theme.DANGER`` through
    this hole and rendered neutral grey on shipped panels, and thirty-four
    more carried an accent nobody ever saw. A linter cannot see it because
    the argument is real and the call is valid, so the gate has to live here.
    """
    offenders = []
    for path, node in _button_calls():
        kwargs = {k.arg for k in node.keywords}
        if "color" in kwargs and not {"active", "kind"} & kwargs:
            offenders.append(f"{path.relative_to(APPS)}:{node.lineno}")
    assert not offenders, (
        "button(color=...) with no active= or kind= is dead — either wire "
        "the state that makes it apply, or drop the argument:\n  "
        + "\n  ".join(offenders))


def test_nothing_passes_a_shadow_keyword():
    """§Component sheet: "No shadows, no gradients."

    ``panel()`` raises on the keyword now, but only for a screen some test
    actually draws. Reading the source catches the one nobody draws, which is
    exactly where a stale call survives.
    """
    offenders = []
    for path in sorted(APPS.glob("*/gui/**/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and any(
                    k.arg == "shadow" for k in node.keywords):
                offenders.append(f"{path.relative_to(APPS)}:{node.lineno}")
    assert not offenders, "shadows are out of the design system:\n  " + \
        "\n  ".join(offenders)


def test_a_meter_registers_no_hit():
    """§Screens/TRACKS: "meter is output, not input". A meter that can be
    pressed is a control the player will try to drag."""
    from rangerkit.gui.widgets import meter
    hits = HitMap()
    meter(surface(), pygame.Rect(0, 0, 120, 12), 0.5)
    assert len(hits) == 0
