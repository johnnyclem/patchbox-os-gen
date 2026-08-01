# Handoff — Patchbox OS gen (Pi 5 + Pisound + HDMI + RK-00pi)

**Date:** 2026-08-01  
**Branch:** `patchbox-2024-01`  
**Repo:** `/Users/johnnyclem/Desktop/Repos/patchbox-os-gen`

---

## Current product stack

```text
Raspberry Pi 5
  ├── Blokas Pisound (40-pin HAT)
  │     • 1/4" audio in/out
  │     • MIDI DIN in/out
  │     • The Button → RK-00pi gestures (play/stop, record, save, panic)
  │     • Patchbox / JACK path available
  ├── HDMI bar / ultrawide monitor 1280×400
  │     • Video: HDMI
  │     • Touch: USB HID
  └── RK-00pi (main appliance UI)
        • SDL KMS/DRM kiosk (no X required)
        • 1280×400 light-industrial touch UI (side transport + tab rails)
        • RK-008 / RK-006 / RK-004 style sequencer + MIDI hub
        • systemd: rk00pi.service (Type=notify, RuntimeDirectory for button sock)
```

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
Boot default remains **multi-user.target** (console) so kmsdrm can own the panel.

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

USB touch is normally plug-and-play via libinput.

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

## Next session ideas

1. Flash image and soak first-boot to RK-00pi UI on real 1280×400 panel  
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
