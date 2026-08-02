"""Render every screen to PNG without a display.

    python bench/render_panel.py [outdir] [--size 1280x400]

Runs the real App against a real engine under SDL's dummy driver and writes
one image per tab. This is how the panel gets reviewed without the hardware
on the desk — and it is worth having as a script rather than a test because
looking at the pictures is the point.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame                                            # noqa: E402

from core import commands as cmd                         # noqa: E402
from core.clock import FakeClock                         # noqa: E402
from core.engine import Engine                           # noqa: E402
from core.events import TICKS_PER_BAR                    # noqa: E402
from core.midi_io import CaptureMidiIO                   # noqa: E402
from core.project import default_project                 # noqa: E402
from core.song import from_symbols                       # noqa: E402
from gui.app import App                                  # noqa: E402


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") \
        else Path("docs/img")
    size = (1280, 400)
    for index, arg in enumerate(argv):
        if arg == "--size" and index + 1 < len(argv):
            width, _, height = argv[index + 1].partition("x")
            size = (int(width), int(height))
    out.mkdir(parents=True, exist_ok=True)

    engine = Engine(default_project(), CaptureMidiIO(), FakeClock())
    app = App(engine, size=size)
    # A demo state worth photographing: playing, a chord held, a song written.
    engine.submit(cmd.SetSong(from_symbols(
        ["Cmaj7", "Am7", "Dm7", "G7", "Em7", "A7", "Dm7", "G7"])))
    engine.submit(cmd.Play("main_b"))
    engine.submit(cmd.PadDown(1))
    engine.submit(cmd.SetRecord(True))
    for _ in range(TICKS_PER_BAR + 40):
        engine.step()

    for index, screen in enumerate(app.screens):
        app.tab = index
        snapshot = engine.snapshot()
        screen.update(snapshot)
        app._draw(snapshot)
        path = out / f"panel-{index}-{screen.title.lower()}.png"
        pygame.image.save(app.surface, str(path))
        print(f"wrote {path}")
    pygame.display.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
