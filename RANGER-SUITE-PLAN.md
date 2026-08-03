# Ranger Suite — build plan for the six new RK-00pi apps

**Status:** Phase 0 (rangerkit + `patchbox-app` + stage3/14 + `ranger-apps.yml`
CI + config toggles) landed. Phases 1–6 (the six apps) follow this document,
one app per phase, in the listed order.

## Context

The dev site (https://xenon-hazel-finch-comet.grok.me, captured in the uploaded PDF)
proposes a **seven-app "Ranger Suite"** for the RK-00pi hardware (Pi 5 16GB, 1280×400
touch bar, 192 kHz DAC, 2×2 TRS + DIN + USB MIDI, 2 pots, 1 button):

| # | App | One-liner | Status |
|---|-----|-----------|--------|
| 01 | ChordRanger | Chord pads + QY-style auto-accompaniment | **Shipped** (`apps/chordranger`, stage3/13) |
| 02 | GrooveRanger | Sample groovebox + step sequencer + FX | To build |
| 03 | SynthRanger | Multi-engine poly softsynth (VA/FM/wavetable) | To build |
| 04 | GenRanger | Generative sequencer (Euclid/Markov/CA, Cruise) | To build |
| 05 | SceneRanger | Ableton-style clip/scene launcher | To build |
| 06 | MidiRanger | MIDI routing matrix + arps + note FX | To build |
| 07 | PhraseRanger | MIDI phrase looper/overdubber/slicer | To build |

ChordRanger defines the pattern to follow: stdlib-only `core/` (no pygame at import),
pygame `gui/` under SDL kmsdrm, immutable-snapshot RT engine with a note release book
(`assert not midi.hanging()` in every engine test), adaptive 1280×400 / 800×480 /
480×800 layouts, headless pytest (SDL dummy + CaptureMidiIO + FakeClock), a pi-gen
stage installing to `/opt/<app>` with venv + systemd unit + Pisound button bridge, and
a path-filtered CI workflow.

## Review of the proposals (feasibility)

The six PRDs are consistent with ChordRanger's conventions (same screen/tab model,
hardware mapping, out-of-scope discipline). Four things need engineering judgment:

1. **"192 kHz" audio (Groove/Synth).** Python cannot synthesize 8–16 voices at 192 kHz
   on a Pi 5. Ship an honest constraint: **internal render 48 kHz float32, block 256
   frames (~5.3 ms)**; 192 kHz remains true of the Pisound DAC path. SynthRanger ships
   an 8-voice × 4-part floor (PRD's 16/8 is a documented stretch goal behind a future
   C extension).
2. **Pots don't exist in the repo** (no ADC on the BOM — Pisound/Pimidi have none).
   Needs a new hardware-agnostic abstraction: MIDI CC learn now, socket bridge later.
3. **Mutual exclusion at N=8.** Pairwise `Conflicts=rk00pi.service` and the two-app
   `patchbox-chordranger` switcher don't scale; needs a generated Conflicts list and
   one `patchbox-app` switcher.
4. **Shared infra vs. "share no code" convention.** The PRDs mandate shared
   theory/geometry/button/snapshot modules. Resolve with a shared package for the six
   new apps, leaving shipped ChordRanger untouched (optional convergence at the end).

Latency targets (<5 ms MIDI thru, <10 ms note) are achievable with the existing ALSA
writer-thread pattern.

## Design decisions

### a) Shared library: `apps/rangerkit/`, vendored per app
Plain Python package, no pyproject (repo has no packaging infra). Dev/CI: apps put
both their root and `apps/` on `sys.path` so `import rangerkit` resolves in-tree.
Device: the install helper rsyncs `apps/rangerkit/` → `/opt/<app>/rangerkit/`, so each
app carries a frozen copy — deployment isolation preserved (one app can roll back
without moving ground under the others). ChordRanger is **not** migrated now; its
modules are the donor source (theory, chords, events, clock, midi_io, button,
gui/theme, gui/widgets, engine skeleton). Update ARCHITECTURE.md §10 wording.

