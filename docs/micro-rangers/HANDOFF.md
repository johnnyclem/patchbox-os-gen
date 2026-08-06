# Handoff — micro-rangers (Ranger suite on MicroDexed-touch / Teensy 4.1)

**To:** the maintainer of the MicroDexed-touch fork `micro-rangers`
**From:** patchbox-os-gen (`apps/` — the Ranger suite reference implementation)
**Date:** 2026-08-06
**Reference tree:** `github.com/johnnyclem/patchbox-os-gen`, branch `patchbox-2024-01`

This document is written to be dropped at the root of the `micro-rangers`
fork. It tells you what the Ranger suite *is*, which of its contracts must
survive a 600 MHz microcontroller, which must be renegotiated, and in what
order to build it. It does not assume you have read any Python.

---

## 0. TL;DR

The Ranger suite is seven MIDI-first instrument apps (~30k lines of Python)
that all share one engine skeleton, one timing model, one command/snapshot
concurrency model and one absolutely non-negotiable invariant: **the engine
owns every note it has sent.** The musical logic is portable and worth
porting verbatim. The Pi-specific half — pygame, SDL/kmsdrm, systemd, venv,
ALSA/JACK, numpy DSP — is not portable and should not be attempted.

The port is therefore:

1. Reimplement `apps/rangerkit/` as a freestanding C++17 library
   (`rangercore/`) that does **not** include `Arduino.h`, so it compiles and
   tests on your laptop.
2. Reimplement each app's `core/` on top of it — that is 1.0k–2.0k lines of
   Python per app, and it is nearly all integer arithmetic over fixed-size
   tables.
3. Write a *new* UI for 320×240 + 2 encoders. Do not port the pygame code;
   port the screen/tab/hit-target **model** only.
4. Bind the `internal` MIDI endpoint to the audio graph MicroDexed-touch
   already has. This is the seam that lets GrooveRanger and SynthRanger
   arrive without porting a single line of DSP.

Everything else in this document is detail on those four points.

---

## 1. What you are being handed

### 1.1 The apps

| # | App | One-liner | `core/` LOC (Python) |
|---|-----|-----------|------|
| 01 | **ChordRanger** | Chord pads + QY-style auto-accompaniment + bass engine | 3748 |
| 02 | **MidiRanger** | Routing matrix · 4 arps · quantize/harmonize · note FX · CC LFOs · 8 scenes | 1212 |
| 03 | **GenRanger** | 6-layer generative sequencer (Euclid/Markov/CA/prob-grid/random) + Cruise mutation | 1635 |
| 04 | **PhraseRanger** | 8-track MIDI phrase looper, 16-deep undo, reverse/stretch, slicer | 1168 |
| 05 | **SceneRanger** | 12×8 clip/scene launcher, follow actions, scene chain | 1078 |
| 06 | **GrooveRanger** | 12-pad sample groovebox, 16-step tracker sequencer, master FX bus | 2000 |
| 07 | **SynthRanger** | 4-part × 4-engine polysynth (VA/FM/wavetable/PD), mod matrix, morph | 1497 |

Plus `apps/rangerkit/` (~1.6k lines of shared runtime, 4.6k with tests) —
the thing you are actually porting first.

`core/` in every app is stdlib-only and never imports a display or an audio
backend. That is enforced in CI by a poisoned-import check, and it is the
single property that makes this port tractable: **the musical logic is
already isolated from the platform.** Read it as a specification.

### 1.2 The files that hold the actual algorithms

Read in this order per app. Everything else is glue.

| App | Read these |
|-----|-----------|
| rangerkit | `enginebase.py` (453) · `events.py` · `clock.py` · `routing.py` · `theory.py` · `chords.py` · `euclid.py` · `audio/bridge.py` |
| MidiRanger | `engine.py` (468) · `arp.py` (167) · `notefx.py` · `harmonizer.py` · `cclfo.py` · `scene.py` |
| GenRanger | `engine.py` (560) · `layers.py` (237) · `mutate.py` · `markov.py` · `cellular.py` · `probgrid.py` · `seeds.py` · `timeline.py` |
| PhraseRanger | `engine.py` (503) · `phrase.py` (143) · `recorder.py` · `track.py` · `history.py` · `slicer.py` |
| SceneRanger | `engine.py` (428) · `clip.py` · `grid.py` · `launcher.py` · `recorder.py` · `arrange.py` |
| GrooveRanger | `engine.py` (524) · `sequencer.py` · `steps.py` · `kit.py` · `pad.py` · `phrasechain.py` (skip `sampler.py`/`fxbus.py`) |
| SynthRanger | `engine.py` (280) · `parts.py` · `patch.py` · `modmatrix.py` · `morph.py` · `preset.py` (skip all of `core/dsp/`) |
| ChordRanger | `engine.py` (719) · `arranger.py` · `style.py` · `chordset.py` · `bass.py` · `cruiser.py` |

Each app also has `docs/ARCHITECTURE.md` (60–100 lines) stating its
invariants in prose. Those files are the design rationale — read them before
you change any behaviour, because most of the "why is it like that" answers
are already written down there.

`apps/rangerkit/docs/CONVENTIONS.md` is the family rulebook. Ten rules. Six
of them survive the port unchanged; four need renegotiation (see §3).

