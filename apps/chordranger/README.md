# ChordRanger

A chord-first backing band for the Patchbox OS / RK-00pi rig: a Raspberry Pi 5
with a Blokas MIDI interface and a 1280×400 touch bar.

You hold a chord. The band plays it.

![The PERFORM screen](docs/img/panel-0-perform.png)

Three instruments are in its ancestry, and each contributed the thing it does
best:

| From | What it contributed |
|------|---------------------|
| **Chordcat** | Twelve pads of assignable chords, Chord Edit, the Chord Cruiser, and per-pad transpose |
| **Yamaha QY** | The auto-accompaniment: six sections, fills that fire on the bar line, and a chord track that re-harmonises the whole arrangement |
| **Orchid ORC-1** | The split between a chord voice with a voicing dial and an independent bass engine that can follow the root or go its own way |

## What it does

**Twelve chord pads.** Tap one and the band follows it — bass, drums, comping,
and whatever else the style has. Pads are tinted by harmonic function, so the
tonic chords share a colour and the layout teaches itself. Hold a pad to open
it in the editor.

**A real arranger.** Six sections in the QY shape: intro, main A, fill AB,
main B, fill BA, ending. Ask for main B while main A is playing and the fill
fires on the next bar line and hands over — you press the section you want,
not the fill that gets you there. The ending plays and stops the transport.

**Chord conversion, not transposition.** A style's phrases are written once in
C and bent onto whatever chord is current, per part: drums never move, the
bass takes the chord's bass note (including a slash chord's), the comp snaps
to the nearest chord tone, melodic lines stay in the key's scale. That is what
lets one bassline work over F♯m7♭5 without anyone writing a second bassline.

**A bass engine that is its own voice.** Root, octave, fifth, walk, arp, or
the style's own written line. The walk mode uses the *next* chord, so it
arrives on a leading tone into the change. A voicing dial moves the line one
chord tone at a time, and a slide mode overlaps notes so a mono synth glides.

**The Chord Cruiser.** Given where you are and what key you are in, it ranks
what could come next by functional harmony *and* voice-leading distance, with
a three-word reason beside each so you learn the vocabulary rather than just
tapping what is offered. Chord Voicing lists eight ways to play the chord you
have.

**A chord track.** Arm record, play the pads over the metronome, and the
progression is written to the song grid quantised to the bar. Sixteen bars on
screen, section markers on the ruler, and no hidden note data — the song *is*
the chord changes, so swapping the style re-arranges the whole tune.

## Running it

On a development host:

```bash
cd apps/chordranger
pip install -r requirements.txt
python main.py                    # 1280x400 window
python main.py --headless         # engine only, no display
python main.py --size 480x800     # the portrait panel
```

Keyboard shortcuts on the bench: space plays, `1`–`9` tap pads, `[` and `]`
nudge the tempo, tab cycles screens, `p` panics, escape quits.

The panel derives its whole layout from two numbers, so both build profiles
work: the 1280×400 HDMI bar gets side rails, and the 800×480 HyperPixel (or
the 480×800 4") gets a stacked top band with bottom tabs.

On the appliance the image installs it to `/opt/chordranger` and it is a
`systemctl` away — see [docs/deploy.md](docs/deploy.md). ChordRanger and
RK-00pi both render through SDL's KMS/DRM backend and there is one panel, so
exactly one of them runs at a time:

```bash
patchbox-chordranger status         # which app owns the panel
sudo patchbox-chordranger enable    # ChordRanger, now and on next boot
sudo patchbox-chordranger disable   # hand it back to RK-00pi
```

## The panel

Five tabs down the right, transport down the left, content in between.

| Tab | What it is for |
|-----|----------------|
| **PERFORM** | The pads, the six section buttons, and the chord readout. The screen you play from. |
| **CHORD** | Chord Edit, the Cruiser and the voicing list, side by side. |
| **BAND** | The mixer (mute, octave, level, per-part activity lamps) and the bass engine. |
| **SONG** | The chord track: sixteen bars, section markers, record and locate. |
| **SET** | MIDI output and binding, chordset/style/project browsers, key, metronome, clock out, theme. |

[docs/USER.md](docs/USER.md) walks through each one.

## The Button

Where the rig has a Pisound board, its button works the way it does on
RK-00pi — deliberately, so an operator who knows one appliance does not have
to learn the other's plumbing. On a build without Pisound the bridge is still
installed and simply has nothing pressing it; every gesture below has an
on-screen equivalent.

| Gesture | Action |
|---------|--------|
| 1 click | play / stop |
| 2 clicks | record toggle |
| 3 clicks | next section |
| hold ~1 s | save project |
| hold ~3 s | next style |
| hold ~5 s | panic (all notes off) |

Rebind under `[button.map]` in `/etc/chordranger/config.toml`. Check it with
`chordranger-btn PING` and `chordranger-btn --map`.

## Layout

```
core/         the engine. stdlib only — no pygame, no MIDI library, no device
  theory      pitch classes, scales, degrees, roman numerals
  chords      the Chord model, parsing, detection, and the voicing engine
  chordset    the twelve pads, per-pad transpose, save/load
  cruiser     "what comes next" — function + voice leading + novelty
  style       parts, sections, phrases, and the chord-conversion rules
  bass        the bass engine (root/octave/fifth/walk/arp/phrase)
  arranger    the form state machine and the per-bar renderer
  song        the chord track
  engine      the RT tick loop: commands in, snapshots out
  midi_io     mido/rtmidi, a capture backend for tests, and null
  button      the Pisound button bridge over a Unix socket
  project     .crproj save/load · config  /etc/chordranger/config.toml
gui/          pygame. theme tokens, widgets, one module per tab
data/         the factory styles and chordsets, in code so a wiped card boots
deploy/       config.toml, the systemd unit, the button scripts
bench/        render every screen to PNG without a display
tests/        295 tests, all of which run headless
```

The one rule worth stating: **nothing in `core/` may import pygame or open a
device at import time.** That is what lets the whole music model — theory,
voicings, styles, the arranger, the engine itself — be tested on a box with no
audio, no MIDI and no display, and it is easy to lose by accident.

## Tests

```bash
cd apps/chordranger
python -m pytest -q            # everything, headless (SDL dummy driver)
python bench/render_panel.py   # write one PNG per screen to docs/img
```

The GUI tests assert the two things that actually break a touch UI: that every
control a screen draws is registered as a hit target, and that pressing every
registered control produces commands the engine accepts without raising.
Between them they catch the whole "the button does nothing" class of bug.

Every engine test ends by asserting nothing is left sounding. A MIDI brain
that strands a note is broken in the way that is most obvious on a stage and
least obvious in a unit test.
