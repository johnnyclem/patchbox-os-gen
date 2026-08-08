# SceneRanger

*"Touch a clip. The scene launches."*

The session view of the Ranger suite: a 12-track × 8-scene grid of MIDI
clips purpose-built for the 1280×400 bar — quantized launch (off/beat/bar),
follow actions with probability, per-clip velocity scale and transpose,
scene rows that launch as *states*, real-time recording into any slot, and
a scene chain that plays the whole set hands-free. Same Pi 5 + touch bar
rig as its siblings.

Inspirations: Ableton Live Session · Push · Bitwig clips · Launchpad.

![SceneRanger PERFORM — the 12-track x 8-scene clip grid](docs/img/panel-1280x400-0-perform.png)

## Running it

```bash
python main.py                    # 1280x400 window
python main.py --size 480x800     # the portrait panel (grid pages in halves)
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/sceneranger/config.toml    # the appliance
```

The transport arms on the first launch — a session starts when you touch a
clip. The engine core is stdlib + the vendored [rangerkit](../rangerkit)
only; MIDI degrades to a null backend when mido/python-rtmidi are absent.

## The shape

- `core/` — `clip` (immutable loop + follow/scale/transpose identity),
  `grid` (12×8 slots + track routing), `launcher` (queue → boundary →
  resolve; "off" resolves next drain, the <5–10 ms path), `arrange` (the
  scene chain), `recorder` (slot takes round up to bars; overdubs keep
  length), `engine`. No pygame at import; every engine test ends
  `assert not midi.hanging()`.
- `gui/` — **PERFORM** (the grid + scene column + track stop keys: tap
  launches, tap-again stops, hold an empty cell to record), **ROUTING**
  (track plumbing + the clip inspector), **ARRANGE** (build and run the
  chain), **LIBRARY** (ports, clock, pot learn, project, theme).

## The Button

1 click play/stop · 2 clicks fire the next filled scene · 3 clicks stop all
tracks · hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

Launch-quantize strength (off → beat → bar) and global scene intensity by
default (`[pots.map]`). MIDI CC learn on the LIBRARY screen.

## Tests

```bash
python -m pytest -q           # headless: SDL dummy + capture MIDI + fake clock
python bench/render_panel.py /tmp/panel --size 1280x400   # screenshots
```
