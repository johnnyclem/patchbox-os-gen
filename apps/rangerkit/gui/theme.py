"""Design tokens and the adaptive chrome geometry.

The palette is the light-industrial scheme the RK-00pi panel settled on, for
the same reason: the reference display is a 1280x400 HDMI bar with a heavy
blue cast and a shallow black, on which three near-black surfaces all collapse
into the same washed navy and a filled pad becomes indistinguishable from an
empty one at arm's length. Separating surfaces by *lightness against a light
ground*, and drawing every rule in true black, is what survives that panel — a
black line is the one thing a bad LCD still renders exactly.

Semantics hold across every colourway: ACCENT is play/active, ACCENT2 is
arm/record/queued, ACCENT3 is focus/selection, DANGER is stop/delete.

Geometry lives in ``Layout``. On the bar panel vertical space is the scarce
resource, so the chrome turns sideways — transport down the left, tabs down
the right, and the content keeps all 400 px of height. A portrait panel gets
the ordinary top-bar/bottom-tabs stack instead.

Nothing here imports the engine, and nothing in the GUI may capture a colour
at import time (no ``color=theme.X`` default arguments, no module-level colour
tables): ``apply`` rebinds these names in place, and a captured value would
keep the old palette forever.
"""
from __future__ import annotations

from dataclasses import dataclass

import pygame

# --- metrics ------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 400       # the reference touch bar
PORTRAIT_SIZE = (480, 800)
RAIL_W = 150                    # wide: transport rail, left edge
TAB_RAIL_W = 112                # wide: tab rail, right edge
TRANSPORT_H = 88                # portrait: top transport band
TABS_H = 46                     # portrait: bottom tab strip
CLOSE_H = 48                    # deck mode: the ✕ corner, top-left
WIDE_ASPECT = 2.0
TOUCH_MIN = 44                  # smallest hit target we will draw
BORDER_W = 2                    # every rule; black, never a hairline (RADIUS 0)
SHADOW_OFF = 2                  # hard offset shadow, no blur (design: 2/2 px)
PAD_GAP = 4                     # base grid unit
# micro-rangers chrome bands, scaled for the 1280×400 bar (design was 320×240)
STATUS_H = 40                   # status ribbon (design 18 px → ~2×)
LEGEND_H = 32                   # encoder legend (design 16 px → 2×)
FOCUS_W = 3                     # orange focus ring thickness

def is_wide(area) -> bool:
    """True for anything at least 2:1 — the panel, and equally the content
    rect inside it. Accepts a Rect or a (w, h) pair."""
    width, height = ((area.width, area.height) if hasattr(area, "width")
                     else area)
    return width >= WIDE_ASPECT * max(1, height)


