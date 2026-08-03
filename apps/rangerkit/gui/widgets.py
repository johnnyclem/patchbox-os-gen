"""Drawing primitives and the hit map.

Every control on the panel is drawn by one of these and registered in a
``HitMap`` under a string key. Touch handling is then a dictionary lookup
rather than a tree of rect comparisons, and — more importantly — a control
that is drawn but not registered simply cannot be pressed, which turns "the
button does nothing" into a mistake you make once.

The house style is hard: no rounded corners, no blur, a 2 px black rule on
everything, and a 3 px offset shadow on anything raised. It reads at arm's
length on a washed-out panel, which is the only test that matters here.
"""
from __future__ import annotations

from dataclasses import dataclass

import pygame

from rangerkit.gui import theme


class HitMap:
    """Rects registered this frame, newest first so an overlay wins."""

    def __init__(self) -> None:
        self._items: list[tuple[str, pygame.Rect]] = []

    def clear(self) -> None:
        self._items.clear()

    def add(self, key: str, rect: pygame.Rect) -> pygame.Rect:
        self._items.append((key, rect))
        return rect

    def hit(self, pos) -> str | None:
        for key, rect in reversed(self._items):
            if rect.collidepoint(pos):
                return key
        return None

    def rect_for(self, key: str) -> pygame.Rect | None:
        for item_key, rect in self._items:
            if item_key == key:
                return rect
        return None

    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _rect in self._items)

    def __len__(self) -> int:
        return len(self._items)


class RepeatRamp:
    """Hold-to-repeat with acceleration.

    A tempo knob you have to tap sixty times is not a tempo knob. The ramp
    starts slow enough that a deliberate single step is still possible, then
    accelerates, and reports how many steps came due this frame so the caller
    applies the batch instead of pretending to be several taps.
    """

    DELAY_MS = 380
    START_MS = 150
    FAST_MS = 45
    RAMP_AFTER = 6

    def __init__(self) -> None:
        self.count = 0
        self._next_ms = 0

    def reset(self) -> None:
        self.count = 0
        self._next_ms = 0

    def due(self, now_ms: int, press_ms: int) -> int:
        held = now_ms - press_ms
        if held < self.DELAY_MS:
            return 0
        if self._next_ms == 0:
            self._next_ms = press_ms + self.DELAY_MS
        steps = 0
        while now_ms >= self._next_ms:
            steps += 1
            self.count += 1
            interval = (self.FAST_MS if self.count > self.RAMP_AFTER
                        else self.START_MS)
            self._next_ms += interval
        return steps


# --- primitives ---------------------------------------------------------------

def fill(surface, rect, color) -> None:
    surface.fill(color, rect)


def rule(surface, rect, color=None, width: int = theme.BORDER_W) -> None:
    pygame.draw.rect(surface, color or theme.BORDER, rect, width)


def panel(surface, rect, color=None, shadow: bool = False,
          border: bool = True) -> pygame.Rect:
    """A raised surface: optional hard shadow, fill, black rule."""
    if shadow:
        shade = rect.move(theme.SHADOW_OFF, theme.SHADOW_OFF)
        surface.fill(theme.BORDER, shade)
    surface.fill(color or theme.BG_RAISED, rect)
    if border:
        rule(surface, rect)
    return rect


def text(surface, value: str, rect, size: int = 16, color=None,
         bold: bool = False, display: bool = False, align: str = "center",
         pad: int = 8):
    """Draw one line, clipped to *rect*. Returns the blitted rect.

    Truncation is by character with no ellipsis: on a panel this size an
    ellipsis costs a character and tells the reader nothing they cannot see.
    """
    if not value:
        return None
    face = theme.font(size, bold=bold, display=display)
    label = value.upper() if display else value
    surf = face.render(label, True, color or theme.TEXT)
    if surf.get_width() > rect.width - pad:
        while label and face.size(label)[0] > rect.width - pad:
            label = label[:-1]
        surf = face.render(label, True, color or theme.TEXT)
    if align == "left":
        position = surf.get_rect(midleft=(rect.left + pad, rect.centery))
    elif align == "right":
        position = surf.get_rect(midright=(rect.right - pad, rect.centery))
    else:
        position = surf.get_rect(center=rect.center)
    surface.blit(surf, position)
    return position


