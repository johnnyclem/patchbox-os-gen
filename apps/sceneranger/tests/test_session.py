"""Clips, the grid, launch queues and chains as pure units."""
from __future__ import annotations

from core.arrange import Chain
from core.clip import Clip, ClipNote
from core.grid import Grid, SCENES, TRACKS
from core.launcher import NOTHING, STOP, TrackLauncher, boundary
from rangerkit.events import PPQN, TICKS_PER_BAR


def clip(*notes, bars=1, **fields):
    c = Clip(length_ticks=bars * TICKS_PER_BAR, **fields).normalised()
    for tick, pitch in notes:
        c = c.with_note(ClipNote(tick=tick, note=pitch, velocity=100,
                                 length_ticks=24))
    return c


def test_clip_round_trips_through_config():
    c = clip((0, 60), (96, 64), bars=2, follow="next", follow_loops=2,
             transpose=5, velocity_scale=0.8)
    assert Clip.from_config(c.to_config()) == c


def test_clip_shaping_clamps():
    c = clip((0, 120), transpose=24)
    pitch, velocity = c.shaped(c.notes[0], intensity=1.0)
    assert pitch == 127
    soft = clip((0, 60), velocity_scale=0.5)
    _p, v = soft.shaped(soft.notes[0], intensity=0.5)
    assert v == 25


def test_grid_puts_and_drops_empties():
    grid = Grid()
    grid.put(0, 0, clip((0, 60)))
    assert grid.clip(0, 0) is not None
    grid.put(0, 0, None)
    assert grid.clip(0, 0) is None
    grid.put(99, 0, clip((0, 60)))          # out of range: ignored
    assert not grid.slots


def test_grid_round_trips_through_config():
    grid = Grid()
    grid.put(2, 3, clip((0, 60), follow="stop"))
    grid.tracks[2] = grid.tracks[2].__class__(dest="usb_out", channel=7)
    again = Grid.from_config(grid.to_config())
    assert again.clip(2, 3) == grid.clip(2, 3)
    assert again.tracks[2].dest == "usb_out"
    assert again.filled_scenes()[3] and not again.filled_scenes()[0]


def test_boundaries():
    assert boundary(0, "bar") and boundary(TICKS_PER_BAR, "bar")
    assert not boundary(PPQN, "bar")
    assert boundary(PPQN, "beat") and not boundary(PPQN + 1, "beat")
    assert boundary(17, "off")              # off: every tick resolves


def test_launcher_queue_resolve_stop():
    launcher = TrackLauncher()
    launcher.queue(3)
    assert launcher.resolve(100) == 3
    assert launcher.active == 3 and launcher.started == 100
    assert launcher.resolve(101) is None    # nothing queued
    launcher.queue_stop()
    assert launcher.resolve(200) == STOP
    assert launcher.active == NOTHING
    launcher.queue_stop()                   # stop with nothing playing
    assert launcher.resolve(300) is None


def test_launcher_wrap_detection():
    launcher = TrackLauncher()
    launcher.queue(0)
    launcher.resolve(0)
    assert not launcher.wrapped(0, TICKS_PER_BAR)   # the launch instant
    assert launcher.wrapped(TICKS_PER_BAR, TICKS_PER_BAR)
    assert not launcher.wrapped(TICKS_PER_BAR + 1, TICKS_PER_BAR)


def test_chain_holds_and_wraps():
    chain = Chain()
    chain.append(0, 2)
    chain.append(3, 1)
    assert chain.start() == 0
    assert chain.on_bar() is None           # held: bar 1 of 2
    assert chain.on_bar() == 3              # advance
    assert chain.on_bar() == 0              # wraps
    chain.stop()
    assert chain.on_bar() is None


def test_chain_round_trips_and_bounds():
    chain = Chain()
    for scene in range(20):
        chain.append(scene % SCENES, 4)
    assert len(chain.entries) == 16         # capped
    again = Chain.from_config(chain.to_config())
    assert again.entries == chain.entries
    assert TRACKS == 12 and SCENES == 8
