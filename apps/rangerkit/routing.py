"""Named MIDI endpoints and the routing matrix.

The rig has a fixed set of physical jacks — Pimidi's two TRS pairs, Pisound's
DIN, and USB in both roles — and every Ranger app that routes (MidiRanger,
SceneRanger, PhraseRanger) needs to talk about them by *name*, not by
whatever ALSA client number they landed on this boot. An endpoint is the
stable name; binding it to a live port is ``autobind``'s job, using the same
case-insensitive substring preference the apps already use for their single
output.

The matrix itself is a value: an immutable set of routes, copied on change.
That is what lets an engine hand its current routing to a snapshot without a
lock, and what makes scene morphing a matter of swapping values.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# Endpoint ids. These are the spellings config files, scenes and snapshots
# use; keep them boring and lowercase.
TRS_A_IN, TRS_A_OUT = "trs_a_in", "trs_a_out"
TRS_B_IN, TRS_B_OUT = "trs_b_in", "trs_b_out"
DIN_IN, DIN_OUT = "din_in", "din_out"
USB_IN, USB_OUT = "usb_in", "usb_out"
INTERNAL = "internal"           # the app's own engine (synth, sampler, …)

INPUTS = (TRS_A_IN, TRS_B_IN, DIN_IN, USB_IN)
OUTPUTS = (TRS_A_OUT, TRS_B_OUT, DIN_OUT, USB_OUT, INTERNAL)

# Port-name substrings tried in order when binding each endpoint.
# PiMIDI (Blokas) shows up as ALSA client ``pimidi0`` with ports ``a`` / ``b``
# (display names ``pimidi0:a`` / ``pimidi0:b`` under both alsa-midi and
# mido/rtmidi). Older match strings stay as fallbacks. Pisound DIN is
# ``pisound``. USB prefers the gadget port (f_midi). "midi through" is
# deliberately absent: routing through it echoes back into the matrix.
PREFER: dict[str, tuple[str, ...]] = {
    TRS_A_IN: ("pimidi0:a", "pimidi-a", "pimidi 0", "pimidi0", "pimidi"),
    TRS_A_OUT: ("pimidi0:a", "pimidi-a", "pimidi 0", "pimidi0", "pimidi"),
    TRS_B_IN: ("pimidi0:b", "pimidi-b", "pimidi 1", "pimidi0:b"),
    TRS_B_OUT: ("pimidi0:b", "pimidi-b", "pimidi 1"),
    DIN_IN: ("pisound", "din"),
    DIN_OUT: ("pisound", "din"),
    USB_IN: ("f_midi", "usb"),
    USB_OUT: ("f_midi", "usb"),
}

ALL_CHANNELS = -1


@dataclass(frozen=True, slots=True)
class Route:
    """One arrow in the matrix.

    ``channel`` filters the source (``ALL_CHANNELS`` passes everything);
    ``to_channel`` rewrites the channel on the way out (``ALL_CHANNELS``
    keeps whatever came in). Note-offs must follow the route their note-ons
    took, so a route change mid-note is the *engine's* problem — the matrix
    is pure data and does not try to be clever about it.
    """

    src: str
    dst: str
    channel: int = ALL_CHANNELS
    to_channel: int = ALL_CHANNELS

    def matches(self, endpoint: str, channel: int) -> bool:
        return self.src == endpoint and \
            self.channel in (ALL_CHANNELS, channel)

    def rewrite(self, channel: int) -> int:
        return channel if self.to_channel == ALL_CHANNELS else self.to_channel


@dataclass(frozen=True, slots=True)
class RoutingMatrix:
    """An immutable set of routes. Mutating operations return a new matrix."""

    routes: frozenset[Route] = field(default_factory=frozenset)

    def with_route(self, route: Route) -> "RoutingMatrix":
        return replace(self, routes=self.routes | {route})

    def without_route(self, route: Route) -> "RoutingMatrix":
        return replace(self, routes=self.routes - {route})

    def toggled(self, route: Route) -> "RoutingMatrix":
        return self.without_route(route) if route in self.routes \
            else self.with_route(route)

    def targets(self, endpoint: str, channel: int) \
            -> tuple[tuple[str, int], ...]:
        """Where an event arriving on ``endpoint``/``channel`` goes:
        ``(dst_endpoint, dst_channel)`` pairs, deterministic order."""
        return tuple(sorted(
            {(r.dst, r.rewrite(channel)) for r in self.routes
             if r.matches(endpoint, channel)}))

    def to_config(self) -> list[dict]:
        """A TOML/JSON-friendly shape, sorted so saves diff cleanly."""
        return [{"src": r.src, "dst": r.dst, "channel": r.channel,
                 "to_channel": r.to_channel}
                for r in sorted(self.routes,
                                key=lambda r: (r.src, r.dst, r.channel,
                                               r.to_channel))]

    @classmethod
    def from_config(cls, raw: list[dict] | None) -> "RoutingMatrix":
        """Unknown endpoints are dropped with the same forgiveness the config
        loader shows unknown keys: a map written for later hardware still
        boots this build."""
        routes = set()
        for item in raw or ():
            src, dst = str(item.get("src", "")), str(item.get("dst", ""))
            if src not in INPUTS or dst not in OUTPUTS:
                continue
            routes.add(Route(src=src, dst=dst,
                             channel=int(item.get("channel", ALL_CHANNELS)),
                             to_channel=int(item.get("to_channel",
                                                     ALL_CHANNELS))))
        return cls(routes=frozenset(routes))


def autobind(midi, matrix_or_endpoints, prefer: dict | None = None) -> None:
    """Bind every endpoint the matrix (or iterable) mentions to a live port.

    Quietly skips endpoints with no matching port — a rig without Pimidi
    still routes DIN to USB, and the panel's routing screen shows the unbound
    jacks greyed rather than the app refusing to start.
    """
    tables = dict(PREFER)
    if prefer:
        tables.update(prefer)
    endpoints = getattr(matrix_or_endpoints, "routes", None)
    if endpoints is not None:
        names = {r.src for r in endpoints} | {r.dst for r in endpoints}
    else:
        names = set(matrix_or_endpoints)
    for endpoint in sorted(names):
        if endpoint == INTERNAL:
            continue
        for pattern in tables.get(endpoint, ()):
            if endpoint in INPUTS:
                if midi.bind_input(endpoint, pattern):
                    break
            elif midi.bind_output(endpoint, pattern):
                break
