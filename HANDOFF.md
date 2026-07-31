# Handoff — Patchbox OS gen (Pi 5 appliance)

**Date:** 2026-07-30  
**Branch:** `patchbox-2024-01`  
**Repo:** `/Users/johnnyclem/Desktop/Repos/patchbox-os-gen`

This document is for the next session. Read it before changing hardware or rebuilding.

---

## Goal (current)

Build a **Patchbox OS** image for **Raspberry Pi 5** with:

1. **Primary display:** Waveshare **3.5″ DPI LCD** — **640×480** IPS, **capacitive** (Goodix), on the **40-pin** header  
2. **Audio:** **USB** class-compliant interface (not I2S HAT)  
3. **MIDI:** USB for now; **Blokas Pimidi** (2× boards ordered) later — **not** with DPI on the same header  
4. Interactive UI on the IPS/touch panel (e-ink abandoned for interaction)

---

## Hardware truth (do not re-learn the hard way)

### Waveshare 3.5″ DPI (active target)

| Item | Detail |
|------|--------|
| Product | [3.5inch DPI LCD](https://www.waveshare.com/wiki/3.5inch_DPI_LCD) |
| Res | 640×480 @ 60 Hz, DPI666 |
| Touch | Goodix capacitive, I2C |
| Bookworm overlays | `dtoverlay=vc4-kms-v3d` + `waveshare-35dpi` + `waveshare-touch-35dpi` |
| DTBO | Vendored in `stage3/08-install-waveshare-dpi/files/overlays/` |

**GPIO:** nearly the entire 40-pin is used. Free NC pins only **1, 17, 35, 37**.  
**Cannot stack on same header:** Inky e-paper, RaspiAudio/I2S, Pisound, Pimidi.

**Audio with this panel:** USB only for JACK.

### Inky Impression 5.7″ (parked / failed for UI)

- 7-colour e-paper, full refresh **~30 s** — unusable for interactive patchbay  
- Observed **half-screen** paint on hardware (driver/SPI/geometry); forced UC8159 600×448 + `clear-test` added  
- Code still in `stage3/06-install-inky/` but **`ENABLE_INKY=0`** by default  
- Prefer `patchbox-inky-tui` (keyboard) if revisiting; not the product path

### RaspiAudio Mic Ultra++ (parked)

- I2S HAT with passthrough — **conflicts with DPI pin mux**  
- Stage exists: `stage3/07-install-raspiaudio/` — **`ENABLE_RASPIAUDIO=0`**  
- Re-enable only if dropping DPI for a different display stack

### Blokas Pimidi (ordered, not integrated)

- 2× Pimidi + stacking header **ordered**  
- 2×2 MIDI TRS **Type A**, stackable, `sel=0` → **GPIO23** (free of Inky, **not free under DPI**)  
- With current DPI panel: **do not enable** on the same Pi header  
- When boards arrive: either use on a **non-DPI** Pi, or wait for a display that frees GPIOs, or use USB MIDI only  
- Docs: https://blokas.io/pimidi/

### Pisound Micro (researched, not integrated)

- Low GPIO use on host (I2S + I2C + GPIO16/26) but **GPIO16 conflicts Inky button C**  
- Also header-heavy vs DPI — not for current stack

---

## Build config defaults (`config` / `build.sh`)

| Variable | Default | Role |
|----------|---------|------|
| `ENABLE_WAVESHARE_DPI` | **1** | Waveshare 3.5″ 640×480 |
| `ENABLE_INKY` | **0** | E-paper software (off) |
| `ENABLE_INKY_UI` | **0** | Boot e-ink service (off) |
| `ENABLE_RASPIAUDIO` | **0** | I2S audio (off) |
| `RASPBIAN_MIRROR` | Berkeley OCF | Avoid flaky `raspbian.raspberrypi.com` (93.93.128.193) |
| `ENABLE_SSH` | 1 | Headless onboarding |
| `IMG_NAME` | Patchbox | |

Mirror note: long stage3 apt storms fail against primary Raspbian; use:

```bash
RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian
# alternatives:
# http://raspbian.mirror.constant.com/raspbian
```

Apt retries: `stage0/00-configure-apt/files/80retries`.

---

## Stages added this effort

| Stage | Purpose |
|-------|---------|
| `stage3/06-install-inky/` | Inky library, splash/patchbay/TUI/keyboard (optional) |
| `stage3/07-install-raspiaudio/` | I2S overlay + ALSA hints (optional) |
| `stage3/08-install-waveshare-dpi/` | **Active** DPI overlays, touch, LightDM no-blank |

**Bug fixed during build:** `08` used `python3` on the pi-gen **host** (Debian image has no python3) → exit 127. Script is **bash-only** now.

---

## Latest image artifact

Successful build after Waveshare stage:

```text
deploy/image_2026-07-30-Patchbox.zip   (~1.9 GB)
deploy/2026-07-30-Patchbox.info
deploy/build-docker-live.log
```

Includes squeekboard (on-screen keyboard). Flash and seat Waveshare on 40-pin.

### First-boot checks on device

```bash
patchbox-display-status
cat ~/WAVESHARE-DPI.txt
# Screen Configuration → DPI-1 / Goodix touch
aplay -l   # pick USB for JACK
```

Rotation if needed — prepend to `/boot/firmware/cmdline.txt`:

```text
video=DPI-1:640x480M@60,rotate=90
```

---

## How to rebuild

```bash
cd /Users/johnnyclem/Desktop/Repos/patchbox-os-gen

# Fresh (recommended after stage0/1 config.txt changes)
docker ps -aq --filter name=pigen | xargs docker rm -fv 2>/dev/null
nohup env RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh > deploy/build-docker-live.log 2>&1 &
tail -f deploy/build-docker-live.log

# Resume after mid-stage3 failure (keep stage0–2 work volume)
docker run --rm --volumes-from pigen_work pi-gen \
  bash -c 'rm -rf /pi-gen/work/Patchbox/stage3'
CONTINUE=1 RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh
```

Host: macOS + Colima/Docker, **arm64**, builds **armhf** rootfs via qemu.

---

## Code / UX leftovers (not done)

1. **Desktop UX for 640×480** — LXDE panel still largely stock; may need denser panel, larger touch targets, auto-start useful apps  
2. **JACK default device** — no auto-select of first USB sound card; still manual via patchbox-cli  
3. **Touch-friendly patchbay** — e-ink TUI exists (`patchbox-inky-tui`); for IPS, either desktop apps (Patchage) or a small web/Qt UI  
4. **Pimidi integration** — blocked by DPI GPIO monopoly  
5. **Inky** — optional path only; half-screen root cause never fully closed on hardware  
6. **Image is armhf** — Pi 5 runs it; native arm64 Patchbox would be a separate branch effort (`arm64_dev` exists upstream-ish)

---

## Suggested next session priorities

1. **Flash latest zip**, verify DPI + touch + desktop on real hardware  
2. **USB audio** end-to-end with JACK / Pd / SC  
3. Tighten **640×480** desktop (panel height, fonts, squeekboard)  
4. When Pimidi arrives: decide architecture (second Pi / different display / USB MIDI only)  
5. Optional: commit deploy cleanup policy / document image naming dates

---

## Key file map

```text
config                          # product toggles
build.sh                        # exports toggles + RASPBIAN_MIRROR
stage1/00-boot-files/files/config.txt
stage0/00-configure-apt/        # mirror + retries
stage3/08-install-waveshare-dpi/  # DPI (ACTIVE)
stage3/06-install-inky/           # e-paper (OFF)
stage3/07-install-raspiaudio/     # I2S (OFF)
README.md                       # user-facing build vars
HANDOFF.md                      # this file
```

---

## Credentials / product defaults (unchanged)

- User: `patch` / `blokaslabs` (force password change on first login if enabled)  
- Hostname: `patchbox`  
- Hotspot passphrase: `blokaslabs` (overridable)

Do not put secrets in this file beyond those well-known product defaults.
