# GrooveRanger

*"Twelve pads, sixteen steps, one bar of trouble."*

The drum machine of the Ranger suite: a sample groovebox purpose-built for
the 1280×400 bar — twelve velocity-layered pads with choke groups, a
sixteen-step sequencer with probability, ratchets, trig conditions,
micro-timing and parameter locks, eight patterns with queued switching and
one-pass fills, a song chain, and a lo-fi master bus (one-knob filter,
tempo-synced delay, small-room reverb) on the Pisound DAC. Same Pi 5 +
touch bar rig as its siblings.

Inspirations: TR-909 · Elektron trig conditions · MPC pads · Volca Beats.

## Running it

```bash
python main.py                    # 1280x400 window
python main.py --size 480x800     # the portrait panel
python main.py --headless         # engine only (systemd, bench, CI)
python main.py --config /etc/grooveranger/config.toml   # the appliance
```

The sequencer core is stdlib + the vendored [rangerkit](../rangerkit) only;
the sampler and FX bus are numpy. MIDI degrades to a null backend without
mido/python-rtmidi, audio to a silent null device without sounddevice —
CI runs both degradations on every push. Internal render is 48 kHz float32,
256-frame blocks (the DAC path may clock higher; the synthesis does not).

## The shape

- `core/` — `steps`/`sequencer` (immutable patterns compiled to tick
  schedules; swing, conditions, fills, mutes), `kit`/`pad` (velocity
  layers, choke and mute groups, per-pad voice params), `sampler` (32
  one-shot voices behind the shared `SynthMidiBridge`), `fxbus` (the
  master bus, block-vectorized), `phrasechain` (song mode), `mixer`,
  `engine`. No pygame at import; every engine test ends
  `assert not midi.hanging()`.
- `gui/` — **PERFORM** (pads + patterns + FILL + mute groups), **SEQ**
  (the step grid and the whole tracker toolbox), **KIT** (voice params,
  kit browsing, routing), **SONG** (the chain + master bus), **SET**
  (ports, clock, pots, project, theme).
- `data/kits/rk909` — the shipped kit: 13 synthesized 16-bit WAVs
  (~460 KiB), CC0-clean by construction; regenerate with
  `python bench/make_kit.py`. Drop extra kits (kit.json + WAVs) under
  `/var/lib/grooveranger/kits`.

## The internal contract

To external gear a pad is (kit channel, pad note) — pick the destination
on KIT. To the internal sampler each pad speaks on its own channel (the
pad index): parameter locks travel as CC 16/74/10 right before the hit,
mixer levels as CC 7, and channel 15 is the master bus. It is all plain
MIDI, which is why the whole audio path is testable with a CaptureMidiIO.

## The Button

1 click play/stop · 2 clicks queue a fill · 3 clicks next used pattern ·
hold ~1 s save · hold ~5 s panic. Remap under `[button.map]`.

## Pots

Master filter and swing by default (`[pots.map]`). MIDI CC learn on the
SET screen.

## Tests

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q
```

Sequencer semantics, sampler voices and FX offline, the engine invariant
(nothing hangs — MIDI notes or sampler voices), determinism across twin
engines, and press-everything GUI tests at 1280×400, 800×480 and 480×800.
