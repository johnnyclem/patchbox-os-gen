"""Interactive JACK patchbay screens for Inky Impression.

Layout (600×448)
----------------
  ┌ PATCHBAY · rate · JACK badge ──────────────────────┐
  │ * OUT n                 │   IN n                   │
  │   jack rows + scrollbar │   jack rows + scrollbar  │
  ├ route: src ────●──── sink · LINKED / PATCH? ───────┤
  │ LINKS n  (existing cables)                         │
  └ A up · B down · C patch · D focus · status ────────┘

Buttons (A/B/C/D top→bottom on the panel edge):
  A  move selection up
  B  move selection down
  C  toggle OUT→IN link (or remove when focus is LINKS)
  D  cycle focus: OUT → IN → LINKS → (refresh graph)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from . import jackutil, sysinfo
from .colors import (
    BLACK,
    BLUE,
    GREEN,
    HEIGHT,
    ORANGE,
    RED,
    WHITE,
    WIDTH,
    YELLOW,
)
from .display import blank
from .fonts import font

FOCUS_SOURCES = "sources"
FOCUS_SINKS = "sinks"
FOCUS_LINKS = "links"
FOCUS_ORDER = (FOCUS_SOURCES, FOCUS_SINKS, FOCUS_LINKS)

HEADER_H = 40
COL_HDR_H = 26
LIST_TOP = HEADER_H + COL_HDR_H
ROUTE_H = 48
LINKS_HDR_H = 22
FOOTER_H = 54
ROUTE_TOP = 248


@dataclass
class PatchbayState:
    graph: jackutil.JackGraph = field(default_factory=jackutil.JackGraph)
    focus: str = FOCUS_SOURCES
    src_idx: int = 0
    sink_idx: int = 0
    link_idx: int = 0
    status_msg: str = "A/B move · C patch · D focus"
    dirty: bool = True

    def refresh_graph(self) -> None:
        self.graph = jackutil.fetch_graph()
        self.src_idx = min(self.src_idx, max(0, len(self.graph.outputs) - 1))
        self.sink_idx = min(self.sink_idx, max(0, len(self.graph.inputs) - 1))
        self.link_idx = min(self.link_idx, max(0, len(self.graph.connections) - 1))
        if self.graph.error:
            self.status_msg = self.graph.error
        else:
            self.status_msg = (
                f"{len(self.graph.outputs)} out · {len(self.graph.inputs)} in · "
                f"{len(self.graph.connections)} links"
            )
        self.dirty = True

    def selected_src(self) -> str | None:
        if not self.graph.outputs:
            return None
        return self.graph.outputs[self.src_idx]

    def selected_sink(self) -> str | None:
        if not self.graph.inputs:
            return None
        return self.graph.inputs[self.sink_idx]

    def pair_linked(self) -> bool:
        s, k = self.selected_src(), self.selected_sink()
        if not s or not k:
            return False
        return (s, k) in self.graph.connections

    def move(self, delta: int) -> None:
        if self.focus == FOCUS_SOURCES and self.graph.outputs:
            self.src_idx = (self.src_idx + delta) % len(self.graph.outputs)
        elif self.focus == FOCUS_SINKS and self.graph.inputs:
            self.sink_idx = (self.sink_idx + delta) % len(self.graph.inputs)
        elif self.focus == FOCUS_LINKS and self.graph.connections:
            self.link_idx = (self.link_idx + delta) % len(self.graph.connections)
        self.dirty = True

    def cycle_focus(self) -> None:
        i = FOCUS_ORDER.index(self.focus)
        prev = self.focus
        self.focus = FOCUS_ORDER[(i + 1) % len(FOCUS_ORDER)]
        if self.focus == FOCUS_SOURCES and prev == FOCUS_LINKS:
            self.refresh_graph()
            self.status_msg = "Graph refreshed"
        else:
            labels = {
                FOCUS_SOURCES: "Focus: OUT",
                FOCUS_SINKS: "Focus: IN",
                FOCUS_LINKS: "Focus: LINKS — C removes",
            }
            self.status_msg = labels[self.focus]
        self.dirty = True

    def toggle_selected(self) -> None:
        if self.focus == FOCUS_LINKS:
            if not self.graph.connections:
                self.status_msg = "No links to remove"
                self.dirty = True
                return
            src, dst = self.graph.connections[self.link_idx]
            _ok, msg = jackutil.disconnect(src, dst)
            self.status_msg = msg
            self.refresh_graph()
            return

        src = self.selected_src()
        dst = self.selected_sink()
        if not src or not dst:
            self.status_msg = "Need an OUT and an IN"
            self.dirty = True
            return
        _ok, msg = jackutil.toggle(src, dst, self.graph)
        self.status_msg = msg
        self.refresh_graph()


def _clip(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    if max_w <= 8:
        return ""
    if draw.textlength(text, font=fnt) <= max_w:
        return text
    ell = "..."
    while text and draw.textlength(text + ell, font=fnt) > max_w:
        text = text[:-1]
    return (text + ell) if text else ell


def _split_port(port: str) -> tuple[str, str]:
    if ":" in port:
        client, name = port.split(":", 1)
        client = (
            client.replace("Pure Data", "PD")
            .replace("SuperCollider", "SC")
            .replace("pisound", "pisnd")
            .replace("system", "sys")
        )
        return client, name
    return "", port


def _label(port: str) -> str:
    client, name = _split_port(port)
    return f"{client}:{name}" if client else name


def _scroll_window(selected: int, n_items: int, visible: int) -> int:
    if n_items <= visible:
        return 0
    if selected <= 0:
        return 0
    if selected >= n_items - 1:
        return max(0, n_items - visible)
    start = selected - visible // 2
    return max(0, min(start, n_items - visible))


def _jack_up(state: PatchbayState) -> bool:
    return not bool(state.graph.error)


def _draw_scrollbar(
    draw: ImageDraw.ImageDraw,
    x: int,
    top: int,
    bottom: int,
    n_items: int,
    visible: int,
    scroll: int,
) -> None:
    """Thin track + thumb on the column's inner edge."""
    if n_items <= visible:
        return
    track_w = 4
    draw.rectangle((x, top + 2, x + track_w, bottom - 2), fill=BLUE)
    track_h = max(1, bottom - top - 4)
    thumb_h = max(10, int(track_h * visible / n_items))
    max_scroll = max(1, n_items - visible)
    thumb_y = top + 2 + int((track_h - thumb_h) * scroll / max_scroll)
    draw.rectangle((x, thumb_y, x + track_w, thumb_y + thumb_h), fill=ORANGE)


