# Handoff — Patchbox OS gen (Pi 5 + Pimidi + ElecLab HDMI + RK-00pi)

**Date:** 2026-08-04  
**Branch:** `patchbox-2024-01`  
**Repo:** `/Users/johnnyclem/Desktop/Repos/patchbox-os-gen`

**Focus (2026-08-04):** Profile A only — ElecLab 1280×400 + multi/hot-swap MIDI
hub + companion routing UI. HyperPixel 4 glass is cracked/parked; do not spend
bring-up time on Profile B unless someone rebuilds that hardware path.

**On-device soak:** [`SOAK-PROFILE-A.md`](SOAK-PROFILE-A.md) · on image as
`~/SOAK-PROFILE-A.md` and `sudo patchbox-soak`.

---

## Current product stack

### Profile A — HDMI ultrawide (default `config`) — **active product**

```text
Raspberry Pi 5
  ├── Blokas Pimidi (sel=0) — 2×2 TRS MIDI  (or Pisound / USB-only)
  ├── ElecLab 7.4″ HDMI 1280×400 + USB capacitive touch
  └── RK-00pi kiosk
        · hub binds by ALSA name (hotplug)
        · autohub at every start (USB devices included)
        · companion :8787 routing matrix (token auth, LAN)
        · soft tape
```

### Profile B — HyperPixel 4.0" DPI (`config.hyperpixel4-pimidi` / `.example`) — **parked**

**Build command (required):**

```bash
./build-docker.sh -c config.hyperpixel4-pimidi
# bare path also works:  ./build-docker.sh config.hyperpixel4-pimidi
```

Plain `./build-docker.sh` is **Profile A (HDMI)** — stage 12 logs
`ENABLE_HYPERPIXEL4!=1 — skipping HyperPixel 4 setup` and the DPI glass stays
black (backlight may flash once). The 2026-08-04 deploy image was this case.

Keep `config.local` for WiFi / machine overrides only — do **not** put
`ENABLE_HDMI_ULTRAWIDE=1` + `RK00PI_WIDTH=1280` there if you also want HyperPixel
builds; those leftovers used to re-assert Profile A.

**Black panel / backlight-only on an already-flashed SD:** convert without
rebuild (SD in Mac):

```bash
./scripts/fix-hyperpixel4-bootfs.sh /Volumes/bootfs
# default --rotate left (270) for landscape 800×480
```

On a booted Pi (SSH): `sudo patchbox-fix-hyperpixel4 && sudo reboot`.  
Do **not** stack `dtoverlay=pimidi` with HyperPixel — DPI needs the header.

**Portrait FB / landscape app (sideways UI):** early bring-up used
`HYPERPIXEL_ROTATE=none`, so DRM often listed **480×800** while the kiosk was
baked at **800×480**. Product default is now `HYPERPIXEL_ROTATE=left`
(`dtoverlay=…,rotate=270`). On a unit that already paints:

```bash
sudo patchbox-fix-hyperpixel4 --rotate 270
sudo reboot
# then: patchbox-hyperpixel-status  → DPI modes should include 800x480
```

If `rotate=270` blacks the panel, fall back to `--rotate none`, then try
`--rotate 90`. Touch calibration is rewritten with the same helper.

```text
Raspberry Pi 5
  ├── Pimoroni HyperPixel 4.0" rectangular (owns 40-pin)
  │     • 800×480 @ 60 FPS DPI (dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=270)
  │     • Goodix capacitive touch (matrix matches left rotation)
  ├── USB MIDI (recommended) — Pimidi DT overlay is NOT loaded
  └── RK-00pi 800×480 (stacked chrome — aspect < 2:1)
```

**GPIO:** HyperPixel uses ~28 pins — no room for Pimidi/Pisound DT on the same
header. Stage 12 strips `dtoverlay=pimidi` / `dtparam=i2c_arm`. For TRS MIDI use
Profile A (HDMI + Pimidi) or USB MIDI.

**Parked:** Pisound (audio + The Button).

No GPIO display. Pisound owns the header for audio/MIDI. Display does not compete for pins.

**App source:** git submodule `RK-00pi` → `git@github.com:johnnyclem/RK-00pi.git`  
Baked into the image by `stage3/10-install-rk00pi` as `/opt/rk00pi`.

