# Deploying ChordRanger

Two ways in: baked into the image by the build, or installed by hand onto a
running Patchbox unit.

---

## In the image

`stage3/11-install-chordranger` does it. Defaults in the repo's `config`:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_CHORDRANGER` | **1** | install to `/opt/chordranger` |
| `ENABLE_CHORDRANGER_SERVICE` | **0** | enable the unit (and disable RK-00pi's) |
| `CHORDRANGER_WIDTH` / `HEIGHT` | (HDMI dims) | written into `config.toml` |
| `CHORDRANGER_USER` | `chordranger` | service user |

Installed but not enabled is the default on purpose: ChordRanger and RK-00pi
both take the panel under SDL kmsdrm, and the image ships both. To build an
image that boots ChordRanger:

```bash
ENABLE_CHORDRANGER_SERVICE=1 ./build-docker.sh
```

The stage disables `rk00pi.service` for you when it does that, so the built
image is never in the state where both units are enabled and the panel is dark
because they raced for DRM master.

### What lands where

| Path | Purpose |
|------|---------|
| `/opt/chordranger/` | app + venv |
| `/var/lib/chordranger/` | projects, chordsets, styles, presets (writable) |
| `/etc/chordranger/config.toml` | panel size, paths, MIDI, button map |
| `/run/chordranger/button.sock` | the button socket (tmpfs, per boot) |
| `/usr/local/bin/chordranger-btn` | stdlib client the pisound scripts call |
| `/usr/local/bin/patchbox-chordranger` | status / enable / disable |
| `chordranger.service` | kiosk unit (`SDL_VIDEODRIVER=kmsdrm`) |

---

## Onto a running unit

```bash
sudo apt install -y python3-venv python3-dev build-essential \
    libasound2-dev libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev \
    libsdl2-ttf-dev libportmidi-dev libdrm2 libgbm1

sudo useradd -r -m -d /var/lib/chordranger -s /usr/sbin/nologin chordranger
sudo usermod -aG audio,video,render,input chordranger

sudo rsync -a --exclude venv/ --exclude __pycache__/ \
    apps/chordranger/ /opt/chordranger/
sudo install -d /var/lib/chordranger/{projects,presets,chordsets,styles}
sudo install -D -m 644 /opt/chordranger/deploy/config.toml \
    /etc/chordranger/config.toml
sudo install -m 644 /opt/chordranger/deploy/chordranger.service \
    /usr/lib/systemd/system/chordranger.service
sudo install -m 755 /opt/chordranger/deploy/pisound/chordranger-btn \
    /usr/local/bin/chordranger-btn
sudo install -d /usr/local/pisound/scripts/pisound-btn
sudo install -m 755 /opt/chordranger/deploy/pisound/chordranger_*.sh \
    /usr/local/pisound/scripts/pisound-btn/

sudo chown -R chordranger:chordranger /opt/chordranger /var/lib/chordranger
sudo -u chordranger python3 -m venv /opt/chordranger/venv
sudo -u chordranger /opt/chordranger/venv/bin/pip install \
    -r /opt/chordranger/requirements.txt

sudo systemctl daemon-reload
sudo patchbox-chordranger enable       # takes the panel from RK-00pi
```

`input` in that `usermod` is not optional. Under kmsdrm SDL reads
`/dev/input/event*` directly — there is no X or Wayland in between — and the
nodes are `root:input 0660`. Without the group the panel draws perfectly and
every tap goes nowhere.

---

## Checking it

```bash
patchbox-chordranger status      # install, config, which app owns the panel
patchbox-chordranger logs        # journalctl -u chordranger
chordranger-btn PING             # PONG = the instrument is listening
chordranger-btn --map            # the live gesture map
amidi -l                         # what ALSA can see
```

Run it by hand with the service stopped, which is the fastest way to see a
traceback:

```bash
sudo systemctl stop chordranger
sudo -u chordranger /opt/chordranger/venv/bin/python /opt/chordranger/main.py \
    --config /etc/chordranger/config.toml --fullscreen --verbose
```

---

## When it goes wrong

**Black panel.** Almost always two apps fighting for it. `patchbox-chordranger
status` prints both units' states and warns when both are active. Also check
that nothing else took DRM master — `systemctl status lightdm`; kmsdrm and X
cannot both own the display.

**Panel draws, taps do nothing.** The service user is not in `input`. Confirm
with `id chordranger`, fix with `usermod -aG input chordranger`, restart.

**Backend says NULL on the SET screen.** `python-rtmidi` did not build (it
often does not, first time, under qemu). Reinstall inside the venv:
`sudo -u chordranger /opt/chordranger/venv/bin/pip install python-rtmidi`.
Everything else keeps working meanwhile; the rig is silent, not broken.

**No sound but the lamps are lit.** The box is playing and the synth is not
hearing it. Check the bound port on SET, then `amidi -l` for what the DIN is
called this boot, then whether the receiving device is listening on the
channel the part is set to (BAND shows each part's channel).

**Button does nothing.** `chordranger-btn PING`. Exit 2 means nothing is
listening — the service is down, or `[button] enabled` is false, or the map
still points at RK-00pi's scripts (`patchbox-chordranger button` repoints it).
`journalctl -u pisound-btn` carries the wrapper's own log line.

**Notes stuck on.** PANIC on the SET screen, the transport rail, or a five
second hold of the Pisound button. If it happens without one of those, it is a
bug worth a report — the engine is written so it should not be possible.
