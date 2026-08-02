"""The bass engine: modes, register, the walk, and the voicing dial."""
from __future__ import annotations

import pytest

from core.bass import (BASS_HIGH, BASS_LOW, BASS_MODES, BASS_PATTERNS,
                       BassSpec, bar_notes, pattern_for, resolve_line)
from core.chords import parse_chord
from core.events import TICKS_PER_16TH, TICKS_PER_BAR


def _pcs(notes):
    return [n.note % 12 for n in notes]


def test_root_mode_plays_the_root_on_every_hit():
    notes = bar_notes(BassSpec(mode="root"), parse_chord("F"))
    assert len(notes) == 4
    assert set(_pcs(notes)) == {5}


def test_hits_land_on_the_pattern_steps():
    notes = bar_notes(BassSpec(pattern="x...x...x...x..."), parse_chord("C"))
    assert [n.tick for n in notes] == [0, 4 * TICKS_PER_16TH,
                                       8 * TICKS_PER_16TH,
                                       12 * TICKS_PER_16TH]


def test_an_empty_pattern_produces_silence():
    assert bar_notes(BassSpec(pattern="................"),
                     parse_chord("C")) == ()


def test_off_mode_is_silent_without_disturbing_anything_else():
    assert bar_notes(BassSpec(mode="off"), parse_chord("C")) == ()


def test_phrase_mode_defers_to_the_style():
    # The arranger reads this as "play the written bassline instead".
    assert bar_notes(BassSpec(mode="phrase"), parse_chord("C")) == ()


def test_octave_mode_alternates_root_and_octave():
    notes = bar_notes(BassSpec(mode="octave"), parse_chord("C"))
    assert notes[1].note - notes[0].note == 12
    assert notes[2].note == notes[0].note


def test_fifth_mode_alternates_root_and_fifth():
    notes = bar_notes(BassSpec(mode="fifth"), parse_chord("C"))
    assert _pcs(notes)[0] == 0
    assert _pcs(notes)[1] == 7


def test_arp_mode_climbs_the_chord_tones():
    notes = bar_notes(BassSpec(mode="arp"), parse_chord("Cmaj7"))
    assert _pcs(notes) == [0, 4, 7, 11]


def test_arp_wraps_into_the_next_octave_past_the_top_tone():
    notes = bar_notes(BassSpec(mode="arp", pattern="x.x.x.x.x.x.x.x."),
                      parse_chord("C"))
    assert notes[3].note == notes[0].note + 12


def test_the_bass_stays_in_the_bass_register():
    for mode in BASS_MODES:
        for symbol in ("C", "F#m7", "Bb13", "Ebmaj9"):
            for note in bar_notes(BassSpec(mode=mode), parse_chord(symbol)):
                assert BASS_LOW - 12 <= note.note <= BASS_HIGH + 24


def test_a_slash_chord_moves_the_bass_note():
    plain = bar_notes(BassSpec(), parse_chord("C"))
    slashed = bar_notes(BassSpec(), parse_chord("C/E"))
    assert _pcs(plain)[0] == 0
    assert _pcs(slashed)[0] == 4


def test_follow_slash_can_be_turned_off():
    notes = bar_notes(BassSpec(follow_slash=False), parse_chord("C/E"))
    assert _pcs(notes)[0] == 0


def test_the_dial_walks_the_line_through_the_chord_tones():
    chord = parse_chord("Cmaj7")
    at_zero = bar_notes(BassSpec(dial=0), chord)[0].note
    at_one = bar_notes(BassSpec(dial=1), chord)[0].note
    at_two = bar_notes(BassSpec(dial=2), chord)[0].note
    assert at_zero < at_one < at_two
    assert {at_one % 12, at_two % 12} <= {p for p in chord.pitch_classes}


def test_a_negative_dial_goes_below_the_bass_note():
    chord = parse_chord("C")
    assert bar_notes(BassSpec(dial=-1), chord)[0].note < \
        bar_notes(BassSpec(dial=0), chord)[0].note


def test_the_downbeat_is_accented():
    notes = bar_notes(BassSpec(accent=20), parse_chord("C"))
    assert notes[0].velocity > notes[1].velocity


def test_gate_controls_note_length():
    short = bar_notes(BassSpec(gate=20), parse_chord("C"))[0]
    long = bar_notes(BassSpec(gate=150), parse_chord("C"))[0]
    assert short.length < long.length


def test_slide_overlaps_consecutive_notes():
    notes = bar_notes(BassSpec(slide=True, gate=30), parse_chord("C"))
    assert notes[0].tick + notes[0].length > notes[1].tick


def test_walk_ends_the_bar_next_to_the_following_root():
    notes = bar_notes(BassSpec(mode="walk"), parse_chord("C"),
                      parse_chord("F"))
    last = notes[-1].note
    # The final note is a step away from an F somewhere in the bass register.
    assert min(abs(last - f) for f in (29, 41, 53)) in (1, 2)


def test_walk_without_a_next_chord_stays_on_the_current_one():
    chord = parse_chord("Cmaj7")
    notes = bar_notes(BassSpec(mode="walk"), chord, None)
    assert all(n.note % 12 in chord.pitch_classes for n in notes)


def test_resolve_line_wraps_the_lookahead_around_the_progression():
    chords = tuple(parse_chord(s) for s in ("Dm7", "G7", "Cmaj7"))
    line = resolve_line(BassSpec(mode="walk"), chords)
    assert {bar for bar, _note in line} == {0, 1, 2}
    assert len(line) == 12


def test_normalised_clamps_everything_a_knob_could_break():
    spec = BassSpec(mode="nonsense", velocity=999, gate=0, octave=9,
                    center=200).normalised()
    assert spec.mode == "root"
    assert spec.velocity == 127
    assert spec.gate >= 5
    assert -3 <= spec.octave <= 3
    assert BASS_LOW <= spec.center <= BASS_HIGH


def test_every_shipped_pattern_is_one_bar_of_sixteenths():
    for name, pattern in BASS_PATTERNS.items():
        assert len(pattern) == 16, name
        assert set(pattern) <= set("xX.-"), name


def test_pattern_for_falls_back_to_four_on_the_floor():
    assert pattern_for("NOT A PATTERN") == BASS_PATTERNS["FOUR"]


@pytest.mark.parametrize("mode", BASS_MODES)
def test_no_mode_ever_emits_an_illegal_note(mode):
    for note in bar_notes(BassSpec(mode=mode, pattern="xxxxxxxxxxxxxxxx"),
                          parse_chord("Bb13"), parse_chord("Ebm9")):
        assert 0 <= note.note <= 127
        assert 1 <= note.velocity <= 127
        assert 0 <= note.tick < TICKS_PER_BAR
        assert note.length > 0