### 1.3 The one invariant that matters

Every note-on leaves the engine through exactly one function, which books
its note-off at the moment the note goes out:

```python
def send_note(self, channel, note, velocity, length_ticks, endpoint=OUT):
    key = (endpoint, channel, note)
    if key in self._release:                 # retrigger: release first
        self.midi.send(endpoint, note_off(channel, note))
    self.midi.send(endpoint, note_on(channel, note, velocity))
    self._release[key] = self.tick + max(1, length_ticks)
    self._channels_used.add((endpoint, channel))
```

Stop, mute, panic, scene recall, route removal, part reassignment, track
clear, kit swap and undo *all* work by consulting that book. None of them
can strand a note, because none of them knows how to send a note-off any
other way. Every engine test in the suite ends with
`assert not midi.hanging()`; the audio apps extend it to
`assert not synth.hanging_voices()`.

**Port this first and port it exactly.** If you get one thing from this
document, get this. A groovebox that occasionally leaves a note screaming
into a rack is a groovebox nobody trusts on stage, and this design is the
reason the suite doesn't.

---

## 2. Target context as I understand it

| | |
|---|---|
| MCU | Teensy 4.1 — i.MX RT1062, Cortex-M7 @ 600 MHz, single-precision FPU, 32 KB I/D cache |
| On-chip RAM | **1024 KB**: 512 KB tightly-coupled (RAM1, split ITCM/DTCM at link time) + 512 KB OCRAM (RAM2 / `DMAMEM`) |
| Flash | 8 MB QSPI (≈7.75 MB usable for program + `PROGMEM` data) |
| PSRAM | **16 MB** on the bottom pads (`EXTMEM`) — 2× 8 MB APS6404, hand-soldered, confirmed populated on every unit |
| SD | 16 GB SDHC in the built-in SDIO socket (4-bit, use SdFat) |
| Display | 320×240 SPI TFT (ILI9341 class) + resistive single-touch |
| Controls | 2 rotary encoders with push |
| MIDI | 2× TRS jacks (A/B switchable) = **1 In / 1 Out** · USB MIDI device · USB MIDI **host** |
| Audio | Teensy Audio Library: 44.1 kHz, `AUDIO_BLOCK_SAMPLES` 128 (2.90 ms), int16 |

Two notes on the spec, both now settled:

- The "1 MB" figure on a Teensy 4.1 is **RAM**, not flash — flash is 8 MB.
  That distinction matters a lot here, because flash is not the constraint
  (your firmware will land in the hundreds of KB) and RAM absolutely is.
  Budgets in §6 are written on that basis, and §4.1's "compile all the modes
  into one image" strategy depends on it.
- **PSRAM is confirmed**: both 8 MB chips are populated on the bottom pads of
  every board, giving 16 MB of contiguous `EXTMEM`. That is the assumption
  the whole Phase 4 (PhraseRanger undo stacks) and Phase 6 (resident sample
  kits) plan rests on, so it being real rather than aspirational removes the
  largest single scoping risk in the port.

**Because the chips are hand-soldered, verify them per unit.** Run PJRC's
PSRAM memory test on every board and record the result alongside the §6.2
measurements. A marginal joint does not fail loudly — it shows up as rare
bit corruption in a sample kit or a stale undo level, weeks later, on one
box out of six. Ten minutes per board now is worth days of "why does *that*
unit glitch". If a board reports 8 MB instead of 16, the second chip's
chip-select or its solder is the first thing to look at, and the firmware
should refuse to boot a 16 MB-assuming build on it rather than quietly
running with half the pool (rule 4 — degrade visibly, don't die, and never
degrade silently).

---

## 3. The ten family rules, ported

From `apps/rangerkit/docs/CONVENTIONS.md`. This table is the contract for
the fork — pin it in the fork's README.

| # | Pi rule | micro-rangers |
|---|---------|---------------|
| 1 | Engine owns every note; `assert not midi.hanging()` | **Unchanged.** Non-negotiable. Extend to voices for the audio modes. |
| 2 | Commands in, snapshots out; engine runs headless | **Unchanged in shape**, different mechanism — no threads (§4.2). |
| 3 | Nothing core-side imports pygame/audio at import time | **Becomes:** nothing in `rangercore/` includes `Arduino.h`, `Audio.h`, or any display header. Enforced by the host build (§7). |
| 4 | Degrade, don't die | **Unchanged.** No SD card → RAM-only session + a SET-screen warning. No USB host device → endpoints greyed. Never freeze, never boot dark. |
| 5 | One panel, one app (systemd `Conflicts=`) | **Becomes:** one firmware, one *active mode* at a time, with a mode manager (§4.1). MidiRanger's matrix is the exception — it becomes always-on plumbing. |
| 6 | Three geometries, ≥44 px targets | **Renegotiated.** One geometry (320×240) and an encoder-first interaction model; touch floor drops to 36 px and touch is never used for fine values (§5). |
| 7 | Hardware arrives as commands (button socket, pots) | **Unchanged in shape.** Encoders, touch, footswitch GPIO and MIDI-CC learn all end as commands in the same queue. |
| 8 | Audio honesty: 48 kHz float32, 256-frame blocks | **Renegotiated:** 44.1 kHz int16, 128-frame blocks — say so in every README, same as the Pi side says 48 kHz. Do not let a spec sheet quote the codec's rate as the synthesis rate. |
| 9 | PPQN 96, absolute-deadline clock, `FakeClock` drives the same `step()` | **Unchanged** — but the tick source becomes the audio sample counter (§4.3). |
| 10 | Config is deployment state only | **Unchanged in spirit**, different file format — SD `.ini`, not TOML (§6.4). |

