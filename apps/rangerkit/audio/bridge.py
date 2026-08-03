"""SynthMidiBridge — the ``internal`` endpoint made real.

A ``MidiIO`` wrapper: events addressed to ``rangerkit.routing.INTERNAL``
drive the synth, everything else passes through to the wrapped backend
untouched. Because the engines' release book releases notes by sending
note-offs (and CC 123) through ``midi.send``, synth voices are released by
the very same mechanism that releases external gear — no engine learns
anything new when a destination says ``internal``.

Wraps *any* backend, including ``CaptureMidiIO`` — tests see the full event
stream and the synth state at once.
"""
from __future__ import annotations

from rangerkit.events import EventKind, MidiEvent
from rangerkit.routing import INTERNAL

_ALL_OFF_CC = (120, 123)


class SynthMidiBridge:
    """MidiIO in front, a synth on the internal jack."""

    def __init__(self, inner, synth) -> None:
        self.inner = inner
        self.synth = synth

    @property
    def backend_name(self) -> str:
        return getattr(self.inner, "backend_name", "null") + "+synth"

    # --- the split -------------------------------------------------------------
    def send(self, endpoint_id: str, event: MidiEvent) -> None:
        if endpoint_id == INTERNAL:
            self._to_synth(event)
            return
        self.inner.send(endpoint_id, event)

    def _to_synth(self, event: MidiEvent) -> None:
        kind = event.kind
        if kind is EventKind.NOTE_ON and event.data2 > 0:
            self.synth.note_on(event.channel, event.data1, event.data2)
        elif kind in (EventKind.NOTE_OFF, EventKind.NOTE_ON):
            self.synth.note_off(event.channel, event.data1)
        elif kind is EventKind.CC and event.data1 in _ALL_OFF_CC:
            self.synth.all_off(event.channel)
        elif kind is EventKind.CC:
            # Instruments that speak CC (GrooveRanger's sampler: p-locks,
            # mixer levels, the master bus) expose ``control``; the simple
            # synth doesn't, and for it CCs stay a no-op.
            control = getattr(self.synth, "control", None)
            if control is not None:
                control(event.channel, event.data1, event.data2)
        # Program/bend: nothing internal speaks them yet.

    def send_realtime(self, endpoint_id: str, status: int,
                      data: int = 0) -> None:
        if endpoint_id == INTERNAL:
            return
        self.inner.send_realtime(endpoint_id, status, data)

    # --- pass-through ----------------------------------------------------------
    def scan(self):
        return self.inner.scan()

    def bind_output(self, endpoint_id: str, port_name: str) -> bool:
        if endpoint_id == INTERNAL:
            return True                 # always "bound": the synth is here
        return self.inner.bind_output(endpoint_id, port_name)

    def bind_input(self, endpoint_id: str, port_name: str) -> bool:
        return self.inner.bind_input(endpoint_id, port_name)

    def unbind(self, endpoint_id: str) -> None:
        if endpoint_id != INTERNAL:
            self.inner.unbind(endpoint_id)

    def is_bound(self, endpoint_id: str) -> bool:
        if endpoint_id == INTERNAL:
            return True
        return self.inner.is_bound(endpoint_id)

    def close_all(self) -> None:
        self.synth.all_off()
        self.inner.close_all()

    def __getattr__(self, name):
        # CaptureMidiIO's assertion helpers (events, hanging, …) stay
        # reachable through the bridge so test rigs need no unwrapping.
        return getattr(self.inner, name)
