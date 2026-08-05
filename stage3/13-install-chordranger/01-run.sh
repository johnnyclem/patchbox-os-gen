#!/bin/bash -e
# Install ChordRanger — the chord-first backing band appliance.
#
# Source of truth: ${BASE_DIR}/apps/chordranger (in this repo, not a submodule)
# Layout mirrors stage3/10-install-rk00pi so an operator who knows one knows
# the other:
#   /opt/chordranger          app + venv
#   /var/lib/chordranger      writable projects/presets/chordsets/styles
#   /etc/chordranger/config.toml
#   chordranger.service       kiosk unit (SDL_VIDEODRIVER=kmsdrm)
#
# Gated on ENABLE_CHORDRANGER (default 1 — installed). The *service* is gated
# separately on ENABLE_CHORDRANGER_SERVICE (default 0 — not enabled), because
# ChordRanger and RK-00pi both want the panel under kmsdrm and only one can
# have it. The image ships both apps and boots whichever one is enabled;
# `patchbox-chordranger enable` swaps them on the running unit.

if [ "${ENABLE_CHORDRANGER}" != "1" ]; then
	echo "ENABLE_CHORDRANGER!=1 — skipping ChordRanger install"
	exit 0
fi

CR_SRC="${BASE_DIR}/apps/chordranger"
if [ ! -f "${CR_SRC}/main.py" ] || [ ! -f "${CR_SRC}/deploy/chordranger.service" ]; then
	echo "ERROR: ChordRanger source missing or incomplete at ${CR_SRC}"
	exit 1
fi

# Panel geometry, resolved the same way stage3/10-install-rk00pi does it so the
# two apps never disagree about what they are drawing on: an explicit override
# wins, then HyperPixel, then Waveshare DPI, then the HDMI bar.
if [ -n "${CHORDRANGER_WIDTH}" ] && [ -n "${CHORDRANGER_HEIGHT}" ]; then
	W="${CHORDRANGER_WIDTH}"
	H="${CHORDRANGER_HEIGHT}"
