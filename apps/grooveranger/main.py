"""GrooveRanger entry point.

    python main.py                       1280x400 window (the reference panel)
    python main.py --fullscreen          the real panel, no window chrome
    python main.py --size 480x800        the portrait panel
    python main.py --headless            engine only (systemd, bench, tests)
    python main.py --config /etc/grooveranger/config.toml      appliance

Both paths build the same rig: engine + multi-port MIDI with the sampler on
the ``internal`` endpoint + audio out + the PiSound button bridge + the pots
service. The GUI is only a client; closing the window stops the picture,
not the beat.
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

log = logging.getLogger("grooveranger.main")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GrooveRanger — sample groovebox for Patchbox OS")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--size", default=None, metavar="WxH",
                        help="window size, e.g. 1280x400 (default: config)")
    parser.add_argument("--headless", action="store_true",
                        help="run the engine without a display")
    parser.add_argument("--project", type=Path, default=None,
                        help=".grproj to load at start")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.toml (appliance: "
                             "/etc/grooveranger/config.toml)")
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
    """Engine + MIDI + sampler-on-internal + audio + button + pots."""
    from rangerkit import enginebase, routing
    from rangerkit.audio.bridge import SynthMidiBridge
    from rangerkit.audio.engine import open_audio
    from rangerkit.clock import RealClock
    from rangerkit.events import EventKind
    from rangerkit.midi_io import open_midi
    from rangerkit.pots import PotsService, socket_path as pots_socket

    from core.engine import GrooveRangerEngine
    from core.project import Project, default_project
    from core.sampler import Sampler

    project = (Project.load(project_path) if project_path is not None
               else default_project())
    engine_ref: list = []
    pots_ref: list = []

    def on_input(endpoint, event, ts):
        # The pots get first crack at CC traffic; notes play the pads.
        if pots_ref and event.kind is EventKind.CC \
                and pots_ref[0].on_cc(event):
            return
        engine_ref[0].on_midi_in(endpoint, event, ts)

    midi = open_midi(
        on_input,
        lambda endpoint, status, data, ts: engine_ref[0].on_realtime_in(
            endpoint, status, data, ts),
        backend=config.midi.backend)

    # The sampler answers on the internal endpoint; the release book
    # releases its voices through the very same note-offs external gear
    # gets. Kit files load on this thread, never the tick thread.
    sampler = Sampler()
    midi = SynthMidiBridge(midi, sampler)
    engine = GrooveRangerEngine(project, midi, RealClock(), config=config)
    engine_ref.append(engine)
    sampler.set_kit(engine.kit)
    sampler.set_tempo(engine.bpm)
    audio = open_audio(sampler, config=config)
    sampler._audio_out = audio

    endpoints = {engine.kit.dest, "din_in", "usb_in", "trs_a_in",
                 "trs_b_in"}
    routing.autobind(midi, endpoints)
    log.info("MIDI backend: %s", getattr(midi, "backend_name", "null"))

    engine.start()

    pots = PotsService(engine.submit, config)
    pots_ref.append(pots)
    if pots.source == "socket":
        pots.start_socket(pots_socket(config))

    button = None
    if config.button.enabled:
        from rangerkit.button import ButtonServer, socket_path
        from core.commands import QueueFill, SelectPattern
        from core.sequencer import PATTERNS

        def next_pattern():
            snapshot = engine.snapshot()
            used = [i for i, u in enumerate(snapshot.patterns_used) if u]
            if not used:
                return
            later = [i for i in used if i > snapshot.pattern_index]
            engine.submit(SelectPattern(index=(later or used)[0]
                                        % PATTERNS))

        actions = {
            "play_stop": lambda: engine.submit(enginebase.TogglePlay()),
            "fill": lambda: engine.submit(QueueFill()),
            "next_pattern": next_pattern,
            "record_arm": lambda: engine.submit(
                enginebase.SetRecord(on=not engine.recording)),
            "panic": lambda: engine.submit(enginebase.Panic()),
            "save_project": lambda: _headless_save(engine, config),
        }
        defaults = {"CLICK_1": "play_stop", "CLICK_2": "fill",
                    "CLICK_3": "next_pattern", "HOLD_1S": "save_project",
                    "HOLD_5S": "panic"}
        button = ButtonServer(actions, socket_path(config),
                              raw_map=getattr(config.button, "map", {}),
                              defaults=defaults, thread_name="gr-button")
        if not button.start():
            button = None
    return engine, midi, button, pots, sampler


def _headless_save(engine, config) -> None:
    from core.project import EXTENSION
    try:
        project = engine.capture()
        directory = Path(config.paths.projects_dir)
        project.save(directory / f"{project.name.lower()}{EXTENSION}")
        log.info("button: saved %s", project.name)
    except OSError as exc:
        log.warning("button: save failed: %s", exc)


def shutdown_rig(engine, midi, button=None, pots=None, sampler=None) -> None:
    if button is not None:
        button.stop()
    if pots is not None:
        pots.stop()
    engine.shutdown()
    audio = getattr(sampler, "_audio_out", None)
    if audio is not None:
        audio.stop()
    midi.close_all()


def run_headless(project_path: Path | None, config) -> int:
    import signal

    engine, midi, button, pots, sampler = build_rig(project_path, config)
    print(f"grooveranger: headless, backend="
          f"{getattr(midi, 'backend_name', 'null')} — Ctrl-C to stop")
    received = signal.sigwait([signal.SIGINT, signal.SIGTERM])
    print(f"grooveranger: signal {received}, shutting down")
    shutdown_rig(engine, midi, button, pots, sampler)
    return 0


def run_gui(args: argparse.Namespace, config) -> int:
    from rangerkit.gui import theme

    from gui.app import App

    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button, pots, sampler = build_rig(args.project, config)
    try:
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project, pots=pots,
                  sampler=sampler)
        if button is not None:
            button.on_message = app.message
            app.wire_save(button)
        return app.run()
    finally:
        shutdown_rig(engine, midi, button, pots, sampler)


def run_deck(args: argparse.Namespace, config) -> int:
    """Guest of the RangerDeck launcher: one rig, a GUI that comes and goes.

    The ✕ the deck layout adds only closes the picture — the engine, MIDI,
    sampler, audio, button and pots stay up between shows, so the beat
    plays straight through a trip back to the launcher.
    """
    from rangerkit.deck import run_deck_session
    from rangerkit.gui import theme

    from gui.app import App

    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button, pots, sampler = build_rig(args.project, config)

    def make_app():
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project, pots=pots,
                  sampler=sampler, deck=True)
        if button is not None:
            button.on_message = app.message
            app.wire_save(button)
        return app

    try:
        return run_deck_session(make_app, args.deck_socket, "grooveranger")
    finally:
        shutdown_rig(engine, midi, button, pots, sampler)


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
