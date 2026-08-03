"""The PhraseRanger engine end to end: record, replay, undo, slice, and the
invariant. Every test here ends with ``assert not midi.hanging()``.
"""
from __future__ import annotations

from core import commands as cmd
from core.engine import PhraseRangerEngine
from core.project import Project, default_project
from rangerkit import enginebase as base
from rangerkit.events import EventKind, PPQN, TICKS_PER_BAR, note_off, \
    note_on
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks


def rig(project=None, play=True):
    midi = CaptureMidiIO()
    engine = PhraseRangerEngine(project or default_project(), midi,
                                FakeClock())
    if play:
        engine.submit(base.Play())
        engine.step()
    return engine, midi


def record_note(engine, note=60, velocity=100, hold=24):
    engine.on_midi_in("din_in", note_on(0, note, velocity), 0)
    run_ticks(engine, hold)
    engine.on_midi_in("din_in", note_off(0, note), 0)
    engine.step()


def ons(midi, channel=None):
    return [e for _ep, e in midi.events if e.kind is EventKind.NOTE_ON
            and (channel is None or e.channel == channel)]


def stop_clean(engine, midi):
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()


# --- record / replay -----------------------------------------------------------

def test_record_lands_in_the_armed_track_and_replays():
    engine, midi = rig()
    record_note(engine, 60)
    assert len(engine.tracks[0].phrase.notes) == 1
    count = len(ons(midi, 0))
    run_ticks(engine, TICKS_PER_BAR * 2)
    assert len(ons(midi, 0)) >= count + 2       # replayed every pass
    stop_clean(engine, midi)


def test_monitor_thru_sounds_and_releases():
    engine, midi = rig(play=False)              # stopped: no recording,
    engine.on_midi_in("din_in", note_on(0, 72, 90), 0)
    engine.step()
    assert [e.data1 for e in ons(midi, 0)] == [72]  # but thru still sounds
    engine.on_midi_in("din_in", note_off(0, 72), 0)
    engine.step()
    assert not midi.hanging()
    assert engine.tracks[0].phrase.empty        # nothing was recorded


def test_record_is_idempotent_across_save_load(tmp_path):
    engine, midi = rig()
    record_note(engine, 60)
    record_note(engine, 64, hold=12)
    path = tmp_path / "take.prproj"
    engine.capture().save(path)
    engine2, midi2 = rig(Project.load(path))
    assert engine2.tracks[0].phrase == engine.tracks[0].phrase
    stop_clean(engine, midi)
    stop_clean(engine2, midi2)


