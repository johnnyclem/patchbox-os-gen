"""The twelve pads: assignment, per-pad transpose, numerals, persistence."""
from __future__ import annotations

import json

from core.chords import Chord, parse_chord
from core.chordset import (PAD_COUNT, Chordset, Pad, diatonic,
                           factory_chordsets, from_symbols)


def test_a_new_chordset_always_has_twelve_pads():
    assert len(Chordset().pads) == PAD_COUNT
    assert len(Chordset(pads=(Pad(Chord(0)),)).pads) == PAD_COUNT


def test_short_chordsets_are_padded_with_dead_keys():
    chordset = Chordset(pads=(Pad(Chord(0)),))
    assert chordset.chord_at(0) is not None
    assert chordset.chord_at(5) is None


def test_diatonic_major_lays_out_the_seven_degrees():
    chordset = diatonic(0, "major")
    assert [chordset.caption(i) for i in range(7)] == \
        ["C", "Dm", "Em", "F", "G", "Am", "B°"]


def test_diatonic_sevenths_gives_the_jazz_set():
    chordset = diatonic(0, "major", sevenths=True)
    assert chordset.caption(4) == "G7"
    assert chordset.caption(6) == "Bm7b5"


def test_diatonic_minor_uses_the_minor_qualities():
    chordset = diatonic(9, "minor")
    assert chordset.caption(0) == "Am"
    assert chordset.caption(2) == "C"


def test_the_extra_pads_are_the_useful_outsiders():
    chordset = diatonic(0, "major")
    captions = [chordset.caption(i) for i in range(7, PAD_COUNT)]
    assert "D7" in captions            # V of V
    assert "Bb" in captions            # flat VII
    assert "Csus4" in captions


def test_numerals_are_printed_for_diatonic_pads_and_blank_otherwise():
    chordset = diatonic(0, "major")
    assert chordset.numeral(0) == "I"
    assert chordset.numeral(1) == "ii"
    assert chordset.numeral(6) == "vii°"
    # The secondary dominant is labelled by what it does, not by its root.
    secondary = chordset.pads.index(
        next(p for p in chordset.pads if p.chord.quality == "dom7"
             and p.chord.root == 2))
    assert chordset.numeral(secondary) == "V/V"


def test_a_chord_unrelated_to_the_key_gets_no_numeral():
    chordset = diatonic(0, "major").with_chord(0, parse_chord("Ebm7"))
    assert chordset.numeral(0) == ""


def test_pad_transpose_is_applied_on_read_not_stored():
    chordset = diatonic(0, "major").transposed_pad(0, 2)
    assert chordset.caption(0) == "D"
    assert chordset.pads[0].chord.root == 0     # the stored chord is untouched


def test_pad_transpose_round_trips_exactly():
    base = diatonic(0, "major")
    there_and_back = base.transposed_pad(3, 5).transposed_pad(3, -5)
    assert there_and_back.caption(3) == base.caption(3)


def test_pad_transpose_is_clamped_to_two_octaves():
    chordset = diatonic(0, "major")
    for _ in range(40):
        chordset = chordset.transposed_pad(0, 1)
    assert chordset.pads[0].transpose == 24


def test_transposing_the_whole_set_moves_the_key_too():
    moved = diatonic(0, "major").transposed(2)
    assert moved.root == 2
    assert moved.caption(0) == "D"
    assert moved.numeral(0) == "I"


def test_editing_a_pad_leaves_the_others_alone():
    base = diatonic(0, "major")
    edited = base.with_chord(3, parse_chord("Ab7"))
    assert edited.caption(3) == "Ab7"
    assert edited.caption(4) == base.caption(4)


def test_chordsets_round_trip_through_json(tmp_path):
    original = from_symbols(["Cmaj7", "Am7", "", "G7"], name="TEST")
    original = original.transposed_pad(1, -2)
    path = tmp_path / "set.json"
    original.save(path)
    loaded = Chordset.load(path)
    assert loaded.name == original.name
    assert [loaded.caption(i) for i in range(PAD_COUNT)] == \
        [original.caption(i) for i in range(PAD_COUNT)]


def test_saving_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "set.json"
    diatonic(0, "major").save(path)
    assert [p.name for p in tmp_path.iterdir()] == ["set.json"]
    assert json.loads(path.read_text())["schema_version"] == 1


def test_edited_chords_survive_a_save(tmp_path):
    chordset = diatonic(0, "major")
    chordset = chordset.with_chord(0, Chord(0, "maj").toggled(11).toggled(7))
    path = tmp_path / "edited.json"
    chordset.save(path)
    loaded = Chordset.load(path)
    assert loaded.chord_at(0).intervals == (0, 4, 11)
    assert loaded.chord_at(0).edited


def test_every_factory_chordset_is_playable():
    for chordset in factory_chordsets():
        assert chordset.name
        playable = [i for i in range(PAD_COUNT)
                    if chordset.chord_at(i) is not None]
        assert len(playable) >= 8
        for index in playable:
            assert chordset.caption(index)
