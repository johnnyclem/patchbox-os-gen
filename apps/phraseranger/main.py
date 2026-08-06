"""PhraseRanger entry point.

    python main.py                       1280x400 window (the reference panel)
    python main.py --fullscreen          the real panel, no window chrome
    python main.py --size 480x800        the portrait panel
    python main.py --headless            engine only (systemd, bench, tests)
    python main.py --config /etc/phraseranger/config.toml       appliance

Both paths build the same rig: engine + multi-port MIDI + the PiSound
button bridge + the pots service — and both press play with track 1 armed,
so play-and-it-records is the first gesture. The GUI is only a client;
closing the window stops the picture, not the loops.
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

log = logging.getLogger("phraseranger.main")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PhraseRanger — MIDI phrase looper for Patchbox OS")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--size", default=None, metavar="WxH",
                        help="window size, e.g. 1280x400 (default: config)")
    parser.add_argument("--headless", action="store_true",
                        help="run the engine without a display")
    parser.add_argument("--project", type=Path, default=None,
                        help=".prproj to load at start")
    parser.add_argument("--config", type=Path, default=None,
                        help="config.toml (appliance: "
                             "/etc/phraseranger/config.toml)")
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
    """Engine + MIDI + button + pots, started, ticking, and playing."""
    from rangerkit import enginebase, routing
    from rangerkit.clock import RealClock
    from rangerkit.events import EventKind
    from rangerkit.midi_io import open_midi
    from rangerkit.pots import PotsService, socket_path as pots_socket

    from core.engine import PhraseRangerEngine
    from core.project import Project, default_project

    project = (Project.load(project_path) if project_path is not None
               else default_project())
    engine_ref: list = []
    pots_ref: list = []

    def on_input(endpoint, event, ts):
        # The pots get first crack at CC traffic; notes feed the recorder.
        if pots_ref and event.kind is EventKind.CC \
                and pots_ref[0].on_cc(event):
            return
        engine_ref[0].on_midi_in(endpoint, event, ts)

    midi = open_midi(
        on_input,
        lambda endpoint, status, data, ts: engine_ref[0].on_realtime_in(
            endpoint, status, data, ts),
        backend=config.midi.backend)
    # The internal audio path (slice preview, or any track pointed at
    # "internal"): a small synth answers on the DAC through the bridge, and
    # the release book releases its voices like any note. No audio stack →
    # null out, silent internal, everything else unchanged.
    from rangerkit.audio.bridge import SynthMidiBridge
    from rangerkit.audio.engine import open_audio
    from rangerkit.audio.synth import SimpleSynth
    synth = SimpleSynth("soft")
    midi = SynthMidiBridge(midi, synth)
    audio = open_audio(synth, config=config)
    midi._audio_out = audio             # shutdown_rig stops the stream
    log.info("audio: %s", audio.backend_name)

    engine = PhraseRangerEngine(project, midi, RealClock(), config=config)
    engine_ref.append(engine)

    # Bind every destination the tracks name — and the inputs, because a
    # looper with nothing to record from is a metronome. A rig that comes up
    # unbound is silent until somebody visits SET, and on an appliance with
    # no keyboard that is a support call.
    endpoints = {track.params.dest for track in engine.tracks}
    endpoints |= {"din_in", "usb_in", "trs_a_in", "trs_b_in"}
    routing.autobind(midi, endpoints)
    log.info("MIDI backend: %s", getattr(midi, "backend_name", "null"))

    engine.start()
    engine.submit(enginebase.Play())        # the piece begins at boot

    pots = PotsService(engine.submit, config)
    pots_ref.append(pots)
    if pots.source == "socket":
        pots.start_socket(pots_socket(config))

    button = None
    if config.button.enabled:
        from rangerkit.button import ButtonServer, socket_path
        from core.commands import ClearTrack, UndoTrack
        actions = {
            "play_stop": lambda: engine.submit(enginebase.TogglePlay()),
            "undo": lambda: engine.submit(UndoTrack()),
            "clear": lambda: engine.submit(ClearTrack(
                index=max(0, engine.recorder.armed))),
            "panic": lambda: engine.submit(enginebase.Panic()),
            "save_project": lambda: _headless_save(engine, config),
        }
        defaults = {"CLICK_1": "play_stop", "CLICK_2": "undo",
                    "CLICK_3": "clear", "HOLD_1S": "save_project",
                    "HOLD_5S": "panic"}
        button = ButtonServer(actions, socket_path(config),
                              raw_map=getattr(config.button, "map", {}),
                              defaults=defaults, thread_name="pr-button")
        if not button.start():
            button = None
    return engine, midi, button, pots


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
    audio = getattr(midi, "_audio_out", None)
    if audio is not None:
        audio.stop()


def run_headless(project_path: Path | None, config) -> int:
    import signal

    engine, midi, button, pots = build_rig(project_path, config)
    print(f"phraseranger: headless, backend="
          f"{getattr(midi, 'backend_name', 'null')} — Ctrl-C to stop")
    received = signal.sigwait([signal.SIGINT, signal.SIGTERM])
    print(f"phraseranger: signal {received}, shutting down")
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


def run_deck(args: argparse.Namespace, config) -> int:
    """Guest of the RangerDeck launcher: one rig, a GUI that comes and goes.

    The ✕ the deck layout adds only closes the picture — the engine, MIDI,
    button and pots stay up between shows, so loops and the transport play
    straight through a trip back to the launcher.
    """
    from rangerkit.deck import run_deck_session
    from rangerkit.gui import theme

    from gui.app import App

    theme.apply(config.display.theme)
    size = (parse_size(args.size) if args.size is not None
            else (config.display.width, config.display.height))
    engine, midi, button, pots = build_rig(args.project, config)

    def make_app():
        app = App(engine, size=size,
                  fullscreen=args.fullscreen or config.display.fullscreen,
                  config=config, project_path=args.project, pots=pots,
                  deck=True)
        if button is not None:
            button.on_message = app.message
            app.wire_save(button)
        return app

    try:
        return run_deck_session(make_app, args.deck_socket, "phraseranger")
    finally:
        shutdown_rig(engine, midi, button, pots)


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
