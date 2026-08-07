# PhraseRanger

*"Play or hold. The phrase loops, overdubs, and slices."*

The live-capture bridge of the Ranger suite: an eight-track MIDI phrase
looper with hardware-pedal feel — free or 1/16-quantized record from any
input, overdub with tape-style feedback decay, sixteen levels of undo per
track, reverse and note-level stretch, independent or locked loop lengths
(polyrhythm for free), and a slicer that maps any take onto sixteen pads or
a chromatic spread in one gesture. Same Pi 5 + 1280×400 touch bar rig as
its siblings.

Inspirations: RC-series loopers · OP-1 tape · Ableton looper · Electribe
phrases.

![PhraseRanger PERFORM — eight loop tracks](docs/img/panel-1280x400-0-perform.png)

## Running it

```bash
python main.py                    # 1280x400 window, playing, track 1 armed
python main.py --size 480x800     # the portrait panel
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/phraseranger/config.toml   # the appliance
```

Play-and-it-records is the first gesture: the transport runs and track 1 is
armed from boot. The engine core is stdlib + the vendored
[rangerkit](../rangerkit) only; MIDI degrades to a null backend when
mido/python-rtmidi are absent.

## The shape

- `core/` — `phrase` (the immutable loop value: with_note / reversed /
  stretched / decayed / window / transposed, all pure), `track`, `recorder`
  (open-note bookkeeping, take boundaries), `history` (undo = a stack of
  phrases), `slicer`, `scene`, `engine`. No pygame at import; every engine
  test ends `assert not midi.hanging()`.
- `gui/` — **PERFORM** (eight strips: arm/mute/undo + loop lanes with
  playheads), **SLICE** (source strip + 16 pads, tap full / hold soft),
  **ROUTING** (plumbing, loop ownership, reverse/½×/2×, feel), **LIBRARY**
  (scene pads + project), **SET**.

## The Button

1 click play/stop · 2 clicks undo last overdub · 3 clicks clear the armed
track · hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

Feedback (tape generations while the take is open) and density on the
armed/last-touched track by default; humanize also available in
`[pots.map]`. MIDI CC learn on the SET screen.

## Tests

```bash
python -m pytest -q           # headless: SDL dummy + capture MIDI + fake clock
python bench/render_panel.py /tmp/panel --size 1280x400   # screenshots
```
