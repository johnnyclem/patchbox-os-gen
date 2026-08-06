# Ranger family conventions

What every app in the suite (MidiRanger, GenRanger, PhraseRanger,
SceneRanger, GrooveRanger, SynthRanger) inherits, and the rules that keep the
family coherent. ChordRanger predates rangerkit and remains self-contained;
it shares these conventions without sharing this code.

## The shape of an app

```
apps/<app>/
  main.py               --fullscreen --size WxH --headless --project --config
  requirements.txt      floors        requirements.lock   pins
  core/                 stdlib (+numpy for the audio apps) — NO pygame at import
  gui/                  pygame; screens/ one module per tab
  data/                 factory content
  deploy/               config.toml · datadirs.txt · pisound/<app>-btn + wrappers
  tests/                headless pytest (SDL dummy, CaptureMidiIO, FakeClock)
  bench/render_panel.py renders every screen to PNG, --size for all geometries
  docs/ARCHITECTURE.md
```

`main.py` and `tests/conftest.py` put the app root *and* its parent (`apps/`)
on `sys.path`, so `import core` and `import rangerkit` resolve identically in
the repo, under pytest, and on the device (where the install stage vendors
`rangerkit/` into `/opt/<app>/`).

## The rules

1. **The engine owns every note it has sent.** Note-ons leave only through
   `RangerEngine.send_note`, which books the off-tick. Every engine test ends
   with `assert not midi.hanging()`. The audio apps extend the invariant to
   voices: `assert not synth.hanging_voices()`.
2. **Commands in, snapshots out.** The GUI never touches engine state; the
   engine publishes one immutable snapshot per tick. The engine must run —
   and be fully testable — with no display, no audio and no MIDI hardware.
3. **Nothing core-side imports pygame or an audio backend at import time.**
   CI poisons `pygame`/`sounddevice`/`soundfile` and imports every core
   module by glob (`rangerkit/ci/check_core_imports.py`).
4. **Degrade, don't die.** Missing mido → null MIDI. Missing sounddevice or
   no device → null audio. Missing button socket → on-screen equivalents.
   The SET screen says what is degraded; the panel never stays dark.
5. **One panel, one app.** Every kiosk unit's `Conflicts=` names all its
   siblings (rendered from `deploy/kiosk-units.txt`); `patchbox-app enable`
   swaps them at runtime; `RANGER_BOOT_APP` picks the boot app at image
   build. Adding kiosk app #9 is one line in `kiosk-units.txt`.
6. **Three geometries, ≥44 px targets.** `rangerkit.gui.theme.Layout`
   resolves 1280×400 (side rails), 800×480 and 480×800 (stacked). GUI tests
   run all three (`rangerkit.testkit.GEOMETRIES`) and assert every drawn
   control is a registered hit target.
7. **Finger → mouse in every GUI.** Capacitive USB-HID panels emit
   `FINGER*` only; the kiosk unit pins `SDL_TOUCH_MOUSE_EVENTS=0`. Every
   App owns a `rangerkit.gui.touch.TouchTranslator` (configured *before*
   `display.init`) and runs every event through it. Without this the panel
   paints perfectly and every tap — including RangerDeck tile launches —
   is silently dropped.
8. **Hardware arrives as commands.** The button (`/run/<app>/button.sock`)
   and the pots (MIDI CC learn, or `/run/<app>/pots.sock`, see
   `rangerkit.pots`) both end as commands in the same engine queue as touch.
9. **Audio honesty.** Internal render is 48 kHz float32, block 256 frames.
   "192 kHz" is the DAC path, not the synthesis rate, and READMEs say so.
10. **Timing.** PPQN 96; absolute-deadline `RealClock`; `FakeClock` in tests
    drives the *same* `step()` playback uses — there is no simulation path.
    MIDI clock in via `ExternalClock` (24 PPQ), out at `PPQN // 24`.
11. **Config is deployment state only.** Shared sections come from
    `rangerkit.configbase`; app tables live under the app's own name and are
    read from `RangerConfig.extra`. Missing file → defaults; malformed →
    raise; unknown keys → dropped.

## Versioning the vendored kit

Each `/opt/<app>/rangerkit` is a frozen copy taken at image build. Apps must
not depend on rangerkit behavior newer than the copy they ship — the repo has
one source of truth (`apps/rangerkit`) and CI runs every app against it, so
drift is caught before an image is cut.
