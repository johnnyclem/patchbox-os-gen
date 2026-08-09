"""MATRIX — the patchbay. Inputs down the side, outputs along the top,
one tappable crosspoint each. Omni routes only from this screen; per-channel
filtering and rewriting stay project/scene data (a 16×16 channel matrix is
not a stage control).
"""
from __future__ import annotations

import pygame

from core import commands as cmd
from gui.screens.base import Screen
from rangerkit.gui import theme
from rangerkit.gui.widgets import button, panel, section_head, text
from rangerkit.routing import INPUTS, OUTPUTS, Route

LABEL_W = 96
HEAD_H = 34


class MatrixScreen(Screen):
    title = "MATRIX"
    legend = "TAP a cell to route that source to that destination"

    def on_tap(self, key: str) -> list:
        if key == "clear":
            self.host.message("MATRIX CLEARED")
            return [cmd.ClearRoutes()]
        if key.startswith("x:"):
            _tag, src, dst = key.split(":")
            return [cmd.ToggleRoute(Route(src=src, dst=dst))]
        return []

    def draw(self, surface: pygame.Surface) -> None:
        self.begin()
        snapshot = self.snapshot
        if snapshot is None:
            return
        inner = self.rect.inflate(-12, -12)
        head = pygame.Rect(inner.x, inner.y, inner.width, 18)
        section_head(surface, head, "ROUTING MATRIX · TAP A CROSSPOINT")
        body = pygame.Rect(inner.x, inner.y + 20, inner.width,
                           inner.height - 20)
        bound = dict(snapshot.inputs_bound) | dict(snapshot.outputs_bound)
        # Omni crosspoints present in the live matrix (any channel filter
        # counts — the panel shows the connection exists).
        active = {(r.src, r.dst) for r in snapshot.routes}

        grid_rect = pygame.Rect(body.x + LABEL_W, body.y + HEAD_H,
                                body.width - LABEL_W,
                                body.height - HEAD_H)
        columns = len(OUTPUTS)
        rows = len(INPUTS)
        for col, dst in enumerate(OUTPUTS):
            x = grid_rect.x + col * grid_rect.width // columns
            width = grid_rect.x + (col + 1) * grid_rect.width // columns - x
            label = pygame.Rect(x, body.y, width, HEAD_H - 4)
            ink = theme.TEXT if bound.get(dst, dst == "internal") \
                else theme.TEXT_MUTED
            text(surface, dst.replace("_out", "").replace("_", " "),
                 label, 12, ink, display=True)
        for row_index, src in enumerate(INPUTS):
            y = grid_rect.y + row_index * grid_rect.height // rows
            height = grid_rect.y + (row_index + 1) * grid_rect.height // rows \
                - y
            label = pygame.Rect(body.x, y, LABEL_W - 4, height - 4)
            panel(surface, label, theme.BG_RAISED)
            ink = theme.TEXT if bound.get(src) else theme.TEXT_MUTED
            text(surface, src.replace("_in", "").replace("_", " "),
                 label, 12, ink, display=True)
            for col, dst in enumerate(OUTPUTS):
                x = grid_rect.x + col * grid_rect.width // columns
                width = grid_rect.x + (col + 1) * grid_rect.width // columns \
                    - x
                cell = pygame.Rect(x + 2, y + 2, width - 6, height - 6)
                on = (src, dst) in active
                # Cyan, not orange: the design system paints an active route
                # cyan (§ROUTE) and keeps orange for transport state. A patch
                # bay full of orange read as a patch bay full of playing.
                button(surface, self.hits, f"x:{src}:{dst}", cell,
                       "●" if on else "", 18, active=on,
                       pressed=self.is_pressed(f"x:{src}:{dst}"),
                       color=theme.ACCENT3 if on else None, display=False)
        # A clear control beats eight taps when re-patching between songs.
        clear = pygame.Rect(body.x, body.y, LABEL_W - 4, HEAD_H - 4)
        button(surface, self.hits, "clear", clear, "CLEAR", 12,
               kind="dang")
