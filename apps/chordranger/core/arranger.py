"""The arranger — the thing that turns "I am holding an F#m7" into a band.

It owns two ideas the rest of the app deliberately does not:

**Where we are in the form.** Intro plays once and hands over to Main A. A
request to move to Main B goes through Fill AB. An Ending plays and stops the
transport. That is the QY form model, and it is a state machine rather than a
song list because a player switching sections with one finger mid-performance
is the primary use, and a written arrangement is the secondary one.

**How a bar sounds over a chord.** Each bar is rendered when it begins: the
style's phrases are bent onto the current chord, the chord part's rhythm is
expanded into a voicing, and the bass engine is asked for its own line. If the
chord changes *inside* the bar the remainder is re-rendered on the spot — a
band does not finish the bar in the old key out of politeness.

Rendering per bar rather than per tick is what keeps the tick loop cheap: at
96 PPQN a bar is 384 ticks, and 383 of them are a dictionary lookup that
usually misses.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from core.bass import PHRASE as BASS_PHRASE, BassSpec
from core.bass import bar_notes as bass_bar_notes
from core.chords import Chord, VoicingSpec, voice
from core.events import TICKS_PER_BAR
from core.style import (ENDING, FILL_FOR, FILL_SECTIONS, FILL_TARGET, INTRO,
                        MAIN_A, MAIN_SECTIONS, Part, Phrase, ROLE_BASS,
                        ROLE_CHORD, Section, Style, render_phrase, swing_tick)

# How a section change is timed. "bar" is the QY feel — press it whenever, it
# happens on the downbeat. "section" waits for the current section to run out,
# which is what you want when the sections are the arrangement.
QUANTIZE_BAR, QUANTIZE_SECTION, QUANTIZE_NOW = "bar", "section", "now"
QUANTIZE_MODES = (QUANTIZE_BAR, QUANTIZE_SECTION, QUANTIZE_NOW)


@dataclass(frozen=True, slots=True)
class NoteOut:
    """One note the arranger wants played, right now."""

    part_id: str
    channel: int
    note: int
    velocity: int
    length: int


@dataclass
class ArrangerState:
    """What the panel needs to draw the form, as plain values."""

    section: str = MAIN_A
    next_section: str = ""
    pos: int = 0                # ticks into the section
    bars: int = 1
    bar: int = 0                # 0-based bar within the section
    stopping: bool = False


class Arranger:
    """Section state machine + per-bar renderer.

    Not thread-safe and not meant to be: it lives on the engine's tick thread,
    and everything the GUI needs comes back through ``state()`` as a copy.
    """

    def __init__(self, style: Style, quantize: str = QUANTIZE_BAR) -> None:
        self.style = style
        self.quantize = quantize if quantize in QUANTIZE_MODES else QUANTIZE_BAR
        self.section = MAIN_A
        self.pos = 0
        self._queued: str | None = None
        self._after_fill: str | None = None
        self._bar_notes: dict[int, list[NoteOut]] = {}
        self._rendered_bar = -1
        self._rendered_chord: Chord | None = None
        self._last_voicing: tuple[int, ...] = ()
        self.stopped = False

    # --- form ----------------------------------------------------------------
    def start(self, section: str = "") -> None:
        """Begin at *section* (default: intro if the style has one, else the
        first main). Resets position and clears any queued move."""
        if not section:
            section = INTRO if self.style.has(INTRO) else MAIN_A
        self.section = section if self.style.has(section) else MAIN_A
        self.pos = 0
        self._queued = None
        self._after_fill = None
        self._invalidate()
        self.stopped = False

    def request(self, section: str) -> None:
        """The player pressed a section button.

        Moving between the two mains goes through the matching fill when the
        style has one — that is what the fills are *for*, and making the
        player press the fill themselves is how you end up with a fill that
        arrives one bar late every time.
        """
        if not self.style.has(section):
            return
        if section == self.section and self._queued is None:
            return
        fill = FILL_FOR.get((self.section, section))
        if fill and self.style.has(fill) and section in MAIN_SECTIONS:
            self._queued, self._after_fill = fill, section
        else:
            self._queued, self._after_fill = section, None

    def cancel_request(self) -> None:
        self._queued = self._after_fill = None

    def state(self) -> ArrangerState:
        section = self.current
        return ArrangerState(
            section=self.section,
            next_section=self._queued or self._natural_next(),
            pos=self.pos, bars=section.bars if section else 1,
            bar=self.pos // TICKS_PER_BAR,
            stopping=self.section == ENDING)

    @property
    def current(self) -> Section | None:
        return self.style.section(self.section)

    def _natural_next(self) -> str:
        """Where this section goes when nobody asks for anything."""
        if self.section == INTRO:
            return MAIN_A
        if self.section in FILL_SECTIONS:
            return FILL_TARGET.get(self.section, MAIN_A)
        if self.section == ENDING:
            return ""
        return self.section

    # --- playback ------------------------------------------------------------
    def step(self, chord: Chord, next_chord: Chord | None,
             voicing: VoicingSpec, bass: BassSpec, scale: str = "major",
             key_root: int = 0, strum: int = 0) -> tuple[NoteOut, ...]:
        """Advance one tick; returns the notes starting on it.

        The caller owns note-offs: everything here carries its length and the
        engine schedules the release. That split is what makes a changed chord
        safe mid-note — the release is already booked against the note that
        was actually sent.
        """
        section = self.current
        if section is None or self.stopped:
            return ()
        bar = self.pos // TICKS_PER_BAR
        if bar != self._rendered_bar or chord != self._rendered_chord:
            self._render_bar(bar, chord, next_chord, voicing, bass, scale,
                             key_root, strum)
        notes = tuple(self._bar_notes.get(self.pos % TICKS_PER_BAR, ()))
        self._advance()
        return notes

    def _advance(self) -> None:
        section = self.current
        limit = section.ticks if section else TICKS_PER_BAR
        self.pos += 1
        if self.pos < limit:
            if self.quantize == QUANTIZE_BAR and self._queued \
                    and self.pos % TICKS_PER_BAR == 0:
                self._enter(self._queued)
            return
        if self._queued:
            self._enter(self._queued)
            return
        nxt = self._natural_next()
        if not nxt:                     # the ending ran out
            self.stopped = True
            self.pos = 0
            return
        self._enter(nxt)

    def _enter(self, section: str) -> None:
        self.section = section
        self.pos = 0
        self._invalidate()
        # A fill hands over to the main it was named for; anything else clears
        # the queue so a section does not repeat forever because nobody said
        # otherwise.
        if section in FILL_SECTIONS and self._after_fill:
            self._queued, self._after_fill = self._after_fill, None
        else:
            self._queued = self._after_fill = None

    def _invalidate(self) -> None:
        self._bar_notes = {}
        self._rendered_bar = -1
        self._rendered_chord = None

    # --- rendering -----------------------------------------------------------
    def _render_bar(self, bar: int, chord: Chord, next_chord: Chord | None,
                    voicing: VoicingSpec, bass: BassSpec, scale: str,
                    key_root: int, strum: int) -> None:
        """Build this bar's note map for *chord*.

        Only ticks at or after the current position are kept when this is a
        re-render caused by a chord change: the notes earlier in the bar have
        already been sent, and re-adding them would double-trigger.
        """
        section = self.current
        assert section is not None
        floor = self.pos % TICKS_PER_BAR if bar == self._rendered_bar else 0
        notes: dict[int, list[NoteOut]] = {}
        for part in self.style.parts:
            if part.muted:
                continue
            phrase = section.phrase_for(part.id)
            if part.role == ROLE_BASS and bass.mode != BASS_PHRASE:
                self._render_bass(notes, part, bass, chord, next_chord, scale,
                                  key_root, bar, floor)
                continue
            if phrase is None or not phrase.notes:
                continue
            if part.role == ROLE_CHORD:
                self._render_chord(notes, part, phrase, chord, voicing, bar,
                                   floor, strum)
            else:
                self._render_line(notes, part, phrase, chord, scale, key_root,
                                  bar, floor)
        self._bar_notes = notes
        self._rendered_bar = bar
        self._rendered_chord = chord

    def _phrase_offset(self, phrase: Phrase, bar: int) -> int:
        """Tick offset into *phrase* for this bar of the section.

        A phrase shorter than its section loops: a one-bar groove under a
        four-bar Main B plays four times, which is what every drum machine
        since 1980 has done and what a style author expects.
        """
        return (bar % max(1, phrase.bars)) * TICKS_PER_BAR

    def _emit(self, notes: dict[int, list[NoteOut]], tick: int, floor: int,
              item: NoteOut) -> None:
        if tick < floor or tick >= TICKS_PER_BAR:
            return
        notes.setdefault(tick, []).append(item)

    def _render_line(self, notes: dict, part: Part, phrase: Phrase,
                     chord: Chord, scale: str, key_root: int, bar: int,
                     floor: int) -> None:
        offset = self._phrase_offset(phrase, bar)
        swing = self.style.swing
        for tick, note, velocity, length in render_phrase(
                phrase, part, chord, scale, key_root):
            local = tick - offset
            if not 0 <= local < TICKS_PER_BAR:
                continue
            self._emit(notes, swing_tick(local, swing), floor,
                       NoteOut(part.id, part.channel, note, velocity, length))

    def _render_chord(self, notes: dict, part: Part, phrase: Phrase,
                      chord: Chord, voicing: VoicingSpec, bar: int,
                      floor: int, strum: int) -> None:
        """Expand the chord part's rhythm into a voicing.

        The phrase supplies *when* and *how hard*; the voicing supplies *what*.
        Keeping the last voicing lets ``voice`` lead into the new chord, so a
        progression comped by the box moves the way a keyboard player's hands
        would.
        """
        offset = self._phrase_offset(phrase, bar)
        voiced = voice(chord, replace(voicing, octave=voicing.octave +
                                      part.octave), self._last_voicing)
        if not voiced:
            return
        self._last_voicing = voiced
        swing = self.style.swing
        for item in phrase.notes:
            local = item.tick - offset
            if not 0 <= local < TICKS_PER_BAR:
                continue
            base = swing_tick(local, swing)
            velocity = max(1, min(127, item.velocity * part.velocity // 100))
            for index, note in enumerate(voiced):
                # Strum: successive voices are delayed by a few ticks each, so
                # a stab becomes a guitar chord. Ticks, not milliseconds — a
                # strum should scale with the tempo like a real one does.
                self._emit(notes, base + index * strum, floor,
                           NoteOut(part.id, part.channel, note,
                                   max(1, velocity - index), item.length))

    def _render_bass(self, notes: dict, part: Part, bass: BassSpec,
                     chord: Chord, next_chord: Chord | None, scale: str,
                     key_root: int, bar: int, floor: int) -> None:
        swing = self.style.swing
        for item in bass_bar_notes(bass, chord, next_chord, scale, key_root,
                                   bar):
            note = item.note + 12 * part.octave
            if not 0 <= note <= 127:
                continue
            velocity = max(1, min(127, item.velocity * part.velocity // 100))
            self._emit(notes, swing_tick(item.tick, swing), floor,
                       NoteOut(part.id, part.channel, note, velocity,
                               item.length))
