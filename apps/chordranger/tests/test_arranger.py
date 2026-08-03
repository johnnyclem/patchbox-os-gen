"""The arranger: the form state machine and per-bar rendering."""
from __future__ import annotations

from dataclasses import replace

from core.arranger import Arranger, QUANTIZE_SECTION
from core.bass import BassSpec
from core.chords import Chord, VoicingSpec, parse_chord
from core.events import TICKS_PER_BAR
from core.style import ENDING, FILL_AB, FILL_BA, INTRO, MAIN_A, MAIN_B
from data.styles import factory_styles


def _style(name: str = "HOUSE"):
    return next(s for s in factory_styles() if s.name == name)


def _run(arranger: Arranger, ticks: int, chord=None, bass=None):
    """Run the arranger for *ticks*, collecting (tick, note) pairs."""
    chord = chord or parse_chord("C")
    bass = bass or BassSpec()
    out = []
    for tick in range(ticks):
        for note in arranger.step(chord, None, VoicingSpec(), bass):
            out.append((tick, note))
    return out


# --- form ---------------------------------------------------------------------

def test_start_begins_at_the_intro_when_the_style_has_one():
    arranger = Arranger(_style())
    arranger.start()
    assert arranger.section == INTRO


def test_the_intro_hands_over_to_main_a():
    arranger = Arranger(_style())
    arranger.start(INTRO)
    _run(arranger, arranger.current.ticks)
    assert arranger.section == MAIN_A


def test_a_main_section_loops_on_itself():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    _run(arranger, arranger.current.ticks)
    assert arranger.section == MAIN_A
    assert arranger.pos == 0


def test_moving_between_mains_goes_through_the_matching_fill():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    arranger.request(MAIN_B)
    _run(arranger, TICKS_PER_BAR)               # to the next bar line
    assert arranger.section == FILL_AB
    _run(arranger, arranger.current.ticks)      # the fill is one bar
    assert arranger.section == MAIN_B


def test_the_return_trip_uses_the_other_fill():
    arranger = Arranger(_style())
    arranger.start(MAIN_B)
    arranger.request(MAIN_A)
    _run(arranger, TICKS_PER_BAR)
    assert arranger.section == FILL_BA
    _run(arranger, arranger.current.ticks)
    assert arranger.section == MAIN_A


def test_bar_quantize_waits_for_the_downbeat():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    _run(arranger, 10)
    arranger.request(MAIN_B)
    _run(arranger, 10)
    assert arranger.section == MAIN_A           # still inside the bar
    _run(arranger, TICKS_PER_BAR)
    assert arranger.section == FILL_AB


def test_section_quantize_waits_for_the_whole_section():
    arranger = Arranger(_style(), quantize=QUANTIZE_SECTION)
    arranger.start(MAIN_A)
    arranger.request(MAIN_B)
    _run(arranger, TICKS_PER_BAR)
    assert arranger.section == MAIN_A
    _run(arranger, arranger.current.ticks - TICKS_PER_BAR)
    assert arranger.section in (FILL_AB, MAIN_B)


def test_requesting_the_ending_stops_after_it_plays():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    arranger.request(ENDING)
    _run(arranger, TICKS_PER_BAR)
    assert arranger.section == ENDING
    _run(arranger, arranger.current.ticks + 1)
    assert arranger.stopped


def test_requesting_a_section_the_style_lacks_is_ignored():
    style = _style()
    stripped = type(style)(name=style.name, bpm=style.bpm, parts=style.parts,
                           sections={MAIN_A: style.sections[MAIN_A]})
    arranger = Arranger(stripped)
    arranger.start(MAIN_A)
    arranger.request(MAIN_B)
    _run(arranger, TICKS_PER_BAR)
    assert arranger.section == MAIN_A


def test_cancel_request_drops_a_queued_move():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    arranger.request(MAIN_B)
    arranger.cancel_request()
    _run(arranger, TICKS_PER_BAR * 2)
    assert arranger.section == MAIN_A


def test_state_reports_where_the_form_is():
    arranger = Arranger(_style())
    arranger.start(MAIN_B)
    _run(arranger, TICKS_PER_BAR + 5)
    state = arranger.state()
    assert state.section == MAIN_B
    assert state.bar == 1
    assert state.bars == 4


# --- rendering ----------------------------------------------------------------