---

## 4. Architecture for the fork

### 4.1 One firmware, N modes

There is no systemd and no second process. The Pi suite's mutual exclusion
becomes a **mode manager** inside one firmware:

```
micro-rangers/
  src/
    rangercore/        ← the port of apps/rangerkit — NO Arduino.h
      events.h/.cpp        MidiEvent, PPQN=96, note_on/note_off helpers
      clock.h/.cpp         SampleClock (device) + FakeClock (host tests)
      engine.h/.cpp        RangerEngine: queue drain, on_tick, release book,
                           clock out, snapshot publish
      release_book.h       the 128-entry booking table
      routing.h/.cpp       endpoint ids + RoutingMatrix (fixed 32 routes)
      theory.h chords.h euclid.h   scales, chord tables, Bjorklund
      rng.h                splitmix64 + the canonical stream PRNG (§4.5)
      snapshot.h           POD snapshot structs
    platform/          ← interfaces only, no implementations
      IMidiIO.h IClock.h IStorage.h IPanel.h
    device/            ← Teensy implementations of platform/
      midi_teensy.cpp      DIN (Serial), usbMIDI, USBHost_t36
      storage_sd.cpp       SdFat + atomic write
      panel_ili9341.cpp    dirty-rect renderer
      encoders.cpp touch.cpp
      instruments.cpp      the internal endpoint → Dexed/Drumset/… (§4.6)
    modes/
      midiranger/ genranger/ phraseranger/ sceneranger/
      grooveranger/ synthranger/ chordranger/
        engine.cpp  screens.cpp  project.cpp
    ui/                shell (transport bar, tabs, widgets, focus ring)
    modemgr.cpp        activate/deactivate, state save on switch
  test/                host build: Unity or doctest, no Arduino
  tools/               golden-vector generator + comparator
```

Gate each mode behind `RANGER_ENABLE_<APP>` so a build can drop modes it
doesn't need. Only the active mode's engine ticks; only the active mode's
state occupies the engine arena. Switching modes: quiesce (panic → release
book empties → `assert` it is empty), save project to SD, tear down, build
the next.

**The exception is MidiRanger.** Its routing matrix is not really an app —
it is the box's MIDI plumbing, and every other mode wants it (route the DIN
input to the internal instrument *and* to USB host while GrooveRanger
plays). Factor it as an always-resident service:

- `MidiMatrix` (routes, thru, channel rewrite) → always on, owned by the
  platform layer, configured from SD.
- MidiRanger the *mode* → the matrix's editor plus the arps, quantizer,
  harmonizer, note FX, LFOs and scenes.
- Arps/FX are an optional insert other modes can enable. Cheap, and it's the
  single biggest musical win available from this architecture.

### 4.2 Threads → three execution contexts

The Pi engine runs a `SCHED_FIFO` tick thread, publishes an immutable
snapshot under a lock, and the GUI thread reads it. On a single-core MCU
with no RTOS, collapse that to:

| Context | Runs | Rules |
|---------|------|-------|
| **Audio ISR** (`AudioStream::update`, every 2.90 ms) | DSP only | No `malloc`, no SD, no `Serial`, no blocking. Increments the global sample counter. |
| **Main loop** | engine `step()`, UI render, SD I/O, MIDI drain | Everything else. Runs `step()` as many times as the sample counter says ticks are due (§4.3). |
| **Interrupts** (UART MIDI RX, encoder pins, USB) | enqueue only | Push into a lock-free SPSC ring; never touch engine state. |

Consequences, and they are all simplifications:

- The snapshot needs **no lock** — engine and UI are both in the main loop.
  Keep it a POD struct, copy it once at the end of `step()`, render from the
  copy. The discipline (UI never touches engine state) still pays: it keeps
  the modes testable and it stops a slow redraw from corrupting a pattern.
- The command queue becomes a fixed-capacity ring, capacity 128 (the Pi's is
  512 — you have less RAM and a much shorter drain latency). Producers that
  can be interrupted push with a 1–2 µs interrupt-disable window; that is
  cheaper than any lock-free MPSC you would write.
- **Nothing allocates after boot.** Every Python `dict`/`list`/dataclass
  becomes a fixed-capacity array or a pool with a free list. Where the Python
  copies an immutable value (patterns, phrases, patches, matrices), use a
  double-buffered pair plus an "active" index — the copy-on-write semantics
  are what make mid-note edits safe, so keep them, just bounded.

### 4.3 Timing: derive the tick from the audio clock

Do **not** use `IntervalTimer` for the sequencer. Derive ticks from the
audio block counter so MIDI and the internal instruments can never drift:

```
tick_period_samples = SR * 60 / (bpm * 96)
```

