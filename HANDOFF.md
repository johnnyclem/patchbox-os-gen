# Handoff — Patchbox OS gen (Pi 5 + Pisound + HDMI ultrawide)

**Date:** 2026-07-31  
**Branch:** `patchbox-2024-01`  
**Repo:** `/Users/johnnyclem/Desktop/Repos/patchbox-os-gen`

---

## Current product stack

```text
Raspberry Pi 5
  ├── Blokas Pisound (40-pin HAT)
  │     • 1/4" audio in/out
  │     • MIDI DIN in/out
  │     • Patchbox / JACK native path
  └── HDMI bar / ultrawide monitor 1280×400
        • Video: HDMI
        • Touch: USB HID
```

No GPIO display. Pisound owns the header for audio/MIDI. Display does not compete for pins.

---

## Build defaults (`config`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_HDMI_ULTRAWIDE` | **1** | Custom HDMI mode **1280×400@60** |
| `HDMI_WIDTH` / `HEIGHT` / `REFRESH` | 1280 / 400 / 60 | Override if panel differs |
| `ENABLE_WAVESHARE_DPI` | **0** | 3.5″ GPIO DPI (parked) |
| `ENABLE_INKY` / `ENABLE_INKY_UI` | **0** | E-paper (parked) |
| `ENABLE_RASPIAUDIO` | **0** | I2S HAT (parked) |
| `PISOUND_GIT_REF` | `patchbox` | Pisound tree checkout |
| `RASPBIAN_MIRROR` | Berkeley OCF | Avoid flaky primary Raspbian |

Stages always install Pisound packages (`stage3/02-install-pisound`) — that is the audio story.

---

## Stages (display / optional)

| Stage | Default | Role |
|-------|---------|------|
| `02-install-pisound` | on | Pisound + IRQ/sysctl audio tuning |
| `03-install-jack` | on | JACK2 + realtime limits |
| `06-install-inky` | off | E-paper UI (legacy) |
| `07-install-raspiaudio` | off | I2S audio HAT (legacy) |
| `08-install-waveshare-dpi` | off | GPIO DPI 640×480 (legacy) |
| `09-hdmi-ultrawide` | **on** | HDMI CVT + cmdline + touch + docs |

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

```bash
cd /Users/johnnyclem/Desktop/Repos/patchbox-os-gen
docker ps -aq --filter name=pigen | xargs docker rm -fv 2>/dev/null
nohup env RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh > deploy/build-docker-live.log 2>&1 &
tail -f deploy/build-docker-live.log
```

Resume after stage3 failure:

```bash
docker run --rm --volumes-from pigen_work pi-gen \
  bash -c 'rm -rf /pi-gen/work/Patchbox/stage3'
CONTINUE=1 RASPBIAN_MIRROR=http://mirrors.ocf.berkeley.edu/raspbian/raspbian \
  ./build-docker.sh
```

---

## First-boot checklist

1. Pisound seated on 40-pin; HDMI + USB touch to ultrawide  
2. `aplay -l` / `amidi -l` → Pisound present  
3. `patchbox-display-status` → HDMI mode / touch  
4. JACK via patchbox-cli → Pisound device  
5. `cat ~/DISPLAY-PISOUND.txt`

---

## Next session ideas

1. Verify 1280×400 EDID vs forced CVT on real panel  
2. Ultrawide desktop UX (panel layout, patchage window sizes)  
3. Auto-select Pisound as default JACK device  
4. Pimidi only if pins free with Pisound (or USB MIDI)

---

## Key paths

```text
config
stage1/00-boot-files/files/config.txt
stage3/02-install-pisound/
stage3/09-hdmi-ultrawide/
HANDOFF.md
deploy/image_*.zip   # after successful build
```