**Submodule tip (2026-08-04):** `c9dfa21` — midi/audio unified setup + hub fit
(`core/hub_fit.py`) + companion remote routing UI (raspimidihub parity 0–3).

---

## Build defaults (`config`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_RK00PI` | **1** | Install main app from submodule |
| `ENABLE_RK00PI_SERVICE` | **1** | `systemctl enable rk00pi` |
| `ENABLE_RK00PI_BUTTON` | **0** | Wire pisound-btn → RK-00pi socket (off when Pimidi is primary) |
| `ENABLE_RK00PI_AUTOHUB` | **1** | Re-fit the hub to the live ALSA graph at every start |
| `ENABLE_RK00PI_COMPANION` | **1** | LAN companion routing UI + backup (token; no TLS) |
| `RK00PI_COMPANION_BIND` | `0.0.0.0` | Companion listen address |
| `RK00PI_COMPANION_PORT` | `8787` | Companion HTTP port |
| `RK00PI_COMPANION_ADVERTISE` | **1** | Avahi `_http._tcp` name |
| `RK00PI_HUB_PRESET` | follows `ENABLE_PIMIDI` | `pimidi-2x2` on a Pimidi rig, else `rk008` (Pisound DIN) |
| `RK00PI_WIDTH` / `HEIGHT` | (HDMI dims) | `/etc/rk00pi/config.toml` panel size |
| `ENABLE_HDMI_ULTRAWIDE` | **1** | Custom HDMI mode **1280×400@60** |
| `HDMI_WIDTH` / `HEIGHT` / `REFRESH` | 1280 / 400 / 60 | Override if panel differs |
| `ENABLE_HYPERPIXEL4` | **0** | Parked — DPI profile |
| `ENABLE_WAVESHARE_DPI` | **0** | 3.5″ GPIO DPI (parked) |
| `ENABLE_INKY` / `ENABLE_INKY_UI` | **0** | E-paper (parked) |
| `ENABLE_RASPIAUDIO` | **0** | I2S HAT (parked) |
| `PISOUND_GIT_REF` | `patchbox` | Pisound tree checkout |
| `RASPBIAN_MIRROR` | Berkeley OCF | Avoid flaky primary Raspbian |

Stages always install Pisound packages (`stage3/02-install-pisound`) — that is the audio story.  
Boot default remains **multi-user.target** (console + `rk00pi`) so kmsdrm can
own the panel. LightDM must stay **disabled** — `graphical.target` starts X and
kmsdrm fails with `pygame.error: kmsdrm not available`.

---

## Stages (product path)

| Stage | Default | Role |
|-------|---------|------|
| `02-install-pisound` | on | Pisound + IRQ/sysctl audio tuning |
| `03-install-jack` | on | JACK2 + realtime limits |
| `06-install-inky` | off | E-paper UI (legacy) |
| `07-install-raspiaudio` | off | I2S audio HAT (legacy) |
| `08-install-waveshare-dpi` | off | GPIO DPI 640×480 (legacy) |
| `09-hdmi-ultrawide` | **on** | HDMI CVT + cmdline + touch + docs |
| `10-install-rk00pi` | **on** | **Main app** + The Button bridge from `RK-00pi` |
| `13-install-chordranger` | **on** (unit off) | **ChordRanger** from `apps/chordranger` — installed, not enabled |

### RK-00pi layout on the image

| Path | Purpose |
|------|---------|
| `/opt/rk00pi/` | App + venv |
| `/var/lib/rk00pi/` | Writable projects / presets / maps / autosave |
| `/etc/rk00pi/config.toml` | Panel size + engine/MIDI/gates + `[button.map]` |
| `/run/rk00pi/button.sock` | The Button control socket (tmpfs, per boot) |
| `/usr/local/bin/rk00pi-btn` | stdlib client called by pisound-btn scripts |
| `/usr/local/sbin/patchbox-rk00pi-autohub` | Fits the hub to this unit's MIDI hardware (`ExecStartPre`) |
| `/etc/rk00pi/autohub.disabled` | Touch it to stop autohub touching the hub |
| `/var/lib/rk00pi/companion-token` | Companion auth token (generated first boot) |
| `/etc/avahi/services/rk00pi-companion.service` | mDNS for `http://hostname.local:8787` |
| `/usr/local/bin/patchbox-soak` | Profile A soak gates (display + touch + MIDI + companion) |
| `~/SOAK-PROFILE-A.md` | Full soak checklist + sign-off table |
| `/etc/pisound.conf` | PiSound gesture → `rk00pi_{click,hold}.sh` (`.rk00pi.bak` backup) |
| `rk00pi.service` | Kiosk unit (`SDL_VIDEODRIVER=kmsdrm`, `RuntimeDirectory=rk00pi`) |