At 44.1 kHz, 120 BPM: 287.5 samples per tick ≈ 6.5 ms — more than two audio
blocks. At 300 BPM (`BPM_MAX`): 115 samples ≈ 2.6 ms — **less than one audio
block.** So the main loop must be able to run *more than one* `step()` per
block:

```cpp
while (samplesElapsed() >= nextTickSample) {
    engine.step();
    nextTickSample += tickPeriodSamples(bpm);   // recompute: tempo may have moved
}
```

Keep the accumulator in fixed point (Q32.32 or samples×256) so tempo changes
don't accumulate rounding error over a set.

Two derived requirements:

- **Sample-offset scheduling for internal notes.** A note fired in the main
  loop lands at the next audio block boundary — up to 2.9 ms of jitter.
  Carry the intended sample offset alongside the note and let the instrument
  layer start the voice at that offset within the block. External MIDI goes
  out immediately (UART is byte-serial; 3 bytes ≈ 0.96 ms at 31250 baud, and
  that is your real floor).
- **Thru is not tick-bound.** MidiRanger's `<5 ms` thru target is a
  *queue-drain* property on the Pi and must stay one here: an input event's
  thru chain (quantize → harmonize → FX → matrix fan-out) runs when the event
  is drained, not on a tick boundary. You should comfortably beat the Pi —
  budget **< 1.5 ms DIN-in → DIN-out** and measure it (§8).

`FakeClock` on the host test build just calls `step()` N times. Rule 9 holds:
tests drive the same code path playback does, never a simulation.

### 4.4 The release book, concretely

The Python is `dict[(endpoint, channel, note)] -> off_tick`, scanned every
tick. In C++:

```cpp
struct Booking { uint8_t ep, ch, note; uint32_t offTick; };
static Booking book[128];    // 896 bytes in DTCM
static uint8_t bookCount;
```

Linear scan every tick. At 300 BPM that is 480 scans/s × ≤128 entries — a
few tens of thousands of comparisons per second on a 600 MHz M7, i.e. free.
Do not get clever with a heap or a tick-bucket wheel until you have measured
a problem; the flat array is what makes the port auditable against the
Python, and auditability is the point.

You need all five operations, and every one of them has callers:

| Operation | Who calls it |
|-----------|--------------|
| `sendNote(ch, note, vel, lenTicks, ep)` | every producer, always |
| `releaseNote(ch, note, ep)` | thru, when the player lifts the key |
| `releaseChannel(ch, ep)` | part mute, clip switch, track reroute |
| `releaseDue(tick)` | the tick loop |
| `allNotesOff()` | stop, panic, scene recall, mode switch — book + CC 123 on every (ep, ch) ever used |

### 4.5 Determinism and the PRNG

Determinism is a *product feature* of GenRanger, SceneRanger and
GrooveRanger: the same project emits the same MIDI, byte for byte, forever.
The headline test builds two engines from one project and asserts identical
event streams over eight bars. Keep that test.

Two halves, and they port differently:

