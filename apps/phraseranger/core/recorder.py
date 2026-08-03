"""The recorder — live MIDI in, phrase notes out.

One armed track at a time (a looper pedal has one input path; arming is the
instrument's focus). Note-ons open; note-offs close and the finished note
lands in the armed track's phrase, optionally snapped to the sixteenth
grid. Notes still open when recording stops (or the input dies) are closed
at the moment of stopping — a take never holds a note the player let go of.

The recorder never touches MIDI out and never edits phrases in place: it
*returns* the new phrase and the engine swaps it in, which is what keeps
the take/undo boundary honest.
"""
from __future__ import annotations

from dataclasses import replace

from core.phrase import Phrase, PhraseNote

MAX_OPEN = 32                   # simultaneous held keys a take will track


class Recorder:
    def __init__(self) -> None:
        self.armed: int = -1        # track index; -1 = disarmed
        self.quantize: bool = True
        self.overdubbed: bool = False   # did this take actually add notes?
        self._open: dict[int, tuple[int, int]] = {}   # note -> (tick, vel)

    @property
    def recording(self) -> bool:
        return self.armed >= 0

    def arm(self, track: int) -> None:
        self.armed = track
        self.overdubbed = False
        self._open.clear()

    def disarm(self) -> None:
        self.armed = -1
        self._open.clear()

    def note_on(self, tick_in_loop: int, note: int, velocity: int) -> None:
        if not self.recording or len(self._open) >= MAX_OPEN:
            return
        self._open[note] = (tick_in_loop, velocity)

    def note_off(self, tick_in_loop: int, note: int,
                 phrase: Phrase) -> Phrase:
        """Close one note into the phrase. Returns the (new) phrase."""
        opened = self._open.pop(note, None)
        if opened is None or not self.recording:
            return phrase
        start, velocity = opened
        length = (tick_in_loop - start) % phrase.length_ticks
        length = max(1, length)
        self.overdubbed = True
        return phrase.with_note(
            PhraseNote(tick=start, note=note, velocity=velocity,
                       length_ticks=length),
            quantize=self.quantize)

    def close_open_notes(self, tick_in_loop: int, phrase: Phrase) -> Phrase:
        """Recording stopped with keys down: every open note ends now."""
        for note in list(self._open):
            phrase = self.note_off(tick_in_loop, note, phrase)
        return phrase

    def open_notes(self) -> tuple[int, ...]:
        return tuple(sorted(self._open))


def humanized(note: PhraseNote, rng, timing: int,
              velocity_jitter: int) -> PhraseNote:
    """Playback-time feel: only ever *delays* (the engine cannot send into
    the past), velocity wobbles both ways. Non-destructive — the phrase is
    untouched; this shapes the copy being emitted."""
    delayed = rng.randint(0, timing) if timing else 0
    velocity = note.velocity
    if velocity_jitter:
        velocity = max(1, min(127, velocity + rng.randint(-velocity_jitter,
                                                          velocity_jitter)))
    return replace(note, tick=note.tick + delayed, velocity=velocity)
