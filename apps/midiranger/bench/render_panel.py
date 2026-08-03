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

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(1, str(_ROOT.parent))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame                                            # noqa: E402

from core import commands as cmd                         # noqa: E402
from core.engine import MidiRangerEngine                 # noqa: E402
from core.project import default_project                 # noqa: E402
from gui.app import App                                  # noqa: E402
from rangerkit import enginebase as base                 # noqa: E402
from rangerkit.events import (PPQN, TICKS_PER_BAR,       # noqa: E402
                              note_on)
from rangerkit.testkit import CaptureMidiIO, FakeClock   # noqa: E402


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") \
        else Path("docs/img")
    size = (1280, 400)
    for index, arg in enumerate(argv):
        if arg == "--size" and index + 1 < len(argv):
            width, _, height = argv[index + 1].partition("x")
            size = (int(width), int(height))
    out.mkdir(parents=True, exist_ok=True)

    project = default_project()
    project.params["arps"] = [
        {"enabled": True, "source": "din_in", "dest": "usb_out",
         "channel_out": 3, "rate": PPQN // 4, "pattern": "updown",
         "octaves": 2}]
    project.params["quantizer"] = {"enabled": True}
    project.params["harmonizer"] = {"mode": "third"}
    project.params["fx"] = {"echo_repeats": 2, "echo_ticks": PPQN,
                            "humanize_timing": 4}
    project.params["lfos"] = [
        {"enabled": True, "shape": "sine", "cc": 74}]
    engine = MidiRangerEngine(project, CaptureMidiIO(), FakeClock())
    app = App(engine, size=size)
    # A demo state worth photographing: running, a chord held into the arp,
    # a thru note sounding, scenes saved.
    engine.submit(cmd.SaveScene(slot=0))
    engine.submit(cmd.SaveScene(slot=3))
    engine.submit(base.Play())
    engine.on_midi_in("din_in", note_on(0, 57, 96), 0)
    engine.on_midi_in("din_in", note_on(0, 60, 104), 0)
    engine.on_midi_in("usb_in", note_on(1, 64, 90), 0)
    for _ in range(TICKS_PER_BAR + 40):
        engine.step()

    for index, screen in enumerate(app.screens):
        app.tab = index
        snapshot = engine.snapshot()
        screen.update(snapshot)
        app._draw(snapshot)
        path = out / (f"panel-{size[0]}x{size[1]}-{index}-"
                      f"{screen.title.lower()}.png")
        pygame.image.save(app.surface, str(path))
        print(f"wrote {path}")
    pygame.display.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