### MIDI binds by name, so the hub has to match the HAT

A hub endpoint does not hold an ALSA client number — it holds a *name*, and
the port scanner binds whatever currently matches it. That is what makes
hotplug work, and it is also the whole failure mode: an image built for one
HAT boots on a rig carrying another, every DIN endpoint asks for a client
that is not there, and nothing binds. The devices still enumerate, so the
DIAGNOSTICS screen lists them all and the endpoint circles stay hollow — no
note, no clock, either direction.

Three things now guard against it:

* `RK00PI_HUB_PRESET` follows `ENABLE_PIMIDI` instead of always baking
  `pimidi-2x2`
* `rk00pi.service` runs `patchbox-rk00pi-autohub --apply` before the app
  starts: it reads `/proc/asound/seq/clients`, builds the hub that graph
  implies (Pimidi's two TRS pairs, or the Pisound's DIN, plus any USB device
  — which the baked presets never covered) and writes it into the starter
  project. It only rewrites when the generated hub binds **strictly more**
  endpoints than the one already there, so a hub built by hand on the unit
  survives. The previous one is kept at `<project>.autohub.bak` and the
  generated one lands in `/var/lib/rk00pi/presets/auto.rkhub`
* `patchbox-rk00pi-status` prints which endpoints resolve and which do not

On the unit, read-only: `patchbox-rk00pi-autohub`. To fix by hand:
`sudo patchbox-rk00pi-autohub --apply && sudo systemctl restart rk00pi`, or
on the panel **I/O → PORTS → AUTO FIT** (also DIN device + per-port rows).

App-side (RK-00pi): the Hub tab and Set → I/O are merged into one **I/O** tab
(PORTS · ROUTE · AUDIO). Port matching no longer collapses a 2×2 PiMIDI onto
one jack when match strings are client-only; `retarget_din` pins `pimidi-a`/`b`
from endpoint id suffixes when needed.

### The Button — default gestures

| Gesture | Action | Meaning |
|---------|--------|---------|
| 1 click | `play_stop` | Start / stop transport |
| 2 clicks | `record_toggle` | Record enable / punch |
| hold ~1 s | `save_project` | Save session |
| hold ~5 s | `panic` | All notes off |
| other gestures | `nothing` | Safe defaults; rebind in `[button.map]` |

Safety net: if the instrument is not listening and the user holds past ~7 s, `rk00pi_hold.sh` still falls through to `shutdown` so a crashed unit is never stranded.

---

## ChordRanger — second app (2026-08-02)

`apps/chordranger` in **this** repo (not a submodule). A chord-first backing
band: twelve chord pads (Chordcat), a six-section auto-accompaniment with
fills on the bar line (Yamaha QY), and an independent bass engine with its own
voicing dial (Orchid ORC-1). Panel is the same 1280×400 bar, same light
industrial look, same rails.

Docs: [`apps/chordranger/README.md`](apps/chordranger/README.md) ·
[`docs/USER.md`](apps/chordranger/docs/USER.md) ·
[`docs/ARCHITECTURE.md`](apps/chordranger/docs/ARCHITECTURE.md) ·
[`docs/deploy.md`](apps/chordranger/docs/deploy.md)

### One panel, two apps

Both render through SDL `kmsdrm`, so exactly one may run. Enforced three ways
so the unit can never boot dark because they raced for DRM master:

* `chordranger.service` declares `Conflicts=rk00pi.service`
* the stage only enables ChordRanger's unit under `ENABLE_CHORDRANGER_SERVICE=1`, and disables `rk00pi.service` when it does
* `patchbox-chordranger enable` / `disable` swaps them live, including the `/etc/pisound.conf` button map (backed up to `.chordranger.bak`, restored on `disable`)

```bash
patchbox-chordranger status         # which app owns the panel
sudo patchbox-chordranger enable    # ChordRanger now and on next boot
sudo patchbox-chordranger disable   # back to RK-00pi
```

### Layout on the image

