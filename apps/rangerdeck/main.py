"""RangerDeck entry point — the Ranger Suite launcher.

    python main.py                       1280x400 window (the reference panel)
    python main.py --fullscreen          the real panel, no window chrome
    python main.py --size 480x800        the portrait panel
    python main.py --config /etc/rangerdeck/config.toml      appliance

The deck owns the panel at boot and *lends* it: tapping a tile spawns that
app with ``--deck-socket``, closes the deck's own display, and hands the
DRM master over. The guest's ✕ hands it back — and only the picture ever
stops. Every guest keeps its engine (clock, transport, arps, recording,
playback) running the whole time it is backgrounded, because a guest's GUI
was always just a client of its rig.
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
# On the device rangerkit is vendored beside core/; in the repo it lives one
# level up, in apps/. Prefer the vendored copy, fall back to the repo layout.
import importlib.util
if importlib.util.find_spec("rangerkit") is None:
    sys.path.insert(1, str(_ROOT.parent))

log = logging.getLogger("rangerdeck.main")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RangerDeck — launcher for the Ranger Suite on "
                    "Patchbox OS")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--size", default=None, metavar="WxH",
                        help="window size, e.g. 1280x400 (default: config)")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.toml (appliance: "
                             "/etc/rangerdeck/config.toml)")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def parse_size(value: str) -> tuple[int, int]:
    width, _, height = value.lower().partition("x")
    if not width.isdigit() or not height.isdigit():
        raise SystemExit(f"--size expects WxH (got {value!r})")
    return int(width), int(height)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from rangerkit.gui import theme

    from core.config import deck_settings, load_config
    from core.engine import DeckFleet
    from core.registry import discover
    from core.selection import resolve_order
    from gui.app import App

    config = load_config(args.config)
    settings = deck_settings(config)
    # Colourway before the window: the first frame is drawn from these tokens
    # and a repaint one frame later is a visible flash on a kiosk boot.
    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    fullscreen = args.fullscreen or config.display.fullscreen

    # Override file (/var/lib/rangerdeck/enabled-apps.txt) wins over config
    # so patchbox-setup and the on-panel SETTINGS tile share one source.
    order = resolve_order(settings.apps)
    specs = discover(order=order, fullscreen=fullscreen, size=size)
    if not specs:
        log.error("no Ranger apps found beside %s — nothing to launch",
                  _ROOT)
    # The appliance names /run/rangerdeck (the unit's RuntimeDirectory=);
    # a dev box gets a throwaway that AF_UNIX's short path limit can live
    # with.
    run_dir = settings.run_dir or Path(tempfile.mkdtemp(prefix="rdeck-"))
    fleet = DeckFleet(specs, run_dir)
    log.info("deck: %d app(s), sockets in %s, order=%s",
             len(specs), run_dir, order)

    try:
        app = App(fleet, size=size, fullscreen=fullscreen, config=config,
                  run_dir=run_dir, fullscreen_guests=fullscreen)
        return app.run()
    finally:
        # The deck going down takes the suite with it: on the appliance
        # systemd kills the whole cgroup anyway; doing it ourselves makes
        # a dev box behave the same and lets every rig close its notes.
        fleet.shutdown()


if __name__ == "__main__":
    sys.exit(main())
