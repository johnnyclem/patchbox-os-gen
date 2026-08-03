"""The engine skeleton: transport, the release book, and the one invariant.

Every test here ends the way every engine test in the family must:
``assert not midi.hanging()``.
"""
from __future__ import annotations

from rangerkit import enginebase as eb
from rangerkit.enginebase import RangerEngine
from rangerkit.events import PPQN, TICKS_PER_BAR
from rangerkit.testkit import CaptureMidiIO, FakeClock, FakePots, run_ticks


class BeepEngine(RangerEngine):
    """A minimal instrument: one note at the top of every bar."""

    THREAD_NAME = "test-engine"

    def on_tick(self, tick: int) -> None:
        if tick % TICKS_PER_BAR == 0:
            self.send_note(channel=0, note=60, velocity=100,
                           length_ticks=PPQN)


def rig(engine_cls=BeepEngine, **kwargs):
    midi = CaptureMidiIO()
    engine = engine_cls(midi, FakeClock(), **kwargs)
    return engine, midi


def test_stopped_engine_ticks_but_stays_silent():
    engine, midi = rig()
    run_ticks(engine, TICKS_PER_BAR)
    assert not midi.events
    assert not midi.hanging()


def test_notes_are_released_on_time():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, TICKS_PER_BAR)
    assert len(midi.notes_on()) == 1
    assert len(midi.notes_off()) == 1
    assert not midi.hanging()


def test_stop_empties_the_release_book():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, 3)                    # note sounding, off not yet due
    assert engine.sounding() == 1
    engine.submit(eb.Stop())
    engine.step()
    assert engine.sounding() == 0
    assert not engine.playing
    assert not midi.hanging()


def test_panic_kills_everything_and_stops():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, 3)
    engine.submit(eb.Panic())
    engine.step()
    assert not engine.playing
    assert engine.snapshot().message == "PANIC"
    assert not midi.hanging()


def test_retrigger_releases_before_reattacking():
    class Machine(BeepEngine):
        def on_tick(self, tick):
            if tick in (0, 4):              # second on before first off is due
                self.send_note(0, 60, 100, PPQN)

    engine, midi = rig(Machine)
    engine.submit(eb.Play())
    run_ticks(engine, 8)
    kinds = [e.kind.name for _id, e in midi.events]
    assert kinds[:3] == ["NOTE_ON", "NOTE_OFF", "NOTE_ON"]
    run_ticks(engine, PPQN)
    assert not midi.hanging()


def test_release_channel_only_kills_that_channel():
    class TwoChannels(RangerEngine):
        def on_tick(self, tick):
            if tick == 0:
                self.send_note(0, 60, 100, TICKS_PER_BAR * 4)
                self.send_note(9, 36, 100, TICKS_PER_BAR * 4)

    engine, midi = rig(TwoChannels)
    engine.submit(eb.Play())
    run_ticks(engine, 2)
    engine.release_channel(9)
    assert midi.hanging() == {(0, 60)}      # channel 9 released, 0 sounding
    engine.all_notes_off()
    assert not midi.hanging()


def test_all_notes_off_belts_and_braces_used_channels():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, 2)
    engine.all_notes_off()
    ccs = [e for _id, e in midi.events
           if e.kind.name == "CC" and e.data1 == 123]
    assert [c.channel for c in ccs] == [0]
    assert not midi.hanging()


def test_second_stop_returns_to_top():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, 10)
    engine.submit(eb.Stop())
    engine.step()
    tick_after_stop = engine.tick
    engine.submit(eb.Stop())
    engine.step()
    assert tick_after_stop > 0 and engine.tick == 0
    assert not midi.hanging()


def test_tempo_commands_clamp():
    engine, midi = rig()
    engine.submit(eb.SetTempo(bpm=1000.0))
    engine.step()
    assert engine.bpm == eb.BPM_MAX
    engine.submit(eb.SetTempo(bpm=1.0))
    engine.step()
    assert engine.bpm == eb.BPM_MIN
    engine.submit(eb.NudgeTempo(delta=-500.0))
    engine.step()
    assert engine.bpm == eb.BPM_MIN
    assert not midi.hanging()


def test_clock_out_runs_at_24_ppq():
    engine, midi = rig()
    engine.clock_out = True
    engine.submit(eb.Play())
    run_ticks(engine, TICKS_PER_BAR)        # ticks 0 … 383
    assert (eb.OUT, eb.START_STATUS, 0) in midi.realtime
    clocks = [r for r in midi.realtime if r[1] == eb.CLOCK_STATUS]
    assert len(clocks) == TICKS_PER_BAR // eb.CLOCK_DIVISOR
    engine.submit(eb.Stop())
    engine.step()
    assert (eb.OUT, eb.STOP_STATUS, 0) in midi.realtime
    assert not midi.hanging()


def test_snapshot_is_immutable_and_current():
    engine, midi = rig()
    engine.submit(eb.Play())
    run_ticks(engine, TICKS_PER_BAR + 1)
    snapshot = engine.snapshot()
    assert snapshot.playing and snapshot.bar == 1 and snapshot.beat == 0
    try:
        snapshot.bar = 99
        raised = False
    except AttributeError:
        raised = True
    assert raised
    engine.submit(eb.Stop())
    engine.step()
    assert not midi.hanging()


def test_unknown_command_is_ignored():
    engine, midi = rig()
    engine.submit(("weird", "tuple"))
    engine.submit(object())
    engine.step()                           # must not raise
    assert not midi.hanging()


def test_pot_moves_are_normalized_and_dispatched():
    seen = []

    class PotAware(BeepEngine):
        def on_pot(self, index, value):
            seen.append((index, value))

    engine, midi = rig(PotAware)
    pots = FakePots(engine.submit)
    pots.turn(0, 0.5)
    pots.turn(0, 0.5)                       # duplicate — dropped at source
    pots.turn(1, 2.0)                       # clamped by the engine
    pots.turn(7, 0.1)                       # bad index — command dropped
    engine.step()
    assert seen == [(0, 0.5), (1, 1.0)]
    assert engine.pots == [0.5, 1.0]
    assert not midi.hanging()


def test_midi_in_reaches_subclass_on_tick_thread():
    from rangerkit.events import note_on
    seen = []

    class Listener(BeepEngine):
        def on_midi_in_event(self, endpoint_id, event):
            seen.append((endpoint_id, event.data1))

    engine, midi = rig(Listener)
    engine.on_midi_in("din_in", note_on(0, 64, 100), ts_ns=0)
    assert not seen                         # not applied until the tick
    engine.step()
    assert seen == [("din_in", 64)]
    assert not midi.hanging()


def test_engine_survives_a_tick_that_raises():
    class Faulty(BeepEngine):
        def on_tick(self, tick):
            super().on_tick(tick)
            if tick == 2:
                raise RuntimeError("boom")

    engine, midi = rig(Faulty)
    engine.submit(eb.Play())
    # step() propagates (tests drive it directly), but the thread loop's
    # net catches and releases; emulate the loop's behavior here.
    run_ticks(engine, 2)
    try:
        engine.step()
    except RuntimeError:
        engine.all_notes_off()
    assert not midi.hanging()
