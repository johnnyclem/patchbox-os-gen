"""Drawing primitives and the hit map.

Every control on the panel is drawn by one of these and registered in a
``HitMap`` under a string key. Touch handling is then a dictionary lookup
rather than a tree of rect comparisons, and — more importantly — a control
that is drawn but not registered simply cannot be pressed, which turns "the
button does nothing" into a mistake you make once.

The house style is the micro-rangers design system, and it is hard: radius 0
everywhere, 2 px rules, no shadows, no gradients, no blur. Depth is carried
by lightness and by the rule, never by a drop shadow — a shadow on a panel
this contrasty reads as a smudge, and the sheet forbids it outright.

Two rules do most of the work and are easy to break by accident:

* **Press is geometry + inverse fill, never colour alone.** A control that
  only changes hue on press is invisible to a player who is looking at the
  keyboard, and indistinguishable from that control being *latched*.
* **Selection is a cyan rule or inverse video, never a glow, and never
  orange.** Orange is spoken for by transport state (playing / armed); if
  selection borrowed it, a selected empty pad and a playing pad would be the
  same picture.
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


def panel(surface, rect, color=None, border: bool = True,
          focus: bool = False) -> pygame.Rect:
    """A surface: fill, then the 2 px rule. No shadow — the sheet forbids it.

    ``focus`` draws the cyan selection rule *inside* the black rule, so a
    selected control keeps its footprint exactly. An outside ring would grow
    the control by 6 px and shove its neighbours, which on a grid of pads is
    a visible reflow every time focus moves.
    """
    surface.fill(color or theme.BG_RAISED, rect)
    if border:
        rule(surface, rect)
    if focus:
        select_rule(surface, rect)
    return rect


def select_rule(surface, rect, width: int | None = None) -> None:
    """The cyan selection frame (RADIUS 0), drawn inside the panel's rule.

    This is the design system's *only* selection mark besides inverse video.
    Never a glow, and never orange — orange means playing.
    """
    w = width if width is not None else theme.FOCUS_W
    pygame.draw.rect(surface, theme.HOT, rect.inflate(-w, -w), w)


#: Retired name for :func:`select_rule`, kept so older screens keep drawing.
focus_ring = select_rule


#: Centre glyphs. The sheet's mark system distinguishes what a pad *holds*
#: (scene ● / clip ■) from what it is *doing*, which is carried by the fill.
MARK_SCENE = "●"
MARK_CLIP = "■"


def pad_face(state: str, hue=None):
    """The fill for one pad state — the sheet's states matrix, in one place.

    Kept separate from :func:`pad` because several screens draw their own pad
    bodies (step grids, matrices) and must not re-derive these by eye.
    """
    hue = hue or theme.ACCENT
    return {
        # The sheet is precise and counter-intuitive here, and worth reading
        # twice: "empty pad — surface fill, dim rule", "filled pad — well
        # fill, mark present". The *empty* one is the lighter surface and the
        # *filled* one is the darker well. That is not an aesthetic whim: on a
        # near-black ground the two greys are eight levels apart and would
        # collapse, but the well carries a blue cast the surface does not, so
        # the pair separates by hue where lightness has nothing left to give.
        "empty": theme.BG_RAISED,
        "filled": theme.BG_LCD,
        "stopped": theme.BG_LCD,
        # queued/armed: orange *dimmed*, so it reads as "about to" next to a
        # pad that already is.
        "queued": theme.ACCENT2,
        "armed": theme.ACCENT2,
        # playing: full orange fill, inverse mark.
        "playing": hue,
        "recording": theme.DANGER,
        # muted: dimmed, never hidden.
        "muted": theme.dim(theme.BG_RAISED, 0.5),
        # pressed: inverse fill — geometry, not colour.
        "pressed": theme.BG_PRESS,
    }.get(state, theme.BG_RAISED)


def pad(surface, rect, *, face=None, state: str = "empty",
        hue=None, label: str = "", sub: str = "",
        chip=None, mark: str = "", selected: bool = False) -> pygame.Rect:
    """One pad cell, drawn to the sheet's states matrix.

    ``state`` is one of empty / filled / stopped / queued / armed / playing /
    recording / muted / pressed. ``selected`` is orthogonal to all of them —
    a pad can be selected *and* playing, and the two marks must not compete,
    which is why one is a fill and the other a rule.

    Press is geometry (state="pressed", or the caller passing ``face``);
    colour alone never means pressed.
    """
    if face is None:
        face = pad_face(state, hue)
    # "empty pad — surface fill, *dim rule*". The rule is what makes a grid of
    # empty cells read as a grid rather than as one large blank, so it stays;
    # dimming it is what stops eight empty pads from being the loudest
    # geometry on the screen.
    surface.fill(face, rect)
    rule(surface, rect, theme.blend(theme.BORDER, theme.BG, 0.45)
         if state == "empty" else None)
    if selected:
        select_rule(surface, rect)
    if chip is not None:
        badge = pygame.Rect(rect.x + 4, rect.y + 4, 14, 10)
        surface.fill(theme.dim(chip) if state == "muted" else chip, badge)
        rule(surface, badge, width=1)
    ink = theme.ink_for(face)
    if state == "muted":
        ink = theme.blend(ink, face, 0.45)
    if label:
        title = pygame.Rect(rect.x + 6, rect.y + (18 if chip else 6),
                            rect.width - 12, 22)
        text(surface, label, title, theme.TYPE_TITLE - 2, ink, bold=True,
             display=True, align="left")
    if sub:
        line = pygame.Rect(rect.x + 6, rect.bottom - 36, rect.width - 12, 16)
        text(surface, sub, line, theme.TYPE_LABEL,
             theme.blend(ink, face, 0.35), align="left")
    if mark:
        body = pygame.Rect(rect.x, rect.y + rect.height // 3,
                           rect.width, rect.height // 2)
        text(surface, mark, body, 22, ink, bold=True, display=True)
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
           size: int = theme.TYPE_TITLE - 3, active: bool = False,
           pressed: bool = False, color=None, disabled: bool = False,
           display: bool = True, sub: str = "", kind: str = "neut",
           focus: bool = False, filled: bool | None = None) -> pygame.Rect:
    """The standard control.

    ``kind`` follows the component sheet: neut / prim / solo / mute / dang /
    dis. ``solo`` and ``mute`` exist as kinds rather than as a colour the
    caller passes because the sheet is specific about both — solo is *green
    emphasis*, mute *dims and never hides* — and eight screens each picking a
    red for M is how the suite drifted apart in the first place.

    ``pressed`` is an inverse fill (BG_PRESS), never a colour swap alone.

    ``color`` is the face used **when the control is active** — it is not a
    resting colour, and passing it without ``active`` or a ``kind`` does
    nothing at all. That combination is a bug (it hid eighteen destructive
    buttons for months) and ``test_design_system`` fails the build on it.

    ``filled`` marks a control that is a *slot* — a seed bank, a scene bank,
    anything that either holds something or does not. ``True`` gives it the
    well face the states matrix wants for a filled pad, ``False`` the plain
    surface of an empty one, and the default ``None`` means "not a slot, an
    ordinary button". Occupancy is a surface, never an accent hue: orange
    means playing, and a seed bank where every saved slot glowed orange
    claimed eight things were sounding.

    Unlike ``disabled``, an empty slot stays pressable — pressing it is how
    you fill it.
    """
    if disabled or kind == "dis":
        face = theme.BG_SUNKEN
        disabled = True
    elif pressed:
        face = theme.BG_PRESS
    elif kind == "solo":
        face = theme.OK if active else theme.BG_RAISED
    elif kind == "mute":
        face = theme.dim(theme.BG_RAISED, 0.5) if active else theme.BG_RAISED
    elif active or kind == "prim":
        face = color or theme.ACCENT
    elif kind == "dang":
        face = theme.DANGER
    elif filled:
        face = theme.BG_LCD
    else:
        face = theme.BG_RAISED
    panel(surface, rect, face, focus=focus)
    ink = theme.TEXT_MUTED if disabled else theme.ink_for(face)
    if kind == "mute" and active:
        ink = theme.blend(ink, face, 0.45)
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


def _fits(size: int, height: int) -> int:
    """The largest size at or below *size* whose line box fits *height*.

    Asked of the font rather than estimated: a point size is not a pixel
    height, and guessing the ratio is how a caption and its value ended up
    overlapping in every well shorter than about 40 px.
    """
    while size > 8 and theme.font(size, bold=True).get_height() > height:
        size -= 1
    return size


def lcd(surface, rect, value: str, size: int = theme.TYPE_VALUE,
        label: str = "", color=None, selected: bool = False) -> pygame.Rect:
    """A readout in its own well: caption above, value in cyan.

    The caption is *permanent*, not a tooltip and not a hover: a player who
    has to press a control to find out what it is has already changed it. Any
    continuous parameter should be drawn with ``label`` set, which is what
    :func:`param` enforces.

    Values are cyan on the well, never pure white on black — white on black
    at this size blooms on an LCD and the digits smear into each other.
    """
    surface.fill(theme.BG_LCD, rect)
    rule(surface, rect)
    body = rect
    if label:
        # Split proportionally, not at a fixed 14 px. A well only 28 px tall
        # gave the caption half its height and then centred a 20 px value in
        # what was left, so the two collided — the caption was drawn, which
        # the rule requires, and unreadable, which defeats it.
        head_h = max(9, min(14, rect.height // 3))
        head = pygame.Rect(rect.x, rect.y + 1, rect.width, head_h)
        text(surface, label, head, min(theme.TYPE_MICRO, head_h),
             theme.DISPLAY_DIM, display=True)
        body = pygame.Rect(rect.x, rect.y + head_h, rect.width,
                           rect.height - head_h)
    text(surface, value, body, _fits(size, body.height),
         color or theme.DISPLAY, bold=True)
    if selected:
        select_rule(surface, rect)
    return rect


def param(surface, rect, caption: str, value: str,
          size: int = theme.TYPE_VALUE, selected: bool = False,
          color=None) -> pygame.Rect:
    """A continuous parameter: caption over value, always both.

    This is :func:`lcd` with the caption made non-optional, and it is the
    control every rate / gate / level / octave readout should be using. The
    separate name is the point — it is impossible to draw one of these
    without its caption.
    """
    return lcd(surface, rect, value, size=size, label=caption,
               color=color, selected=selected)


def toast(surface, rect, value: str) -> pygame.Rect:
    """Transient voice strip — well ground, cyan type (MIDI LEARN · …)."""
    surface.fill(theme.BG_LCD, rect)
    rule(surface, rect)
    text(surface, value, rect, theme.TYPE_CAPTION, theme.DISPLAY, bold=True,
         display=True, align="left", pad=12)
    return rect


def chip(surface, rect, label: str, color=None, active: bool = False,
         muted: bool = False, selected: bool = False) -> pygame.Rect:
    """Small status chip (track name, UPDATE · TAP, SC 1–5/8, …).

    ``muted`` dims the chip rather than dropping it, so a muted track keeps
    its place and its name in the row — the sheet's mute rule, applied to the
    one element that says which track you are looking at.
    """
    face = color or (theme.ACCENT if active else theme.BG_LCD)
    if muted:
        face = theme.dim(face)
    surface.fill(face, rect)
    rule(surface, rect)
    ink = theme.ink_for(face)
    text(surface, label, rect, theme.TYPE_LABEL,
         theme.blend(ink, face, 0.4) if muted else ink,
         bold=True, display=True)
    if selected:
        select_rule(surface, rect)
    return rect


def ribbon(surface, rect, screen: str, clock: str = "", tempo: str = "",
           playing: bool = False, recording: bool = False) -> pygame.Rect:
    """The status band: which screen you are on, the clock, the tempo.

    Three fixed slots, always in this order and always the same width, so the
    eye learns where to land: name hard left, transport state and bar:beat:
    tick in the middle, BPM hard right. It is the one piece of chrome that
    never changes between screens, which is exactly what makes it readable
    without being read.
    """
    surface.fill(theme.BG, rect)
    rule(surface, rect)
    inner = rect.inflate(-8, -4)
    text(surface, screen, inner, theme.TYPE_TITLE, theme.TEXT, bold=True,
         display=True, align="left")
    if clock:
        mark = MARK_CLIP if not playing else "▶"
        colour = (theme.DANGER if recording else
                  theme.ACCENT if playing else theme.TEXT_DIM)
        state = pygame.Rect(inner.centerx - 90, inner.y, 24, inner.height)
        text(surface, mark, state, theme.TYPE_CAPTION, colour, bold=True)
        body = pygame.Rect(state.right, inner.y, 160, inner.height)
        text(surface, clock, body, theme.TYPE_CAPTION, theme.DISPLAY,
             bold=True, align="left")
    if tempo:
        text(surface, tempo, inner, theme.TYPE_CAPTION, theme.DISPLAY,
             bold=True, align="right")
    return rect


def tab_rail(surface, hits: HitMap, rects, titles, active: int) -> None:
    """The tab rail — down the right edge when wide, across the bottom when
    not. ``Layout`` already decided which and handed over the rects.

    The current tab is drawn as inverse video (cyan ground, dark ink), which
    is the design system's selection mark. It is emphatically not orange:
    on a screen where a pad is playing, an orange tab would read as a second
    piece of transport state.

    Shared rather than copied into each app because it was already identical
    in all seven, and a tab rail that drifts between rangers is the single
    most obvious way for the suite to stop feeling like one instrument.
    """
    for index, (rect, title) in enumerate(zip(rects, titles)):
        face = theme.SELECT if index == active else theme.BG_RAISED
        panel(surface, rect, face)
        text(surface, title, rect, theme.TYPE_CAPTION, theme.ink_for(face),
             bold=True, display=True)
        hits.add(f"tab{index}", rect)


def message_strip(surface, content: pygame.Rect, copy: str) -> pygame.Rect:
    """The transient notice ("SAVED", "POT A = CC 74"), drawn as a toast.

    In a well with cyan type, not on an orange panel: orange is transport
    state, and a notice that borrows it makes the panel look like it started
    playing every time you save a file.
    """
    rect = pygame.Rect(content.x + 8, content.bottom - 34,
                       min(420, content.width - 16), 26)
    return toast(surface, rect, copy)


def legend(surface, rect, copy: str) -> pygame.Rect:
    """The legend row: what the controls do, right now, on this screen.

    Permanent and contextual — it reflects the *focused* control, so a
    secondary action on long-press is discoverable without a manual and
    without a dedicated button. Dim type on the ground, never a well: it is
    reference, not a value, and it must not compete with the readouts.
    """
    surface.fill(theme.BG, rect)
    text(surface, copy, rect, theme.TYPE_CAPTION, theme.TEXT_DIM,
         display=False, align="left", pad=10)
    return rect


def meter(surface, rect, value: float, color=None) -> None:
    """A horizontal bar, 0..1, drawn as a filled proportion of a sunken well.

    A meter is *output* — it shows what is coming out, and pressing it does
    nothing. It is deliberately not registered in any hit map.
    """
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
    text(surface, label, rect, theme.TYPE_LABEL, theme.TEXT_DIM, display=True,
         align="left")
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
             pressed: str | None = None, size: int = theme.TYPE_TITLE,
             selected: bool = False) -> None:
        minus = pygame.Rect(rect.x, rect.y, self.width, rect.height)
        plus = pygame.Rect(rect.right - self.width, rect.y, self.width,
                           rect.height)
        middle = pygame.Rect(minus.right + 2, rect.y,
                             plus.left - minus.right - 4, rect.height)
        button(surface, hits, f"{self.key}-", minus, "−", size + 2,
               pressed=pressed == f"{self.key}-")
        # The value sits in a well with its caption above it: a stepper is a
        # continuous parameter, and the sheet wants caption-over-value on
        # every one of those.
        param(surface, middle, self.label, self.value, size=size,
              selected=selected)
        button(surface, hits, f"{self.key}+", plus, "+", size + 2,
               pressed=pressed == f"{self.key}+")


def close_badge(surface, hits: HitMap, rect: pygame.Rect) -> pygame.Rect:
    """The deck-mode ✕ — hands the panel back to the launcher.

    Registered as ``deck-close`` so every app's chrome handler spells the
    hide the same way. It closes the *picture* only; the engine underneath
    keeps its clock, arps and tape rolling, which is why the sublabel says
    where you are going rather than warning about what you would lose.
    """
    inner = rect.inflate(-8, -8)
    return button(surface, hits, "deck-close", inner, "×", 22,
                  sub="APPS")
