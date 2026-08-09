"""Re-export the family MIDI stack (ALSA + mido + null).

ChordRanger historically kept a private copy; it now tracks rangerkit so
PiSound / PiMIDI bind the same way as every other Ranger app.
"""
from rangerkit.midi_io import (
    BACKENDS,
    CaptureMidiIO,
    MidiIO,
    MidoMidiIO,
    NullMidiIO,
    PortInfo,
    autobind_output,
    event_to_bytes,
    event_to_message,
    is_critical,
    message_to_event,
    open_midi,
    strip_port_numbers,
    DEFAULT_PREFER,
)

# Re-exports are "unused" to a linter reading this file alone, and the CI gate
# is pyflakes, which has no `# noqa` (that is a flake8 directive and was being
# silently ignored here). Naming them in ``__all__`` is what pyflakes actually
# reads, and it doubles as the shim's contract.
__all__ = [
    "BACKENDS",
    "CaptureMidiIO",
    "MidiIO",
    "MidoMidiIO",
    "NullMidiIO",
    "PortInfo",
    "autobind_output",
    "event_to_bytes",
    "event_to_message",
    "is_critical",
    "message_to_event",
    "open_midi",
    "strip_port_numbers",
    "DEFAULT_PREFER",
]