def button(surface, hits: HitMap, key: str, rect, label: str,
           size: int = 15, active: bool = False, pressed: bool = False,
           color=None, disabled: bool = False, display: bool = True,
           sub: str = "") -> pygame.Rect:
    """The standard control. ``active`` fills it with *color*; ``pressed``
    flashes it; ``disabled`` greys it and does not register a hit."""
    accent = color or theme.ACCENT3
    if pressed:
        face = theme.BG_PRESS
    elif active:
        face = accent
    else:
        face = theme.tint(accent, 0.14) if color else theme.BG_RAISED
    panel(surface, rect, face)
    ink = theme.TEXT_MUTED if disabled else theme.ink_for(face)
    if sub:
        top = pygame.Rect(rect.x, rect.y + 2, rect.width, rect.height * 3 // 5)
        bottom = pygame.Rect(rect.x, rect.bottom - rect.height * 2 // 5,
                             rect.width, rect.height * 2 // 5)
        text(surface, label, top, size, ink, bold=True, display=display)
        text(surface, sub, bottom, max(9, size - 5), ink, display=False)
    else:
        text(surface, label, rect, size, ink, bold=True, display=display)
    if not disabled:
        hits.add(key, rect)
    return rect


def lcd(surface, rect, value: str, size: int = 30, label: str = "",
        color=None) -> pygame.Rect:
    """A readout in its own black well. On this panel the well *is* the
    signal: a number on a light grey face reads as a label, the same number
    in a black window reads as a value."""
    surface.fill(theme.BG_LCD, rect)
    rule(surface, rect)
    body = rect
    if label:
        head = pygame.Rect(rect.x, rect.y + 2, rect.width, 14)
        text(surface, label, head, 10, theme.blend(theme.BG_LCD,
                                                   theme.DISPLAY, 0.55),
             display=True)
        body = pygame.Rect(rect.x, rect.y + 12, rect.width, rect.height - 12)
    text(surface, value, body, size, color or theme.DISPLAY, bold=True)
    return rect


def meter(surface, rect, value: float, color=None) -> None:
    """A horizontal bar, 0..1, drawn as a filled proportion of a sunken well."""
    surface.fill(theme.BG_SUNKEN, rect)
    filled = pygame.Rect(rect.x, rect.y, int(rect.width * max(0.0, min(
        1.0, value))), rect.height)
    if filled.width:
        surface.fill(color or theme.ACCENT, filled)
    rule(surface, rect, width=1)


def led(surface, center, on: bool, color=None, radius: int = 5) -> None:
    """A round indicator. Off is drawn as an empty ring rather than nothing,
    so the row keeps its rhythm and the player can see there is a lamp there
    at all."""
    fill_color = (color or theme.ACCENT) if on else theme.BG_SUNKEN
    pygame.draw.circle(surface, fill_color, center, radius)
    pygame.draw.circle(surface, theme.BORDER, center, radius, 1)


def grid(rect: pygame.Rect, cols: int, rows: int, gap: int = theme.PAD_GAP
         ) -> list[pygame.Rect]:
    """Row-major cells filling *rect*, sliced from the edges so rounding never
    leaves a dead strip."""
    cells: list[pygame.Rect] = []
    for row in range(rows):
        top = rect.y + row * rect.height // rows
        bottom = rect.y + (row + 1) * rect.height // rows
        for col in range(cols):
            left = rect.x + col * rect.width // cols
            right = rect.x + (col + 1) * rect.width // cols
            cells.append(pygame.Rect(left, top, right - left - gap,
                                     bottom - top - gap))
    return cells


def row(rect: pygame.Rect, count: int, gap: int = theme.PAD_GAP
        ) -> list[pygame.Rect]:
    return grid(rect, count, 1, gap)


def column(rect: pygame.Rect, count: int, gap: int = theme.PAD_GAP
           ) -> list[pygame.Rect]:
    return grid(rect, 1, count, gap)


def section_head(surface, rect, label: str) -> pygame.Rect:
    """A titled band above a group of controls."""
    surface.fill(theme.BG, rect)
    text(surface, label, rect, 11, theme.TEXT_DIM, display=True, align="left")
    return rect


@dataclass(frozen=True, slots=True)
class Stepper:
    """A ``- value +`` control, laid out and drawn as one thing.

    Returned keys are ``f"{key}-"`` and ``f"{key}+"``, which is the convention
    the screens' repeat handling keys off — so a stepper that ramps is one
    line, not five.
    """

    key: str
    label: str
    value: str
    width: int = 44

    def draw(self, surface, hits: HitMap, rect: pygame.Rect,
             pressed: str | None = None, size: int = 16) -> None:
        minus = pygame.Rect(rect.x, rect.y, self.width, rect.height)
        plus = pygame.Rect(rect.right - self.width, rect.y, self.width,
                           rect.height)
        middle = pygame.Rect(minus.right + 2, rect.y,
                             plus.left - minus.right - 4, rect.height)
        button(surface, hits, f"{self.key}-", minus, "−", size + 2,
               pressed=pressed == f"{self.key}-")
        panel(surface, middle, theme.BG_SUNKEN)
        if self.label:
            head = pygame.Rect(middle.x, middle.y + 1, middle.width, 12)
            text(surface, self.label, head, 10, theme.TEXT_DIM, display=True)
            body = pygame.Rect(middle.x, middle.y + 11, middle.width,
                               middle.height - 12)
        else:
            body = middle
        text(surface, self.value, body, size, theme.TEXT, bold=True)
        button(surface, hits, f"{self.key}+", plus, "+", size + 2,
               pressed=pressed == f"{self.key}+")
