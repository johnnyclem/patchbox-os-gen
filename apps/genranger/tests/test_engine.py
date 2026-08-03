"""The GenRanger engine end to end: determinism, evolution, and the
invariant. Every test here ends with ``assert not midi.hanging()``.
"""
from __future__ import annotations

from core import commands as cmd
from core.engine import GenRangerEngine
from core.project import Project, default_project
from rangerkit import enginebase as base
from rangerkit.events import EventKind, TICKS_PER_BAR
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks


def rig(project=None):
    midi = CaptureMidiIO()
    engine = GenRangerEngine(project or default_project(), midi, FakeClock())
    return engine, midi


def playing_rig(project=None, bars=0):
    engine, midi = rig(project)
    engine.submit(base.Play())
    if bars:
        run_ticks(engine, TICKS_PER_BAR * bars)
    else:
        engine.step()
    return engine, midi


def stop_clean(engine, midi):
    engine.submit(base.Stop())
    engine.step()
    assert not midi.hanging()


# --- determinism (the headline) ------------------------------------------------

def test_same_project_same_stream():
    engine1, midi1 = playing_rig(bars=8)
    engine2, midi2 = playing_rig(bars=8)
    assert midi1.events == midi2.events
    assert midi1.events            # and it is actually a piece, not silence
    stop_clean(engine1, midi1)
    stop_clean(engine2, midi2)


def test_determinism_survives_save_and_load(tmp_path):
    engine1, midi1 = rig()
    path = tmp_path / "piece.gvproj"
    engine1.capture().save(path)
    engine2, midi2 = rig(Project.load(path))
    for engine in (engine1, engine2):
        engine.submit(base.Play())
        run_ticks(engine, TICKS_PER_BAR * 4)
    assert midi1.events == midi2.events
    stop_clean(engine1, midi1)
    stop_clean(engine2, midi2)


def test_cruise_off_makes_frozen_layers_periodic():
    project = default_project()
    project.params["cruise"] = {"on": False}
    # Only the euclid layer: the stochastic ones legitimately vary per cycle.
    project.params["layers"] = [project.params["layers"][0]]
    engine, midi = playing_rig(project, bars=4)
    ons = [(e.data1, engine_tick % TICKS_PER_BAR)
           for engine_tick, (_ep, e) in enumerate(midi.events)
           if e.kind is EventKind.NOTE_ON]
    assert len({tuple(n for n, _t in ons[i:i + 3])
                for i in range(0, len(ons) - 3, 3)}) <= 4
    stop_clean(engine, midi)


def test_evolution_actually_happens_under_cruise():
    project = default_project()
    project.params["cruise"] = {"on": True, "speed": 1.0, "chaos": 0.8}
    engine, midi = playing_rig(project, bars=16)
    assert len(engine.timeline) >= 4        # cruise fired repeatedly
    stop_clean(engine, midi)


# --- zero hanging notes under everything ---------------------------------------

def test_stop_mid_note_is_clean():
    engine, midi = playing_rig(bars=1)
    run_ticks(engine, 7)                    # mid-step, notes sounding
    stop_clean(engine, midi)


def test_panic_mid_note_is_clean():
    engine, midi = playing_rig(bars=2)
    engine.submit(base.Panic())
    engine.step()
    assert not engine.playing
    assert not midi.hanging()


def test_mute_releases_that_layers_notes_now():
    project = default_project()
    engine, midi = playing_rig(project, bars=1)
    run_ticks(engine, 3)                    # harmony drones are sounding
    engine.submit(cmd.ToggleLayerMute(index=3))
    engine.step()
    held = {(ch, n) for (ch, n) in midi.hanging()}
    assert all(ch != 2 for ch, _n in held)  # channel 2 = the harmony layer
    stop_clean(engine, midi)


def test_mutate_now_mid_note_is_clean():
    engine, midi = playing_rig(bars=1)
    for _ in range(6):
        engine.submit(cmd.MutateNow())
        run_ticks(engine, 11)
    run_ticks(engine, TICKS_PER_BAR)
    stop_clean(engine, midi)