- **`seeds.mix()` is splitmix64** written out arithmetically (specifically
  *because* Python's `hash()` is salted per process). It ports to C++
  **bit-exactly** — copy the constants, use `uint64_t`, mask to 63 bits at
  the end. Free win.
- **The stream PRNG is Python's `random.Random` (MT19937)**, and its
  derivations (`random()` builds a 53-bit double from two 32-bit draws,
  `choices()` uses accumulate+bisect) are *not* reproducible without
  reimplementing CPython's `_randommodule.c`. Don't.

Recommendation: define the canonical micro-rangers stream PRNG as **PCG32 or
xoshiro128\*\***, seeded from `mix()`. You then get:

- per-implementation determinism (twin engines identical) — the must-have,
  and the property all the tests actually assert;
- no cross-implementation golden vectors — Pi and Teensy will make different
  (equally valid) choices from the same seed.

If you want cross-implementation goldens too — and it is genuinely the
cheapest way to prove a port of GenRanger's five generators is correct — I
can add a `--prng pcg32` switch on the Python side and a
`tools/emit_goldens.py` that dumps `(tick, status, d1, d2)` streams for a
fixed project. Say the word and it lands in patchbox-os-gen; it is maybe a
day's work and it converts "does my Markov walk sound right?" into a diff.

### 4.6 The `internal` endpoint — the seam that saves you months

This is the most important structural fact in the handoff.

Both audio apps address their sound engine as **a MIDI endpoint**, through a
wrapper called `SynthMidiBridge`. Events addressed to `internal` drive the
instrument; everything else passes through to the real backend untouched.
Because the release book releases notes *by sending note-offs*, internal
voices are released by exactly the same machinery that releases a rack full
of external gear. The engine never learns anything new when a destination
says `internal`.

And the encodings are already plain MIDI:

**GrooveRanger** — internal destination means **channel = pad index**:

| What | Wire |
|------|------|
| parameter locks (tune / filter / pan) | CC 16 / 74 / 10, emitted immediately *before* the hit, consumed by the next note-on on that channel |
| mixer level per pad | CC 7 |
| master bus | channel 15: CC 74 filter, 85 delay division, 91 reverb, 92 damping, 7 level |
| chokes, mutes | the release book, unchanged |

**SynthRanger** — **channel = part index**, CC 1 wheel, 74 cutoff, 16/17 XY
pad.

So your Teensy implementation of `IMidiIO::send()` for the `internal`
endpoint is a switch statement that calls into the audio graph the fork
already has: `Drumset`/sample voices for GrooveRanger, Dexed / MicroSynth /
wavetable for SynthRanger. **You port zero DSP.** You port the sequencer,
the pattern model and the parameter encodings, and the sound comes from
instruments you already trust and have already optimised.

Corollary for testing: because it is all plain MIDI, the *whole audio
feature set* is testable on the host with a capture backend — exactly as it
is on the Pi. `hanging_voices()` becomes a query on your voice allocator,
and the test that ties them together (`the voice ledger empties exactly when
the release book drains`) is the one to port first.

---

## 5. The panel: 320×240, two encoders, one finger

This is where the port is genuinely new work. **Do not port `gui/`.** Port
the model, throw away the pixels.

### 5.1 What survives

- **The screen/tab model.** Every app is 4–5 tabs; a tab is a screen; a
  screen registers hit targets and returns commands. Keep that exactly —
  it's what makes the panel testable ("every drawn control is a registered
  hit target" is a real test in every app and it should survive).
- **Transport chrome** — playing/recording/bpm/bar/beat/backend/message all
  come from the snapshot's base fields.
- **The command vocabulary.** Touching a control produces a command; the
  engine is the only thing that changes state.

### 5.2 What changes

**Interaction model: encoder-first, touch-assist.** A 44 px target on
1280×400 is 3.4% of the width; on 320×240 it is 14%, and resistive touch
adds parallax and needs calibration. So:

| Control | Role |
|---------|------|
| **ENC 1** turn | move focus (widget → widget within the screen) |
| **ENC 1** push | enter / back (drill into a group, or pop out) |
| **ENC 1** hold | tab switch mode — turn to change tab |
| **ENC 2** turn | change the focused value |
| **ENC 2** push | toggle / commit / trigger the focused control |
| **ENC 2** hold | shift — fine adjust (×0.1) while held |
| **Touch** | direct-select coarse targets only: pads, steps, clip cells, tabs. Never a fader, never a value. |

Every value on screen must be reachable by encoder alone. Assume the touch
panel is dirty, uncalibrated, or being used through a glove — because on
stage it will be.

**Layout.** Keep the transport/content/tabs split; it works at this size:

```
┌────────────────────────────────────┐  320 × 22   transport strip
├────────────────────────────────────┤
│                                    │  320 × 190  content
│                                    │
├────────────────────────────────────┤
│  PERF │ SEQ  │ KIT  │ SONG │ SET   │  320 × 28   5 tabs × 64 px
└────────────────────────────────────┘
```

Touch floor **36 px** for tabs and pads; encoder-only controls may be
smaller. A layout test (port `test_theme_layout.py`) should pin the floor so
a future screen can't quietly violate it.

**Grids must be re-designed, not scaled.** Two examples, and the reasoning
generalises:

| Pi | micro-rangers |
|----|---------------|
| SceneRanger 12 tracks × 8 scenes, all visible | **8 × 8** grid, 4×4 visible page (each cell 72×44), ENC 1 pages, scene column pinned. Or: track-strip view + scene list — decide by playing it. |
| GrooveRanger 12 pads × 16 steps matrix | **classic TR row**: one selected pad, 16 steps across (16 × 18 px = 288 px, fits with margins), pad selected by a 12-cell strip above. This is a better instrument at this size, not a compromise. |
| SynthRanger 2-octave touch keyboard | drop it. Use the DIN/USB input; add a 12-pad chromatic strip for auditioning. |
| MidiRanger 4×5 matrix | **3 in × 4 out** (§6.3) = 12 cells at 80×44. Genuinely more readable than the Pi version. |

**Rendering budget.** Full-frame 320×240×16 bit = 150 KB. Over SPI at
30 MHz that is ~40 ms — you cannot full-redraw. Two viable strategies:

1. **Dirty-rect, no framebuffer.** Widgets mark themselves dirty; only
   changed rects are pushed. Lowest RAM, most discipline required.
2. **Framebuffer in `DMAMEM` + async DMA update** (ILI9341_t3n supports
   this). 150 KB of your 512 KB OCRAM, but you draw freely and let DMA push
   only changed row bands.

Recommend measuring both in Phase 1 and picking on data. Target **≥25 fps
for the playhead/meter regions** and "no perceptible lag" on encoder turns —
the playhead is the thing that makes a sequencer feel alive, and it is the
one region that must never stutter.

**Do not render from the audio ISR, and do not let a redraw block a tick.**
If a redraw would overrun, drop the frame, never the tick.

---

## 6. Resources

### 6.1 A starting budget

| Region | Size | Put here |
|--------|------|----------|
| **ITCM** (RAM1) | ~128 KB | hot code: engine `step()`, release book, audio ISR paths |
| **DTCM** (RAM1) | ~384 KB | engine arena (active mode's state), release book, command ring, snapshot, stacks. Fastest, uncached — the sequencer lives here. |
| **OCRAM / `DMAMEM`** (RAM2) | 512 KB | `AudioMemory()` blocks, display framebuffer (150 KB if you take option 2), SD/SdFat buffers, USB host buffers |
| **PSRAM** (`EXTMEM`) | 16 MB (2× 8 MB, populated) | sample kits, phrase/clip pools, PhraseRanger's undo stacks, wavetables, project staging, MIDI recording buffers |
| **Flash** | 8 MB | firmware (expect 400–900 KB with all 7 modes) + factory content in `PROGMEM`: presets, chord/style tables, a small factory kit |
| **SD** | 16 GB | user projects, sample libraries, kits, logs, firmware update images |

**PSRAM is fast storage, not RAM.** It is cacheable but off-chip QSPI:
sequential streaming is fine, scattered small reads are not. Never run
per-sample DSP against a PSRAM pointer — DMA or block-copy into OCRAM first.
Sample playback should read ahead in blocks, not chase a per-sample pointer.

PhraseRanger is the app that will teach you this: 8 tracks × 16 undo levels
× a phrase each. That is exactly what PSRAM is for — a slab allocator with a
free list, sized at boot, never `malloc`.

### 6.2 What to measure in Phase 0 and report before designing anything else

- Linker `Program Size` (text/data/bss, ITCM/DTCM/OCRAM split) for a
  hello-world fork build.
- `AudioProcessorUsageMax()` and `AudioMemoryUsageMax()` with the fork's
  current instrument set resident and idle.
- Same, with N Dexed voices sounding — **the real SynthRanger voice ceiling
  is whatever this number says, not what the Pi README claims.** The Pi
  documents an honest floor (8 voices × 4 parts at 48 kHz) precisely so a
  spec sheet can't write a cheque the DSP won't cash. Do the same here with
  *your* measured number, and put it in the fork's README.
- PSRAM: PJRC's memory test (**per unit** — see §2), reported size (expect
  16 MB; anything else is a solder fault, not a config), and sequential vs
  random read throughput.
- SD sustained read with SdFat on a preallocated contiguous file.
- Full-frame and 64×64-rect SPI push times at your SPI clock.

That is a day of work and it determines the scope of Phases 6 and 7. Do it
before writing a line of GrooveRanger.

### 6.3 MIDI endpoints, remapped

The Pi rig has Pimidi's two TRS pairs, Pisound's DIN and USB. Yours has one
TRS in, one TRS out, USB device and USB host. Remap:

| rangerkit id | micro-rangers | Notes |
|---|---|---|
| `trs_a_in` / `trs_a_out` | **`din_in` / `din_out`** | the TRS jacks; A/B is a wiring concern, expose as `[midi] trs_type` only if switchable in software |
| `trs_b_in` / `trs_b_out` | **absent** | keep the ids reserved so Pi projects load; show greyed |
| `usb_in` / `usb_out` | **`usb_in` / `usb_out`** | `usbMIDI` — to a computer |
| — | **`uhost_in` / `uhost_out`** (new) | `USBHost_t36`, up to 4 devices merged, with a per-device filter — keeps the matrix screen small |
| `internal` | **`internal`** | §4.6 |

Result: **3 inputs × 4 outputs**. MidiRanger's matrix gets *more* readable at
320×240 than it was on the bar. Project files from the Pi should load with
`trs_b_*` routes dropped and a message on the SET screen — rule 4, degrade
don't die.

USB host caution: hot-plug, enumeration failures and class-compliant-only
support are all real. Endpoints must bind by *name* and rebind on hotplug —
this is the exact failure mode the Pi side documents at length (an image
built for one HAT, booted on a rig carrying another: everything enumerates,
nothing binds, and the panel looks perfect). Show bound/unbound state
explicitly on the SET screen.

### 6.4 Storage on SD

Replaces `/opt/<app>`, `/var/lib/<app>` and `/etc/<app>/config.toml`:

```
/RANGERS/
  config.ini                    display · midi · clock · encoders · pots · button map
  factory/                      shipped presets, kits, chordsets, styles
  midiranger/projects/*.mrp
  genranger/projects/*.grp
  phraseranger/projects/*.prp
  sceneranger/projects/*.srp
  grooveranger/projects/*.ggp
  grooveranger/kits/<name>/kit.json + *.wav
  synthranger/{projects,presets}/
  chordranger/{projects,chordsets,styles}/
  logs/
```

- **Project format: versioned binary**, not TOML — you have no TOML parser
  and shouldn't write one. Magic + `uint16` version + payload + CRC32.
  Refuse unknown majors with a message; migrate minors.
- **Atomic writes**: write `foo.tmp`, `fsync`, rename. A card yanked
  mid-save must never cost the previous save.
- **`config.ini`** is deployment state only (rule 10): panel, MIDI prefs,
  clock source, encoder acceleration, pot CC mappings, button map. Missing
  file → defaults. Malformed → refuse and say so; do not silently half-apply.
- **Never touch SD from the audio ISR or from inside `step()`.** Saves are a
  main-loop job, ideally on a "save requested" flag drained between ticks.

### 6.5 The button and the pots

There is no Pisound button and no ADC pots. Both abstractions survive
because both were already defined as *command sources*, not as hardware
(rule 7):

**Button vocabulary** (`play_stop`, `record_toggle`, `next_scene`/app-specific
3-click, `save_project`, `panic`) binds to:

- ENC 2 push / double-push / hold (the default),
- an optional footswitch on a GPIO — 1 click / 2 clicks / hold ~1 s /
  hold ~5 s, same gesture grammar as the Pi,
- MIDI CC learn.

Keep the Pi's safety net in spirit: a hold past ~7 s should always do
*something* recoverable (there, it shuts the Pi down cleanly; here, panic +
save is the right analogue).

**Pots** (`PotMove(index, value_0_1)`) — the Pi's default source is already
MIDI CC learn (CC 20/21, omni), which works on your hardware unchanged. Add
two optional analog inputs on `A0`/`A1` if the fork's board has them, and
encoder-as-pot in perform mode. `rangerkit/pots.py` ports nearly verbatim;
it was written hardware-agnostic precisely because the Pi rig had no pots
either.

---

## 7. Testing — the part that makes this survivable

The Pi suite's core is testable with no display, no audio and no MIDI
hardware, and that is why 30k lines of instrument logic can be refactored
without fear. Reproduce that on day one or the port will rot.

**Set up two build targets before you write feature code:**

1. **`native`** — compiles `rangercore/` + `modes/*/engine.cpp` + fakes
   (`FakeClock`, `CaptureMidiIO`, `FakeStorage`) with your host compiler and
   runs the test suite. No Arduino, no Teensy toolchain. This is where 90%
   of the port's bugs die.
2. **`teensy41`** — the firmware.

If a `modes/*/engine.cpp` won't compile in `native`, it has a platform
dependency it shouldn't have. That is the C++ spelling of the Pi's poisoned
import check, and it should fail the build, not a review.

**Port these assertions per mode** (they exist in the Python; the names map
almost 1:1 to `apps/<app>/tests/test_engine.py`):

| Test | Every mode |
|------|-----------|
| `assert not midi.hanging()` at the end of **every** engine test | required |
| stop / panic / mute / scene recall / reroute mid-note strand nothing | required |
| twin engines from one project emit identical streams over 8 bars | GenRanger, SceneRanger, GrooveRanger |
| project save → load → save is byte-identical | required |
| every drawn control is a registered hit target, at 320×240 | required |
| pressing every registered control produces a command the engine accepts | required |
| voice ledger empties exactly when the release book drains | GrooveRanger, SynthRanger |
| DIN-in → DIN-out latency under load | MidiRanger |

**On-device self-test.** Add a hidden SET-screen action that runs a
90-second soak: play, churn every producer, panic, and assert the book is
empty and `AudioMemoryUsageMax()` hasn't grown. Cheap insurance against
"it passes on the host and hangs a note on stage".

---

## 8. Phased plan

Each phase ends green and playable. Do not start the next until the gate
passes — this order front-loads every risk that could invalidate the
architecture.

| Phase | Deliverable | Gate |
|---|---|---|
| **0** | Measurements (§6.2) + `native`/`teensy41` build split + `rangercore` spine: events, PPQN-96 sample clock, release book, command ring, snapshot, `RangerEngine` | Host tests green. On device: emits MIDI clock, echoes DIN→DIN, 1-hour soak with the book empty at the end. **Report the §6.2 numbers before Phase 6/7 is scoped.** |
| **1** | Panel shell: display driver + dirty-rect/FB decision, encoders, touch calibration, tab/transport chrome, focus model, SD storage + `config.ini` | ≥25 fps on the playhead region; every control encoder-reachable; card pull mid-save loses nothing |
| **2** | **MidiRanger** — matrix (always-on service), 4 arps, quantizer, harmonizer, note FX, CC LFOs, 8 scenes | **< 1.5 ms** DIN-in → DIN-out; 4 arps from 2 inputs + thru on a third; scene recall mid-note strands nothing; 1-hour soak |
| **3** | **GenRanger** — 6 layers, 5 generators, Cruise, locks, seed slots, 32-entry timeline | Twin-engine determinism over 8 bars; Euclid property tests; mutate-storm leaves nothing hanging |
| **4** | **PhraseRanger** — 8 tracks, recorder, 16-deep undo, reverse/stretch/decay, slicer | PSRAM slab allocator proven; undo peels to empty releasing everything; free-length polyrhythm |
| **5** | **SceneRanger** — grid, launcher, follow actions, chain, slot recording | Launch-quantize boundaries exact; scene = state (absent tracks stop); grid holds the 36 px floor |
| **6** | **GrooveRanger** — sequencer, patterns, fills, song chain, kits → the fork's existing sample engine via `internal` | Locks/probability/conditions/ratchets exact; choke cuts; voice ledger drains with the book; measured pad-voice ceiling documented |
| **7** | **SynthRanger** — 4 parts, mod matrix, morph, presets → Dexed/MicroSynth/wavetable via `internal` | Measured voice ceiling documented in the README; morph endpoints exact; part mute releases voices |
| **8** | **ChordRanger** — chord pads, auto-accompaniment sections, bass engine | Section changes on the bar line; style content fits flash/SD budget |
| **9** | Cross-mode polish: mode manager state handoff, MidiRanger insert available to every mode, factory content, user manual | Mode switch is silent (no stuck notes, no click); full-suite soak |

Phases 2 and 3 are pure MIDI and need no new subsystems — they are where you
prove the spine is right, cheaply. Phase 4 is the first memory-pressure app.
Phase 5 is the first hard UI problem. 6 and 7 are the audio phases and their
scope is set by Phase 0's numbers, not by the Pi's feature list.

---

## 9. Explicitly not ported

Do not spend a day on any of these. They are Pi-platform artefacts, and
their *function* is either irrelevant or already covered above.

| Pi thing | Why not |
|----------|---------|
| `gui/` (pygame), SDL, kmsdrm | Model ports (§5), pixels don't |
| `core/dsp/` (numpy), `rangerkit/audio/` | Use the fork's audio graph via `internal` (§4.6) |
| systemd units, `Conflicts=`, `patchbox-app`, stage3/* | Mode manager (§4.1) |
| venv, pip, `requirements.lock` | No package manager |
| ALSA/JACK, `autobind` by ALSA client name | Teensy MIDI objects; keep name-based binding for USB host |
| TOML parsing | `.ini` + binary projects (§6.4) |
| `SCHED_FIFO`, RT priority, GIL tuning | No OS |
| The companion web UI (`:8787`) | Out of scope. If you ever want remote editing, USB MIDI SysEx is the cheap route. |
| 1280×400 / 800×480 / 480×800 layouts | One geometry (§5) |
| `button.sock`, `pots.sock` | GPIO/encoder/CC sources into the same command queue (§6.5) |

---

## 10. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| SynthRanger's 4 parts × 4 engines don't fit alongside resident Dexed | **High** | Phase 0 measurement sets the ceiling; ship a documented floor (the Pi did exactly this); consider parts-share-an-engine |
| Display redraw starves the tick loop | Medium | Drop frames, never ticks; dirty-rect; measure in Phase 1 with the gate above |
| PSRAM latency makes sample playback stutter | Medium | Block read-ahead into OCRAM; never per-sample PSRAM access; measure in Phase 0 |
| A hand-soldered PSRAM joint is marginal on one unit out of the batch | Medium | PJRC memory test per unit at build time (§2); firmware refuses to boot a 16 MB build on a board reporting 8 MB rather than silently halving the pool |
| 320×240 can't carry SceneRanger's grid usefully | Medium | Redesign, don't scale (§5.2); play it before committing |
| Fixed-capacity everything hits a ceiling mid-phase | Medium | Every pool declares its capacity in one header; overflow is a logged, visible message, never silent truncation and never a crash |
| USB host hotplug/enumeration flakiness | Medium | Name-based binding + explicit bound/unbound UI; degrade to DIN |
| Determinism quietly breaks (uninitialised state, ordering) | Medium | The twin-engine test in CI from Phase 3 onward |
| Port drifts from the Python and the two suites diverge | **High over time** | Pin the rangerkit revision you ported from in the fork README; when you change *behaviour*, open an issue on patchbox-os-gen so the reference can follow |

---

## 11. Open questions — I can't answer these for you

1. **Framebuffer or dirty-rect?** Costs 150 KB of OCRAM, buys a much simpler
   UI layer. Decide in Phase 1 on measured numbers.
2. **Does Dexed stay resident in all builds**, or does SynthRanger own the
   audio graph exclusively when active? Changes the RAM budget and the mode
   manager's teardown story.
3. **How many USB host devices** do you want to support concurrently? 4
   merged endpoints is my recommendation; more makes the matrix unreadable.
4. **Do you want cross-implementation golden vectors** against the Python
   (§4.5)? If yes, I'll add the PRNG switch and the emitter on this side.
5. **Is the TRS A/B switch software-controllable** on your board, or a
   jumper? Determines whether it's a config field or a manual note.
6. **Which board, exactly?** This document is written against the **Teensy
   4.1** memory map (1 MB RAM / 8 MB flash / 16 MB `EXTMEM`). If the boards
   are something else — a variant, a clone, or a revision I don't have specs
   for — send me the part and I'll re-derive §6.1, because every budget in
   this document is keyed to that map. The PSRAM half is settled either way:
   2× 8 MB populated, 16 MB contiguous.

---

## 12. Reference material

In `patchbox-os-gen`:

```
apps/rangerkit/docs/CONVENTIONS.md        the family rulebook — read first
apps/rangerkit/enginebase.py              the spine you are porting
apps/rangerkit/{events,clock,routing}.py  time, endpoints
apps/rangerkit/audio/bridge.py            the `internal` seam (§4.6)
apps/<app>/docs/ARCHITECTURE.md           per-app invariants and rationale
apps/<app>/core/                          the specification
apps/<app>/tests/test_engine.py           the assertions to port
RANGER-SUITE-PLAN.md                      how the suite was built, and why
HANDOFF.md                                the Pi-side handoff (context only)
```

To run the reference implementation on a laptop and *play* an app before
porting it — strongly recommended, especially for GenRanger and
SceneRanger, whose feel is hard to read off the source:

```bash
cd apps/<app>
pip install pygame            # that's the whole dependency for MIDI-only apps
python main.py --size 800x480
python -m pytest -q           # headless: SDL dummy + capture MIDI + fake clock
```

MIDI degrades to a null backend with nothing installed, so it runs on any
machine. Install `mido` + `python-rtmidi` to hear it through real ports.

---

*Questions, or a decision from §11 that changes the plan — open an issue on
`johnnyclem/patchbox-os-gen` and reference this file.*
