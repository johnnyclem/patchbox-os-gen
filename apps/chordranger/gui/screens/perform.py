"""PERFORM — the screen the instrument boots into.

Twelve pads, six section buttons, and a chord readout big enough to be legible
from behind a keyboard stand. Everything else is one tab away; this screen is
what you use with the lights down.

Layout on the 1280x400 bar (content is roughly 1012x400):

    ┌──────────────────────────────────────────────────────┐
    │ Cmaj7            ▸ Am7      KEY C MAJ   LATCH  MAIN A│  readout
    ├──────────────────────────────────────────────────────┤
    │  I    ii   iii   IV    V    vi                       │  pads 1-6
    │ vii°  V/V  iv    bVII  Isus V7                       │  pads 7-12
    ├──────────────────────────────────────────────────────┤
    │ INTRO  A   FILL   B   FILL  END   LATCH   CRUISE     │  form
    └──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.chordset import PAD_COUNT
from core.style import (ENDING, FILL_AB, FILL_BA, INTRO, MAIN_A, MAIN_B,
                        SECTION_LABELS)
from core.theory import SCALES, note_name
from gui import theme
from gui.screens.base import Screen
from gui.widgets import button, grid, lcd, panel, row, text

# The order the six form buttons sit in, left to right: it is the shape of the
# arrangement, so INTRO is on the left and ENDING on the right and the two
# mains have their fills beside them.
FORM_BUTTONS = (INTRO, MAIN_A, FILL_AB, MAIN_B, FILL_BA, ENDING)

# Pads are tinted by harmonic function rather than by position, so the layout
# teaches itself: the three tonic chords share a colour, the two predominants
# share another, and anything borrowed from outside the key is grey. A player
# learns where the "home" pads are without ever reading a numeral.
_TONIC = ("I", "i", "vi", "VI", "iii", "III")
_SUBDOMINANT = ("IV", "iv", "ii", "II")
_DOMINANT = ("V", "v", "vii°", "VII", "vii")


def _family_color(numeral: str):
    """Which function family a numeral belongs to. Secondary dominants
    (``V/ii``) take the dominant colour — that is what they are doing."""
    if not numeral:
        return theme.BG_RAISED
    if numeral.startswith("V/"):
        return theme.ACCENT2
    head = numeral.rstrip("°7")
    if head in _TONIC:
        return theme.ACCENT
    if head in _SUBDOMINANT:
        return theme.ACCENT3
    if head in _DOMINANT or numeral.startswith(("V", "v")):
        return theme.ACCENT2
    return theme.BG_RAISED


class PerformScreen(Screen):
    title = "PERFORM"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self._held: set[int] = set()

    # --- input ---------------------------------------------------------------
    def on_press(self, key: str) -> list:
        if key.startswith("pad"):
            index = int(key[3:])
            self._held.add(index)
            return [cmd.PadDown(index)]
        return []

    def on_release(self, key: str, moved_away: bool = False) -> list:
        if key and key.startswith("pad"):
            index = int(key[3:])
            self._held.discard(index)
            return [cmd.PadUp(index)]
        return []

    def on_tap(self, key: str) -> list:
        if key.startswith("pad"):
            return []                   # the press already did the work
        if key.startswith("form:"):
            return [cmd.RequestSection(key.split(":", 1)[1])]
        if key == "latch":
            snapshot = self.snapshot
            return [cmd.SetLatch(not (snapshot.latch if snapshot else True))]
        if key == "cruise":
            self.host.set_tab("CHORD")
            return []
        if key == "song":
            snapshot = self.snapshot
            return [cmd.SetSongMode(not (snapshot.song_mode if snapshot
                                         else False))]
        return []

    def on_long_press(self, key: str) -> list:
        """Holding a pad opens it in the chord editor — the shortcut that
        makes Chord Edit reachable without leaving the performance."""
        if key.startswith("pad"):
            self.host.set_edit_target(int(key[3:]))
            self.host.set_tab("CHORD")
            return []
        return self.on_tap(key)

    # --- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        snapshot = self.snapshot
        surface.fill(theme.BG, self.rect)
        head = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, 92)
        pads = pygame.Rect(self.rect.x, head.bottom + 2, self.rect.width,
                           self.rect.height - head.height - 78)
        form = pygame.Rect(self.rect.x, pads.bottom + 2, self.rect.width,
                           self.rect.bottom - pads.bottom - 4)
        self._draw_head(surface, head, snapshot)
        self._draw_pads(surface, pads, snapshot)
        self._draw_form(surface, form, snapshot)

    def _draw_head(self, surface, rect, snapshot) -> None:
        panel(surface, rect, theme.BG_RAISED)
        chord_rect = pygame.Rect(rect.x + 4, rect.y + 4, 300, rect.height - 8)
        lcd(surface, chord_rect,
            snapshot.chord_symbol if snapshot else "—", size=44,
            label="CHORD")
        nxt = pygame.Rect(chord_rect.right + 6, rect.y + 4, 190,
                          rect.height - 8)
        following = (snapshot.next_chord_symbol if snapshot else "") or "—"
        lcd(surface, nxt, following, size=24, label="NEXT",
            color=theme.blend(theme.BG_LCD, theme.DISPLAY, 0.7))

        info = pygame.Rect(nxt.right + 6, rect.y + 4,
                           rect.right - nxt.right - 10, rect.height - 8)
        panel(surface, info, theme.BG_SUNKEN)
        cells = grid(info.inflate(-6, -6), 2, 2, gap=4)
        key_text = ("%s %s" % (note_name(snapshot.key_root),
                               SCALES[snapshot.scale].label
                               if snapshot.scale in SCALES else "")
                    if snapshot else "—")
        self._stat(surface, cells[0], "KEY", key_text)
        self._stat(surface, cells[1], "STYLE",
                   snapshot.style_name if snapshot else "—")
        self._stat(surface, cells[2], "SET",
                   snapshot.chordset_name if snapshot else "—")
        section = (SECTION_LABELS.get(snapshot.section, snapshot.section)
                   if snapshot else "—")
        queued = (snapshot.next_section if snapshot else "")
        if queued and snapshot and queued != snapshot.section:
            section += " ▸ " + SECTION_LABELS.get(queued, queued)[:6]
        self._stat(surface, cells[3], "SECTION", section,
                   color=theme.ACCENT2 if queued and snapshot
                   and queued != snapshot.section else None)

    def _stat(self, surface, rect, label, value, color=None) -> None:
        text(surface, label, pygame.Rect(rect.x, rect.y, rect.width, 13), 10,
             theme.TEXT_DIM, display=True, align="left", pad=4)
        text(surface, value,
             pygame.Rect(rect.x, rect.y + 11, rect.width, rect.height - 11),
             16, color or theme.TEXT, bold=True, align="left", pad=4)

    def _draw_pads(self, surface, rect, snapshot) -> None:
        cells = grid(rect, 6, 2, gap=theme.PAD_GAP)
        for index in range(PAD_COUNT):
            cell = cells[index]
            caption = (snapshot.pad_captions[index]
                       if snapshot and index < len(snapshot.pad_captions)
                       else "")
            numeral = (snapshot.pad_numerals[index]
                       if snapshot and index < len(snapshot.pad_numerals)
                       else "")
            live = bool(snapshot and snapshot.pad_active[index])
            held = index in self._held
            if not caption:
                # A dead pad is drawn as an empty well and registers no hit,
                # so a stray touch on the far end of the panel does nothing.
                panel(surface, cell, theme.BG_SUNKEN)
                text(surface, "·", cell, 18, theme.TEXT_MUTED)
                continue
            face = (theme.ACCENT if live else
                    theme.BG_PRESS if held else
                    theme.tint(_family_color(numeral), 0.18))
            panel(surface, cell, face, shadow=not live)
            ink = theme.ink_for(face)
            text(surface, caption,
                 pygame.Rect(cell.x, cell.y + 6, cell.width,
                             cell.height - 26), 26, ink, bold=True)
            # Not ``display``: a roman numeral's case is its meaning — ii is
            # a minor chord and II is not — so this is the one label on the
            # panel that must never be upper-cased for style.
            text(surface, numeral,
                 pygame.Rect(cell.x, cell.bottom - 22, cell.width, 20), 13,
                 ink if live else theme.TEXT_DIM)
            index_rect = pygame.Rect(cell.x + 3, cell.y + 2, 22, 14)
            text(surface, str(index + 1), index_rect, 10,
                 ink if live else theme.TEXT_MUTED, align="left", pad=2)
            self.hits.add(f"pad{index}", cell)

    def _draw_form(self, surface, rect, snapshot) -> None:
        cells = row(rect, 9, gap=theme.PAD_GAP)
        for index, name in enumerate(FORM_BUTTONS):
            active = bool(snapshot and snapshot.section == name)
            queued = bool(snapshot and snapshot.next_section == name
                          and not active)
            color = (theme.ACCENT if name in (MAIN_A, MAIN_B) else
                     theme.DANGER if name == ENDING else theme.ACCENT3)
            button(surface, self.hits, f"form:{name}", cells[index],
                   SECTION_LABELS[name], 13,
                   active=active or queued,
                   color=theme.ACCENT2 if queued else color,
                   pressed=self.is_pressed(f"form:{name}"))
        latched = bool(snapshot and snapshot.latch)
        button(surface, self.hits, "latch", cells[6], "LATCH", 12,
               active=latched, color=theme.ACCENT3,
               sub="HOLD" if latched else "GATE")
        song = bool(snapshot and snapshot.song_mode)
        button(surface, self.hits, "song", cells[7], "SONG", 12, active=song,
               color=theme.ACCENT2,
               sub=f"{snapshot.song_bar + 1}/{snapshot.song_bars}"
               if snapshot and song else "OFF")
        button(surface, self.hits, "cruise", cells[8], "CRUISE", 12,
               color=theme.ACCENT3)