elif [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	W="${HYPERPIXEL_WIDTH:-800}"
	H="${HYPERPIXEL_HEIGHT:-480}"
elif [ "${ENABLE_WAVESHARE_DPI}" = "1" ]; then
	W="${WAVESHARE_WIDTH:-640}"
	H="${WAVESHARE_HEIGHT:-480}"
else
	W="${HDMI_WIDTH:-1280}"
	H="${HDMI_HEIGHT:-400}"
fi
APP_USER="${CHORDRANGER_USER:-chordranger}"
PREFIX=/opt/chordranger
DATA_DIR=/var/lib/chordranger
CONFIG_DIR=/etc/chordranger

echo "Installing ChordRanger → ${PREFIX} (${W}x${H} panel)"

# --- app tree ----------------------------------------------------------------
install -d "${ROOTFS_DIR}${PREFIX}"
if command -v rsync >/dev/null 2>&1; then
	rsync -a --delete \
		--exclude '.git/' \
		--exclude 'venv/' \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		--exclude '.pytest_cache/' \
		--exclude 'data/projects/' \
		"${CR_SRC}/" "${ROOTFS_DIR}${PREFIX}/"
	# ChordRanger's theory/chords/events/clock and the GUI kit are shims
	# over rangerkit since suite Phase 7 — vendor a frozen copy beside
	# core/, the same way every sibling app carries its own.
	rsync -a --delete \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		--exclude '.pytest_cache/' \
		"${CR_SRC}/../rangerkit/" "${ROOTFS_DIR}${PREFIX}/rangerkit/"
else
	# Fallback: selective copy (rsync is in 00-packages for the rootfs, and
	# a macOS host building under Docker may not have it either).
	cp -a "${CR_SRC}/main.py" "${CR_SRC}/requirements.txt" \
		"${CR_SRC}/requirements.lock" "${CR_SRC}/README.md" \
		"${ROOTFS_DIR}${PREFIX}/" 2>/dev/null || true
	for d in core gui data deploy docs bench tests; do
		if [ -d "${CR_SRC}/${d}" ]; then
			rm -rf "${ROOTFS_DIR}${PREFIX}/${d}"
			cp -a "${CR_SRC}/${d}" "${ROOTFS_DIR}${PREFIX}/"
		fi
	done
	rm -rf "${ROOTFS_DIR}${PREFIX}/rangerkit"
	cp -a "${CR_SRC}/../rangerkit" "${ROOTFS_DIR}${PREFIX}/rangerkit"
	find "${ROOTFS_DIR}${PREFIX}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
fi

# Record which commit was baked, so a unit in the field can be asked what it
# is running instead of being guessed at from a directory listing.
if [ -d "${BASE_DIR}/.git" ] || [ -f "${BASE_DIR}/.git" ]; then
	git -C "${BASE_DIR}" rev-parse HEAD 2>/dev/null \
		> "${ROOTFS_DIR}${PREFIX}/.patchbox-source-commit" || true
fi

# --- data partition ----------------------------------------------------------
install -d "${ROOTFS_DIR}${DATA_DIR}"/{projects,presets,chordsets,styles}

# --- config.toml for this panel ----------------------------------------------
install -d "${ROOTFS_DIR}${CONFIG_DIR}"
install -m 644 "${CR_SRC}/deploy/config.toml" \
	"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
sed -i \
	-e "s/^width = .*/width = ${W}/" \
	-e "s/^height = .*/height = ${H}/" \
	-e "s|^data_dir = .*|data_dir = \"${DATA_DIR}\"|" \
	-e "s|^presets_dir = .*|presets_dir = \"${DATA_DIR}/presets\"|" \
	"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"

# --- systemd unit ------------------------------------------------------------
install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
install -m 644 "${CR_SRC}/deploy/chordranger.service" \
	"${ROOTFS_DIR}/usr/lib/systemd/system/chordranger.service"
if [ "${APP_USER}" != "chordranger" ]; then
	sed -i "s/^User=chordranger$/User=${APP_USER}/" \
		"${ROOTFS_DIR}/usr/lib/systemd/system/chordranger.service"
fi

# --- The Button bridge -------------------------------------------------------
# The client and the wrapper scripts are always installed; /etc/pisound.conf is
# only rewritten when ChordRanger is the app that boots. Otherwise stage 10
# owns that file and rewriting it here would silently steal the button from
# RK-00pi — the two apps' scripts can coexist on disk, but only one map can be
# live at a time.
BUTTON_SRC="${CR_SRC}/deploy/pisound"
if [ -f "${BUTTON_SRC}/chordranger-btn" ]; then
	install -d "${ROOTFS_DIR}/usr/local/bin"
	install -m 755 "${BUTTON_SRC}/chordranger-btn" \
		"${ROOTFS_DIR}/usr/local/bin/chordranger-btn"
	install -d "${ROOTFS_DIR}/usr/local/pisound/scripts/pisound-btn"
	install -m 755 "${BUTTON_SRC}"/chordranger_*.sh \
		"${ROOTFS_DIR}/usr/local/pisound/scripts/pisound-btn/"
	echo "  button client + wrappers installed"
else
	echo "WARNING: ${BUTTON_SRC}/chordranger-btn missing — button not wired"
fi

# --- helper CLI --------------------------------------------------------------
install -m 755 files/patchbox-chordranger \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-chordranger"

# Brief note for the login user, alongside RK-00PI.txt.
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/CHORDRANGER.txt" <<EOF
Patchbox OS — ChordRanger (chord-first backing band)
====================================================

What it is
  Twelve chord pads, a QY-style backing band (intro / main A / fill / main B
  / fill / ending), and a bass engine that follows the chord you are holding.
  Plays out over MIDI — Pisound DIN, or any USB device you bind on SET.

Two apps, one panel
  ChordRanger and RK-00pi both take the display under SDL kmsdrm, so exactly
  one of them runs at a time:

    patchbox-chordranger status     which app owns the panel
    sudo patchbox-chordranger enable    ChordRanger on next boot (and now)
    sudo patchbox-chordranger disable   back to RK-00pi

The Button (PiSound board)
  1 click     play / stop
  2 clicks    record toggle (writes pad taps to the chord track)
  3 clicks    next section
  hold ~1 s   save project
  hold ~3 s   next style
  hold ~5 s   panic (all notes off)
  Re-map in /etc/chordranger/config.toml under [button.map]
  Checks:  chordranger-btn PING · chordranger-btn --map

Paths
  app:     ${PREFIX}
  data:    ${DATA_DIR}   (projects, chordsets, styles, presets)
  config:  ${CONFIG_DIR}/config.toml
  socket:  /run/chordranger/button.sock
  unit:    systemctl status chordranger

Checks
  patchbox-chordranger status
  journalctl -u chordranger -b -n 80
  amidi -l ; aplay -l

Run it by hand (with the service stopped)
  sudo systemctl stop chordranger
  sudo -u ${APP_USER} ${PREFIX}/venv/bin/python ${PREFIX}/main.py \\
      --config ${CONFIG_DIR}/config.toml --fullscreen

SSH
  ssh ${FIRST_USER_NAME}@${HOSTNAME}.local
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/CHORDRANGER.txt" 2>/dev/null || true

# --- user, groups, venv, unit (inside the rootfs) ----------------------------
# shellcheck disable=SC2086
on_chroot << EOF
set -e
APP_USER='${APP_USER}'
PREFIX='${PREFIX}'
DATA_DIR='${DATA_DIR}'

if id "\${APP_USER}" >/dev/null 2>&1; then
	echo "user \${APP_USER} already exists"
else
	echo "creating service user \${APP_USER}"
	useradd -r -m -d "\${DATA_DIR}" -s /usr/sbin/nologin "\${APP_USER}"
fi

# input: USB-HID touch via evdev — required under SDL kmsdrm. Without it the
# panel paints perfectly and every tap does nothing, which is a maddening
# fault to chase. Also declared in the unit's SupplementaryGroups=.
for group in audio video render input; do
	if getent group "\${group}" >/dev/null 2>&1; then
		usermod -aG "\${group}" "\${APP_USER}" || true
	else
		echo "warning: no group '\${group}' — skipped"
	fi
done

chown -R "\${APP_USER}:\${APP_USER}" "\${PREFIX}" "\${DATA_DIR}"
chown root:"\${APP_USER}" /etc/chordranger /etc/chordranger/config.toml 2>/dev/null || true
chmod 755 /etc/chordranger
chmod 644 /etc/chordranger/config.toml

# venv without system-site-packages: a stale distro pygame is the classic
# cause of a black panel that logs nothing useful.
if [ ! -x "\${PREFIX}/venv/bin/python" ]; then
	echo "creating venv at \${PREFIX}/venv"
	sudo -u "\${APP_USER}" python3 -m venv "\${PREFIX}/venv"
fi

PIP="\${PREFIX}/venv/bin/pip"
echo "pip install ChordRanger dependencies (slow under qemu — hang tight)"
sudo -u "\${APP_USER}" "\${PIP}" install --upgrade pip wheel
if ! sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir -r "\${PREFIX}/requirements.lock"; then
	echo "requirements.lock failed — installing floors from requirements.txt"
	sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "pygame>=2.5" || {
		echo "ERROR: pygame failed — the panel cannot start"
		exit 1
	}
	for package in "mido>=1.3" "python-rtmidi>=1.5"; do
		sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "\${package}" || \
			echo "warning: optional \${package} not installed — MIDI out will be silent"
	done
	rm -rf "${ROOTFS_DIR}${PREFIX}/rangerkit"
	cp -a "${CR_SRC}/../rangerkit" "${ROOTFS_DIR}${PREFIX}/rangerkit"
fi

# Smoke test the import path while we still have a build log to read it in.
sudo -u "\${APP_USER}" "\${PREFIX}/venv/bin/python" - <<'PY' || echo "warning: import smoke test failed"
import sys
sys.path.insert(0, "/opt/chordranger")
from core.project import default_project
from data.styles import factory_styles
project = default_project()
print(f"  chordranger: {len(factory_styles())} styles, "
      f"chordset {project.chordset.name!r}, ok")
PY

systemctl daemon-reload
if [ "${ENABLE_CHORDRANGER_SERVICE:-0}" = "1" ] || [ "${RANGER_BOOT_APP:-rk00pi}" = "chordranger" ]; then
	# ChordRanger is the app that boots: stand RK-00pi down first so the two
	# do not race for the panel on the next boot.
	systemctl disable rk00pi.service 2>/dev/null || true
	systemctl enable chordranger.service
	systemctl set-default multi-user.target
	echo "chordranger.service enabled (RK-00pi disabled)"
else
	systemctl disable chordranger.service 2>/dev/null || true
	echo "chordranger.service installed but not enabled"
	echo "  enable on the device with: sudo patchbox-chordranger enable"
fi
EOF

echo "ChordRanger installed: ${PREFIX}  panel=${W}x${H}  user=${APP_USER}"