@dataclass(frozen=True, slots=True)
class Layout:
    """Where the chrome sits for one window size. ``tabs`` is one rect per
    tab, in the order the App passes the names, so no screen ever does
    geometry and the two orientations differ in exactly one place."""

    width: int
    height: int
    wide: bool
    transport: pygame.Rect
    content: pygame.Rect
    tabs: tuple[pygame.Rect, ...]
    # Deck mode only: the ✕ that hands the panel back to the launcher. It
    # takes its corner *out of* the transport chrome rather than floating
    # over it — nothing on an appliance panel may be covered by anything.
    close: pygame.Rect | None = None

    @classmethod
    def for_size(cls, size: tuple[int, int], tab_count: int,
                 close_button: bool = False) -> "Layout":
        width, height = size
        count = max(1, tab_count)
        if is_wide(size):
            close = pygame.Rect(0, 0, RAIL_W, CLOSE_H) if close_button \
                else None
            rail_top = CLOSE_H if close_button else 0
            transport = pygame.Rect(0, rail_top, RAIL_W, height - rail_top)
            tab_x = width - TAB_RAIL_W
            # Slice from the edges so the last tab absorbs the rounding
            # remainder instead of leaving a dead strip at the bottom.
            tabs = tuple(
                pygame.Rect(tab_x, i * height // count, TAB_RAIL_W,
                            (i + 1) * height // count - i * height // count)
                for i in range(count))
            content = pygame.Rect(RAIL_W, 0, tab_x - RAIL_W, height)
            return cls(width, height, True, transport, content, tabs, close)
        close_w = TOUCH_MIN + 12
        close = pygame.Rect(0, 0, close_w, TRANSPORT_H) if close_button \
            else None
        band_x = close_w if close_button else 0
        transport = pygame.Rect(band_x, 0, width - band_x, TRANSPORT_H)
        tabs = tuple(
            pygame.Rect(i * width // count, height - TABS_H,
                        (i + 1) * width // count - i * width // count, TABS_H)
            for i in range(count))
        content = pygame.Rect(0, TRANSPORT_H, width,
                              height - TRANSPORT_H - TABS_H)
        return cls(width, height, False, transport, content, tabs, close)


# --- colourways ---------------------------------------------------------------

Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Colorway:
    """One complete palette — a value that is swapped whole, never patched.

    Tokens follow the micro-rangers design handoff (2026-08-06): RADIUS 0,
    numbers in black LCD wells, focus is HOT orange, never colour alone for
    press (geometry drop). ``ink_dark``/``ink_light`` are the two inks
    ``ink_for`` picks between.
    """

    name: str
    label: str
    bg: Rgb
    bg_raised: Rgb
    bg_sunken: Rgb
    bg_press: Rgb
    bg_lcd: Rgb
    border: Rgb
    text: Rgb
    text_dim: Rgb
    text_muted: Rgb
    ink_dark: Rgb
    ink_light: Rgb
    accent: Rgb          # primary / play / rec (ACCENT2 in the handoff)
    accent2: Rgb         # secondary warm (kept for suite compatibility)
    accent3: Rgb         # cool secondary / chip
    hot: Rgb             # focus ring (HOT)
    danger: Rgb
    warn: Rgb
    display: Rgb         # LCD cyan
    display_dim: Rgb     # LCD caption
    parts: tuple[Rgb, ...]


# Track / part chips on a light industrial ground (LAUNCH ribbon colours).
_LIGHT_PARTS: tuple[Rgb, ...] = (
    (0xE8, 0x5D, 0x04), (0xC4, 0x7A, 0x4A), (0x2A, 0xA0, 0x8A),
    (0x3A, 0x5A, 0x7A), (0xD4, 0xA0, 0x17), (0x7A, 0x4A, 0x9A),
    (0x20, 0xA0, 0xD0), (0xC0, 0x4A, 0x8A))
_DARK_PARTS: tuple[Rgb, ...] = (
    (0xF0, 0x90, 0x40), (0xD0, 0xA0, 0x70), (0x40, 0xC0, 0xA8),
    (0x70, 0x90, 0xB0), (0xE8, 0xC0, 0x40), (0xB0, 0x80, 0xD0),
    (0x50, 0xC0, 0xE8), (0xE0, 0x70, 0xB0))

# micro-rangers INDUSTRIAL tokens (design handoff §Tokens).
INDUSTRIAL = Colorway(
    name="industrial", label="INDUSTRIAL",
    bg=(0xB8, 0xB4, 0xAC),          # panel face
    bg_raised=(0xD0, 0xCC, 0xC4),    # button rest
    bg_sunken=(0x9A, 0x96, 0x8E),    # wells, empty
    bg_press=(0x8A, 0x86, 0x80),     # geometry press
    bg_lcd=(0x0A, 0x0A, 0x0A),       # black well
    border=(0x0A, 0x0A, 0x0A),       # 2 px hard rule
    text=(0x12, 0x12, 0x12),
    text_dim=(0x4A, 0x4A, 0x44),
    text_muted=(0x6A, 0x6A, 0x64),
    ink_dark=(0x12, 0x12, 0x12),
    ink_light=(0xF6, 0xF6, 0xF4),
    accent=(0xC4, 0x4B, 0x00),       # primary / rec
    accent2=(0xE8, 0x5D, 0x04),      # warm secondary
    accent3=(0x20, 0xA0, 0xD0),      # cool chip
    hot=(0xE8, 0x5D, 0x04),          # focus ring
    danger=(0xB9, 0x1C, 0x1C),
    warn=(0xD4, 0xA0, 0x17),
    display=(0x56, 0xD6, 0xFF),      # lit cyan
    display_dim=(0x3A, 0x8A, 0x9E),  # well caption
    parts=_LIGHT_PARTS)

# micro-rangers NIGHT (LAUNCH dark proof).
NIGHT = Colorway(
    name="night", label="NIGHT",
    bg=(0x2A, 0x2C, 0x30), bg_raised=(0x3A, 0x3C, 0x42),
    bg_sunken=(0x1A, 0x1C, 0x20), bg_press=(0x4A, 0x4C, 0x52),
    bg_lcd=(0x08, 0x08, 0x0A), border=(0xE8, 0xE6, 0xE0),
    text=(0xE8, 0xE6, 0xE0), text_dim=(0xA0, 0xA0, 0x9A),
    text_muted=(0x70, 0x70, 0x6A),
    ink_dark=(0x10, 0x10, 0x12), ink_light=(0xF4, 0xF2, 0xEC),
    accent=(0xC4, 0x4B, 0x00), accent2=(0xE8, 0x5D, 0x04),
    accent3=(0x40, 0xB0, 0xE0), hot=(0xE8, 0x5D, 0x04),
    danger=(0xD0, 0x40, 0x40), warn=(0xE0, 0xB0, 0x30),
    display=(0x56, 0xD6, 0xFF), display_dim=(0x3A, 0x8A, 0x9E),
    parts=_DARK_PARTS)

# Legacy aliases kept so existing configs keep working.
MONO = Colorway(
    name="mono", label="MONO",
    bg=NIGHT.bg, bg_raised=NIGHT.bg_raised, bg_sunken=NIGHT.bg_sunken,
    bg_press=NIGHT.bg_press, bg_lcd=NIGHT.bg_lcd, border=NIGHT.border,
    text=NIGHT.text, text_dim=NIGHT.text_dim, text_muted=NIGHT.text_muted,
    ink_dark=NIGHT.ink_dark, ink_light=NIGHT.ink_light,
    accent=NIGHT.accent, accent2=NIGHT.accent2, accent3=NIGHT.accent3,
    hot=NIGHT.hot, danger=NIGHT.danger, warn=NIGHT.warn,
    display=NIGHT.display, display_dim=NIGHT.display_dim, parts=_DARK_PARTS)

DUSK = Colorway(
    name="dusk", label="DUSK",
    bg=(28, 30, 46), bg_raised=(48, 52, 76), bg_sunken=(72, 78, 108),
    bg_press=(110, 118, 154), bg_lcd=(12, 13, 22), border=(226, 224, 236),
    text=(232, 231, 242), text_dim=(172, 174, 196), text_muted=(126, 130, 156),
    ink_dark=(14, 15, 24), ink_light=(244, 243, 250),
    accent=(0xC4, 0x4B, 0x00), accent2=(0xE8, 0x5D, 0x04),
    accent3=(126, 156, 255), hot=(0xE8, 0x5D, 0x04),
    danger=(226, 76, 84), warn=(238, 186, 88),
    display=(184, 220, 255), display_dim=(0x3A, 0x8A, 0x9E),
    parts=_DARK_PARTS)

COLORWAYS: dict[str, Colorway] = {
    c.name: c for c in (INDUSTRIAL, NIGHT, MONO, DUSK)}
COLORWAY_NAMES = tuple(COLORWAYS)
DEFAULT_COLORWAY = INDUSTRIAL.name

# --- the live palette ---------------------------------------------------------
BG = INDUSTRIAL.bg
BG_RAISED = INDUSTRIAL.bg_raised
BG_SUNKEN = INDUSTRIAL.bg_sunken
BG_PRESS = INDUSTRIAL.bg_press
BG_LCD = INDUSTRIAL.bg_lcd
BORDER = INDUSTRIAL.border
TEXT = INDUSTRIAL.text
TEXT_DIM = INDUSTRIAL.text_dim
TEXT_MUTED = INDUSTRIAL.text_muted
INK_DARK = INDUSTRIAL.ink_dark
INK_LIGHT = INDUSTRIAL.ink_light
ACCENT = INDUSTRIAL.accent
ACCENT2 = INDUSTRIAL.accent2
ACCENT3 = INDUSTRIAL.accent3
HOT = INDUSTRIAL.hot
DANGER = INDUSTRIAL.danger
WARN = INDUSTRIAL.warn
DISPLAY = INDUSTRIAL.display
DISPLAY_DIM = INDUSTRIAL.display_dim
SELECT = INDUSTRIAL.hot
PART_COLORS = INDUSTRIAL.parts

_active = DEFAULT_COLORWAY


def apply(name: str) -> str:
    """Make *name* the live palette; returns the colourway actually in force.

    An unknown name is ignored rather than raising: this is fed by a config
    file and a saved preference, and a typo must not stop the panel booting.
    """
    global _active, BG, BG_RAISED, BG_SUNKEN, BG_PRESS, BG_LCD, BORDER
    global TEXT, TEXT_DIM, TEXT_MUTED, INK_DARK, INK_LIGHT, ACCENT, ACCENT2
    global ACCENT3, HOT, DANGER, WARN, DISPLAY, DISPLAY_DIM, SELECT
    global PART_COLORS
    way = COLORWAYS.get(name)
    if way is None:
        return _active
    BG, BG_RAISED, BG_SUNKEN = way.bg, way.bg_raised, way.bg_sunken
    BG_PRESS, BG_LCD, BORDER = way.bg_press, way.bg_lcd, way.border
    TEXT, TEXT_DIM, TEXT_MUTED = way.text, way.text_dim, way.text_muted
    INK_DARK, INK_LIGHT = way.ink_dark, way.ink_light
    ACCENT, ACCENT2, ACCENT3 = way.accent, way.accent2, way.accent3
    HOT = way.hot
    DANGER, WARN = way.danger, way.warn
    DISPLAY, DISPLAY_DIM = way.display, way.display_dim
    SELECT = way.hot
    PART_COLORS = way.parts
    _active = way.name
    return _active


def active() -> str:
    return _active


apply(DEFAULT_COLORWAY)

# --- type ---------------------------------------------------------------------
# Two families: a monospace for anything with a value in it, so digits do not
# shift width as they count, and a grotesque for the display voice — headings,
# buttons, tabs — always upper case.
#
# Coverage picks the order, not width: DejaVu carries the geometric shapes
# (U+25B6 ▶, U+266F ♯, U+00B0 °) the transport and chord symbols need, and
# Liberation renders several of them as a notdef box.
MONO_FAMILIES = "dejavusansmono,liberationmono,monospace"
DISPLAY_FAMILIES = "dejavusans,freesans,liberationsans,sans"
DISPLAY_FONT_PATH: str | None = None

_fonts: dict[tuple[int, bool, bool], "pygame.font.Font"] = {}


def font(size: int, bold: bool = False,
         display: bool = False) -> "pygame.font.Font":
    """Cached font. ``pygame.font`` initialises lazily, so importing the theme
    from a test or a docs script never needs a display."""
    key = (size, bold, display)
    cached = _fonts.get(key)
    if cached is None:
        if not pygame.font.get_init():
            pygame.font.init()
        if display and DISPLAY_FONT_PATH:
            cached = pygame.font.Font(DISPLAY_FONT_PATH, size)
            cached.set_bold(bold)
        else:
            cached = pygame.font.SysFont(
                DISPLAY_FAMILIES if display else MONO_FAMILIES, size,
                bold=bold)
        _fonts[key] = cached
    return cached


def part_color(index: int) -> Rgb:
    return PART_COLORS[index % len(PART_COLORS)]


def blend(base: Rgb, over: Rgb, amount: float) -> Rgb:
    """``base`` moved *amount* (0..1) toward ``over`` — tinted fills without a
    per-frame alpha surface."""
    return (round(base[0] + (over[0] - base[0]) * amount),
            round(base[1] + (over[1] - base[1]) * amount),
            round(base[2] + (over[2] - base[2]) * amount))


def tint(color: Rgb, amount: float = 0.22) -> Rgb:
    """A raised surface carrying just enough of *color* to be found without
    being read. Concepts are coloured at rest — PLAY is green whether or not
    it is playing — so the finger aims by hue and the *fill* means latched."""
    return blend(BG_RAISED, color, amount)


def luminance(color: Rgb) -> float:
    """Perceived lightness 0..1 (Rec. 601 — close enough for picking ink)."""
    return (0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]) / 255


def ink_for(fill: Rgb) -> Rgb:
    """Dark or light type, whichever survives on *fill*.

    No scheme can assume either: the same button draws white on the orange and
    black on a grey face, and the part hues straddle the line. Asking the fill
    is the only thing that stays right when a hue is re-tuned or the whole
    ground flips.
    """
    return INK_DARK if luminance(fill) > 0.55 else INK_LIGHT
