"""Styles: the step-string authoring layer, chord conversion, factory data."""
from __future__ import annotations

import pytest

from core.chords import Chord, parse_chord
from core.events import TICKS_PER_16TH, TICKS_PER_BAR
from core.style import (CHORD_TONE, FILL_FOR, FILL_TARGET, FIXED, PARALLEL,
                        ROOT, SCALE, SECTION_BARS, SECTION_ORDER, Part,
                        Phrase, convert_note, merge, render_phrase, repeat,
                        steps, swing_tick)
from core.theory import scale_for
from data.styles import PART_IDS, factory_styles, style_named


# --- authoring ----------------------------------------------------------------

def test_step_strings_place_hits_on_the_sixteenth_grid():
    notes = steps("x...x...x...x...", note=36)
    assert [n.tick for n in notes] == [0, 4 * TICKS_PER_16TH,
                                       8 * TICKS_PER_16TH,
                                       12 * TICKS_PER_16TH]


def test_capital_x_is_an_accent():
    quiet, loud = steps("x.", note=38, velocity=90), steps("X.", note=38,
                                                           velocity=90)
    assert loud[0].velocity > quiet[0].velocity


def test_a_dash_ties_the_previous_note_over_a_step():
    notes = steps("x---", note=60)
    assert len(notes) == 1
    assert notes[0].length == 4 * TICKS_PER_16TH


def test_a_dash_still_consumes_a_step():
    notes = steps("x-x.", note=60)
    assert [n.tick for n in notes] == [0, 2 * TICKS_PER_16TH]


def test_bad_step_characters_are_rejected_at_authoring_time():
    with pytest.raises(ValueError):
        steps("x..?", note=60)


def test_merge_orders_lines_by_tick():
    body = merge(steps("..x.", note=42), steps("x...", note=36))
    assert [n.tick for n in body] == [0, 2 * TICKS_PER_16TH]


def test_repeat_offsets_each_bar():
    body = repeat(steps("x...", note=36), 3)
    assert [n.tick for n in body] == [0, TICKS_PER_BAR, 2 * TICKS_PER_BAR]


def test_swing_delays_only_the_off_steps():
    assert swing_tick(0, 50) == 0
    assert swing_tick(TICKS_PER_16TH, 50) > TICKS_PER_16TH
    assert swing_tick(2 * TICKS_PER_16TH, 50) == 2 * TICKS_PER_16TH
    assert swing_tick(TICKS_PER_16TH, 0) == TICKS_PER_16TH


# --- conversion ---------------------------------------------------------------

MAJOR = scale_for("major")


def test_fixed_conversion_never_moves_a_note():
    for note in (36, 42, 60, 99):
        assert convert_note(note, parse_chord("F#m7b5"), FIXED, MAJOR) == note


def test_parallel_conversion_transposes_by_the_root_delta():
    assert convert_note(60, parse_chord("F"), PARALLEL, MAJOR) == 65
    assert convert_note(64, parse_chord("F"), PARALLEL, MAJOR) == 69


def test_parallel_conversion_takes_the_short_way_round():
    # C -> B is a semitone down, not eleven up: the line must not climb an
    # octave because the root crossed the top of the pitch-class circle.
    assert convert_note(60, parse_chord("B"), PARALLEL, MAJOR) == 59


def test_root_conversion_lands_on_the_chord_bass_in_the_same_register():
    note = convert_note(36, parse_chord("F"), ROOT, MAJOR)
    assert note % 12 == 5
    assert abs(note - 36) <= 6


def test_root_conversion_follows_a_slash_bass():
    note = convert_note(36, parse_chord("C/E"), ROOT, MAJOR)
    assert note % 12 == 4


def test_chord_tone_conversion_only_produces_chord_tones():
    chord = parse_chord("Abmaj7")
    for source in range(48, 72):
        note = convert_note(source, chord, CHORD_TONE, MAJOR)
        assert note % 12 in {p for p in chord.pitch_classes}


def test_scale_conversion_keeps_the_line_in_the_key():
    chord = parse_chord("Dm7")
    for source in range(60, 72):
        note = convert_note(source, chord, SCALE, MAJOR, key_root=0)
        assert MAJOR.contains(note, 0)


def test_render_phrase_applies_part_octave_and_velocity():
    phrase = Phrase(notes=steps("x...", note=60, velocity=100), bars=1)
    part = Part("keys", "KEYS", channel=2, conversion=PARALLEL, octave=1,
                velocity=50)
    rendered = render_phrase(phrase, part, Chord(0, "maj"), "major")
    assert rendered == ((0, 72, 50, TICKS_PER_16TH),)


def test_render_phrase_drops_notes_pushed_out_of_midi_range():
    phrase = Phrase(notes=steps("x...", note=120), bars=1)
    part = Part("keys", "KEYS", conversion=PARALLEL, octave=3)
    assert render_phrase(phrase, part, Chord(0, "maj"), "major") == ()


def test_a_phrase_can_override_its_parts_conversion_rule():
    phrase = Phrase(notes=steps("x...", note=60), bars=1, conversion=FIXED)
    part = Part("keys", "KEYS", conversion=PARALLEL)
    rendered = render_phrase(phrase, part, parse_chord("F"), "major")
    assert rendered[0][1] == 60


# --- factory data -------------------------------------------------------------

def test_every_factory_style_has_all_six_sections():
    for style in factory_styles():
        for name in SECTION_ORDER:
            assert style.has(name), f"{style.name} is missing {name}"


def test_section_lengths_follow_the_qy_convention():
    for style in factory_styles():
        for name, section in style.sections.items():
            assert section.bars == SECTION_BARS[name], \
                f"{style.name}/{name} is {section.bars} bars"


def test_every_style_has_the_same_parts_in_the_same_order():
    for style in factory_styles():
        assert tuple(p.id for p in style.parts) == PART_IDS


def test_drum_parts_are_on_the_gm_percussion_channel_and_never_transposed():
    for style in factory_styles():
        drums = style.part("drum")
        assert drums.channel == 9
        assert drums.conversion == FIXED


def test_phrase_notes_never_run_past_their_section():
    for style in factory_styles():
        for name, section in style.sections.items():
            for part_id, phrase in section.phrases.items():
                for note in phrase.notes:
                    assert note.tick < phrase.ticks, \
                        f"{style.name}/{name}/{part_id} at {note.tick}"


def test_every_phrase_note_is_a_legal_midi_note():
    for style in factory_styles():
        for section in style.sections.values():
            for phrase in section.phrases.values():
                for note in phrase.notes:
                    assert 0 <= note.note <= 127
                    assert 1 <= note.velocity <= 127


def test_style_named_falls_back_rather_than_raising():
    assert style_named("NOT A STYLE").name == factory_styles()[0].name
    assert style_named("FUNK").name == "FUNK"


def test_fills_point_at_the_main_they_hand_over_to():
    assert FILL_TARGET["fill_ab"] == "main_b"
    assert FILL_TARGET["fill_ba"] == "main_a"
    assert FILL_FOR[("main_a", "main_b")] == "fill_ab"