| Path | Purpose |
|------|---------|
| `/opt/chordranger/` | app + venv |
| `/var/lib/chordranger/` | projects (`.crproj`), chordsets, styles, presets |
| `/etc/chordranger/config.toml` | panel size, paths, MIDI, `[button.map]` |
| `/run/chordranger/button.sock` | button socket (tmpfs, per boot) |
| `/usr/local/bin/chordranger-btn` | stdlib client the pisound scripts call |
| `/usr/local/bin/patchbox-chordranger` | status / enable / disable / button / logs |

### The Button — ChordRanger gestures

| Gesture | Action |
|---------|--------|
| 1 click | `play_stop` |
| 2 clicks | `record_toggle` (pad taps write to the chord track) |
| 3 clicks | `next_section` |
| hold ~1 s | `save_project` |
| hold ~3 s | `next_style` |
| hold ~5 s | `panic` |

Same socket shape as RK-00pi's on purpose, and the same ≥7 s fall-through to
`shutdown` when nothing is listening.

### Build toggles

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_CHORDRANGER` | **1** | install to `/opt/chordranger` |
| `ENABLE_CHORDRANGER_SERVICE` | **0** | boot ChordRanger instead of RK-00pi |
| `CHORDRANGER_WIDTH` / `HEIGHT` | (panel dims) | HyperPixel dims when `ENABLE_HYPERPIXEL4=1`, else HDMI |
| `CHORDRANGER_USER` | `chordranger` | service user |

### Tests

`cd apps/chordranger && python -m pytest -q` — everything runs headless (SDL
dummy driver, a capture MIDI backend, a fake clock). `python
bench/render_panel.py docs/img` regenerates the screenshots in the docs.

Panel geometry follows the same resolution order as `10-install-rk00pi`, so
both hardware profiles work: the 1280×400 bar gets side rails, the 800×480
HyperPixel and the 480×800 4" get a stacked top band and bottom tabs. The
Pisound button bridge is installed either way but only does anything on a rig
that has the board — with Pisound parked in Profile A, every gesture has an
on-screen equivalent and nothing is lost.

Not yet verified on hardware: touch on the real ElecLab panel, MIDI DIN
output, and the button under a live `pisound-btn`. Same on-device checklist as
RK-00pi applies — the `input` group is the usual culprit.

Update submodule then rebuild:

```bash
git submodule update --init --remote RK-00pi
# rebuild image (docker COPY includes submodule tree)
```

---

## HDMI 1280×400 notes

Applied by `stage3/09-hdmi-ultrawide`:

```text
hdmi_force_hotplug=1
hdmi_ignore_edid=0xa5000080
hdmi_group=2
hdmi_mode=87
hdmi_cvt=1280 400 60 6 0 0 0
hdmi_drive=2
```

cmdline:

```text
video=HDMI-A-1:1280x400@60D …
```

If the monitor is on the **other** Pi 5 HDMI port, change to `HDMI-A-2` or swap the cable to the port nearest USB-C.

### Touch — ElecLab USB-HID (common failure modes)

Reference panel: **ElecLab 7.4″ 1280×400** (HDMI + capacitive USB). Onboard
Cortex-M4 HID — no vendor kernel driver, no `goodtft` script.

| Need | Why |
|------|-----|
| **HDMI + USB both plugged** | HDMI = video only. USB carries touch. |
| `rk00pi` ∈ group **`input`** | SDL kmsdrm opens `/dev/input/event*` |
| unit `SupplementaryGroups=… input` | same, for the service process |
| app **FINGER→mouse** bridge | many HID panels emit SDL `FINGER*` only; widgets listen for `MOUSE*` |
| `SDL_TOUCH_MOUSE_EVENTS=0` | with the bridge, avoid double-fire |

X11 libinput conf does **not** apply to the kiosk path. Missing `input` or
missing USB → UI looks perfect, taps do nothing.

Live checks:

```bash
patchbox-display-status
sudo patchbox-touch-probe          # tap the glass; expect ABS/BTN lines
sudo patchbox-fix-input-button    # groups + unit drop-in + udev
```

---

## Parked hardware (do not re-enable without reason)

| Gear | Why parked |
|------|------------|
| Waveshare 3.5 DPI | Black screen issues; **full GPIO** — blocks Pisound |
| Inky Impression 5.7 | Slow + half-screen; GPIO conflict with Pisound |
| RaspiAudio Ultra++ | I2S; replaced by Pisound |
| Pimidi (ordered) | Extra MIDI TRS; check pin clash with Pisound before stacking |

---

## Rebuild

Fresh build (picks up new stage + submodule via Docker `COPY`):

```bash
cd /Users/johnnyclem/Desktop/Repos/patchbox-os-gen
git submodule update --init --recursive
docker ps -aq --filter name=pigen | xargs docker rm -fv 2>/dev/null
nohup env RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh > deploy/build-docker-live.log 2>&1 &
tail -f deploy/build-docker-live.log
```

`stage3/10-install-rk00pi` runs `pip install` under qemu — expect that substep to take a while.

Resume after stage3 failure:

```bash
docker run --rm --volumes-from pigen_work pi-gen \
  bash -c 'rm -rf /pi-gen/work/Patchbox/stage3'
