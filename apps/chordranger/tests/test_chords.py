"""Chord model, parsing, detection and the voicing engine."""
from __future__ import annotations

import pytest

from core.chords import (COMMON_QUALITIES, Chord, VoicingSpec,
                         chord_tone_near, detect_chord, nearest_inversion,
                         parse_chord, stack, voice, voicing_options, walk)
from core.theory import scale_for


# --- model --------------------------------------------------------------------

def test_chord_intervals_come_from_its_quality():
    assert Chord(0, "maj").intervals == (0, 4, 7)
    assert Chord(0, "min7").intervals == (0, 3, 7, 10)


def test_pitch_classes_wrap_extensions_into_the_octave():
    # A maj9 spells its ninth as 14 semitones; as a pitch class that is D.
    assert Chord(0, "maj9").pitch_classes == frozenset({0, 4, 7, 11, 2})


def test_symbol_spells_flat_keys_with_flats():
    assert Chord(10, "maj").symbol() == "Bb"
    assert Chord(6, "min7").symbol() == "F#m7"


def test_slash_chords_keep_their_bass_and_their_upper_structure():
    chord = Chord(0, "maj", bass=4)
    assert chord.symbol() == "C/E"
    assert chord.bass_pc == 4
    assert chord.pitch_classes == frozenset({0, 4, 7})


def test_transposing_moves_the_slash_bass_with_the_chord():
    moved = Chord(0, "maj", bass=4).transposed(2)
    assert moved.root == 2 and moved.bass == 6


def test_edited_chords_override_the_quality_and_say_so():
    chord = Chord(0, "maj").toggled(11)         # add a major seventh
    assert chord.edited
    assert chord.intervals == (0, 4, 7, 11)
    assert chord.symbol().endswith("*")


def test_toggling_twice_returns_the_original_intervals():
    chord = Chord(0, "min7")
    assert chord.toggled(2).toggled(2).intervals == chord.intervals


def test_toggling_can_remove_the_root_for_a_rootless_voicing():
    chord = Chord(0, "dom7").toggled(0)
    assert 0 not in chord.intervals
    # The bass part still knows what the chord is called.
    assert chord.bass_pc == 0


def test_with_quality_discards_a_hand_edit():
    edited = Chord(0, "maj").toggled(11)
    assert not edited.with_quality("min7").edited


def test_minor_detects_a_flat_third_in_an_edited_chord():
    assert Chord(0, "maj").toggled(4).toggled(3).minor


# --- parsing ------------------------------------------------------------------

@pytest.mark.parametrize("text,root,quality", [
    ("C", 0, "maj"), ("Cm", 0, "min"), ("C7", 0, "dom7"),
    ("Cmaj7", 0, "maj7"), ("F#m7", 6, "min7"), ("Bb7sus4", 10, "7sus4"),
    ("Am7b5", 9, "min7b5"), ("Ebm9", 3, "min9"), ("G+", 7, "aug"),
])
def test_parse_chord_reads_common_symbols(text, root, quality):
    chord = parse_chord(text)
    assert (chord.root, chord.quality) == (root, quality)


def test_parse_chord_reads_slash_notation():
    chord = parse_chord("C/E")
    assert (chord.root, chord.bass) == (0, 4)


@pytest.mark.parametrize("text", ["", "H7", "Cwhat", "/E"])
def test_parse_chord_rejects_nonsense(text):
    with pytest.raises(ValueError):
        parse_chord(text)


def test_every_common_quality_round_trips_through_its_symbol():
    for quality in COMMON_QUALITIES:
        chord = Chord(0, quality)
        assert parse_chord(chord.symbol()).quality == quality


# --- detection ----------------------------------------------------------------

def test_detect_names_a_plain_triad():
    chord = detect_chord((60, 64, 67))
    assert chord is not None
    assert (chord.root, chord.quality) == (0, "maj")


def test_detect_names_a_seventh_chord_in_any_inversion():
    chord = detect_chord((64, 67, 70, 72))      # E G Bb C = C7 first inversion
    assert chord is not None
    assert chord.root == 0 and chord.quality == "dom7"
    assert chord.bass == 4


def test_detect_needs_at_least_two_notes():
    assert detect_chord((60,)) is None
    assert detect_chord(()) is None


def test_detect_returns_none_for_a_cluster_no_quality_matches():
    assert detect_chord((60, 61, 62, 63, 64, 65)) is None


# --- voicing ------------------------------------------------------------------