Contents (~4.5k lines, mostly proven code moving house):
`theory.py`, `chords.py`, `events.py` (PPQN=96), `clock.py` (Real/Fake/External),
`midi_io.py` (protocol + Null/Capture/Mido + writer thread), **new** `routing.py`
(named endpoints TRS_A/TRS_B/DIN/USB/INTERNAL, autobind preference tables,
RoutingMatrix), **new** `enginebase.py` (RangerEngine: bounded command deque,
snapshot publish, release book, tick thread + SCHED_FIFO, panic, clock in/out),
`button.py` (parameterized), **new** `pots.py` (see g), `configbase.py` (shared
config.toml sections), **new** `euclid.py`, `gui/{theme,widgets,shell}.py` (shell =
transport/tab chrome extracted from app.py), `testkit.py` (GEOMETRIES, hit-target
helpers, re-exports CaptureMidiIO/FakeClock), `audio/` (Phase 4),
`ci/check_core_imports.py`, `deploy/{install-ranger-app.sh, ranger.service.template,
kiosk-units.txt}`, `tests/`, `docs/CONVENTIONS.md`.

### b) Mutual exclusion: generated `Conflicts=` + one `patchbox-app` CLI
- Unit template has `Conflicts=@KIOSK_CONFLICTS@`; installer fills it with all other
  kiosk units from `kiosk-units.txt` (rk00pi, chordranger + the six). systemd
  Conflicts is bidirectional, so rk00pi/chordranger units never need editing. App #9
  = one line in one file.
- New `patchbox-app` CLI (stage3/14): `status` (table of installed kiosk units, button
  map owner), `enable <app>` (stop/disable all others, enable app, point
  `/etc/pisound.conf` button map at `<app>_click.sh`/`<app>_hold.sh`), `disable`
  (restore rk00pi + base map). One backup slot: first ranger takeover copies
  `/etc/pisound.conf` → `.ranger-base.bak`; app→app switches never touch it.
  `patchbox-chordranger` stays untouched (superseded, noted in help).
- Build toggle: single `RANGER_BOOT_APP="${RANGER_BOOT_APP:-rk00pi}"` in `config`
  names the boot unit (replaces six pairwise `ENABLE_*_SERVICE` flags;
  `ENABLE_CHORDRANGER_SERVICE=1` kept as an alias — the only stage-13 edit).

### c) Audio: sounddevice (PortAudio) callback, 48 kHz numpy block DSP, null-degradable
`rangerkit/audio/`: `[audio] backend = "auto"` → JACK if a server is running (jackd2
ships via stage3/03) → ALSA hw → **NullAudio** (app boots, SET screen says "audio:
null" — same philosophy as NullMidiIO). pygame.mixer rejected (no synthesis callback,
~40 ms latency). Tick thread posts sample-timestamped events to a preallocated inbox;
the PortAudio callback renders numpy blocks. GrooveRanger: kits resampled to 48 kHz
at load, 32 sample voices + FX bus (SVF filter, delay, Freeverb-ish reverb, sidechain
compressor) — comfortably one Pi 5 core. SynthRanger: mip-mapped wavetable lookup for
everything (VA/wavetable/FM via vectorized phase accumulation, feedback ops in
16-sample sub-chunks); 8 voices × 2 osc, 4 parts floor. Voice invariant mirrors MIDI:
`assert not synth.hanging_voices()` via offline `audio/render.py` (deterministic, no
device — what CI runs). Deps for those two apps only: numpy, sounddevice, soundfile
(+ `libportaudio2 libsndfile1` in stage 00-packages); CI deliberately omits
sounddevice to exercise the null path.

### d) Stages: thin per-app stages 15–20 + stage 14 for shared tooling
- `stage3/14-install-rangerkit/` — installs `patchbox-app` only (rangerkit is vendored
  per app, not installed standalone).
- `stage3/15-install-midiranger` … `20-install-synthranger` (landing order: midi, gen,
  phrase, scene, groove, synth). Each `01-run.sh` is ~25 lines: gate on
  `ENABLE_<APP>`, source `apps/rangerkit/deploy/install-ranger-app.sh`, call
  `install_ranger_app <app> <width> <height>`.
