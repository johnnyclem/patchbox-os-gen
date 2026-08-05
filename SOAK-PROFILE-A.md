# On-device soak — Profile A (ElecLab 1280×400 + MIDI hub)

**Hardware:** Raspberry Pi 5 · Pimidi (or Pisound / USB MIDI) · ElecLab 7.4″ HDMI bar (1280×400) + USB touch  
**App:** RK-00pi kiosk (`rk00pi.service`) · name-based hub · autohub · companion routing UI  

Run this after every new image flash. SSH as `patch` (default password is the usual Patchbox one — change it).

```bash
ssh patch@patchbox.local
# or: ssh patch@<ip>
```

---

## 0. Cabling (do this before blaming software)

| Cable | Role |
|-------|------|
| **HDMI** | Video only |
| **USB** (panel → Pi USB-A) | Capacitive touch (Cortex-M4 HID) |
| **Power** | Official 5 V / 5 A for Pi 5 if possible |

HDMI alone paints a perfect UI with **zero** taps. Prefer HDMI port nearest USB-C (`HDMI-A-1`); if blank, swap ports or set `video=HDMI-A-2:…` in `/boot/firmware/cmdline.txt`.

---

## 1. Display + touch (P0)

### 1a. One-shot status

```bash
patchbox-display-status
sudo patchbox-touch-probe
# optional, stops the kiosk for SDL probe:
# sudo systemctl stop rk00pi
# sudo -u rk00pi /opt/rk00pi/venv/bin/python -m bench.touch_doctor --live 15
# sudo systemctl start rk00pi
```

| Expect | Fail → |
|--------|--------|
| DRM shows `1280x400` (or close) on an HDMI connector | wrong port / CVT; check `config.txt` + `cmdline.txt` |
| `lsusb` has a non-hub device when panel USB is plugged | cable / port; try USB2 |
| `/proc/bus/input/devices` has a Touch/HID name | same |
| `rk00pi ∈ input` and unit `SupplementaryGroups` includes `input` | `sudo patchbox-fix-input-button` |
| Probe prints `ABS_` / `BTN_` lines while tapping | kernel path dead — reseat USB / power-cycle panel |
| Launch grid pads light under finger | app path; see §1b |

### 1b. UI taps

1. Confirm kiosk is up: `systemctl is-active rk00pi` → `active`
2. Tap Launch pads, transport, tab strip
3. Diagnostics (Set → …) should show a `touch` line with device count and tap counter

```bash
# if paint works, taps do not:
sudo patchbox-fix-input-button
sudo systemctl restart rk00pi
journalctl -u rk00pi -b -n 80 | grep -iE 'touch|input|kmsdrm|error'
```

Field repair is idempotent: groups, unit drop-in, SDL env (`SDL_TOUCH_MOUSE_EVENTS=0`), udev.

### 1c. Pass criteria (display)

- [ ] Stable 1280×400 picture (no flicker / wrong mode)
- [ ] Kernel sees touch HID
- [ ] ≥1 successful `patchbox-touch-probe` session with events
- [ ] Launch grid + one settings control respond to taps
- [ ] No double-fires (one tap → one action)

---

## 2. MIDI hub + hot-swap (P0)

### 2a. What is live

```bash
patchbox-rk00pi-status
patchbox-rk00pi-autohub              # read-only fit report
cat /proc/asound/seq/clients
# or: aconnect -l
```

Endpoints bind by **ALSA client name**, not client number. That is what makes hotplug work — and why a hub baked for the wrong HAT is silent.

### 2b. Cold boot fit

1. Boot with the HAT + any USB MIDI already plugged  
2. `patchbox-rk00pi-autohub` — DIN / USB endpoints should **resolve**  
3. On panel: **I/O → PORTS** — circles filled for live ports  
4. Play notes into an input; confirm output on the main DIN/USB out  

If DIAGNOSTICS lists devices but nothing plays:

```bash
sudo patchbox-rk00pi-autohub --apply
sudo systemctl restart rk00pi
# previous hub kept at starter.rkproj.autohub.bak
# generated: /var/lib/rk00pi/presets/auto.rkhub
```

