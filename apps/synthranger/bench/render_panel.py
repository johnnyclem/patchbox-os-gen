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
from core.engine import SynthRangerEngine                # noqa: E402
from core.preset import factory_dir, load_preset         # noqa: E402
from core.project import default_project                 # noqa: E402
from core.voices import Synth                            # noqa: E402
from gui.app import App                                  # noqa: E402
from rangerkit.audio.bridge import SynthMidiBridge       # noqa: E402
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

    synth = Synth()
    engine = SynthRangerEngine(default_project(),
                               SynthMidiBridge(CaptureMidiIO(), synth),
                               FakeClock())
    app = App(engine, size=size, synth=synth)
    # A demo state worth photographing: a rig mid-set — presets on three
    # parts, a chord held, the XY pad off-center, a morph in progress.
    for part, name in ((0, "warm-pad"), (1, "acid-line"),
                       (2, "glass-keys")):
        patch = load_preset(factory_dir() / f"{name}.synpatch")
        engine.submit(cmd.SetPatchState(part=part,
                                        params=patch.to_config()))
    engine.submit(cmd.SetPatchState(
        part=0, params={"name": "CZ BELLS", "engine": "pd"}, slot_b=True))
    engine.submit(cmd.SetPartField(part=0, name="morph", value=0.35))
    engine.submit(cmd.SetXY(x=0.7, y=0.3))
    for note in (48, 55, 60, 64):
        engine.submit(cmd.KeyDown(note=note))
    for _ in range(12):
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
