"""The pots service: CC learn, socket protocol, dedup — all sourceless."""
from __future__ import annotations

from rangerkit.configbase import RangerConfig
from rangerkit.enginebase import PotMove
from rangerkit.events import EventKind, MidiEvent, note_on
from rangerkit.pots import PotsService


def cc(control: int, value: int, channel: int = 0) -> MidiEvent:
    return MidiEvent(EventKind.CC, 0, channel, control, value)


def service(queue, **overrides):
    config = RangerConfig()
    pots = PotsService(queue.append, config)
    for key, value in overrides.items():
        setattr(pots, key, value)
    return pots


def test_default_ccs_move_the_pots():
    queue = []
    pots = service(queue)
    assert pots.on_cc(cc(20, 127))
    assert pots.on_cc(cc(21, 0))
    assert queue == [PotMove(index=0, value=1.0),
                     PotMove(index=1, value=0.0)]


def test_non_pot_traffic_falls_through():
    queue = []
    pots = service(queue)
    assert not pots.on_cc(cc(74, 64))
    assert not pots.on_cc(note_on(0, 60, 100))
    assert not queue


def test_channel_filter():
    queue = []
    pots = service(queue, channel=5)
    assert not pots.on_cc(cc(20, 64, channel=0))
    assert pots.on_cc(cc(20, 64, channel=5))
    assert len(queue) == 1


def test_duplicate_positions_are_dropped():
    queue = []
    pots = service(queue)
    pots.on_cc(cc(20, 64))
    pots.on_cc(cc(20, 64))
    assert len(queue) == 1
    pots.on_cc(cc(20, 65))
    assert len(queue) == 2


def test_learn_captures_the_next_cc():
    queue, learned = [], []
    pots = service(queue)
    pots.on_learned = lambda index, control: learned.append((index, control))
    pots.learn(1)
    assert pots.on_cc(cc(74, 40))           # captured, not forwarded
    assert learned == [(1, 74)] and not queue
    assert pots.on_cc(cc(74, 80))           # now it is pot B
    assert queue == [PotMove(index=1, value=80 / 127.0)]


def test_socket_protocol():
    queue = []
    pots = service(queue, source="socket")
    assert pots.handle("PING") == "PONG"
    assert pots.handle("POT 0 1023") == "OK"
    assert pots.handle("POT 1 0") == "OK"
    assert pots.handle("POT 9 12") == "ERR index"
    assert pots.handle("POT a b") == "ERR not a number"
    assert pots.handle("SPIN") == "ERR unknown"
    assert pots.handle("") == "ERR empty"
    assert queue == [PotMove(index=0, value=1.0),
                     PotMove(index=1, value=0.0)]


def test_none_source_ignores_cc():
    queue = []
    pots = service(queue, source="none")
    assert not pots.on_cc(cc(20, 64))
    assert not queue
