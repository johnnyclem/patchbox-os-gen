"""Terminal patchbay view — usable without e-ink (SSH / IPS later)."""

from __future__ import annotations

import sys

from . import jackutil
from .inputctl import HELP_TEXT
from .patchbay import (
    FOCUS_LINKS,
    FOCUS_SINKS,
    FOCUS_SOURCES,
    PatchbayState,
)


def _clear() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def render_patchbay(state: PatchbayState) -> None:
    _clear()
    g = state.graph
    jack_ok = not bool(g.error)
    badge = "JACK *" if jack_ok else "JACK -"
    print("=" * 60)
    print(f"  PATCHBAY  (TUI)   {badge}   focus={state.focus}")
    print("=" * 60)
    if g.error:
        print(f"  ! {g.error}")
    print()
    print(f"  OUT ({len(g.outputs)})" + ("  <" if state.focus == FOCUS_SOURCES else ""))
    for i, p in enumerate(g.outputs):
        mark = ">" if i == state.src_idx else " "
        link = "*" if state.selected_sink() and (p, state.selected_sink()) in g.connections else " "
        print(f"  {mark}{link} {jackutil.short(p, 40)}")
    print()
    print(f"  IN ({len(g.inputs)})" + ("  <" if state.focus == FOCUS_SINKS else ""))
    for i, p in enumerate(g.inputs):
        mark = ">" if i == state.sink_idx else " "
        link = "*" if state.selected_src() and (state.selected_src(), p) in g.connections else " "
        print(f"  {mark}{link} {jackutil.short(p, 40)}")
    print()
    print(f"  LINKS ({len(g.connections)})" + ("  <" if state.focus == FOCUS_LINKS else ""))
    if not g.connections:
        print("    (none)")
    for i, (a, b) in enumerate(g.connections):
        mark = ">" if i == state.link_idx else " "
        print(f"  {mark}  {jackutil.short(a, 24)} -> {jackutil.short(b, 24)}")
    print()
    s, k = state.selected_src(), state.selected_sink()
    if s and k:
        linked = (s, k) in g.connections
        print(f"  route: {jackutil.short(s, 20)} {'==' if linked else '--'} {jackutil.short(k, 20)}")
        print(f"         {'LINKED' if linked else 'open — Enter to patch'}")
    print()
    print(f"  status: {state.status_msg}")
    print("-" * 60)
    print(HELP_TEXT)
    sys.stdout.flush()


def render_status_line(msg: str) -> None:
    print(msg)
    sys.stdout.flush()