CONTINUE=1 RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh
```

---

## Client WiFi (SSH headless)

Bake home WiFi into the image so the Pi joins your AP on first boot:

```bash
cp config.local.example config.local
# edit config.local — set WPA_COUNTRY, WPA_ESSID, WPA_PASSWORD
# ENABLE_WIFI_HOTSPOT is forced to 0 when SSID is set (unless FORCE_WIFI_HOTSPOT=1)
./build-docker.sh
```

Or one-shot:

```bash
WPA_COUNTRY=US WPA_ESSID='MyNet' WPA_PASSWORD='secret' ./build-docker.sh
```

Writes NetworkManager `preconfigured.nmconnection` + `wpa_supplicant.conf`.  
`config.local` is **gitignored** — never commit secrets.

After boot: `ssh patch@patchbox.local` (or the DHCP IP). Password: `blokaslabs` unless changed.

## First-boot checklist

1. Pisound seated on 40-pin; HDMI + USB touch to ultrawide  
2. Pi joins preconfigured WiFi → `ssh patch@patchbox.local`  
3. Panel should show **RK-00pi** Launch grid (light industrial UI, side rails)  
4. `patchbox-rk00pi-status` → unit active, imports OK, button socket + map  
5. `rk00pi-btn PING` → `OK ping pong …`; one-click → transport toggles  
6. `aplay -l` / `amidi -l` → Pisound present  
7. `patchbox-display-status` → HDMI mode / touch  
8. `cat ~/RK-00PI.txt` / `~/DISPLAY-PISOUND.txt`

Optional desktop: `sudo systemctl stop rk00pi && sudo systemctl start lightdm`  
(kmsdrm and X cannot both own the panel.)

---

## Known field issues (2026-08-01)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| UI looks great, **touch dead** | missing `input` group / unit groups / no USB | **`sudo patchbox-fix-input-button`** then **`sudo patchbox-touch-probe`** |
| probe sees **no** events | USB unplugged, bad port, or dead controller | Plug ElecLab USB; try USB2 port; `lsusb` + `/proc/bus/input/devices` |
| probe sees events, UI still dead | old app (no FINGER→mouse) or wrong SDL env | scp updated `gui/app.py` + re-run fix script; or re-flash |
| MIDI IN LEDs flash, **din_in unbound / no notes** | Patchbox **amidiauto** `*→*` races binds (EBUSY) | `sudo systemctl disable --now amidiauto`; restart rk00pi (fixed in `midi_alsa.py` too) |
| **DIAGNOSTICS lists every device, no notes or clock either way** | Hub endpoints name a HAT this Pi does not have (image built for Pimidi, rig is Pisound) — endpoint circles hollow | `patchbox-rk00pi-autohub` to confirm, then `sudo patchbox-rk00pi-autohub --apply && sudo systemctl restart rk00pi`; panel equivalent is Set → I/O → MIDI → DIN |
| **USB controller listed, plays nothing** | Baked hub presets declare DIN endpoints only — no `usb_in`/`usb_out` to route | same `--apply`: the generated hub gives each USB device an endpoint and routes it to the main out + REC |
| **The Button** does nothing | `pisound-btn` inactive, conf not mapped, or no socket | same one-shot; then `rk00pi-btn PING` |
| Button LEDs flash long, no transport | Socket missing (rk00pi down) | `systemctl status rk00pi`; journal for “button listening” |
| No `/sys/kernel/pisound` | HAT/driver not loaded | Reseat HAT; `lsmod \| grep pisound`; Pisound package/overlay |

### Live repair (no re-flash) — preferred when both touch + button are dead

The **flashed image** often still has an older `/opt/rk00pi/gui/app.py` without
FINGER→mouse. Group/`input` alone is not enough for USB-HID under kmsdrm.

```bash
# from patchbox-os-gen checkout (password prompts OK)
./scripts/live-repair-pi.sh
# or: ./scripts/live-repair-pi.sh patch@192.168.50.190
# diag only (no changes):
./scripts/live-repair-pi.sh --diag-only
```

Pushes: `gui/app.py` (FINGER bridge), `rk00pi.service` + drop-in, broad
udev rules, button client/scripts/conf, then prints a full DIAG block.

Also: `sudo patchbox-fix-input-button` · `sudo patchbox-diag-input-button`

**Hardware:** bar panels need **HDMI + USB**. HDMI alone = picture, no touch.

### Field-update touch path (manual)

```bash
# from patchbox-os-gen checkout
scp RK-00pi/gui/app.py patch@patchbox.local:/tmp/app.py
scp stage3/10-install-rk00pi/files/patchbox-fix-input-button \
    stage3/09-hdmi-ultrawide/files/patchbox-touch-probe \
    stage3/09-hdmi-ultrawide/files/patchbox-display-status \
    patch@patchbox.local:/tmp/