def test_stack_places_the_root_near_the_requested_register():
    assert stack(Chord(0, "maj"), 60) == (60, 64, 67)
    # B major near middle C voices at 59, not an octave away.
    assert stack(Chord(11, "maj"), 60)[0] == 59


def test_walk_moves_one_note_per_step_and_preserves_the_harmony():
    notes = (60, 64, 67)
    up = walk(notes, 1)
    assert up == (64, 67, 72)
    assert {n % 12 for n in up} == {n % 12 for n in notes}


def test_walk_is_reversible():
    notes = (60, 64, 67, 71)
    assert walk(walk(notes, 3), -3) == notes


def test_walk_with_zero_steps_changes_nothing():
    assert walk((60, 64, 67), 0) == (60, 64, 67)


def test_drop2_lowers_the_second_voice_from_the_top():
    notes = voice(Chord(0, "maj7"), VoicingSpec(style="drop2",
                                                lock_center=False))
    assert notes == (55, 60, 64, 71)


def test_shell_keeps_root_third_and_seventh():
    notes = voice(Chord(0, "dom7"), VoicingSpec(style="shell"))
    assert {n % 12 for n in notes} == {0, 4, 10}


def test_rootless_drops_the_root_when_something_is_left():
    notes = voice(Chord(0, "min9"), VoicingSpec(style="rootless"))
    assert 0 not in {n % 12 for n in notes}


def test_rootless_keeps_the_root_of_a_power_chord():
    notes = voice(Chord(0, "5"), VoicingSpec(style="rootless"))
    assert 0 in {n % 12 for n in notes}


def test_max_notes_trims_from_the_middle_and_keeps_the_colour():
    notes = voice(Chord(0, "dom13"), VoicingSpec(max_notes=4,
                                                 lock_center=False))
    assert len(notes) == 4
    # The 13th (A) survives the trim; the fifth does not.
    assert 9 in {n % 12 for n in notes}


def test_every_voicing_style_produces_notes_in_range():
    for _label, notes in voicing_options(Chord(3, "maj9")):
        assert notes
        assert all(0 <= n <= 127 for n in notes)


def test_voicing_never_changes_the_pitch_class_set_for_dial_moves():
    chord = Chord(7, "dom7")
    base = voice(chord, VoicingSpec(lock_center=False))
    for dial in range(-3, 4):
        moved = voice(chord, VoicingSpec(dial=dial, lock_center=False))
        assert {n % 12 for n in moved} == {n % 12 for n in base}


def test_octave_shift_moves_the_whole_voicing():
    spec = VoicingSpec(lock_center=False)
    base = voice(Chord(0, "maj"), spec)
    up = voice(Chord(0, "maj"), VoicingSpec(octave=1, lock_center=False))
    assert up == tuple(n + 12 for n in base)


def test_nearest_inversion_beats_the_naive_stack_for_voice_leading():
    previous = voice(Chord(0, "maj"), VoicingSpec())        # C E G
    naive = stack(Chord(5, "maj"), 60)                      # F A C
    led = nearest_inversion(naive, previous)
    def travel(notes):
        return sum(min(abs(n - p) for p in previous) for n in notes)
    assert travel(led) <= travel(naive)


def test_voice_uses_the_previous_chord_when_the_dial_is_centred():
    previous = voice(Chord(0, "maj"), VoicingSpec())
    led = voice(Chord(5, "maj"), VoicingSpec(), previous)
    assert max(abs(n - p) for n, p in zip(led, previous)) <= 5


def test_lock_center_keeps_a_long_progression_in_register():
    spec = VoicingSpec()
    previous: tuple[int, ...] = ()
    for root in [0, 5, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10] * 3:
        previous = voice(Chord(root, "maj7"), spec, previous)
        assert 40 <= sum(previous) / len(previous) <= 84


def test_chord_tone_near_snaps_to_the_closest_tone():
    chord = Chord(5, "min7")            # F Ab C Eb
    assert chord_tone_near(chord, 60) == 60         # C is a chord tone
    assert chord_tone_near(chord, 61) in (60, 63)   # Db -> C or Eb


def test_chord_tone_near_falls_back_to_the_scale_for_distant_notes():
    chord = Chord(0, "5")               # C G only
    scale = scale_for("major")
    # Eb is three semitones from the nearest chord tone. Dragging it onto C
    # would flatten the line, so with a scale to fall back on it stays a
    # scale note instead.
    assert chord_tone_near(chord, 63, scale) in (62, 64)
    # Two semitones is close enough to snap: D over a C power chord becomes C.
    assert chord_tone_near(chord, 62, scale) == 60
