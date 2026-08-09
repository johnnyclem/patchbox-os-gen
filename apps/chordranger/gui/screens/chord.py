"""CHORD — Chord Edit, Chord Cruiser and Chord Voicing on one screen.

Chordcat splits these across modes. On a 1280-pixel-wide panel they fit
side by side, and they belong together: you edit a chord, you ask what could
follow it, you try it in another voicing, and each answer feeds the next.

    ┌──────────┬───────────────────────────┬──────────────────┐
    │ PAD  5   │  R  b2  2  b3  3  4       │  CRUISER         │
    │ Cmaj7    │  b5 5  b6  6  b7  7       │  Am7   RELATIVE  │
    │ ◂ QUALITY│  (tap a degree to add or  │  F     SUBDOM    │
    │ ◂ TRANSP │   remove it)              │  G7    DOMINANT  │
    │ WRITE    │  VOICING  DROP2  ◂ DIAL ▸ │  ...             │
    └──────────┴───────────────────────────┴──────────────────┘

The edited chord is *local* to this screen until WRITE is pressed. That is the
Chordcat behaviour (press Enter to confirm, Back to cancel) and it is the only
sane one: half-built chords must not leak into a performance, and the pad you
are editing is very often the pad you are currently playing.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.chords import (COMMON_QUALITIES, Chord, VOICINGS, VOICING_LABELS,
                         VoicingSpec, quality_for, voice)
from core.chordset import PAD_COUNT
from core.cruiser import suggest
from core.theory import note_label, note_name
from gui import theme
from gui.screens.base import Screen
from gui.widgets import Stepper, button, column, grid, lcd, panel, row, text

# Interval names for the twelve edit keys. Flats throughout: a chord tone a
# semitone under the fifth is a b5 to every player alive, whatever the key
# signature says it should be spelled.
DEGREE_NAMES = ("R", "b2", "2", "b3", "3", "4", "b5", "5", "b6", "6", "b7",
                "7")
SUGGESTION_ROWS = 6


class ChordScreen(Screen):
    title = "CHORD"
    legend = "TAP a degree to add or remove it · − / + step the value"

    def __init__(self, host, rect) -> None:
        super().__init__(host, rect)
        self.working: Chord | None = None   # the edit in progress
        self._source: Chord | None = None   # what the pad held when we started
        self._suggestions = ()
        self._suggest_key: tuple = ()

    # --- state ---------------------------------------------------------------
    def target(self) -> int:
        return max(0, min(PAD_COUNT - 1, self.host.edit_target()))

    def current(self) -> Chord | None:
        """The chord being edited: the local working copy if there is one,
        else whatever the pad currently holds."""
        if self.working is not None:
            return self.working
        snapshot = self.snapshot
        if snapshot is None or not snapshot.pad_captions:
            return None
        return self._pad_chord()

    def _pad_chord(self) -> Chord | None:
        """The target pad's chord, straight off the snapshot.

        The snapshot carries the chord objects and not just the captions
        precisely so this is a lookup: a hand-edited chord cannot be
        reconstructed by parsing its printed symbol back, and an editor that
        silently reverted your edits every time you left the screen would be
        worse than no editor.
        """
        snapshot = self.snapshot
        index = self.target()
        if snapshot is None or index >= len(snapshot.pad_chords):
            return None
        return snapshot.pad_chords[index]

    def _dirty(self) -> bool:
        return self.working is not None and self.working != self._pad_chord()

    # --- input ---------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        chord = self.current()
        if key.startswith("deg"):
            if chord is None:
                return []
            self.working = chord.toggled(int(key[3:]))
            return self._audition()
        if key.startswith("sug"):
            index = int(key[3:])
            if index < len(self._suggestions):
                self.working = self._suggestions[index].chord
                return self._audition()
            return []
        if key.startswith("voi:"):
            style = key.split(":", 1)[1]
            spec = self._spec()
            return [cmd.SetVoicing(_replace(spec, style=style))]
        if key == "pad-" or key == "pad+":
            step = 1 if key.endswith("+") else -1
            self.host.set_edit_target((self.target() + step) % PAD_COUNT)
            self.working = None
            return []
        if key in ("qual-", "qual+"):
            return self._cycle_quality(1 if key.endswith("+") else -1)
        if key in ("trans-", "trans+"):
            step = 1 if key.endswith("+") else -1
            if chord is None:
                return []
            self.working = chord.transposed(step)
            return self._audition()
        if key in ("dial-", "dial+"):
            spec = self._spec()
            step = 1 if key.endswith("+") else -1
            return [cmd.SetVoicing(_replace(spec, dial=max(
                -6, min(6, spec.dial + step))))]
        if key in ("oct-", "oct+"):
            spec = self._spec()
            step = 1 if key.endswith("+") else -1
            return [cmd.SetVoicing(_replace(spec, octave=max(
                -2, min(2, spec.octave + step))))]
        if key == "write":
            if chord is None:
                return []
            self.working = None
            self.host.message(f"PAD {self.target() + 1} = {chord.symbol()}")
            return [cmd.SetPad(self.target(), chord)]
        if key == "revert":
            self.working = None
            self.host.message("EDIT CANCELLED")
            return []
        if key == "play":
            return self._audition()
        return []

    def _cycle_quality(self, step: int) -> list:
        chord = self.current()
        if chord is None:
            return []
        qualities = list(COMMON_QUALITIES)
        try:
            index = qualities.index(chord.quality)
        except ValueError:
            index = 0
        self.working = chord.with_quality(
            qualities[(index + step) % len(qualities)])
        return self._audition()

    def _audition(self) -> list:
        chord = self.current()
        return [cmd.SetChord(chord)] if chord is not None else []

    def _spec(self) -> VoicingSpec:
        return self.snapshot.voicing if self.snapshot else VoicingSpec()

    def repeats(self, key: str) -> bool:
        return key in ("trans-", "trans+", "dial-", "dial+")

    def on_repeat(self, key: str, steps: int) -> list:
        out: list = []
        for _ in range(steps):
            out.extend(self.on_tap(key))
        return out[-1:] if out else []

    # --- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        surface.fill(theme.BG, self.rect)
        left = pygame.Rect(self.rect.x, self.rect.y, 236, self.rect.height)
        right = pygame.Rect(self.rect.right - 300, self.rect.y, 300,
                            self.rect.height)
        middle = pygame.Rect(left.right + 4, self.rect.y,
                             right.left - left.right - 8, self.rect.height)
        self._draw_target(surface, left)
        self._draw_degrees(surface, middle)
        self._draw_cruiser(surface, right)

    def _draw_target(self, surface, rect) -> None:
        chord = self.current()
        panel(surface, rect, theme.BG_RAISED)
        inner = rect.inflate(-8, -8)
        cells = column(inner, 6, gap=5)
        lcd(surface, cells[0], chord.symbol() if chord else "—", size=30,
            label=f"PAD {self.target() + 1}"
            + ("  ·EDIT" if self._dirty() else ""))
        Stepper("pad", "PAD", str(self.target() + 1)).draw(
            surface, self.hits, cells[1], self._pressed)
        Stepper("qual", "QUALITY",
                quality_for(chord.quality).label or "MAJ" if chord else "—"
                ).draw(surface, self.hits, cells[2], self._pressed)
        Stepper("trans", "ROOT",
                note_name(chord.root) if chord else "—").draw(
                    surface, self.hits, cells[3], self._pressed)
        actions = row(cells[4], 2, gap=5)
        button(surface, self.hits, "write", actions[0], "WRITE", 14,
               active=self._dirty(), color=theme.ACCENT2,
               pressed=self.is_pressed("write"))
        button(surface, self.hits, "revert", actions[1], "CANCEL", 14,
               disabled=not self._dirty(), kind="dang",
               pressed=self.is_pressed("revert"))
        notes = (voice(chord, self._spec()) if chord else ())
        text(surface, " ".join(note_label(n) for n in notes[:6]) or "—",
             cells[5], 13, theme.TEXT_DIM, align="left")

    def _draw_degrees(self, surface, rect) -> None:
        chord = self.current()
        present = {i % 12 for i in chord.intervals} if chord else set()
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        text(surface, "CHORD EDIT — TAP A DEGREE TO ADD OR REMOVE", head, 11,
             theme.TEXT_DIM, display=True, align="left", pad=2)
        keys = pygame.Rect(rect.x, head.bottom, rect.width, 168)
        cells = grid(keys, 6, 2, gap=5)
        for degree in range(12):
            cell = cells[degree]
            on = degree in present
            face = theme.ACCENT if on else theme.BG_RAISED
            panel(surface, cell, face)
            ink = theme.ink_for(face)
            text(surface, DEGREE_NAMES[degree],
                 pygame.Rect(cell.x, cell.y + 4, cell.width,
                             cell.height - 18), 22, ink, bold=True)
            if chord is not None:
                pitch = (chord.root + degree) % 12
                text(surface, note_name(pitch),
                     pygame.Rect(cell.x, cell.bottom - 20, cell.width, 18), 12,
                     ink if on else theme.TEXT_MUTED)
            self.hits.add(f"deg{degree}", cell)

        voicing = pygame.Rect(rect.x, keys.bottom + 6, rect.width,
                              rect.bottom - keys.bottom - 8)
        self._draw_voicing(surface, voicing)

    def _draw_voicing(self, surface, rect) -> None:
        """All eight voicing styles, then the two dials.

        The styles get two rows of four rather than one row of eight: at this
        width eight cells put every label under 90 px, which truncates
        "ROOTLESS" to something unreadable and drops each target below the
        44 px the touch rules ask for.
        """
        spec = self._spec()
        head = pygame.Rect(rect.x, rect.y, rect.width, 16)
        text(surface, "VOICING", head, 11, theme.TEXT_DIM, display=True,
             align="left", pad=2)
        body = pygame.Rect(rect.x, head.bottom, rect.width,
                           rect.height - head.height)
        bands = column(body, 3, gap=4)
        for band, offset in ((bands[0], 0), (bands[1], 4)):
            cells = row(band, 4, gap=4)
            for index, style in enumerate(VOICINGS[offset:offset + 4]):
                button(surface, self.hits, f"voi:{style}", cells[index],
                       VOICING_LABELS[style], 12, active=spec.style == style,
                       color=theme.ACCENT3)
        dials = row(bands[2], 3, gap=4)
        Stepper("dial", "DIAL", f"{spec.dial:+d}", width=40).draw(
            surface, self.hits, dials[0], self._pressed, size=15)
        Stepper("oct", "OCT", f"{spec.octave:+d}", width=40).draw(
            surface, self.hits, dials[1], self._pressed, size=15)
        button(surface, self.hits, "play", dials[2], "AUDITION", 12,
               pressed=self.is_pressed("play"))

    def _draw_cruiser(self, surface, rect) -> None:
        panel(surface, rect, theme.BG_RAISED)
        inner = rect.inflate(-8, -8)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        text(surface, "CHORD CRUISER — WHAT COMES NEXT", head, 11,
             theme.TEXT_DIM, display=True, align="left", pad=2)
        self._refresh_suggestions()
        body = pygame.Rect(inner.x, head.bottom + 2, inner.width,
                           inner.bottom - head.bottom - 4)
        cells = column(body, SUGGESTION_ROWS, gap=4)
        for index in range(SUGGESTION_ROWS):
            cell = cells[index]
            if index >= len(self._suggestions):
                panel(surface, cell, theme.BG_SUNKEN)
                continue
            pick = self._suggestions[index]
            panel(surface, cell, theme.BG_PRESS
                  if self.is_pressed(f"sug{index}") else theme.BG_SUNKEN)
            text(surface, pick.symbol,
                 pygame.Rect(cell.x, cell.y, cell.width // 2, cell.height),
                 20, theme.TEXT, bold=True, align="left")
            text(surface, pick.reason,
                 pygame.Rect(cell.centerx, cell.y, cell.width // 2,
                             cell.height), 11, theme.TEXT_DIM, display=True,
                 align="right")
            self.hits.add(f"sug{index}", cell)

    def _refresh_suggestions(self) -> None:
        """Recompute only when the question changed. The cruiser is cheap but
        it runs every frame otherwise, and a suggestion list that reshuffles
        under a finger is unusable."""
        chord = self.current()
        snapshot = self.snapshot
        key = (chord, snapshot.key_root if snapshot else 0,
               snapshot.scale if snapshot else "major")
        if key == self._suggest_key:
            return
        self._suggest_key = key
        avoid = tuple(c for c in (snapshot.pad_chords if snapshot else ())
                      if c is not None)
        self._suggestions = suggest(chord, key[1], key[2],
                                    limit=SUGGESTION_ROWS, avoid=avoid)


def _replace(spec: VoicingSpec, **fields) -> VoicingSpec:
    from dataclasses import replace
    return replace(spec, **fields)
