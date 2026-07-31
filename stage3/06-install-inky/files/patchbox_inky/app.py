"""Patchbox UI entrypoint: Inky e-paper and/or keyboard TUI patchbay."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from . import jackutil, patchbay, splash, status, tui
from .display import open_display, push
from .inputctl import HELP_TEXT, InputEvent, InputHub


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patchbox-inky-ui",
        description="Patchbox splash + JACK patchbay (Inky e-paper and/or terminal)",
    )
    p.add_argument(
        "command",
        nargs="?",
        default="ui",
        choices=["ui", "splash", "status", "patchbay", "once", "tui", "clear-test"],
        help="ui=splash+patchbay; tui=keyboard terminal only; clear-test=full white then black",
    )
    p.add_argument("--simulate", action="store_true", help="Write PNGs instead of driving the panel")
    p.add_argument(
        "--type",
        choices=["auto", "impressions", "7colour", "uc8159", "5.7"],
        default="5.7",
        help="Display driver (default: force 5.7\" UC8159 600x448)",
    )
    p.add_argument(
        "--no-eink",
        action="store_true",
        help="Do not paint e-paper (keyboard TUI only; fast)",
    )
    p.add_argument(
        "--tui",
        action="store_true",
        help="Show terminal patchbay (implied by --no-eink / tui command)",
    )
    p.add_argument("--splash-delay", type=float, default=8.0)
    p.add_argument("--jack-wait", type=float, default=45.0)
    p.add_argument("--poll", type=float, default=0.12)
    p.add_argument(
        "--idle-refresh",
        type=float,
        default=0.0,
        help="Re-fetch JACK graph every N idle seconds (0=off; avoid on e-ink)",
    )
    p.add_argument(
        "--eink-on-action",
        action="store_true",
        help="With TUI+e-ink: also repaint e-paper on each action (~30s). Default: e-ink only for splash/once.",
    )
    p.add_argument("--title", default="Patchbox OS")
    return p


def _display_from_args(args: argparse.Namespace):
    force = None if args.type == "auto" else args.type
    return open_display(force_type=force, simulate=args.simulate, verbose=True)


def cmd_clear_test(args: argparse.Namespace) -> int:
    from .colors import BLACK, WHITE
    from .display import blank

    disp = _display_from_args(args)
    print("[inky] clear-test: full WHITE (~30s)…", file=sys.stderr)
    push(disp, blank(WHITE), "clear-white")
    time.sleep(0.5)
    print("[inky] clear-test: full BLACK (~30s)…", file=sys.stderr)
    push(disp, blank(BLACK), "clear-black")
    print(
        "[inky] Both frames should cover the ENTIRE glass. "
        "Half-screen ⇒ SPI/header/geometry issue.",
        file=sys.stderr,
    )
    return 0


def cmd_splash(args: argparse.Namespace) -> int:
    disp = _display_from_args(args)
    push(disp, splash.render("starting audio engine…"), "splash")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    disp = _display_from_args(args)
    push(disp, status.render(title=args.title), "status")
    return 0


def cmd_patchbay_once(args: argparse.Namespace) -> int:
    state = patchbay.PatchbayState()
    state.refresh_graph()
    if args.tui or args.no_eink:
        tui.render_patchbay(state)
    if not args.no_eink:
        disp = _display_from_args(args)
        push(disp, patchbay.render(state), "patchbay")
    return 0


def _wait_for_jack(seconds: float) -> None:
    deadline = time.time() + max(0.0, seconds)
    while time.time() < deadline:
        if jackutil.is_running():
            return
        time.sleep(0.5)


def _apply_input(state: patchbay.PatchbayState, ev: InputEvent) -> str | None:
    if ev.action == "quit":
        return "quit"
    if ev.action == "up":
        state.move(-1)
    elif ev.action == "down":
        state.move(1)
    elif ev.action == "patch":
        state.toggle_selected()
    elif ev.action == "focus":
        state.cycle_focus()
    elif ev.action == "refresh":
        state.refresh_graph()
        state.status_msg = "Graph refreshed"
        state.dirty = True
    elif ev.action.startswith("screen_"):
        return ev.action.replace("screen_", "")
    return None


def cmd_ui(args: argparse.Namespace, interactive: bool = True) -> int:
    use_eink = not args.no_eink
    use_tui = args.tui or args.no_eink or args.command == "tui"
    # Interactive e-ink without --eink-on-action: paint splash+initial patchbay only;
    # further navigation is TUI/keyboard (or buttons won't repaint until flag set).
    live_eink = use_eink and (args.eink_on_action or not interactive)

    disp = _display_from_args(args) if use_eink else None
    stop = False

    def _sig(_signum, _frame):  # noqa: ANN001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    if use_eink and disp is not None:
        push(disp, splash.render("starting audio engine…"), "splash")
        if stop:
            return 0
        wait = max(args.splash_delay, 0.0)
        t0 = time.time()
        while time.time() - t0 < wait and not stop:
            if jackutil.is_running() and (time.time() - t0) >= min(3.0, wait):
                break
            time.sleep(0.25)
        if not jackutil.is_running() and args.jack_wait > 0 and not stop:
            remaining = args.jack_wait - (time.time() - t0)
            if remaining > 0:
                push(disp, splash.render("waiting for JACK…"), "splash-wait-jack")
                _wait_for_jack(remaining)
    else:
        _wait_for_jack(min(max(args.jack_wait, 0.0), 8.0))

    if stop:
        return 0

    state = patchbay.PatchbayState()
    state.refresh_graph()
    if use_tui:
        tui.render_patchbay(state)
    if use_eink and disp is not None:
        push(disp, patchbay.render(state), "patchbay")
    state.dirty = False

    if not interactive:
        return 0

    hub = InputHub(simulate_buttons=args.simulate)
    last_idle = time.time()
    print(HELP_TEXT, file=sys.stderr)
    if use_eink and not args.eink_on_action:
        print(
            "[inky] E-ink: initial frames only. Navigation via keyboard/TUI "
            "(no 30s repaint per key). Use --eink-on-action to paint every change.",
            file=sys.stderr,
        )
    print("[inky] TUI: patchbox-inky-ui tui   |  half-screen test: clear-test", file=sys.stderr)

    while not stop:
        ev = hub.wait(timeout_s=args.poll)
        if ev is not None:
            result = _apply_input(state, ev)
            if result == "quit":
                break
            if result == "splash" and use_eink and disp is not None:
                push(disp, splash.render("manual splash"), "splash")
            elif result == "status" and use_eink and disp is not None:
                push(disp, status.render(title=args.title), "status")
            else:
                if use_tui:
                    tui.render_patchbay(state)
                if live_eink and state.dirty and disp is not None:
                    push(disp, patchbay.render(state), "patchbay")
            state.dirty = False
            last_idle = time.time()
            continue

        if args.idle_refresh > 0 and (time.time() - last_idle) >= args.idle_refresh:
            state.refresh_graph()
            if use_tui:
                tui.render_patchbay(state)
            if live_eink and disp is not None:
                push(disp, patchbay.render(state), "patchbay")
            state.dirty = False
            last_idle = time.time()

    hub.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "clear-test":
            return cmd_clear_test(args)
        if args.command == "splash":
            return cmd_splash(args)
        if args.command == "status":
            return cmd_status(args)
        if args.command == "patchbay":
            return cmd_patchbay_once(args)
        if args.command == "tui":
            args.no_eink = True
            args.tui = True
            return cmd_ui(args, interactive=True)
        if args.command == "once":
            return cmd_ui(args, interactive=False)
        # default ui: enable TUI alongside e-ink so keyboard always works
        args.tui = True
        return cmd_ui(args, interactive=True)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"patchbox-inky-ui error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