- The helper holds the ~300 lines once (byte-for-byte the stage-13 logic,
  parameterized): geometry resolution (explicit → HyperPixel → HDMI), rsync app +
  rangerkit to `/opt/<app>`, `/var/lib/<app>` seeding from `deploy/datadirs.txt`,
  config.toml sed, unit from template, button wrappers, on_chroot (useradd + groups
  audio/video/render/input, venv, lock-with-floor-fallback pip, import smoke test,
  enable iff `RANGER_BOOT_APP=<app>`).
- `config`: `ENABLE_<APP>=0` initially (flip to 1 in each app's ship PR — six qemu
  venv builds and ~100 MB/app argue against premature default-on), `<APP>_WIDTH/HEIGHT`
  empty → derived, plus `RANGER_BOOT_APP`.

### e) CI: one matrix workflow `.github/workflows/ranger-apps.yml`
Matrix `app: [rangerkit, midiranger, …] × python: [3.11, 3.12]`, path-filtered to
`apps/**` + `stage3/*-install-*/**` + itself. Steps mirror chordranger.yml: install
only `pygame pytest pyflakes numpy` (mido/rtmidi/sounddevice absent → degradation
paths exercised); poisoned-import check generalized to **glob discovery** (poisons
pygame *and* sounddevice) via `rangerkit/ci/check_core_imports.py`; pyflakes; pytest;
bench render at all three geometries with artifact upload. One shellcheck job covers
all stage scripts + `patchbox-app` + the install helper + ordinal-uniqueness check.
`chordranger.yml` untouched.

### f) Pots: `rangerkit/pots.py` — MIDI CC learn default, socket bridge for future HW
`Pots` service emits `PotCommand(index, value_0_1)` into the engine command queue
(slew-limited, deduped). `[pots] source = "midi_cc" | "socket" | "none"`:
- **midi_cc** (default): CC 20/21 omni by default; LEARN control on every SET screen
  captures the next CC and writes config back.
- **socket**: `/run/<app>/pots.sock`, line protocol `POT <i> <raw>` — same shape as
  button.sock; a future ADC daemon can drive it.
- **none**: pot widgets greyed.
`[pots.map]` mirrors `[button.map]` (e.g. `pot_a = "master_filter"`). `FakePots` in
testkit; every app has a pot-sweep test ending `assert not midi.hanging()`.

## Per-app modules (all mirror chordranger naming)

Every app: `main.py` (same CLI flags), `requirements.txt`+`.lock`, `README.md`,
`bench/render_panel.py`, `tests/conftest.py`, `deploy/{config.toml, <app>.service,
datadirs.txt, pisound/<app>-btn + _click.sh + _hold.sh}`, `docs/ARCHITECTURE.md`.
`core/` imports rangerkit + stdlib (+numpy where noted) only.

- **midiranger** `core/`: matrix, arp (≥4 instances), quantizer, harmonizer, notefx
  (delay/humanize/velocity curves/randomizer), cclfo, scene (+morph), commands,
  engine, config, project, version. Screens: perform, matrix, fx, arp, settings.
- **genranger** `core/`: layers, markov (order-N theory-aware), cellular, probgrid,
  randomgen, cruise, mutate (latch/lock regions), seeds (one seeded `random.Random`
  per layer — determinism is a test), timeline, macros, drones (Phase 4), + the usual
  five. Screens: perform, map, layers, seeds, settings.
- **phraseranger** `core/`: phrase, track (8, independent/locked lengths), recorder,
  history (multi-level undo as immutable snapshots), stretch (+reverse), humanize,
  slicer (→ pads/chromatic + velocity layers), scene, cruise, preview (Phase 4), +
  usual. Screens: perform, slice, routing, library, settings.
- **sceneranger** `core/`: clip (notes/CC/program + optional sample ref), grid, scene,
  launcher (quantize/follow/probability through the release book), recorder, follow,
  transposer, arrange, + usual. Screens: perform (the grid), routing, arrange,
  library/set. Grid layout test: 16×8 keeps ≥44 px targets on 1280×400, pages on
  480×800.