ssh patch@patchbox.local 'sudo install -m 644 /tmp/app.py /opt/rk00pi/gui/app.py \
  && sudo install -m 755 /tmp/patchbox-fix-input-button /usr/local/sbin/ \
  && sudo install -m 755 /tmp/patchbox-touch-probe /usr/local/bin/ \
  && sudo install -m 755 /tmp/patchbox-display-status /usr/local/bin/ \
  && sudo patchbox-fix-input-button \
  && sudo patchbox-touch-probe'
```

## Power / clean reboot (panel)

Set → **DIAG** → **SHUT DOWN** / **REBOOT** / **RESTART** (double-tap confirm).
Saves first, clears unclean marker, uses `sudo -n systemctl` via
`/etc/sudoers.d/rk00pi-power`. No more hard-unplug for software changes.

## Screensaver (LCD burn-in)

`[display] screensaver_sec = 120` (default). After 2 min without touch/key
the panel goes near-black with a drifting dim tempo mark; engine keeps
running. First tap wakes only (does not hit a control). Set `0` to disable.

## Multi-HAT MIDI (Pimidi + Pisound)

AUTO FIT / boot autohub now keep **both** HATs: Pimidi → `din_*_a/b`,
Pisound → `din_*_ps`. I/O → PORTS → **DIN DEVICE** shows `pimidi+pisound`
(or step to one family only). Per-endpoint rows still assign individual jacks.

## Factory songs (QY100-style)

**14** demo songs in `RK-00pi/data/factory/songs/` — each is a `.rkproj` with
2–5 Parts (patterns) + a Song arrangement that chains them. Regenerated by
`python data/factory/make_songs.py`. Stage install copies them into
`/var/lib/rk00pi/projects/`. Boot still opens `starter.rkproj`; load others
from **Files**. Tracks: drums/bass/chords/lead/perc/pads (GM ch layout).

## Next session ideas

1. **P0 — ElecLab soak** (see `SOAK-PROFILE-A.md`): HDMI+USB cables,  
   `sudo patchbox-soak --touch-live`, Launch-grid taps  
2. **P0 — Multi USB MIDI hot-swap**: autohub / I/O AUTO FIT, dual devices,  
   unplug/replug without restart  
3. **P1 — Companion matrix** from phone: token, live route edit mid-play  
4. Gate driver still `null` until buffered stage is signed off  
5. HyperPixel Profile B — parked (glass dead)

---

## Key paths

```text
config
.gitmodules
SOAK-PROFILE-A.md                 # on-device soak (Profile A)
RK-00pi/                          # submodule (main app) @ c9dfa21+
apps/chordranger/                 # second app (in-repo, not a submodule)
stage3/02-install-pisound/
stage3/09-hdmi-ultrawide/         # ElecLab HDMI + touch helpers + patchbox-soak
stage3/10-install-rk00pi/         # bake app + companion + autohub
stage3/10-install-rk00pi/files/patchbox-rk00pi-autohub
stage3/10-install-rk00pi/tests/
stage3/13-install-chordranger/
HANDOFF.md
deploy/image_*.zip                # after successful build
```
