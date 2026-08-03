"""MidiRanger entry point.

    python main.py                       1280x400 window (the reference panel)
    python main.py --fullscreen          the real panel, no window chrome
    python main.py --size 480x800        the portrait panel
    python main.py --headless            engine only (systemd, bench, tests)
    python main.py --config /etc/midiranger/config.toml      appliance

Both paths build the same rig: engine + multi-port MIDI + the PiSound button
bridge + the pots service. The GUI is only a client of it, so closing the
window stops the picture and not the routing — which is also why
``--headless`` is a supported way to run the instrument and not just a test
mode.
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

log = logging.getLogger("midiranger.main")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MidiRanger — MIDI matrix, arps and note FX "
                    "for Patchbox OS")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--size", default=None, metavar="WxH",
                        help="window size, e.g. 1280x400 (default: config)")
    parser.add_argument("--headless", action="store_true",
                        help="run the engine without a display")
    parser.add_argument("--project", type=Path, default=None,
                        help=".mrproj to load at start")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.toml (appliance: "
                             "/etc/midiranger/config.toml)")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def parse_size(value: str) -> tuple[int, int]:
    width, _, height = value.lower().partition("x")
    if not width.isdigit() or not height.isdigit():
        raise SystemExit(f"--size expects WxH (got {value!r})")
    return int(width), int(height)


def build_rig(project_path: Path | None, config):
    """Engine + MIDI + button + pots, started and ticking."""
    from rangerkit import enginebase, routing
    from rangerkit.clock import RealClock
    from rangerkit.events import EventKind
    from rangerkit.midi_io import open_midi
    from rangerkit.pots import PotsService, socket_path as pots_socket

    from core.engine import MidiRangerEngine
    from core.project import Project, default_project

    project = (Project.load(project_path) if project_path is not None
               else default_project())
    engine_ref: list = []
    pots_ref: list = []

    def on_input(endpoint, event, ts):
        # The pots get first crack at CC traffic; what they consume is a
        # control gesture, not performance data for the matrix.
        if pots_ref and event.kind is EventKind.CC \
                and pots_ref[0].on_cc(event):
            return
        engine_ref[0].on_midi_in(endpoint, event, ts)

    midi = open_midi(
        on_input,
        lambda endpoint, status, data, ts: engine_ref[0].on_realtime_in(
            endpoint, status, data, ts),
        backend=config.midi.backend)
    engine = MidiRangerEngine(project, midi, RealClock(), config=config)
    engine_ref.append(engine)

    # Bind every endpoint the matrix mentions before the first tick: a rig
    # that comes up unbound is silent until somebody visits SET, and on an
    # appliance with no keyboard that is a support call.
    routing.autobind(midi, engine.matrix)
    log.info("MIDI backend: %s", getattr(midi, "backend_name", "null"))

    engine.start()
    # The matrix box routes whether or not anyone pressed play; arps and
    # LFOs are what the transport arms. Start running.
    engine.submit(enginebase.Play())

    pots = PotsService(engine.submit, config)
    pots_ref.append(pots)
    if pots.source == "socket":
        pots.start_socket(pots_socket(config))

    button = None
    if config.button.enabled:
        from rangerkit.button import ButtonServer, socket_path
        actions = {
            "play_stop": lambda: engine.submit(enginebase.TogglePlay()),
            "record_toggle": lambda: engine.submit(
                enginebase.SetRecord(not engine.snapshot().recording)),
            "panic": lambda: engine.submit(enginebase.Panic()),
            "save_project": lambda: _headless_save(engine, config),
            "bypass": lambda: _toggle_bypass(engine),
            "next_scene": lambda: _next_scene(engine),
        }
        defaults = {"CLICK_1": "play_stop", "CLICK_2": "bypass",
                    "CLICK_3": "next_scene", "HOLD_1S": "save_project",
                    "HOLD_5S": "panic"}
        button = ButtonServer(actions, socket_path(config),
                              raw_map=getattr(config.button, "map", {}),
                              defaults=defaults, thread_name="mr-button")
        if not button.start():
            button = None
    return engine, midi, button, pots


def _toggle_bypass(engine) -> None:
    from core.commands import SetBypass
    engine.submit(SetBypass(on=not engine.bypass))


def _next_scene(engine) -> None:
    from core.commands import RecallScene
    occupied = [i for i, used in enumerate(engine.scenes.occupied()) if used]
    if not occupied:
        return
    current = engine.morph_state[0] if engine.morph_state else -1
    later = [i for i in occupied if i > current]
    engine.submit(RecallScene(slot=(later or occupied)[0]))


def _headless_save(engine, config) -> None:
    from core.project import EXTENSION
    try:
        project = engine.capture()
        directory = Path(config.paths.projects_dir)
        project.save(directory / f"{project.name.lower()}{EXTENSION}")
        log.info("button: saved %s", project.name)
    except OSError as exc:
        log.warning("button: save failed: %s", exc)


def shutdown_rig(engine, midi, button=None, pots=None) -> None:
    if button is not None:
        button.stop()
    if pots is not None:
        pots.stop()
    engine.shutdown()
    midi.close_all()


def run_headless(project_path: Path | None, config) -> int:
    import signal

    engine, midi, button, pots = build_rig(project_path, config)
    print(f"midiranger: headless, backend="
          f"{getattr(midi, 'backend_name', 'null')} — Ctrl-C to stop")
    received = signal.sigwait([signal.SIGINT, signal.SIGTERM])
    print(f"midiranger: signal {received}, shutting down")
    shutdown_rig(engine, midi, button, pots)
    return 0


def run_gui(args: argparse.Namespace, config) -> int:
    from rangerkit.gui import theme

    from gui.app import App

    # Colourway before the window: the first frame is drawn from these tokens
    # and a repaint one frame later is a visible flash on a kiosk boot.
    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button, pots = build_rig(args.project, config)
    try:
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project, pots=pots)
        if button is not None:
            # With a window up the App is the authority on which file is
            # current, and it can say on the panel what the button just did.
            button.on_message = app.message
            app.wire_save(button)
        return app.run()
    finally:
        shutdown_rig(engine, midi, button, pots)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from core.config import load_config
    config = load_config(args.config)
    if args.headless:
        return run_headless(args.project, config)
    return run_gui(args, config)


if __name__ == "__main__":
    sys.exit(main())