Opt out forever: `sudo touch /etc/rk00pi/autohub.disabled`

### 2c. Hot-swap matrix (do all rows)

| Step | Action | Expect |
|------|--------|--------|
| A | Plug class-compliant USB controller | New port in seq clients within ~1–2 s |
| B | Autohub or I/O → AUTO FIT | New `usb_*` endpoint bound |
| C | I/O → ROUTE: controller → main out | Notes reach synth / next device |
| D | Unplug controller mid-idle | Endpoint goes dormant; no crash |
| E | Replug same port | Route restores without restart |
| F | Second USB device at once | Both bind; independent routes |
| G | Unplug HAT side (if safe) / leave USB | Remaining path still works |

### 2d. Pass criteria (MIDI)

- [ ] At least one DIN (or primary) endpoint bound after cold boot
- [ ] USB device appears without restarting `rk00pi`
- [ ] Autohub or AUTO FIT adds it when the baked hub was empty for USB
- [ ] Unplug → replug restores routing
- [ ] Two USB devices can be routed independently
- [ ] No stuck notes after unplug (panic / all-notes-off if needed)

---

## 3. Companion routing UI (P1 — enabled on this product image)

Default appliance config turns the companion **on**, bound to LAN, with hub edits allowed mid-set.

```bash
# Token generated at first boot:
sudo cat /var/lib/rk00pi/companion-token
# or: journalctl -u rk00pi -b | grep -i companion

# From a phone on the same Wi‑Fi / hotspot:
#   http://patchbox.local:8787
#   http://<pi-ip>:8787
```

| Check | Expect |
|-------|--------|
| `grep -A6 '^\[companion\]' /etc/rk00pi/config.toml` | `enabled = true`, `bind = "0.0.0.0"`, `allow_hub_edit = true` |
| Browser opens UI | Login / token prompt works |
| Matrix toggle while stopped | Route changes on device |
| Matrix toggle while playing | Route changes without 409 (hub edits live) |
| SSE / live view | Port online/offline updates within ~1 s |

Disable on a public network:

```bash
sudo sed -i '/^\[companion\]/,/^\[/{s/^enabled = .*/enabled = false/}' /etc/rk00pi/config.toml
sudo systemctl restart rk00pi
```

There is **no TLS** — trusted LAN / hotspot only.

### Pass criteria (companion)

- [ ] UI reachable from a second device
- [ ] Token auth required
- [ ] Add/remove route visible on panel after phone edit
- [ ] (Optional) mDNS name resolves if `advertise = true` + avahi running

---

## 4. Orchestrated run (on the unit)

```bash
sudo patchbox-soak                 # display + touch + midi status
sudo patchbox-soak --touch-live    # + 12 s tap listen
sudo patchbox-soak --midi-live     # + remind hot-swap steps
```

Exit non-zero if a hard fail is detected (no HDMI mode, no input group, kiosk dead). Soft warnings (companion off, no USB yet) print but do not fail the run.

---

## 5. Sign-off table

| Area | Pass | Notes / commit |
|------|------|----------------|
| Picture 1280×400 | ☐ | |
| Touch probe events | ☐ | |
| UI taps | ☐ | |
| Cold-boot MIDI bind | ☐ | |
| USB hotplug + route | ☐ | |
| Dual USB | ☐ | |
| Companion matrix | ☐ | |
| Image / app commit | ☐ | `cat /opt/rk00pi/.patchbox-source-commit` |

**Image zip:** `deploy/image_YYYY-MM-DD-Patchbox.zip`  
**Parked:** HyperPixel Profile B (DPI) — not required for this soak.

---

## Quick command cheat sheet

```bash
patchbox-display-status
sudo patchbox-touch-probe
sudo patchbox-fix-input-button
patchbox-rk00pi-status
patchbox-rk00pi-autohub
sudo patchbox-rk00pi-autohub --apply && sudo systemctl restart rk00pi
sudo patchbox-soak
journalctl -u rk00pi -b -n 100
sudo cat /var/lib/rk00pi/companion-token
```