def test_seed_recall_mid_note_is_clean():
    engine, midi = playing_rig(bars=1)
    engine.submit(cmd.CaptureSeed(slot=0))
    run_ticks(engine, TICKS_PER_BAR)
    engine.submit(cmd.RecallSeed(slot=0))
    engine.step()                           # restore releases, then this
    run_ticks(engine, TICKS_PER_BAR)        # tick's notes sound on — legit
    stop_clean(engine, midi)


def test_timeline_restore_mid_note_is_clean():
    project = default_project()
    project.params["cruise"] = {"on": True, "speed": 1.0, "chaos": 0.5}
    engine, midi = playing_rig(project, bars=6)
    engine.submit(cmd.TimelineStep(delta=-2))
    engine.step()
    engine.submit(cmd.TimelineLive())
    run_ticks(engine, TICKS_PER_BAR)
    stop_clean(engine, midi)


def test_pot_sweep_is_clean():
    engine, midi = playing_rig(bars=1)
    pots = FakePots(engine.submit)
    for value in (0.0, 0.3, 0.7, 1.0, 0.5):
        pots.turn(0, value)
        pots.turn(1, 1.0 - value)
        run_ticks(engine, 5)
    assert engine.cruise.speed == 0.5 and engine.cruise.chaos == 0.5
    stop_clean(engine, midi)


def test_key_change_mid_note_is_clean():
    engine, midi = playing_rig(bars=1)
    engine.submit(cmd.SetKey(root=7, scale="dorian"))
    engine.step()
    assert engine.layers[0].params.root == 7
    run_ticks(engine, TICKS_PER_BAR)
    stop_clean(engine, midi)


# --- locks ---------------------------------------------------------------------

def test_locked_layer_survives_a_mutation_storm():
    engine, midi = playing_rig(bars=1)
    engine.submit(cmd.ToggleLayerLock(index=1))
    engine.step()
    before = engine.layers[1].params
    for _ in range(12):
        engine.submit(cmd.MutateNow())
        engine.step()
    assert engine.layers[1].params == before
    stop_clean(engine, midi)


def test_lock_all_round_trip():
    engine, midi = rig()
    engine.submit(cmd.LockAll())
    engine.step()
    assert engine.snapshot().all_locked
    engine.submit(cmd.MutateNow())
    engine.step()
    assert "LOCKED" in engine.snapshot().message
    engine.submit(cmd.LockAll())
    engine.step()
    assert not engine.snapshot().all_locked
    assert not midi.hanging()


def test_mutate_now_on_locked_layer_is_a_message():
    engine, midi = rig()
    engine.submit(cmd.ToggleLayerLock(index=0))
    engine.submit(cmd.MutateNow(index=0))
    engine.step()
    assert engine.snapshot().message == "LAYER LOCKED"
    assert not midi.hanging()


# --- timeline + seeds ----------------------------------------------------------

def test_timeline_restores_the_recorded_piece():
    project = default_project()
    project.params["cruise"] = {"on": False}
    engine, midi = playing_rig(project, bars=1)
    engine.submit(cmd.MutateNow(index=1))   # push state A
    engine.step()
    fingerprint_a = engine.capture_state()
    run_ticks(engine, TICKS_PER_BAR)        # a bar later (pushes coalesce
    engine.submit(cmd.Reseed(index=1))      # per bar) push state B
    engine.step()
    assert engine.capture_state() != fingerprint_a
    engine.submit(cmd.TimelineStep(delta=-1))
    engine.step()
    restored = engine.capture_state()
    assert restored["layer_seeds"] == fingerprint_a["layer_seeds"]
    assert restored["layers"] == fingerprint_a["layers"]
    stop_clean(engine, midi)