def _draw_jack(draw: ImageDraw.ImageDraw, cx: int, cy: int, filled: bool, on_colour: bool) -> None:
    """1/4\" jack socket glyph."""
    r = 6
    ring = BLACK
    hole = WHITE if on_colour else WHITE
    if filled:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ring)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=hole)
    else:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ring, width=2)
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), outline=ring, width=1)


def render(state: PatchbayState) -> Image.Image:
    img = blank(WHITE)
    draw = ImageDraw.Draw(img)

    title_f = font(20, "bold")
    head_f = font(13, "bold")
    row_f = font(14, "bold")
    mono_f = font(13, "mono")
    small_f = font(12, "regular")
    route_f = font(15, "bold")
    tag_f = font(11, "bold")

    mid = WIDTH // 2
    src_focus = state.focus == FOCUS_SOURCES
    sink_focus = state.focus == FOCUS_SINKS
    link_focus = state.focus == FOCUS_LINKS

    # ── Header ──────────────────────────────────────────────────────────
    draw.rectangle((0, 0, WIDTH, HEADER_H), fill=BLACK)
    draw.text((12, HEADER_H // 2), "PATCHBAY", fill=YELLOW, font=title_f, anchor="lm")

    rate = jackutil.sample_rate()
    buf = jackutil.buffer_size()
    if rate != "—":
        meta = f"{rate}  {buf}"
    else:
        meta = sysinfo.hostname()
    draw.text((WIDTH // 2, HEADER_H // 2), meta, fill=WHITE, font=small_f, anchor="mm")

    jack_ok = _jack_up(state)
    badge_c = GREEN if jack_ok else RED
    badge_fg = BLACK if jack_ok else WHITE
    badge = "JACK *" if jack_ok else "JACK -"
    draw.rounded_rectangle((WIDTH - 108, 7, WIDTH - 10, HEADER_H - 7), radius=8, fill=badge_c)
    draw.text((WIDTH - 59, HEADER_H // 2), badge, fill=badge_fg, font=head_f, anchor="mm")

    # ── Column headers ──────────────────────────────────────────────────
    col_top = HEADER_H
    list_top = LIST_TOP
    list_bottom = ROUTE_TOP
    footer_top = HEIGHT - FOOTER_H
    links_top = ROUTE_TOP + ROUTE_H

    draw.rectangle((0, col_top, mid - 1, list_top - 1), fill=ORANGE if src_focus else BLUE)
    draw.rectangle((mid, col_top, WIDTH, list_top - 1), fill=ORANGE if sink_focus else BLUE)

    n_out = len(state.graph.outputs)
    n_in = len(state.graph.inputs)
    out_title = f"* OUT  {n_out}" if src_focus else f"  OUT  {n_out}"
    in_title = f"* IN  {n_in}" if sink_focus else f"  IN  {n_in}"
    draw.text((mid // 2, col_top + COL_HDR_H // 2), out_title, fill=WHITE, font=head_f, anchor="mm")
    draw.text((mid + mid // 2, col_top + COL_HDR_H // 2), in_title, fill=WHITE, font=head_f, anchor="mm")

    # Column body + divider
    draw.rectangle((0, list_top, mid - 1, list_bottom - 1), fill=WHITE)
    draw.rectangle((mid, list_top, WIDTH, list_bottom - 1), fill=WHITE)
    draw.line((mid, col_top, mid, list_bottom), fill=BLACK, width=2)

    row_h = 24
    visible = max(1, (list_bottom - list_top) // row_h)

    def paint_column(
        items: list[str],
        selected: int,
        x0: int,
        x1: int,
        focused: bool,
        peer: str | None,
        as_source: bool,
    ) -> None:
        pad_r = 8  # room for scrollbar
        if not items:
            draw.text(
                ((x0 + x1) // 2, (list_top + list_bottom) // 2),
                "no ports",
                fill=BLUE,
                font=small_f,
                anchor="mm",
            )
            return

        scroll = _scroll_window(selected, len(items), visible)
        # Scrollbar on the edge toward the centre divider
        sb_x = (x1 - pad_r) if as_source else (x0 + 2)
        _draw_scrollbar(draw, sb_x, list_top, list_bottom, len(items), visible, scroll)

        text_right = (sb_x - 4) if as_source else (x1 - 6)
        text_left = x0 + 22

        y = list_top
        for i in range(scroll, min(scroll + visible, len(items))):
            port = items[i]
            is_sel = i == selected
            if peer:
                is_linked = (
                    (port, peer) in state.graph.connections
                    if as_source
                    else (peer, port) in state.graph.connections
                )
            else:
                is_linked = False

            if as_source:
                degree = sum(1 for a, _b in state.graph.connections if a == port)
            else:
                degree = sum(1 for _a, b in state.graph.connections if b == port)

            bg = None
            if is_sel and focused:
                bg = ORANGE
            elif is_sel:
                bg = YELLOW
            elif is_linked:
                bg = GREEN

            if bg is not None:
                draw.rectangle((x0 + 1, y + 1, x1 - 1, y + row_h - 2), fill=bg)
            elif i > scroll:
                draw.line((text_left, y, text_right, y), fill=BLUE)

            cy = y + row_h // 2
            _draw_jack(draw, x0 + 12, cy, filled=(degree > 0), on_colour=(bg is not None))

            label = _label(port)
            max_w = text_right - text_left - (14 if degree else 0)
            draw.text(
                (text_left, cy),
                _clip(draw, label, row_f, max_w),
                fill=BLACK,
                font=row_f,
                anchor="lm",
            )

            if degree:
                # Small count, no heavy chip
                draw.text((text_right - 2, cy), str(degree), fill=BLACK, font=small_f, anchor="rm")

            y += row_h

    paint_column(
        state.graph.outputs,
        state.src_idx,
        0,
        mid,
        src_focus,
        state.selected_sink(),
        as_source=True,
    )
    paint_column(
        state.graph.inputs,
        state.sink_idx,
        mid,
        WIDTH,
        sink_focus,
        state.selected_src(),
        as_source=False,
    )

    # ── Route strip ─────────────────────────────────────────────────────
    linked = state.pair_linked()
    s = state.selected_src()
    k = state.selected_sink()

    if s and k:
        route_bg = GREEN if linked else ORANGE
    elif state.graph.error:
        route_bg = RED
    else:
        route_bg = BLUE
    draw.rectangle((0, ROUTE_TOP, WIDTH, ROUTE_TOP + ROUTE_H), fill=route_bg)

    # Top hairline so route reads as a separate band
    draw.line((0, ROUTE_TOP, WIDTH, ROUTE_TOP), fill=BLACK, width=2)
    draw.line((0, ROUTE_TOP + ROUTE_H - 1, WIDTH, ROUTE_TOP + ROUTE_H - 1), fill=BLACK, width=2)

    cy = ROUTE_TOP + ROUTE_H // 2
    if s and k:
        left = _clip(draw, _label(s), route_f, 190)
        right = _clip(draw, _label(k), route_f, 190)
        draw.text((14, cy), left, fill=BLACK, font=route_f, anchor="lm")
        draw.text((WIDTH - 14, cy), right, fill=BLACK, font=route_f, anchor="rm")

        # Cable
        x_a, x_b = 210, WIDTH - 210
        draw.line((x_a, cy + 6, x_b, cy + 6), fill=BLACK, width=3)
        _draw_jack(draw, x_a, cy + 6, filled=True, on_colour=True)
        _draw_jack(draw, x_b, cy + 6, filled=True, on_colour=True)
        # Centre ferrule
        draw.ellipse((WIDTH // 2 - 9, cy - 3, WIDTH // 2 + 9, cy + 15), fill=BLACK)
        if linked:
            draw.ellipse((WIDTH // 2 - 4, cy + 2, WIDTH // 2 + 4, cy + 10), fill=GREEN)
            tag = "LINKED"
        else:
            draw.ellipse((WIDTH // 2 - 4, cy + 2, WIDTH // 2 + 4, cy + 10), fill=ORANGE)
            tag = "C = PATCH"
        draw.text((WIDTH // 2, ROUTE_TOP + 11), tag, fill=BLACK, font=tag_f, anchor="mm")
    elif state.graph.error:
        draw.text((WIDTH // 2, cy), state.graph.error, fill=WHITE, font=route_f, anchor="mm")
    else:
        draw.text(
            (WIDTH // 2, cy),
            "select OUT + IN, press C to patch",
            fill=WHITE,
            font=route_f,
            anchor="mm",
        )

    # ── Links ───────────────────────────────────────────────────────────
    draw.rectangle((0, links_top, WIDTH, links_top + LINKS_HDR_H), fill=BLACK if link_focus else BLUE)
    n_links = len(state.graph.connections)
    links_title = f"* LINKS  {n_links}" if link_focus else f"  LINKS  {n_links}"
    if link_focus:
        links_title += "   C removes"
    draw.text(
        (12, links_top + LINKS_HDR_H // 2),
        links_title,
        fill=YELLOW if link_focus else WHITE,
        font=head_f,
        anchor="lm",
    )

    y = links_top + LINKS_HDR_H + 2
    link_area_bottom = footer_top - 2
    link_row_h = 18
    link_rows = max(1, (link_area_bottom - y) // link_row_h)
    links = state.graph.connections

    if not links:
        draw.text(
            (14, y + 2),
            "No cables yet — highlight OUT + IN, press C",
            fill=BLUE,
            font=small_f,
        )
    else:
        # When browsing OUT/IN, auto-scroll to the cable for the selected pair.
        pair_idx = -1
        if s and k:
            try:
                pair_idx = links.index((s, k))
            except ValueError:
                pair_idx = -1
        focus_idx = state.link_idx if link_focus else (pair_idx if pair_idx >= 0 else 0)
        scroll = _scroll_window(focus_idx, len(links), link_rows)
        _draw_scrollbar(
            draw, WIDTH - 8, y, link_area_bottom, len(links), link_rows, scroll
        )
        for i in range(scroll, min(scroll + link_rows, len(links))):
            src, dst = links[i]
            line = f"{_label(src)}  ->  {_label(dst)}"
            is_focus_sel = link_focus and i == state.link_idx
            is_pair = (s is not None and k is not None and (src, dst) == (s, k))
            if is_focus_sel:
                draw.rectangle((4, y, WIDTH - 12, y + link_row_h - 1), fill=ORANGE)
            elif is_pair:
                draw.rectangle((4, y, WIDTH - 12, y + link_row_h - 1), fill=GREEN)
            # Mini cable
            draw.line((12, y + 8, 26, y + 8), fill=BLACK, width=2)
            draw.ellipse((10, y + 5, 16, y + 11), outline=BLACK, width=1)
            draw.ellipse((24, y + 5, 30, y + 11), outline=BLACK, width=1)
            draw.text(
                (36, y + 1),
                _clip(draw, line, mono_f, WIDTH - 52),
                fill=BLACK,
                font=mono_f,
            )
            y += link_row_h

    # ── Footer ──────────────────────────────────────────────────────────
    draw.rectangle((0, footer_top, WIDTH, HEIGHT), fill=BLACK)
    draw.text(
        (12, footer_top + 11),
        _clip(draw, state.status_msg, small_f, WIDTH - 24),
        fill=WHITE,
        font=small_f,
    )

    # Buttons A–D + keyboard (↑↓ Enter Tab) — not a touch screen
    legend = [("A", "up"), ("B", "dn"), ("C", "patch"), ("D", "foc")]
    x = 8
    ly = HEIGHT - 16
    for key, desc in legend:
        draw.rounded_rectangle((x, ly - 10, x + 16, ly + 8), radius=3, fill=ORANGE)
        draw.text((x + 8, ly - 1), key, fill=BLACK, font=head_f, anchor="mm")
        draw.text((x + 20, ly - 1), desc, fill=WHITE, font=small_f, anchor="lm")
        x += 72
    draw.text((x + 4, ly - 1), "keys: arrows/enter/tab", fill=YELLOW, font=small_f, anchor="lm")

    if s and k:
        mark = "LINKED" if linked else "open"
        draw.text(
            (WIDTH - 12, ly - 1),
            mark,
            fill=GREEN if linked else YELLOW,
            font=head_f,
            anchor="rm",
        )

    return img
