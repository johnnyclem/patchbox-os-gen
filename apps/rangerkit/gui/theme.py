"""Design tokens and the adaptive chrome geometry.

The tokens are the micro-rangers design system (master sheet 2026-08-09,
``docs/design/UI-UX-SPEC.md``). That sheet is the system of record for the
*language* — colour, type, geometry, state — and this module is its only
implementation. Layouts are ours: the sheet's fixed 320x240 bands do not
apply to a 1280x400 bar, and it says so itself ("inherit language, not
layouts").

Semantics hold across every colourway, and they are the sheet's, not ours:
ORANGE is playing (fill) and armed (dimmed fill), CYAN is selection and every
value in a well, GREEN is solo, RED is stop/delete/record, YELLOW is warn.
Selection is a cyan rule or inverse video — never a glow, and never orange,
which is spoken for by transport state.

Geometry lives in ``Layout``. On the bar panel vertical space is the scarce
resource, so the chrome turns sideways — transport down the left, tabs down
the right, and the content keeps all 400 px of height. A portrait panel gets
the ordinary top-bar/bottom-tabs stack instead.

DAYLIGHT is the light-industrial scheme this panel previously defaulted to.
It is kept, and kept selectable, because the finding behind it is real: the
reference 1280x400 HDMI bar has a heavy blue cast and a shallow black, on
which the sheet's three near-black surfaces (bg #0A0A0A, surface #1A1A1A,
well #0D1A20) can collapse into one washed navy. If that happens on a given
panel, ``colorway = "daylight"`` in the app config is the whole fix.

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
BORDER_W = 2                    # every rule; never a hairline (RADIUS 0)
PAD_GAP = 4                     # base grid unit
# micro-rangers chrome bands, scaled for the 1280×400 bar (design was 320×240)
STATUS_H = 40                   # status ribbon (design 18 px → ~2×)
LEGEND_H = 32                   # legend row (design 16 px → 2×)
FOCUS_W = 3                     # selection rule thickness

# Two touch floors, because the design system has two classes of control and
# collapsing them costs real estate on every list in the suite. Direct-action
# fires on press (transport, mute, solo, launch pads); selectable takes focus
# on press and is edited afterwards, so it may be smaller. These are the
# sheet's numbers exactly — they are a *floor*, the point below which a
# control stops being reliably hittable, not a target to design toward.
#
# Neither is square, and that matters: the bar is 400 px tall, so a grid that
# had to be 40 in both axes would give up a whole row of scenes to buy width
# that nothing needs.
TOUCH_DIRECT_W, TOUCH_DIRECT_H = 40, 36
TOUCH_SELECT_W, TOUCH_SELECT_H = 28, 24
# What the rails and single-row strips actually aim for. Comfortably above
# the floor, because those have the room and a transport button is the one
# control you press without looking.
TOUCH_MIN = 44

# Type scale — the sheet's four steps (9 / 7 / 6 / 5 px at 320×240) plus the
# primary value, mapped onto this panel. Screens name a step instead of
# picking a number, so a re-tune is one edit rather than three hundred.
TYPE_VALUE = 30                 # the number in a well
TYPE_TITLE = 18                 # ribbon title, headings, button faces
TYPE_CAPTION = 14               # caption, legend, chip
TYPE_LABEL = 12                 # secondary label
TYPE_MICRO = 10                 # step index, unit suffix


def touch_ok(rect, direct: bool = True) -> bool:
    """Does *rect* clear the floor for its control class? The conformance
    test asks this of every registered hit rect; screens use it when they
    are deciding whether a row still fits."""
    if direct:
        return rect.width >= TOUCH_DIRECT_W and rect.height >= TOUCH_DIRECT_H
    return rect.width >= TOUCH_SELECT_W and rect.height >= TOUCH_SELECT_H


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
    # The legend row, when the app asked for one. Like the ✕ it is carved out
    # of the content rather than floated over it, so a screen's own layout
    # never has to know the legend exists.
    legend: pygame.Rect | None = None

    @classmethod
    def for_size(cls, size: tuple[int, int], tab_count: int,
                 close_button: bool = False,
                 legend: bool = False) -> "Layout":
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
            legend_rect = None
            if legend:
                content, legend_rect = _carve_legend(content)
            return cls(width, height, True, transport, content, tabs, close,
                       legend_rect)
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
        legend_rect = None
        if legend:
            content, legend_rect = _carve_legend(content)
        return cls(width, height, False, transport, content, tabs, close,
                   legend_rect)


def _carve_legend(content: pygame.Rect
                  ) -> tuple[pygame.Rect, pygame.Rect | None]:
    """Take the legend row off the bottom of *content*.

    Refused on a content band too short to give it up: a legend that costs a
    screen its last usable row has stopped being a help and started being the
    reason a control does not fit. Below that floor the app simply goes
    without one, which is the same call the sheet makes about the ✕.
    """
    if content.height < LEGEND_H + 3 * TOUCH_DIRECT_H:
        return content, None
    body = pygame.Rect(content.x, content.y, content.width,
                       content.height - LEGEND_H)
    strip = pygame.Rect(content.x, body.bottom, content.width, LEGEND_H)
    return body, strip


# --- colourways ---------------------------------------------------------------

Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Colorway:
    """One complete palette — a value that is swapped whole, never patched.

    Tokens follow the micro-rangers design system: RADIUS 0, values in wells,
    selection is a cyan rule, playing is an orange fill, solo is green, and
    press is never colour alone (geometry + inverse fill).
    ``ink_dark``/``ink_light`` are the two inks ``ink_for`` picks between.
    """

    name: str
    label: str
    bg: Rgb
    bg_raised: Rgb       # "surface" on the sheet
    bg_sunken: Rgb
    bg_press: Rgb
    bg_lcd: Rgb          # "well" on the sheet
    border: Rgb
    text: Rgb
    text_dim: Rgb
    text_muted: Rgb
    ink_dark: Rgb
    ink_light: Rgb
    accent: Rgb          # ORANGE — playing / record
    accent2: Rgb         # ORANGE dimmed — armed / queued
    accent3: Rgb         # CYAN — selection, routes, values
    hot: Rgb             # CYAN — the selection rule (alias of accent3)
    ok: Rgb              # GREEN — solo emphasis
    danger: Rgb          # RED
    warn: Rgb            # YELLOW
    display: Rgb         # value in a well (cyan)
    display_dim: Rgb     # well caption
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

# The design system's own tokens, verbatim from the master sheet (§Tokens):
# bg #0A0A0A · surface #1A1A1A · well #0D1A20 · text #E8E8E8 · text_dim
# #7A7A7A · cyan #56D6FF · orange #FF6B2C · green #3DFF8A · red #FF3D4A ·
# yellow #FFD12A. Every other value here is derived from those, not invented.
INDUSTRIAL = Colorway(
    name="industrial", label="INDUSTRIAL",
    bg=(0x0A, 0x0A, 0x0A),           # panel ground
    bg_raised=(0x1A, 0x1A, 0x1A),    # surface — button rest, pad rest
    bg_sunken=(0x12, 0x12, 0x12),    # empty pad: below the surface, above bg
    bg_press=(0x2E, 0x2E, 0x2E),     # geometry press (inverse of the rest)
    bg_lcd=(0x0D, 0x1A, 0x20),       # well
    border=(0xE8, 0xE8, 0xE8),       # 2 px rule — reads against #0A0A0A
    text=(0xE8, 0xE8, 0xE8),
    text_dim=(0x7A, 0x7A, 0x7A),
    text_muted=(0x5A, 0x5A, 0x5A),
    ink_dark=(0x0A, 0x0A, 0x0A),
    ink_light=(0xE8, 0xE8, 0xE8),
    accent=(0xFF, 0x6B, 0x2C),       # orange — playing / record
    accent2=(0x8A, 0x3A, 0x18),      # orange dimmed — armed / queued
    accent3=(0x56, 0xD6, 0xFF),      # cyan
    hot=(0x56, 0xD6, 0xFF),          # selection rule
    ok=(0x3D, 0xFF, 0x8A),           # green — solo
    danger=(0xFF, 0x3D, 0x4A),       # red
    warn=(0xFF, 0xD1, 0x2A),         # yellow
    display=(0x56, 0xD6, 0xFF),      # value in a well
    display_dim=(0x3A, 0x8A, 0x9E),  # well caption
    parts=_DARK_PARTS)

# NIGHT — the same language a step off pure black, for panels whose backlight
# never fully closes and turns #0A0A0A into grey anyway.
NIGHT = Colorway(
    name="night", label="NIGHT",
    bg=(0x16, 0x18, 0x1A), bg_raised=(0x26, 0x28, 0x2C),
    bg_sunken=(0x1E, 0x20, 0x23), bg_press=(0x3C, 0x3E, 0x44),
    bg_lcd=(0x0D, 0x1A, 0x20), border=(0xE8, 0xE6, 0xE0),
    text=(0xE8, 0xE6, 0xE0), text_dim=(0x9A, 0x9A, 0x94),
    text_muted=(0x70, 0x70, 0x6A),
    ink_dark=(0x10, 0x10, 0x12), ink_light=(0xF4, 0xF2, 0xEC),
    accent=(0xFF, 0x6B, 0x2C), accent2=(0x8A, 0x3A, 0x18),
    accent3=(0x56, 0xD6, 0xFF), hot=(0x56, 0xD6, 0xFF),
    ok=(0x3D, 0xFF, 0x8A),
    danger=(0xFF, 0x3D, 0x4A), warn=(0xFF, 0xD1, 0x2A),
    display=(0x56, 0xD6, 0xFF), display_dim=(0x3A, 0x8A, 0x9E),
    parts=_DARK_PARTS)

# DAYLIGHT — the light-industrial scheme the RK-00pi bar shipped with, kept
# because its finding stands: a panel with a blue cast and a shallow black
# collapses the three near-black surfaces above into one washed navy, and a
# filled pad stops being distinguishable from an empty one at arm's length.
# Here the surfaces separate by lightness against a light ground and every
# rule is true black — the one thing a bad LCD still renders exactly. State
# semantics are unchanged; only the ground and the rule flip.
DAYLIGHT = Colorway(
    name="daylight", label="DAYLIGHT",
    bg=(0xB8, 0xB4, 0xAC),          # panel face
    bg_raised=(0xD0, 0xCC, 0xC4),    # button rest
    bg_sunken=(0x9A, 0x96, 0x8E),    # wells, empty
    bg_press=(0x8A, 0x86, 0x80),     # geometry press
    bg_lcd=(0x0D, 0x1A, 0x20),       # well — the sheet's value, unchanged
    border=(0x0A, 0x0A, 0x0A),       # 2 px hard rule
    text=(0x12, 0x12, 0x12),
    text_dim=(0x4A, 0x4A, 0x44),
    text_muted=(0x6A, 0x6A, 0x64),
    ink_dark=(0x12, 0x12, 0x12),
    ink_light=(0xF6, 0xF6, 0xF4),
    accent=(0xE8, 0x5D, 0x04),       # orange, darkened to hold on a light bg
    accent2=(0xC4, 0x9A, 0x70),      # orange dimmed — armed
    accent3=(0x0E, 0x6E, 0x92),      # cyan, darkened for contrast on light
    hot=(0x0E, 0x6E, 0x92),
    ok=(0x0F, 0x7A, 0x42),           # green, darkened for contrast on light
    danger=(0xB9, 0x1C, 0x1C),
    warn=(0xD4, 0xA0, 0x17),
    display=(0x56, 0xD6, 0xFF),      # in a well it is still the lit cyan
    display_dim=(0x3A, 0x8A, 0x9E),
    parts=_LIGHT_PARTS)

COLORWAYS: dict[str, Colorway] = {
    c.name: c for c in (INDUSTRIAL, NIGHT, DAYLIGHT)}
# Names retired by the design-system pass, kept resolvable so a config or a
# saved preference written before it still boots into something sensible.
COLORWAYS["mono"] = NIGHT
COLORWAYS["dusk"] = NIGHT
COLORWAY_NAMES = tuple(c.name for c in (INDUSTRIAL, NIGHT, DAYLIGHT))
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
OK = INDUSTRIAL.ok
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
    global ACCENT3, HOT, OK, DANGER, WARN, DISPLAY, DISPLAY_DIM, SELECT
    global PART_COLORS
    way = COLORWAYS.get(name)
    if way is None:
        return _active
    BG, BG_RAISED, BG_SUNKEN = way.bg, way.bg_raised, way.bg_sunken
    BG_PRESS, BG_LCD, BORDER = way.bg_press, way.bg_lcd, way.border
    TEXT, TEXT_DIM, TEXT_MUTED = way.text, way.text_dim, way.text_muted
    INK_DARK, INK_LIGHT = way.ink_dark, way.ink_light
    ACCENT, ACCENT2, ACCENT3 = way.accent, way.accent2, way.accent3
    HOT, OK = way.hot, way.ok
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


def dim(color: Rgb, amount: float = 0.55) -> Rgb:
    """*color* pulled back toward the ground — the design system's mute.

    Mute dims, it never hides: the row keeps its chip, its label and its
    place, so a muted track still tells you what it is and one press brings
    it back. Pulling toward ``BG`` rather than to grey keeps the hue legible
    at arm's length, which is what makes "this one is muted" readable across
    a row of eight without counting.
    """
    return blend(color, BG, amount)


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