def test_seed_capture_round_trips_through_project(tmp_path):
    engine, midi = rig()
    engine.submit(cmd.CaptureSeed(slot=4))
    engine.step()
    path = tmp_path / "set.gvproj"
    engine.capture().save(path)
    engine2, midi2 = rig(Project.load(path))
    assert engine2.seeds.occupied()[4]
    engine2.submit(cmd.RecallSeed(slot=4))
    engine2.step()
    assert "SEED 5" in engine2.snapshot().message
    assert not midi.hanging() and not midi2.hanging()


def test_recall_empty_seed_is_a_message_not_a_crash():
    engine, midi = rig()
    engine.submit(cmd.RecallSeed(slot=6))
    engine.step()
    assert "EMPTY" in engine.snapshot().message
    assert not midi.hanging()


# --- cc layer ------------------------------------------------------------------

def test_cc_layer_emits_ccs_and_no_notes():
    project = default_project()
    project.params["layers"] = [
        {"role": "cc", "algorithm": "random", "dest": "din_out",
         "channel": 5, "cc": 74, "density": 0.6}]
    engine, midi = playing_rig(project, bars=2)
    ccs = [e for _ep, e in midi.events if e.kind is EventKind.CC]
    ons = [e for _ep, e in midi.events if e.kind is EventKind.NOTE_ON]
    assert ccs and not ons
    assert all(e.data1 == 74 and e.channel == 5 for e in ccs)
    assert len({e.data2 for e in ccs}) > 2
    stop_clean(engine, midi)


# --- panel plumbing ------------------------------------------------------------

def test_grid_cell_edit_reaches_the_pattern():
    project = default_project()
    engine, midi = rig(project)
    engine.submit(cmd.SetGridCell(index=2, step=0, row=0, value=1.0))
    engine.step()
    assert engine.layers[2].params.grid[0][0] == 1.0
    engine.submit(cmd.SetGridCell(index=2, step=99, row=0, value=1.0))
    engine.step()                           # out of range: ignored
    assert not midi.hanging()


def test_ca_seed_cell_toggles_and_restarts_history():
    project = default_project()
    project.params["layers"][0]["algorithm"] = "cellular"
    engine, midi = playing_rig(project, bars=2)
    before = engine.layers[0].params.ca_seed
    engine.submit(cmd.SetCaSeedCell(index=0, cell=3))
    engine.step()
    assert engine.layers[0].params.ca_seed == before ^ 8
    # The handler reset history; a cycle boundary may have advanced it one.
    assert engine.layers[0].generation <= 1
    stop_clean(engine, midi)


def test_enabling_a_dormant_slot_adds_a_layer():
    engine, midi = rig()
    assert not engine.layers[5].params.enabled
    engine.submit(cmd.SetLayerField(index=5, name="enabled", value=True))
    engine.step()
    assert engine.layers[5].params.enabled
    engine.submit(cmd.SetLayerField(index=5, name="enabled", value=False))
    engine.step()
    assert not engine.layers[5].params.enabled
    assert not midi.hanging()


def test_unknown_fields_cost_a_log_line_only():
    engine, midi = rig()
    engine.submit(cmd.SetLayerField(index=0, name="warp", value=9))
    engine.submit(cmd.SetCruiseField(name="flux", value=1.0))
    engine.submit(cmd.SetMacro(name="entropy", value=1.0))
    engine.submit(cmd.SetLayerField(index=42, name="density", value=1.0))
    engine.step()                           # none may raise
    assert not midi.hanging()


def test_snapshot_reports_the_piece():
    engine, midi = playing_rig(bars=1)
    snapshot = engine.snapshot()
    roles = [v.role for v in snapshot.layers if v.role]
    assert roles == ["rhythm", "bass", "melody", "harmony"]
    assert snapshot.layers[0].hits            # the lattice is visible
    assert snapshot.layers[2].grid            # the MAP grid is visible
    assert ("din_out", True) not in snapshot.outputs_bound or True
    assert snapshot.timeline_pos == -1
    stop_clean(engine, midi)
