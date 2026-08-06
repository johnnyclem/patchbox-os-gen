"""ChordRanger entry point.

    python main.py                       1280x400 window (the reference panel)
    python main.py --fullscreen          the real panel, no window chrome
    python main.py --size 480x800        the portrait panel
    python main.py --headless            engine only (systemd, bench, tests)
    python main.py --config /etc/chordranger/config.toml     appliance

Both paths build the same rig: engine + MIDI out + the PiSound button bridge.
The GUI is only a client of it, so closing the window stops the picture and
not the music — which is also why ``--headless`` is a supported way to run the
instrument and not just a test mode.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
# On the device rangerkit is vendored beside core/; in the repo it lives one
# level up, in apps/. Prefer the vendored copy, fall back to the repo layout.
import importlib.util
if importlib.util.find_spec("rangerkit") is None:
    sys.path.insert(1, str(_ROOT.parent))

log = logging.getLogger("chordranger.main")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ChordRanger — chord-first backing band for Patchbox OS")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--size", default=None, metavar="WxH",
                        help="window size, e.g. 1280x400 (default: config)")
    parser.add_argument("--headless", action="store_true",
                        help="run the engine without a display")
    parser.add_argument("--project", type=Path, default=None,
                        help=".crproj to load at start")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.toml (appliance: "
                             "/etc/chordranger/config.toml)")
    parser.add_argument("--deck-socket", type=Path, default=None,
                        metavar="SOCK",
                        help="run under the RangerDeck launcher: build the "
                             "rig, then show/hide the GUI on command over "
                             "this socket (the engine survives every hide)")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def parse_size(value: str) -> tuple[int, int]:
    width, _, height = value.lower().partition("x")
    if not width.isdigit() or not height.isdigit():
        raise SystemExit(f"--size expects WxH (got {value!r})")
    return int(width), int(height)


def build_rig(project_path: Path | None, config):
    """Engine + MIDI + button bridge, started and ticking."""
    from core.clock import RealClock
    from core.engine import OUT, Engine
    from core.midi_io import autobind_output, open_midi
    from core.project import Project, default_project

    project = (Project.load(project_path) if project_path is not None
               else default_project())
    engine_ref: list = []
    midi = open_midi(
        lambda endpoint, event, ts: engine_ref[0].on_midi_in(endpoint, event,
                                                             ts),
        lambda endpoint, status, data, ts: engine_ref[0].on_realtime_in(
            endpoint, status, data, ts),
        backend=config.midi.backend)
    engine = Engine(project, midi, RealClock(), config=config)
    engine_ref.append(engine)

    # Bind the output before the first tick: a rig that comes up unbound is
    # silent until somebody visits the Settings screen, and on an appliance
    # with no keyboard that is a support call.
    bound = (midi.bind_output(OUT, config.midi.out_port)
             and config.midi.out_port) if config.midi.out_port else \
        autobind_output(midi, OUT, config.midi.prefer)
    log.info("MIDI out: %s (%s)", bound or "unbound",
             getattr(midi, "backend_name", "null"))
    if config.midi.in_port:
        midi.bind_input("in", config.midi.in_port)
    if config.midi.clock_out:
        engine.clock_out = True

    engine.start()
    button = None
    if config.button.enabled:
        from core.button import ButtonServer
        button = ButtonServer(engine, config)
        if not button.start():
            button = None
    return engine, midi, button


def shutdown_rig(engine, midi, button=None) -> None:
    if button is not None:
        button.stop()
    engine.shutdown()
    midi.close_all()


def run_headless(project_path: Path | None, config) -> int:
    import signal

    engine, midi, button = build_rig(project_path, config)
    print(f"chordranger: headless, backend="
          f"{getattr(midi, 'backend_name', 'null')} — Ctrl-C to stop")
    received = signal.sigwait([signal.SIGINT, signal.SIGTERM])
    print(f"chordranger: signal {received}, shutting down")
    shutdown_rig(engine, midi, button)
    return 0


def run_gui(args: argparse.Namespace, config) -> int:
    from gui import theme
    from gui.app import App

    # Colourway before the window: the first frame is drawn from these tokens
    # and a repaint one frame later is a visible flash on a kiosk boot.
    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button = build_rig(args.project, config)
    try:
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project)
        if button is not None:
            # With a window up the App is the authority on which file is
            # current, and it can say on the panel what the button just did.
            button.on_message = app.message
            button.on_save = app.save_project
        return app.run()
    finally:
        shutdown_rig(engine, midi, button)


def run_deck(args: argparse.Namespace, config) -> int:
    """Guest of the RangerDeck launcher: one rig, a GUI that comes and goes.

    The ✕ the deck layout adds only closes the picture — the engine, MIDI
    and button stay up between shows, so the band and the transport play
    straight through a trip back to the launcher.
    """
    from rangerkit.deck import run_deck_session

    from gui import theme
    from gui.app import App

    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button = build_rig(args.project, config)

    def make_app():
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project, deck=True)
        if button is not None:
            # With a window up the App is the authority on which file is
            # current, and it can say on the panel what the button just did.
            button.on_message = app.message
            button.on_save = app.save_project
        return app

    try:
        return run_deck_session(make_app, args.deck_socket, "chordranger")
    finally:
        shutdown_rig(engine, midi, button)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from core.config import load_config
    config = load_config(args.config)
    if args.deck_socket is not None:
        return run_deck(args, config)
    if args.headless:
        return run_headless(args.project, config)
    return run_gui(args, config)


if __name__ == "__main__":
    sys.exit(main())
