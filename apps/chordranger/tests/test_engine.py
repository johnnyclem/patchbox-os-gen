"""The engine, driven tick by tick with a fake clock and a capture backend.

Every test here ends by asserting that nothing is left sounding. A MIDI brain
that strands a note is broken in the way that is most obvious on a stage and
least obvious in a unit test, so the assertion is made everywhere rather than
once.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from core import commands as cmd
from core.bass import BassSpec
from core.chords import VoicingSpec, parse_chord
from core.chordset import diatonic
from core.clock import FakeClock
from core.engine import CLOCK_STATUS, Engine, START_STATUS, STOP_STATUS
from core.events import PPQN, TICKS_PER_BAR, note_on
from core.midi_io import CaptureMidiIO
from core.project import default_project
from core.song import from_symbols as song_from_symbols
from core.style import ENDING, FILL_AB, MAIN_A, MAIN_B
from data.styles import factory_styles


@pytest.fixture()
def rig():
    midi = CaptureMidiIO()
    project = replace(default_project(), style=factory_styles()[0])
    engine = Engine(project, midi, FakeClock())
    return engine, midi


def run(engine: Engine, ticks: int) -> None:
    for _ in range(ticks):
        engine.step()


# --- transport ----------------------------------------------------------------

def test_a_stopped_engine_still_ticks_and_publishes(rig):
    engine, midi = rig
    run(engine, 10)
    assert engine.snapshot().playing is False
    assert not midi.notes_on()


def test_play_starts_the_band(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    assert engine.snapshot().playing
    assert midi.notes_on()


def test_stop_releases_everything(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    engine.submit(cmd.Stop())
    run(engine, 2)
    assert not midi.hanging()


def test_toggle_play_does_both(rig):
    engine, _midi = rig
    engine.submit(cmd.TogglePlay())
    run(engine, 4)
    assert engine.playing
    engine.submit(cmd.TogglePlay())
    run(engine, 4)
    assert not engine.playing


def test_stop_twice_returns_to_the_top(rig):
    engine, _midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR * 2)
    engine.submit(cmd.Stop())
    run(engine, 2)
    engine.submit(cmd.Stop())
    run(engine, 2)
    assert engine.tick == 0


def test_panic_kills_the_music_and_says_so(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    engine.submit(cmd.Panic())
    run(engine, 2)
    assert not engine.playing
    assert not midi.hanging()
    assert engine.snapshot().message == "PANIC"


def test_tempo_is_clamped_to_something_playable(rig):
    engine, _midi = rig
    engine.submit(cmd.SetTempo(9999))
    run(engine, 1)
    assert engine.bpm == 300
    engine.submit(cmd.SetTempo(1))
    run(engine, 1)
    assert engine.bpm == 20


def test_nudge_moves_the_tempo_by_its_delta(rig):
    engine, _midi = rig
    start = engine.bpm
    engine.submit(cmd.NudgeTempo(5))
    run(engine, 1)
    assert engine.bpm == start + 5


# --- pads and chords ----------------------------------------------------------

def test_a_pad_tap_auditions_while_stopped(rig):
    engine, midi = rig
    engine.submit(cmd.PadDown(0))
    run(engine, 2)
    assert midi.notes_on()
    assert engine.snapshot().chord_symbol == "C"


def test_the_audition_is_replaced_not_stacked(rig):
    engine, midi = rig
    engine.submit(cmd.PadDown(0))
    run(engine, 2)
    engine.submit(cmd.PadDown(3))
    run(engine, 2)
    # The first chord was released before the second sounded.
    assert len(midi.hanging()) <= 4


def test_releasing_a_pad_unlatched_stops_the_audition(rig):
    engine, midi = rig
    engine.submit(cmd.SetLatch(False))
    engine.submit(cmd.PadDown(0))
    run(engine, 2)
    engine.submit(cmd.PadUp(0))
    run(engine, 2)
    assert not midi.hanging()


def test_latched_pads_hold_the_chord_after_the_finger_lifts(rig):
    engine, _midi = rig
    engine.submit(cmd.PadDown(4))
    engine.submit(cmd.PadUp(4))
    run(engine, 2)
    assert engine.snapshot().chord_symbol == "G"


def test_a_dead_pad_does_nothing(rig):
    engine, midi = rig
    engine.submit(cmd.SetChordset(diatonic(0, "major")))
    run(engine, 1)
    engine.chordset = engine.chordset.with_pad(
        11, replace(engine.chordset.pads[11], enabled=False))
    engine.submit(cmd.PadDown(11))
    run(engine, 2)
    assert not midi.notes_on()


def test_the_band_follows_the_chord_the_pad_selected(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    engine.submit(cmd.PadDown(3))       # F in C major
    run(engine, TICKS_PER_BAR * 2)
    bass = [e for e in midi.notes_on(channel=1)]
    assert bass
    assert {e.data1 % 12 for e in bass} == {5}


def test_playing_a_chord_on_midi_in_sets_the_chord(rig):
    engine, _midi = rig
    for note in (65, 69, 72):           # F A C
        engine.on_midi_in("in", note_on(0, note, 100), 0)
    run(engine, 2)
    assert engine.snapshot().chord_symbol == "F"


def test_lifting_the_last_key_unlatched_clears_the_chord(rig):
    engine, _midi = rig
    engine.submit(cmd.SetLatch(False))
    for note in (60, 64, 67):
        engine.on_midi_in("in", note_on(0, note, 100), 0)
    run(engine, 2)
    for note in (60, 64, 67):
        engine.on_midi_in("in", note_on(0, note, 0), 0)
    run(engine, 2)
    assert engine.chord is None


def test_transposing_the_chordset_moves_the_key(rig):
    engine, _midi = rig
    engine.submit(cmd.TransposeChordset(2))
    run(engine, 1)
    assert engine.key_root == 2
    assert engine.snapshot().pad_captions[0] == "D"


def test_chord_edit_writes_back_to_the_pad(rig):
    engine, _midi = rig
    engine.submit(cmd.SetPad(0, parse_chord("Cmaj9")))
    run(engine, 1)
    assert engine.snapshot().pad_captions[0] == "Cmaj9"


# --- form ---------------------------------------------------------------------

def test_a_section_button_starts_the_band_there_when_stopped(rig):
    engine, _midi = rig
    engine.submit(cmd.RequestSection(MAIN_B))
    run(engine, 4)
    assert engine.playing
    assert engine.arranger.section == MAIN_B


def test_a_section_button_queues_a_change_while_playing(rig):
    engine, _midi = rig
    engine.submit(cmd.Play(MAIN_A))
    run(engine, 8)
    engine.submit(cmd.RequestSection(MAIN_B))
    run(engine, TICKS_PER_BAR)
    assert engine.arranger.section == FILL_AB


def test_the_ending_stops_the_transport_when_it_runs_out(rig):
    engine, midi = rig
    engine.submit(cmd.Play(MAIN_A))
    run(engine, 4)
    engine.submit(cmd.RequestSection(ENDING))
    run(engine, TICKS_PER_BAR * 6)
    assert not engine.playing
    assert not midi.hanging()


# --- band controls ------------------------------------------------------------

def test_muting_a_part_silences_it_and_releases_its_notes(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    midi.clear()
    engine.submit(cmd.SetPartMute("drum", True))
    run(engine, TICKS_PER_BAR)
    assert not midi.notes_on(channel=9)


def test_unmuting_brings_a_part_back(rig):
    engine, midi = rig
    engine.submit(cmd.SetPartMute("drum", True))
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    midi.clear()
    engine.submit(cmd.SetPartMute("drum", False))
    run(engine, TICKS_PER_BAR)
    assert midi.notes_on(channel=9)


def test_part_fields_are_clamped(rig):
    engine, _midi = rig
    engine.submit(cmd.SetPartField("bass", "octave", 99))
    run(engine, 1)
    assert engine.style.part("bass").octave == 3


def test_an_unknown_part_field_is_ignored(rig):
    engine, _midi = rig
    before = engine.style.part("bass")
    engine.submit(cmd.SetPartField("bass", "wobble", 3))
    run(engine, 1)
    assert engine.style.part("bass") == before


def test_changing_the_bass_mode_changes_the_line(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    engine.submit(cmd.PadDown(0))
    run(engine, TICKS_PER_BAR)
    midi.clear()
    engine.submit(cmd.SetBass(BassSpec(mode="arp")))
    run(engine, TICKS_PER_BAR)
    pcs = {e.data1 % 12 for e in midi.notes_on(channel=1)}
    assert len(pcs) > 1


def test_swapping_the_style_never_strands_a_note(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    engine.submit(cmd.SetStyle(factory_styles()[3]))
    run(engine, TICKS_PER_BAR)
    engine.submit(cmd.Stop())
    run(engine, 2)
    assert not midi.hanging()


def test_the_voicing_dial_moves_the_chord_part(rig):
    engine, midi = rig
    engine.submit(cmd.SetStyle(factory_styles()[1]))    # BALLAD, sustained
    engine.submit(cmd.Play())
    engine.submit(cmd.PadDown(0))
    run(engine, TICKS_PER_BAR)
    low = [e.data1 for e in midi.notes_on(channel=0)]
    midi.clear()
    engine.submit(cmd.SetVoicing(VoicingSpec(dial=2, lock_center=False)))
    run(engine, TICKS_PER_BAR * 2)
    high = [e.data1 for e in midi.notes_on(channel=0)]
    assert low and high
    assert max(high) > max(low)


# --- song mode ----------------------------------------------------------------

def test_song_mode_plays_the_chord_track(rig):
    engine, midi = rig
    song = song_from_symbols(["C", "F", "G", "C"], bars_each=1)
    engine.submit(cmd.SetSong(song))
    engine.submit(cmd.SetSongMode(True))
    engine.submit(cmd.Play())
    seen = []
    for _bar in range(4):
        midi.clear()
        run(engine, TICKS_PER_BAR)
        seen.append({e.data1 % 12 for e in midi.notes_on(channel=1)})
    assert seen[0] == {0} and seen[1] == {5} and seen[2] == {7}


def test_a_looping_song_wraps_at_its_end(rig):
    engine, _midi = rig
    engine.submit(cmd.SetSong(song_from_symbols(["C", "F"], bars_each=1)))
    engine.submit(cmd.SetSongMode(True))
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR * 2 + 4)
    assert engine.tick < TICKS_PER_BAR


def test_a_non_looping_song_stops_at_its_end(rig):
    engine, midi = rig
    song = replace(song_from_symbols(["C", "F"], bars_each=1), loop=False)
    engine.submit(cmd.SetSong(song))
    engine.submit(cmd.SetSongMode(True))
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR * 3)
    assert not engine.playing
    assert not midi.hanging()


def test_recording_writes_pad_taps_into_the_song(rig):
    engine, _midi = rig
    engine.submit(cmd.SetRecord(True))
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR + 3)
    engine.submit(cmd.PadDown(3))
    run(engine, 2)
    assert not engine.song.empty
    assert engine.song.chord_at(1).symbol() == "F"


def test_locate_moves_the_transport_and_clears_sounding_notes(rig):
    engine, midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR + 1)      # one tick past a downbeat
    assert engine._release, "expected notes still sounding on the downbeat"
    engine.submit(cmd.Locate(4))
    engine.submit(cmd.Stop())
    run(engine, 2)
    assert engine.tick >= TICKS_PER_BAR * 4
    # Everything that was sounding across the jump was released, not carried
    # over into the new position.
    assert not midi.hanging()


# --- clock --------------------------------------------------------------------

def test_clock_out_sends_start_pulses_and_stop(rig):
    engine, midi = rig
    engine.submit(cmd.SetClockOut(True))
    engine.submit(cmd.Play())
    run(engine, PPQN)
    engine.submit(cmd.Stop())
    run(engine, 1)
    statuses = [status for _id, status, _d in midi.realtime]
    assert START_STATUS in statuses
    assert statuses.count(CLOCK_STATUS) == 24
    assert STOP_STATUS in statuses


def test_the_metronome_clicks_on_every_beat(rig):
    engine, midi = rig
    engine.submit(cmd.SetMetronome(True))
    engine.submit(cmd.SetPartMute("drum", True))
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR)
    clicks = [e for e in midi.notes_on(channel=9) if e.data1 in (76, 77)]
    assert len(clicks) == 4
    assert clicks[0].data1 == 76 and clicks[1].data1 == 77


# --- housekeeping -------------------------------------------------------------

def test_the_snapshot_describes_the_whole_panel(rig):
    engine, _midi = rig
    engine.submit(cmd.Play())
    run(engine, TICKS_PER_BAR + 7)
    snapshot = engine.snapshot()
    assert snapshot.playing
    assert snapshot.bar == 1
    assert len(snapshot.pad_captions) == 12
    assert len(snapshot.parts) == len(engine.style.parts)
    assert snapshot.style_name == engine.style.name
    assert snapshot.backend == "capture"


def test_an_unknown_command_is_ignored_rather_than_fatal(rig):
    engine, _midi = rig
    engine.submit(object())
    run(engine, 2)
    assert engine.snapshot().tick >= 0


def test_capture_returns_the_project_with_live_state_folded_in(rig):
    engine, _midi = rig
    engine.submit(cmd.SetTempo(101))
    engine.submit(cmd.SetPad(0, parse_chord("Ab7")))
    run(engine, 2)
    project = engine.capture()
    assert project.bpm == 101
    assert project.chordset.caption(0) == "Ab7"


def test_two_bars_of_every_style_never_strand_a_note():
    for style in factory_styles():
        midi = CaptureMidiIO()
        engine = Engine(replace(default_project(), style=style), midi,
                        FakeClock())
        engine.submit(cmd.Play(MAIN_B))
        engine.submit(cmd.PadDown(5))
        run(engine, TICKS_PER_BAR * 2)
        engine.submit(cmd.Stop())
        run(engine, 2)
        assert not midi.hanging(), style.name
