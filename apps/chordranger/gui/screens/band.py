"""BAND — the mixer and the bass engine.

Left half is the band: one column per part, each with a mute, an octave and a
level, and a lamp that lights while that part is actually sounding. The lamp
matters more than it looks: when something is not coming out of the rig, the
first question is always "is the box playing it, or is the synth not hearing
it?", and a lit lamp with silence downstream answers it instantly.

Right half is the bass engine — Orchid's second voice, with its own mode,
pattern, register and dial. It is given a whole half of the screen because on
a chord instrument the bass is the part players actually reach for mid-song.
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from core.bass import (BASS_MODE_LABELS, BASS_MODES, BASS_PATTERNS, BassSpec)
from gui import theme
from gui.screens.base import Screen
from gui.widgets import (Stepper, button, column, led, meter, panel, row,
                         text)

PATTERN_NAMES = tuple(BASS_PATTERNS)


class BandScreen(Screen):
    title = "BAND"

    # --- input ---------------------------------------------------------------
    def on_tap(self, key: str) -> list:
        snapshot = self.snapshot
        if snapshot is None:
            return []
        if key.startswith("mute:"):
            part_id = key.split(":", 1)[1]
            part = next((p for p in snapshot.parts if p.id == part_id), None)
            return [] if part is None else [cmd.SetPartMute(part_id,
                                                            not part.muted)]
        if key.startswith("oct"):
            part_id, _, sign = key[3:].rpartition(":")
            part = next((p for p in snapshot.parts if p.id == part_id), None)
            if part is None:
                return []
            step = 1 if sign == "+" else -1
            return [cmd.SetPartField(part_id, "octave", part.octave + step)]
        if key.startswith("vel"):
            part_id, _, sign = key[3:].rpartition(":")
            part = next((p for p in snapshot.parts if p.id == part_id), None)
            if part is None:
                return []
            step = 5 if sign == "+" else -5
            return [cmd.SetPartField(part_id, "velocity",
                                     part.velocity + step)]
        spec = snapshot.bass
        if key.startswith("mode:"):
            return [cmd.SetBass(_with(spec, mode=key.split(":", 1)[1]))]
        if key in ("patt-", "patt+"):
            return [cmd.SetBass(_with(spec, pattern=_cycle_pattern(
                spec.pattern, 1 if key.endswith("+") else -1)))]
        if key in ("bdial-", "bdial+"):
            step = 1 if key.endswith("+") else -1
            return [cmd.SetBass(_with(spec, dial=max(-6, min(
                6, spec.dial + step))))]
        if key in ("boct-", "boct+"):
            step = 1 if key.endswith("+") else -1
            return [cmd.SetBass(_with(spec, octave=spec.octave + step))]
        if key in ("gate-", "gate+"):
            step = 10 if key.endswith("+") else -10
            return [cmd.SetBass(_with(spec, gate=spec.gate + step))]
        if key == "slide":
            return [cmd.SetBass(_with(spec, slide=not spec.slide))]
        if key == "slash":
            return [cmd.SetBass(_with(spec,
                                      follow_slash=not spec.follow_slash))]
        if key in ("strum-", "strum+"):
            step = 1 if key.endswith("+") else -1
            return [cmd.SetStrum(snapshot.strum + step)]
        return []

    def repeats(self, key: str) -> bool:
        return key.endswith(("+", "-")) and not key.startswith("mode:")

    def on_repeat(self, key: str, steps: int) -> list:
        out: list = []
        for _ in range(steps):
            out.extend(self.on_tap(key))
        return out[-1:] if out else []

    # --- drawing -------------------------------------------------------------
    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        surface.fill(theme.BG, self.rect)
        left = pygame.Rect(self.rect.x, self.rect.y, self.rect.width * 5 // 9,
                           self.rect.height)
        right = pygame.Rect(left.right + 4, self.rect.y,
                            self.rect.right - left.right - 4,
                            self.rect.height)
        self._draw_mixer(surface, left)
        self._draw_bass(surface, right)

    def _draw_mixer(self, surface, rect) -> None:
        snapshot = self.snapshot
        parts = snapshot.parts if snapshot else ()
        head = pygame.Rect(rect.x, rect.y, rect.width, 18)
        text(surface, f"BAND — {snapshot.style_name if snapshot else ''}",
             head, 11, theme.TEXT_DIM, display=True, align="left", pad=2)
        body = pygame.Rect(rect.x, head.bottom, rect.width,
                           rect.height - head.height - 4)
        if not parts:
            panel(surface, body, theme.BG_SUNKEN)
            return
        strips = row(body, len(parts), gap=5)
        for index, part in enumerate(parts):
            self._draw_strip(surface, strips[index], part, index)

    def _draw_strip(self, surface, rect, part, index) -> None:
        color = theme.part_color(index)
        panel(surface, rect, theme.tint(color, 0.10 if part.muted else 0.20))
        cells = column(rect.inflate(-6, -6), 5, gap=4)
        text(surface, part.name, cells[0], 15, theme.TEXT, bold=True,
             display=True)
        led(surface, (cells[0].right - 8, cells[0].centery),
            part.active > 0, color=theme.ACCENT, radius=4)
        button(surface, self.hits, f"mute:{part.id}", cells[1],
               "MUTE" if not part.muted else "MUTED", 12,
               active=part.muted, color=theme.DANGER)
        Stepper(f"oct{part.id}:", "OCT", f"{part.octave:+d}", width=26).draw(
            surface, self.hits, cells[2], self._pressed, size=13)
        Stepper(f"vel{part.id}:", "VEL", str(part.velocity), width=26).draw(
            surface, self.hits, cells[3], self._pressed, size=13)
        # Voices sounding, then the channel underneath. Split explicitly
        # rather than overlaid: a meter with type on top of it is unreadable
        # in exactly the moment it has something to say.
        bar = pygame.Rect(cells[4].x, cells[4].y, cells[4].width, 12)
        meter(surface, bar, min(1.0, part.active / 4.0), color)
        channel = pygame.Rect(cells[4].x, bar.bottom + 2, cells[4].width,
                              cells[4].bottom - bar.bottom - 2)
        text(surface, f"CH{part.channel + 1}", channel, 12, theme.TEXT_DIM)

    def _draw_bass(self, surface, rect) -> None:
        snapshot = self.snapshot
        spec = snapshot.bass if snapshot else BassSpec()
        panel(surface, rect, theme.BG_RAISED)
        inner = rect.inflate(-8, -8)
        head = pygame.Rect(inner.x, inner.y, inner.width, 16)
        text(surface, "BASS ENGINE", head, 11, theme.TEXT_DIM, display=True,
             align="left", pad=2)
        rows = column(pygame.Rect(inner.x, head.bottom, inner.width,
                                  inner.height - head.height), 4, gap=5)

        modes = row(rows[0], 4, gap=4)
        for index, mode in enumerate(BASS_MODES[:4]):
            button(surface, self.hits, f"mode:{mode}", modes[index],
                   BASS_MODE_LABELS[mode], 13, active=spec.mode == mode,
                   color=theme.ACCENT)
        more = row(rows[1], 4, gap=4)
        for index, mode in enumerate(BASS_MODES[4:]):
            button(surface, self.hits, f"mode:{mode}", more[index],
                   BASS_MODE_LABELS[mode], 13, active=spec.mode == mode,
                   color=theme.ACCENT)
        button(surface, self.hits, "slide", more[3], "SLIDE", 12,
               active=spec.slide, color=theme.ACCENT3,
               sub="GLIDE" if spec.slide else "OFF")

        knobs = row(rows[2], 4, gap=4)
        Stepper("patt", "PATT", _pattern_name(spec.pattern),
                width=28).draw(surface, self.hits, knobs[0], self._pressed,
                               size=12)
        Stepper("bdial", "DIAL", f"{spec.dial:+d}", width=28).draw(
            surface, self.hits, knobs[1], self._pressed, size=13)
        Stepper("boct", "OCT", f"{spec.octave:+d}", width=28).draw(
            surface, self.hits, knobs[2], self._pressed, size=13)
        Stepper("gate", "GATE", f"{spec.gate}%", width=28).draw(
            surface, self.hits, knobs[3], self._pressed, size=13)

        bottom = row(rows[3], 3, gap=4)
        self._draw_pattern(surface, bottom[0], spec)
        button(surface, self.hits, "slash", bottom[1], "SLASH", 12,
               active=spec.follow_slash, color=theme.ACCENT3,
               sub="C/E" if spec.follow_slash else "ROOT")
        Stepper("strum", "STRUM",
                f"{snapshot.strum if snapshot else 0}t", width=28).draw(
                    surface, self.hits, bottom[2], self._pressed, size=13)

    def _draw_pattern(self, surface, rect, spec) -> None:
        """The bass step pattern, drawn as sixteen lamps.

        Read-only here — it is a display of what the named pattern is, and the
        PATTERN stepper is how you change it. A sixteen-step editor at this
        size would be a row of 12-pixel targets, which is below anything a
        finger can hit reliably.
        """
        panel(surface, rect, theme.BG_SUNKEN)
        steps = spec.pattern[:16]
        width = max(1, (rect.width - 8) // 16)
        for index in range(16):
            centre = (rect.x + 6 + index * width + width // 2, rect.centery)
            led(surface, centre, steps[index:index + 1] in ("x", "X"),
                color=theme.ACCENT2 if index % 4 == 0 else theme.ACCENT,
                radius=max(2, min(5, width // 2 - 1)))


def _with(spec: BassSpec, **fields) -> BassSpec:
    from dataclasses import replace
    return replace(spec, **fields)


def _pattern_name(pattern: str) -> str:
    for name, value in BASS_PATTERNS.items():
        if value == pattern:
            return name
    return "CUSTOM"


def _cycle_pattern(pattern: str, step: int) -> str:
    names = PATTERN_NAMES
    current = _pattern_name(pattern)
    index = names.index(current) if current in names else 0
    return BASS_PATTERNS[names[(index + step) % len(names)]]