def test_quantize_snaps_the_take():
    engine, midi = rig()
    run_ticks(engine, 5)                        # a sloppy entrance
    record_note(engine, 60, hold=20)
    assert engine.tracks[0].phrase.notes[0].tick % (PPQN // 4) == 0
    engine.submit(cmd.SetQuantize(on=False))
    engine.step()
    run_ticks(engine, 7)
    record_note(engine, 62, hold=20)
    ticks = [n.tick for n in engine.tracks[0].phrase.notes]
    assert any(t % (PPQN // 4) for t in ticks)  # the loose one stayed loose
    stop_clean(engine, midi)


def test_stop_mid_take_closes_open_notes():
    engine, midi = rig()
    engine.on_midi_in("din_in", note_on(0, 60, 100), 0)
    run_ticks(engine, 30)
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()
    assert len(engine.tracks[0].phrase.notes) == 1  # the take survived


# --- undo / history ------------------------------------------------------------

def test_undo_peels_takes_in_order():
    engine, midi = rig()
    record_note(engine, 60)
    engine.submit(cmd.ArmTrack(index=0))        # take boundary: new arm
    engine.step()
    record_note(engine, 64)
    assert len(engine.tracks[0].phrase.notes) == 2
    engine.submit(cmd.UndoTrack())
    engine.step()
    assert [n.note for n in engine.tracks[0].phrase.notes] == [60]
    engine.submit(cmd.UndoTrack())
    engine.step()
    assert engine.tracks[0].phrase.empty
    engine.submit(cmd.UndoTrack())
    engine.step()
    assert "NOTHING" in engine.snapshot().message
    stop_clean(engine, midi)


def test_undo_mid_note_releases_what_sounded():
    engine, midi = rig()
    record_note(engine, 60, hold=TICKS_PER_BAR // 2)
    run_ticks(engine, TICKS_PER_BAR)            # the long note is sounding
    engine.submit(cmd.UndoTrack(index=0))
    engine.step()
    assert not midi.hanging()
    stop_clean(engine, midi)


def test_clear_and_reverse_and_stretch_are_undoable():
    engine, midi = rig()
    record_note(engine, 60)
    before = engine.tracks[0].phrase
    for command in (cmd.ReverseTrack(index=0),
                    cmd.StretchTrack(index=0, factor=2.0),
                    cmd.ClearTrack(index=0)):
        engine.submit(command)
        engine.step()
    assert engine.tracks[0].phrase.empty
    for _ in range(3):
        engine.submit(cmd.UndoTrack(index=0))
        engine.step()
    assert engine.tracks[0].phrase == before
    stop_clean(engine, midi)


# --- feedback decay ------------------------------------------------------------

def test_feedback_decays_old_material_while_overdubbing():
    engine, midi = rig()
    engine.submit(cmd.SetTrackField(index=0, name="feedback", value=0.5))
    engine.step()
    record_note(engine, 60, hold=24)            # take is open (still armed)
    velocity0 = engine.tracks[0].phrase.notes[0].velocity
    run_ticks(engine, TICKS_PER_BAR * 2)        # two wraps, take open
    notes = engine.tracks[0].phrase.notes
    assert not notes or notes[0].velocity < velocity0
    stop_clean(engine, midi)


def test_full_feedback_keeps_layers_forever():
    engine, midi = rig()
    record_note(engine, 60)
    velocity0 = engine.tracks[0].phrase.notes[0].velocity
    run_ticks(engine, TICKS_PER_BAR * 4)
    assert engine.tracks[0].phrase.notes[0].velocity == velocity0
    stop_clean(engine, midi)


# --- loop lengths --------------------------------------------------------------

def test_free_length_track_polyrhythms():
    engine, midi = rig()
    engine.submit(cmd.SetGlobalBars(bars=2))
    engine.submit(cmd.SetTrackBars(index=1, bars=1))
    engine.step()
    assert engine.tracks[0].phrase.bars == 2    # locked follows global
    assert engine.tracks[1].phrase.bars == 1    # free keeps its own
    stop_clean(engine, midi)


# --- playback feel -------------------------------------------------------------

def test_probability_thins_playback_without_touching_the_phrase():
    engine, midi = rig()
    record_note(engine, 60)
    engine.submit(cmd.SetTrackField(index=0, name="probability",
                                    value=0.0))
    engine.step()
    count = len(ons(midi, 0))
    run_ticks(engine, TICKS_PER_BAR * 4)
    assert len(ons(midi, 0)) == count           # silent
    assert len(engine.tracks[0].phrase.notes) == 1  # material intact
    stop_clean(engine, midi)


def test_humanize_only_delays():
    engine, midi = rig()
    record_note(engine, 60)
    engine.submit(cmd.SetTrackField(index=0, name="humanize_timing",
                                    value=8))
    engine.step()
    run_ticks(engine, TICKS_PER_BAR * 4)
    stop_clean(engine, midi)                    # delayed notes still release


# --- slices --------------------------------------------------------------------

def test_slice_pad_fires_now_even_stopped():
    engine, midi = rig()
    record_note(engine, 60, hold=12)
    engine.submit(base.Stop())
    engine.step()
    count = len(ons(midi, 0))
    engine.submit(cmd.FireSlice(pad=0, layer=1.0))
    run_ticks(engine, PPQN)                     # FREE_RUN: fires anyway
    assert len(ons(midi, 0)) == count + 1
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()


def test_chromatic_pad_transposes_and_soft_layer_scales():
    engine, midi = rig()
    record_note(engine, 60, hold=12)
    engine.submit(cmd.SetSliceMode(mode="chromatic"))
    engine.submit(cmd.FireSlice(pad=10, layer=0.0))
    run_ticks(engine, PPQN)
    fired = ons(midi, 0)[-1]
    assert fired.data1 == 62
    assert fired.data2 < 100                    # soft layer
    stop_clean(engine, midi)


# --- scenes --------------------------------------------------------------------

def test_scene_round_trip_restores_takes():
    engine, midi = rig()
    record_note(engine, 60)
    engine.submit(cmd.SaveScene(slot=0))
    engine.submit(cmd.ClearTrack(index=0))
    engine.step()
    assert engine.tracks[0].phrase.empty
    engine.submit(cmd.RecallScene(slot=0))
    engine.step()
    assert not midi.hanging()                   # recall released everything
    assert len(engine.tracks[0].phrase.notes) == 1
    stop_clean(engine, midi)


def test_recall_empty_scene_is_a_message():
    engine, midi = rig()
    engine.submit(cmd.RecallScene(slot=5))
    engine.step()
    assert "EMPTY" in engine.snapshot().message
    stop_clean(engine, midi)


# --- pots / rerouting / hygiene ------------------------------------------------

def test_pot_sweep_shapes_the_focused_track():
    engine, midi = rig()
    pots = FakePots(engine.submit)
    pots.turn(0, 0.5)                           # feedback
    pots.turn(1, 0.25)                          # density
    engine.step()
    assert abs(engine.tracks[0].params.feedback - 0.5) < 0.01
    assert abs(engine.tracks[0].params.probability - 0.25) < 0.01
    stop_clean(engine, midi)


def test_reroute_mid_note_releases_the_old_plumbing():
    engine, midi = rig()
    record_note(engine, 60, hold=TICKS_PER_BAR // 2)
    run_ticks(engine, TICKS_PER_BAR)            # long note sounding
    engine.submit(cmd.SetTrackField(index=0, name="channel", value=5))
    engine.step()
    held = midi.hanging()
    assert all(ch != 0 for ch, _n in held)
    stop_clean(engine, midi)


def test_panic_lands_the_take_and_silences():
    engine, midi = rig()
    engine.on_midi_in("din_in", note_on(0, 60, 100), 0)
    run_ticks(engine, 20)
    engine.submit(base.Panic())
    engine.step()
    assert not engine.playing
    assert not midi.hanging()
    assert engine.recorder.armed == -1


def test_unknown_fields_cost_a_log_line_only():
    engine, midi = rig()
    engine.submit(cmd.SetTrackField(index=0, name="warp", value=9))
    engine.submit(cmd.SetTrackField(index=42, name="feedback", value=0.5))
    engine.submit(cmd.StretchTrack(index=0, factor=3.0))
    engine.step()
    stop_clean(engine, midi)


def test_snapshot_reports_the_loops():
    engine, midi = rig()
    record_note(engine, 60)
    snapshot = engine.snapshot()
    assert len(snapshot.tracks) == 8
    assert snapshot.tracks[0].armed and snapshot.tracks[0].notes == 1
    assert snapshot.tracks[0].hits
    assert snapshot.armed == 0 and snapshot.recording
    assert len(snapshot.slice_captions) == 16
    assert snapshot.slice_filled[0]
    stop_clean(engine, midi)
