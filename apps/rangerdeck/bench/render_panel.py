"""Render the launch grid to PNG without a display.

    python bench/render_panel.py [outdir] [--size 1280x400]

Runs the real App against a fake fleet under SDL's dummy driver and writes
one image per fleet state worth photographing. This is how the panel gets
reviewed without the hardware on the desk — and it is worth having as a
script rather than a test because looking at the pictures is the point.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(1, str(_ROOT.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import tempfile                                          # noqa: E402

import pygame                                            # noqa: E402

from core.engine import BACKGROUND, DeckFleet            # noqa: E402
from core.registry import KNOWN_APPS, AppSpec            # noqa: E402
from gui.app import App                                  # noqa: E402


class _Idle:
    def send(self, command):
        return True

    def wait_event(self, timeout=None):
        return None

    def drain(self):
        return []

    def close(self):
        pass

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        pass


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") \
        else Path("docs/img")
    size = (1280, 400)
    for index, arg in enumerate(argv):
        if arg == "--size" and index + 1 < len(argv):
            width, _, height = argv[index + 1].partition("x")
            size = (int(width), int(height))
    out.mkdir(parents=True, exist_ok=True)

    specs = tuple(AppSpec(name, title, tagline, ("python", "main.py"))
                  for name, title, tagline in KNOWN_APPS)
    fleet = DeckFleet(specs, Path(tempfile.mkdtemp(prefix="rdeck-")),
                      spawn=lambda command: _Idle(),
                      connect=lambda name, timeout: _Idle())
    app = App(fleet, size=size)

    shots = [("idle", ())]
    fleet.launch("midiranger")
    fleet.try_attach("midiranger")
    fleet.launch("grooveranger")
    fleet.try_attach("grooveranger")
    assert fleet.state("midiranger") == BACKGROUND
    app.message("MIDIRANGER RUNNING")
    shots.append(("running", ("midiranger", "grooveranger")))

    for index, (label, _running) in enumerate(shots):
        app._draw()
        path = out / f"deck-{size[0]}x{size[1]}-{index}-{label}.png"
        pygame.image.save(app.surface, str(path))
        print(f"wrote {path}")
    pygame.display.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