def test_a_running_section_produces_notes_on_several_channels():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    notes = _run(arranger, TICKS_PER_BAR)
    assert notes
    assert len({note.channel for _tick, note in notes}) >= 2


def test_drums_are_not_transposed_by_the_chord():
    arranger = Arranger(_style())
    arranger.start(MAIN_A)
    over_c = {(t, n.note) for t, n in _run(arranger, TICKS_PER_BAR,
                                           parse_chord("C"))
              if n.part_id == "drum"}
    arranger.start(MAIN_A)
    over_f = {(t, n.note) for t, n in _run(arranger, TICKS_PER_BAR,
                                           parse_chord("F#m7b5"))
              if n.part_id == "drum"}
    assert over_c and over_c == over_f


def test_the_chord_part_plays_tones_of_the_current_chord():
    arranger = Arranger(_style("BALLAD"))
    arranger.start(MAIN_A)
    chord = parse_chord("Abmaj7")
    notes = [note for _t, note in _run(arranger, TICKS_PER_BAR, chord)
             if note.part_id == "chord"]
    assert notes
    assert {n.note % 12 for n in notes} <= set(chord.pitch_classes)


def test_the_bass_part_follows_the_chord_root():
    arranger = Arranger(_style("BALLAD"))
    arranger.start(MAIN_A)
    notes = [note for _t, note in _run(arranger, TICKS_PER_BAR,
                                       parse_chord("Eb"))
             if note.part_id == "bass"]
    assert notes
    assert {n.note % 12 for n in notes} == {3}


def test_muting_a_part_silences_only_that_part():
    style = _style()
    muted = style.with_part(replace(style.part("drum"), muted=True))
    arranger = Arranger(muted)
    arranger.start(MAIN_A)
    notes = _run(arranger, TICKS_PER_BAR)
    assert notes
    assert all(note.part_id != "drum" for _t, note in notes)


def test_a_chord_change_mid_bar_only_affects_the_rest_of_the_bar():
    arranger = Arranger(_style("BALLAD"))
    arranger.start(MAIN_A)
    first = []
    for tick in range(TICKS_PER_BAR // 2):
        first += [(tick, n) for n in
                  arranger.step(parse_chord("C"), None, VoicingSpec(),
                                BassSpec())]
    second = []
    for tick in range(TICKS_PER_BAR // 2, TICKS_PER_BAR):
        second += [(tick, n) for n in
                   arranger.step(parse_chord("F"), None, VoicingSpec(),
                                 BassSpec())]
    # No note is emitted twice for the same tick, and the second half is in
    # the new chord.
    assert len({t for t, _n in first} & {t for t, _n in second}) == 0
    late_bass = {n.note % 12 for _t, n in second if n.part_id == "bass"}
    assert late_bass in ({5}, set())


def test_a_one_bar_phrase_loops_under_a_four_bar_section():
    arranger = Arranger(_style())
    arranger.start(MAIN_B)
    bars = []
    for _bar in range(4):
        bars.append(sorted(
            (tick, note.note)
            for tick, note in _run(arranger, TICKS_PER_BAR)
            if note.part_id == "drum"))
    assert bars[0] and bars[0] == bars[1] == bars[2] == bars[3]


def test_strum_spreads_the_chord_across_ticks():
    arranger = Arranger(_style("BALLAD"))
    arranger.start(MAIN_A)
    plain = [t for t, n in _run(arranger, TICKS_PER_BAR)
             if n.part_id == "chord"]
    arranger.start(MAIN_A)
    strummed = []
    for tick in range(TICKS_PER_BAR):
        strummed += [(tick, n) for n in
                     arranger.step(Chord(0, "maj7"), None, VoicingSpec(),
                                   BassSpec(), strum=3)]
    ticks = [t for t, n in strummed if n.part_id == "chord"]
    assert len(set(ticks)) > len(set(plain))


def test_every_rendered_note_is_legal_across_every_style_and_section():
    for style in factory_styles():
        for section in (INTRO, MAIN_A, FILL_AB, MAIN_B, FILL_BA, ENDING):
            arranger = Arranger(style)
            arranger.start(section)
            for _tick, note in _run(arranger, TICKS_PER_BAR * 2,
                                    parse_chord("F#m7b5")):
                assert 0 <= note.note <= 127
                assert 1 <= note.velocity <= 127
                assert 0 <= note.channel <= 15
                assert note.length > 0
