# MidiRanger

*"You hold notes. The processors transform them."*

The central MIDI brain of the Ranger suite: a multi-port routing matrix, four
advanced arpeggiators, a scale quantizer and diatonic harmonizer, note FX
(velocity curves, humanize, constrained random, delay/echo), a bank of
syncable CC LFOs, and eight morphable scenes — on the same Pi 5 + 1280×400
touch bar rig as RK-00pi and ChordRanger.

Inspirations: Squarp Pyramid/Hermod · Oxi One · KeyStep Pro arps ·
MIDI Solutions.

## Running it

```bash
python main.py                    # 1280x400 window (the reference panel)
python main.py --size 480x800     # the portrait panel
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/midiranger/config.toml   # the appliance
```

The engine core is stdlib + the vendored [rangerkit](../rangerkit) only; MIDI
degrades to a null backend when mido/python-rtmidi are absent, so all of the
above run on a laptop with nothing installed but pygame.

## The shape

- `core/` — engine (a `rangerkit.enginebase.RangerEngine`), matrix over
  `rangerkit.routing`, `arp`, `quantizer`, `harmonizer`, `notefx`, `cclfo`,
  `scene`, `project`. No pygame at import; every note-on is booked with its
  off-tick and every engine test ends `assert not midi.hanging()`.
- `gui/` — pygame under SDL kmsdrm. Screens: **PERFORM** (activity, scene
  pads, bypass, pots), **MATRIX** (the patchbay), **FX** (quantize /
  harmonize / feel / LFOs), **ARP** (four slots, one deep editor), **SET**
  (port binding, clock, pot learn, project, theme).
- `deploy/` — config.toml, PiSound button bridge, datadirs; the systemd unit
  is rendered from rangerkit's shared template by `stage3/15-install-…`.

## The Button

1 click play/stop (arps + LFOs) · 2 clicks bypass · 3 clicks next scene ·
hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

`[pots] source = "midi_cc"` by default: tap LEARN on SET, wiggle any CC, and
that knob is pot A/B. `[pots.map]` binds them (arp probability and humanize
out of the box). A `pots.sock` source exists for future ADC hardware.

## Tests

```bash
python -m pytest -q           # headless: SDL dummy + capture MIDI + fake clock
python bench/render_panel.py /tmp/panel --size 1280x400   # screenshots
```
