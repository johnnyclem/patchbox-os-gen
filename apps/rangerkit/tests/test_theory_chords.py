"""Parity checks on the theory/chords modules rangerkit inherited.

The full behavioral suite lives with ChordRanger (the donor); these pin the
properties every Ranger app leans on, so a drift in the kit's copy fails
here even before an app imports it.
"""
from __future__ import annotations

from rangerkit.chords import Chord, parse_chord, voice, walk
from rangerkit.theory import pc, snap_to_scale


def test_pc_is_the_one_way_door():
    assert pc(60) == 0 and pc(61) == 1 and pc(72) == 0
    assert pc(0) == 0 and pc(127) == 7


def test_voicing_preserves_the_pitch_class_set():
    chord = parse_chord("Cmaj7")
    notes = voice(chord)
    assert {pc(n) for n in notes} == {0, 4, 7, 11}


def test_walk_is_voice_leading_not_reharmonisation():
    chord = parse_chord("F")
    notes = voice(chord)
    for steps in (-3, -1, 1, 2, 4):
        assert {pc(n) for n in walk(notes, steps)} == {pc(n) for n in notes}


def test_walk_travels():
    notes = voice(parse_chord("C"))
    lifted = walk(notes, 1)
    assert min(lifted) > min(notes)


def test_scale_snap_stays_in_key():
    from rangerkit.theory import SCALES
    major = SCALES["major"]
    for note in range(48, 84):
        snapped = snap_to_scale(note, 0, major)
        assert major.contains(snapped, 0)
        assert abs(snapped - note) <= 1     # register kept


def test_slash_chord_names_its_bass():
    chord = parse_chord("C/E")
    assert isinstance(chord, Chord)
    assert chord.bass is not None and pc(chord.bass) == 4