- **grooveranger** `core/`: kit (velocity/choke layers, per-pad tune/filter/amp/pan),
  pad, sampler (32 voices over rangerkit.audio), steps (prob/ratchet/conditional/
  micro-timing/p-locks), sequencer (fills/variations/mute groups, euclid), phrasechain
  (song mode), fxbus, mixer, + usual; `data/kits/` (small CC0 WAVs, size-budgeted).
  Screens: perform, seq, kit, song, settings.
- **synthranger** `core/`: voices (allocator + `hanging_voices()`), parts, patch,
  modmatrix, envelope, lfo, morph, preset, fxchain, `dsp/` (numpy, headless-importable:
  tables, va, fm, wavetable, pd, filters, effects), + usual. Screens: perform (touch
  XY mod source), edit, browser, mix, settings.

## Phased PR sequence (each lands green)

| Phase | Deliverable | Notes / "done" |
|---|---|---|
| 0 (2 PRs) | `apps/rangerkit` + tests + `ranger-apps.yml`; then stage3/14 + `patchbox-app` + install helper + config toggles | CI green 3.11/3.12; chordranger.yml untouched and green; all-flags-0 docker build unchanged |
| 1 (3 PRs) | **MidiRanger** — core; gui; deploy+stage3/15 | Riskiest shared code (routing, ExternalClock, <5 ms, release-book stress) proven first |
| 2 (2–3 PRs) | **GenRanger** — stage3/16 | Determinism tests (same seed → identical stream); euclid property tests |
| 3 (3+3 PRs) | **PhraseRanger** (stage3/17) then **SceneRanger** (stage3/18) | Undo-depth / record-idempotence; launch-quantize boundaries; grid density layout |
| 4 (2 PRs) | `rangerkit/audio` + wire GenRanger drones / PhraseRanger preview | Offline render + null-degradation green in CI with no audio device |
| 5 (3–4 PRs) | **GrooveRanger** — stage3/19 | Sequencer core is pure-MIDI testable before sampler lands |
| 6 (4 PRs) | **SynthRanger** — stage3/20 | CI perf canary: 8 voices × 1 s renders > 0.5× realtime; README documents 48 kHz floor |
| 7 (opt.) | ChordRanger → rangerkit re-export shims; `patchbox-chordranger` delegates | Only after all six ship, behind unchanged tests |

Per-app "done": pytest/pyflakes/poisoned-import green on both Pythons; bench PNGs at
all three geometries in CI artifacts; `python main.py --headless` boots and degrades
to null MIDI/audio; stage shellcheck green; ordinal unique.

## Verification

Per app (dev box / CI):
```
cd apps/<app>
python -m pyflakes .
python ../rangerkit/ci/check_core_imports.py .
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m pytest -q
SDL_VIDEODRIVER=dummy python bench/render_panel.py /tmp/panel --size 1280x400  # + 800x480, 480x800
python main.py --headless --config deploy/config.toml   # boots, ^C clean
```
Repo-level: `bash -n` all stage scripts + patchbox-app + helper; ordinal dupe check;
grep that every rendered unit's `Conflicts=` names all 7 other kiosk units.
Image-level (per app ship): `ENABLE_<APP>=1 RANGER_BOOT_APP=<app> ./build-docker.sh`;
on device: `patchbox-app status`; start another kiosk unit while `<app>` runs →
systemd stops `<app>` (Conflicts proven live); button sock PING→PONG; `amidi -l` /
`aplay -l`; Groove/Synth journal shows chosen audio backend; `patchbox-app disable`
restores RK-00pi + base button map.

## Critical files

- `apps/chordranger/core/{engine,midi_io,theory,chords,clock,button}.py`,
  `gui/{theme,widgets,app}.py` — donor source for rangerkit
- `stage3/13-install-chordranger/01-run.sh` — template for
  `apps/rangerkit/deploy/install-ranger-app.sh`
- `stage3/13-install-chordranger/files/patchbox-chordranger` — template for
  `stage3/14-install-rangerkit/files/patchbox-app`
- `.github/workflows/chordranger.yml` — template for `.github/workflows/ranger-apps.yml`
- top-level `config` — new toggles (`RANGER_BOOT_APP`, six `ENABLE_<APP>`)
