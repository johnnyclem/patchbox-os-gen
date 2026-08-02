# Handoff — Patchbox OS gen (Pi 5 + Pisound + HDMI + RK-00pi)

**Date:** 2026-08-01  
**Branch:** `patchbox-2024-01`  
**Repo:** `/Users/johnnyclem/Desktop/Repos/patchbox-os-gen`

---

## Current product stack

### Profile A — HDMI ultrawide (default `config`)

```text
Raspberry Pi 5
  ├── Blokas Pimidi (sel=0) — 2×2 TRS MIDI
  ├── HDMI 1280×400 + USB touch (ElecLab ILI)
  └── RK-00pi kiosk · hub pimidi-2x2 · soft tape
```

### Profile B — HyperPixel 4.0" DPI (`config.hyperpixel4-pimidi.example`)

```text
Raspberry Pi 5
  ├── Blokas Pimidi (sel=0) — 2×2 TRS MIDI  ⚠ pin-contested with DPI
  ├── Pimoroni HyperPixel 4.0" rectangular
  │     • 800×480 @ 60 FPS DPI (dtoverlay=vc4-kms-dpi-hyperpixel4)
  │     • Goodix capacitive touch
  └── RK-00pi 800×480 (portrait chrome — aspect < 2:1)
```

**GPIO warning:** HyperPixel 4 DPI uses almost the entire 40-pin. Pimidi needs
I2C + a data GPIO. Stacking both may leave Pimidi silent — verify with
`amidi -l` / `patchbox-pimidi-status`. Fallbacks: USB MIDI, or HDMI bar + Pimidi.

**Parked:** Pisound (audio + The Button).

No GPIO display. Pisound owns the header for audio/MIDI. Display does not compete for pins.

**App source:** git submodule `RK-00pi` → `git@github.com:johnnyclem/RK-00pi.git`  
Baked into the image by `stage3/10-install-rk00pi` as `/opt/rk00pi`.

**Submodule tip (2026-08-01):** `15e389a` — designer UI pass + PiSound Button (M10).  
Shipped default map: `CLICK_1=play_stop`, `CLICK_2=record_toggle`, `HOLD_1S=save_project`, `HOLD_5S=panic`.

---

## Build defaults (`config`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_RK00PI` | **1** | Install main app from submodule |
| `ENABLE_RK00PI_SERVICE` | **1** | `systemctl enable rk00pi` |
| `ENABLE_RK00PI_BUTTON` | **1** | Wire pisound-btn → RK-00pi socket |
| `RK00PI_WIDTH` / `HEIGHT` | (HDMI dims) | `/etc/rk00pi/config.toml` panel size |
| `ENABLE_HDMI_ULTRAWIDE` | **1** | Custom HDMI mode **1280×400@60** |
| `HDMI_WIDTH` / `HEIGHT` / `REFRESH` | 1280 / 400 / 60 | Override if panel differs |
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

### RK-00pi layout on the image

| Path | Purpose |
|------|---------|
| `/opt/rk00pi/` | App + venv |
| `/var/lib/rk00pi/` | Writable projects / presets / maps / autosave |
| `/etc/rk00pi/config.toml` | Panel size + engine/MIDI/gates + `[button.map]` |
| `/run/rk00pi/button.sock` | The Button control socket (tmpfs, per boot) |
| `/usr/local/bin/rk00pi-btn` | stdlib client called by pisound-btn scripts |
| `/etc/pisound.conf` | PiSound gesture → `rk00pi_{click,hold}.sh` (`.rk00pi.bak` backup) |
| `rk00pi.service` | Kiosk unit (`SDL_VIDEODRIVER=kmsdrm`, `RuntimeDirectory=rk00pi`) |

### The Button — default gestures

| Gesture | Action | Meaning |
|---------|--------|---------|
| 1 click | `play_stop` | Start / stop transport |
| 2 clicks | `record_toggle` | Record enable / punch |
| hold ~1 s | `save_project` | Save session |
| hold ~5 s | `panic` | All notes off |
| other gestures | `nothing` | Safe defaults; rebind in `[button.map]` |

Safety net: if the instrument is not listening and the user holds past ~7 s, `rk00pi_hold.sh` still falls through to `shutdown` so a crashed unit is never stranded.

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

## Next session ideas

1. On-device ElecLab soak: `patchbox-touch-probe` then Launch-grid taps  
2. Verify Pisound DIN MIDI + prefer_pisound path in journal  
3. On-device pass for The Button (CI has no pisound-btn hardware)  
4. Gate driver still `null` until buffered stage is signed off  
5. Pimidi only if pins free with Pisound (or USB MIDI)

---

## Key paths

```text
config
.gitmodules
RK-00pi/                          # submodule (main app)
stage3/02-install-pisound/
stage3/09-hdmi-ultrawide/
stage3/10-install-rk00pi/         # bake app into image
HANDOFF.md
deploy/image_*.zip                # after successful build
```
