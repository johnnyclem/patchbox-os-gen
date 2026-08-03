"""The phrase value type and the slicer, as pure functions."""
from __future__ import annotations

from core.phrase import MIN_VELOCITY, Phrase, PhraseNote, QUANTIZE_TICKS
from core.slicer import PAD_COUNT, pad_phrase, velocity_scale
from rangerkit.events import PPQN, TICKS_PER_BAR


def note(tick, pitch=60, velocity=100, length=PPQN // 2):
    return PhraseNote(tick=tick, note=pitch, velocity=velocity,
                      length_ticks=length)


def phrase(*notes, bars=1):
    p = Phrase(length_ticks=bars * TICKS_PER_BAR)
    for n in notes:
        p = p.with_note(n)
    return p


def test_with_note_sorts_and_wraps():
    p = phrase(note(400), note(10))
    assert [n.tick for n in p.notes] == [10, 400 % TICKS_PER_BAR]


def test_quantize_snaps_to_the_sixteenth():
    p = Phrase().with_note(note(QUANTIZE_TICKS + 5), quantize=True)
    assert p.notes[0].tick == QUANTIZE_TICKS
    p = Phrase().with_note(note(QUANTIZE_TICKS * 2 - 4), quantize=True)
    assert p.notes[0].tick == QUANTIZE_TICKS * 2


def test_reverse_mirrors_onsets_and_is_involutive():
    p = phrase(note(0, length=24), note(96, length=48))
    r = p.reversed()
    assert {n.tick for n in r.notes} == \
        {(TICKS_PER_BAR - 0 - 24) % TICKS_PER_BAR, TICKS_PER_BAR - 96 - 48}
    assert r.reversed() == p


def test_stretch_scales_positions_and_lengths_not_loop():
    p = phrase(note(96, length=24))
    double = p.stretched(2.0)
    assert double.length_ticks == p.length_ticks
    assert double.notes[0].tick == 192 and double.notes[0].length_ticks == 48
    half = p.stretched(0.5)
    assert half.notes[0].tick == 48 and half.notes[0].length_ticks == 12


def test_decay_scales_and_kills_whispers():
    p = phrase(note(0, velocity=100), note(96, velocity=MIN_VELOCITY + 1))
    d = p.decayed(0.5)
    assert [n.velocity for n in d.notes] == [50]    # the whisper died


def test_with_length_folds_instead_of_deleting():
    p = phrase(note(TICKS_PER_BAR + 96), bars=2)
    shrunk = p.with_length(1)
    assert shrunk.length_ticks == TICKS_PER_BAR
    assert shrunk.notes[0].tick == 96


def test_transpose_clamps_at_the_rails():
    p = phrase(note(0, pitch=120))
    assert p.transposed(12).empty               # off the top: dropped
    assert p.transposed(-12).notes[0].note == 108


def test_round_trip_through_config():
    p = phrase(note(0), note(96, pitch=64, velocity=80, length=12), bars=2)
    assert Phrase.from_config(p.to_config()) == p


def test_window_rebases():
    p = phrase(note(96), note(200))
    w = p.window(96, 96)
    assert [n.tick for n in w.notes] == [0]
    assert w.length_ticks == 96


# --- slicer --------------------------------------------------------------------

def test_slice_pads_cover_the_loop():
    p = phrase(*(note(i * 24, pitch=36 + i) for i in range(16)))
    recovered = []
    for pad in range(PAD_COUNT):
        piece = pad_phrase(p, "slice", pad)
        recovered += [n.note for n in piece.notes]
    assert sorted(recovered) == [36 + i for i in range(16)]


def test_chromatic_pads_transpose():
    p = phrase(note(0, pitch=60))
    assert pad_phrase(p, "chromatic", 8).notes[0].note == 60    # unison pad
    assert pad_phrase(p, "chromatic", 10).notes[0].note == 62
    assert pad_phrase(p, "chromatic", 0).notes[0].note == 52


def test_empty_source_makes_dead_pads():
    assert pad_phrase(Phrase(), "slice", 3).empty
    assert pad_phrase(Phrase(), "chromatic", 3).empty


def test_velocity_layers_have_a_floor():
    assert velocity_scale(0.0) > 0.3
    assert velocity_scale(1.0) == 1.0
