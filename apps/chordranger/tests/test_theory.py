"""Pitch, scale and key vocabulary."""
from __future__ import annotations

import pytest

from core.theory import (SCALES, degree_of, note_label, note_name, parse_note,
                         pc, roman, scale_for, snap_to_scale, transpose_all)


def test_parse_note_round_trips_every_pitch_class():
    for value in range(12):
        assert parse_note(note_name(value)) == value


@pytest.mark.parametrize("text,expected", [
    ("C", 0), ("c", 0), ("Bb", 10), ("A#", 10), ("Cb", 11), ("B#", 0),
    ("F##", 7), ("E♭", 3),
])
def test_parse_note_accepts_accidentals(text, expected):
    assert parse_note(text) == expected


@pytest.mark.parametrize("text", ["", "H", "C#x", "9", " "])
def test_parse_note_rejects_nonsense(text):
    with pytest.raises(ValueError):
        parse_note(text)


def test_note_label_uses_scientific_octaves():
    assert note_label(60) == "C4"
    assert note_label(21) == "A0"
    assert note_label(127) == "G9"


def test_pc_reduces_midi_notes():
    assert pc(60) == 0
    assert pc(61) == 1
    assert pc(0) == 0


def test_every_scale_starts_on_its_tonic_and_stays_in_an_octave():
    for scale in SCALES.values():
        assert scale.degrees[0] == 0
        assert all(0 <= d < 12 for d in scale.degrees)
        assert list(scale.degrees) == sorted(scale.degrees)


def test_scale_contains_respects_the_root():
    major = scale_for("major")
    assert major.contains(64, 0)        # E is in C major
    assert not major.contains(61, 0)    # C# is not
    assert major.contains(61, 2)        # but it is in D major


def test_scale_for_falls_back_rather_than_raising():
    assert scale_for("not-a-scale").name == "major"


def test_snap_to_scale_keeps_notes_already_in_it():
    major = scale_for("major")
    for note in (60, 62, 64, 65, 67, 69, 71):
        assert snap_to_scale(note, 0, major) == note


def test_snap_to_scale_prefers_down_then_up():
    major = scale_for("major")
    assert snap_to_scale(61, 0, major) == 60        # C# -> C
    assert snap_to_scale(61, 0, major, prefer_up=True) == 62


def test_degree_of_answers_none_outside_the_scale():
    major = scale_for("major")
    assert degree_of(7, 0, major) == 4              # G is the fifth degree
    assert degree_of(1, 0, major) is None           # Db is not in C major


def test_roman_lowercases_minor_and_appends_symbols():
    assert roman(0) == "I"
    assert roman(1, minor_quality=True) == "ii"
    assert roman(6, minor_quality=True, symbol="°") == "vii°"


def test_transpose_all_moves_the_whole_voicing_in_octaves_at_the_edges():
    assert transpose_all((60, 64, 67), 2) == (62, 66, 69)
    # Pushed past the top, the shape survives — the chord simply drops an
    # octave rather than collapsing onto 127.
    high = transpose_all((120, 124, 127), 6)
    assert max(high) <= 127
    assert [b - a for a, b in zip(high, high[1:])] == [4, 3]


def test_transpose_all_is_a_no_op_on_empty_input():
    assert transpose_all((), 5) == ()
