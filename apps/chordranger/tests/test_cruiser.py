"""Chord Cruiser: suggestions, voicing lists, progressions."""
from __future__ import annotations

from core.chords import Chord, parse_chord
from core.cruiser import (progression, quality_alternatives, suggest,
                          voice_leading_cost, voicings)


def _symbols(picks):
    return [s.chord.symbol() for s in picks]


def test_the_dominant_offers_the_tonic_first():
    picks = suggest(parse_chord("G7"), root=0, scale="major")
    assert picks[0].chord.root == 0


def test_the_supertonic_leads_to_the_dominant():
    picks = suggest(parse_chord("Dm7"), root=0, scale="major")
    assert 7 in [p.chord.root for p in picks[:3]]


def test_suggestions_never_include_the_chord_you_are_already_on():
    current = parse_chord("Cmaj7")
    picks = suggest(current, root=0, scale="major", limit=12)
    assert all((p.chord.root, p.chord.quality)
               != (current.root, current.quality) for p in picks)


def test_suggestions_are_ranked_by_descending_score():
    picks = suggest(parse_chord("C"), root=0, scale="major", limit=8)
    assert [p.score for p in picks] == sorted((p.score for p in picks),
                                              reverse=True)


def test_every_suggestion_carries_a_reason_and_a_playable_voicing():
    for pick in suggest(parse_chord("Am7"), root=9, scale="minor"):
        assert pick.reason
        assert pick.notes and all(0 <= n <= 127 for n in pick.notes)


def test_chords_already_on_pads_are_demoted_but_not_removed():
    avoid = (parse_chord("F"),)
    plain = suggest(parse_chord("C"), root=0, scale="major", limit=12)
    demoted = suggest(parse_chord("C"), root=0, scale="major", limit=12,
                      avoid=avoid)
    def rank(picks, symbol):
        return [p.chord.symbol() for p in picks].index(symbol)
    assert "Fmaj7" in _symbols(demoted)
    assert rank(demoted, "Fmaj7") > rank(plain, "Fmaj7")


def test_a_minor_key_suggests_minor_key_chords():
    picks = suggest(parse_chord("Am"), root=9, scale="minor", limit=6)
    roots = {p.chord.root for p in picks}
    assert 2 in roots or 5 in roots     # Dm or F, the minor subdominants


def test_suggest_works_with_no_current_chord():
    picks = suggest(None, root=0, scale="major")
    assert picks


def test_voice_leading_cost_is_zero_for_the_same_chord():
    chord = parse_chord("Fmaj7")
    assert voice_leading_cost(chord, chord) == 0


def test_voice_leading_cost_grows_with_distance():
    home = parse_chord("C")
    close = voice_leading_cost(home, parse_chord("Am"))     # two common tones
    far = voice_leading_cost(home, parse_chord("F#"))       # none
    assert close < far


def test_a_progression_keeps_moving_rather_than_oscillating():
    chords = progression(parse_chord("C"), root=0, scale="major", length=6)
    assert len(chords) == 6
    symbols = [c.symbol() for c in chords]
    assert len(set(symbols)) >= 4


def test_voicings_lists_every_style_for_a_chord():
    options = voicings(parse_chord("Cmaj9"))
    labels = [label for label, _notes in options]
    assert "CLOSED" in labels and "DROP 2" in labels
    assert len(set(labels)) == len(labels)


def test_quality_alternatives_start_near_and_end_far():
    alternatives = quality_alternatives(Chord(0, "maj"), limit=6)
    assert alternatives[0].root == 0
    # The nearest recolouring shares most of its intervals with a plain major.
    first = set(alternatives[0].spec.intervals)
    last = set(alternatives[-1].spec.intervals)
    assert len(first & {0, 4, 7}) >= len(last & {0, 4, 7})
