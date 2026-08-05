#!/bin/bash -e
# Install RK-00pi (main Patchbox OS appliance) from the git submodule.
#
# Source of truth: ${BASE_DIR}/RK-00pi  (git@github.com:johnnyclem/RK-00pi.git)
# Layout matches deploy/install.sh / docs/deploy.md:
#   /opt/rk00pi          app + venv
#   /var/lib/rk00pi      writable projects/presets/maps/autosave
#   /etc/rk00pi/config.toml
#   rk00pi.service       Type=notify kiosk (SDL_VIDEODRIVER=kmsdrm)
#
# Gated on ENABLE_RK00PI (default 1). Panel size defaults to HDMI_* dims.

if [ "${ENABLE_RK00PI}" != "1" ]; then
	echo "ENABLE_RK00PI!=1 — skipping RK-00pi install"
	exit 0
fi

RK_SRC="${BASE_DIR}/RK-00pi"
if [ ! -f "${RK_SRC}/main.py" ] || [ ! -f "${RK_SRC}/deploy/rk00pi.service" ]; then
	echo "ERROR: RK-00pi submodule missing or incomplete at ${RK_SRC}"
	echo "  Run: git submodule update --init --recursive"
	exit 1
fi

# Panel size priority: explicit RK00PI_* → HyperPixel → HDMI ultrawide defaults
if [ -n "${RK00PI_WIDTH}" ] && [ -n "${RK00PI_HEIGHT}" ]; then
	W="${RK00PI_WIDTH}"
	H="${RK00PI_HEIGHT}"
elif [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	W="${HYPERPIXEL_WIDTH:-800}"
	H="${HYPERPIXEL_HEIGHT:-480}"
else
	W="${HDMI_WIDTH:-1280}"
	H="${HDMI_HEIGHT:-400}"
fi
APP_USER="${RK00PI_USER:-rk00pi}"
PREFIX=/opt/rk00pi
DATA_DIR=/var/lib/rk00pi
CONFIG_DIR=/etc/rk00pi

echo "Installing RK-00pi from submodule → ${PREFIX} (${W}x${H} panel)"

# --- app tree (exclude venv/git/caches; keep benches + deploy docs) ------------
install -d "${ROOTFS_DIR}${PREFIX}"
if command -v rsync >/dev/null 2>&1; then
	rsync -a --delete \
		--exclude '.git/' \
		--exclude '.github/' \
		--exclude 'venv/' \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		--exclude '.pytest_cache/' \
		--exclude 'data/projects/' \
		"${RK_SRC}/" "${ROOTFS_DIR}${PREFIX}/"
else
	# Fallback: selective copy (rsync is in 00-packages for the rootfs, not host)
	cp -a "${RK_SRC}/main.py" "${RK_SRC}/requirements.txt" "${RK_SRC}/requirements.lock" \
		"${RK_SRC}/NOTICE" "${RK_SRC}/README.md" "${RK_SRC}/CHANGELOG.md" \
		"${ROOTFS_DIR}${PREFIX}/" 2>/dev/null || true
	for d in core gui companion data bench deploy docs tests; do
		if [ -d "${RK_SRC}/${d}" ]; then
			rm -rf "${ROOTFS_DIR}${PREFIX}/${d}"
			cp -a "${RK_SRC}/${d}" "${ROOTFS_DIR}${PREFIX}/"
		fi
	done
	find "${ROOTFS_DIR}${PREFIX}" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
fi

# Record which submodule commit was baked (best-effort).
if [ -d "${BASE_DIR}/.git" ] || [ -f "${BASE_DIR}/.git" ]; then
	git -C "${RK_SRC}" rev-parse HEAD 2>/dev/null \
		> "${ROOTFS_DIR}${PREFIX}/.patchbox-source-commit" || true
fi

# --- data partition + factory presets ----------------------------------------
install -d "${ROOTFS_DIR}${DATA_DIR}"/{projects,presets,maps,autosave}
if [ -d "${RK_SRC}/data/presets" ]; then
	cp -a "${RK_SRC}/data/presets/." "${ROOTFS_DIR}${DATA_DIR}/presets/" 2>/dev/null || true
fi
if [ -d "${RK_SRC}/data/maps" ]; then
	cp -a "${RK_SRC}/data/maps/." "${ROOTFS_DIR}${DATA_DIR}/maps/" 2>/dev/null || true
fi

# --- config.toml for this panel ----------------------------------------------
install -d "${ROOTFS_DIR}${CONFIG_DIR}"
install -m 644 "${RK_SRC}/deploy/config.toml" "${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
# portable sed (macOS host can run stages? usually Linux in docker — both OK)
sed -i \
	-e "s/^width = .*/width = ${W}/" \
	-e "s/^height = .*/height = ${H}/" \
	-e "s|^data_dir = .*|data_dir = \"${DATA_DIR}\"|" \
	-e "s|^presets_dir = .*|presets_dir = \"${DATA_DIR}/presets\"|" \
	"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
# Tape: soft-null on Pimidi-only (no PiSound PCM); hw:pisound when button HAT present.
TAPE_DEVICE="null"
if [ "${ENABLE_RK00PI_BUTTON:-0}" = "1" ] && [ "${ENABLE_PIMIDI:-0}" != "1" ]; then
	TAPE_DEVICE="hw:pisound"
fi
if grep -qE '^\[tape\]' "${ROOTFS_DIR}${CONFIG_DIR}/config.toml"; then
	sed -i \
		-e '/^\[tape\]/,/^\[/{s/^enabled = .*/enabled = true/}' \
		-e "/^\[tape\]/,/^\[/{s/^device = .*/device = \"${TAPE_DEVICE}\"/}" \
		-e '/^\[tape\]/,/^\[/{s/^period_frames = .*/period_frames = 512/}' \
		-e '/^\[tape\]/,/^\[/{s/^link_transport = .*/link_transport = "follow_start_stop"/}' \
		-e '/^\[tape\]/,/^\[/{s/^color = .*/color = "per_track"/}' \
		-e '/^\[tape\]/,/^\[/{s/^monitor = .*/monitor = true/}' \
		"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
	echo "  [tape] enabled + device=${TAPE_DEVICE}"
fi
# MIDI: hub endpoints match the HAT; prefer_pisound is historical only.
if grep -qE '^prefer_pisound' "${ROOTFS_DIR}${CONFIG_DIR}/config.toml"; then
	if [ "${ENABLE_PIMIDI:-0}" = "1" ]; then
		sed -i 's/^prefer_pisound = .*/prefer_pisound = false/' \
			"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
	else
		sed -i 's/^prefer_pisound = .*/prefer_pisound = true/' \
			"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
	fi
fi

# Companion: remote MIDI routing matrix + backup (token auth, no TLS).
# Product default ON (ENABLE_RK00PI_COMPANION=1) for the hot-swap hub story.
COMPANION_ON="${ENABLE_RK00PI_COMPANION:-1}"
COMPANION_BIND="${RK00PI_COMPANION_BIND:-0.0.0.0}"
COMPANION_PORT="${RK00PI_COMPANION_PORT:-8787}"
COMPANION_ADV="${RK00PI_COMPANION_ADVERTISE:-1}"
if grep -qE '^\[companion\]' "${ROOTFS_DIR}${CONFIG_DIR}/config.toml"; then
	if [ "${COMPANION_ON}" = "1" ]; then
		# Rewrite keys inside the [companion] table only.
		awk -v bind="${COMPANION_BIND}" -v port="${COMPANION_PORT}" -v adv="${COMPANION_ADV}" '
			BEGIN { in_c = 0 }
			/^\[companion\]/ { in_c = 1; print; next }
			/^\[/ { in_c = 0 }
			in_c && /^enabled[[:space:]]*=/ { print "enabled = true"; next }
			in_c && /^bind[[:space:]]*=/ { print "bind = \"" bind "\""; next }
			in_c && /^port[[:space:]]*=/ { print "port = " port; next }
			in_c && /^advertise[[:space:]]*=/ {
				if (adv == "1") print "advertise = true";
				else print "advertise = false";
				next
			}
			in_c && /^allow_hub_edit[[:space:]]*=/ { print "allow_hub_edit = true"; next }
			{ print }
		' "${ROOTFS_DIR}${CONFIG_DIR}/config.toml" > "${ROOTFS_DIR}${CONFIG_DIR}/config.toml.companion"
		mv "${ROOTFS_DIR}${CONFIG_DIR}/config.toml.companion" \
			"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
		echo "  [companion] enabled bind=${COMPANION_BIND} port=${COMPANION_PORT} advertise=${COMPANION_ADV}"
	else
		awk '
			BEGIN { in_c = 0 }
			/^\[companion\]/ { in_c = 1; print; next }
			/^\[/ { in_c = 0 }
			in_c && /^enabled[[:space:]]*=/ { print "enabled = false"; next }
			{ print }
		' "${ROOTFS_DIR}${CONFIG_DIR}/config.toml" > "${ROOTFS_DIR}${CONFIG_DIR}/config.toml.companion"
		mv "${ROOTFS_DIR}${CONFIG_DIR}/config.toml.companion" \
			"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
		echo "  [companion] disabled (ENABLE_RK00PI_COMPANION!=1)"
	fi
fi
# mDNS advertisement for http://<hostname>.local:PORT
if [ "${COMPANION_ON}" = "1" ] && [ "${COMPANION_ADV}" = "1" ]; then
	if [ -f "${RK_SRC}/deploy/avahi/rk00pi-companion.service" ]; then
		install -d "${ROOTFS_DIR}/etc/avahi/services"
		# Port in the XML must match config.
		sed "s|<port>8787</port>|<port>${COMPANION_PORT}</port>|" \
			"${RK_SRC}/deploy/avahi/rk00pi-companion.service" \
			> "${ROOTFS_DIR}/etc/avahi/services/rk00pi-companion.service"
		echo "  avahi: /etc/avahi/services/rk00pi-companion.service (port ${COMPANION_PORT})"
	else
		echo "  warning: deploy/avahi/rk00pi-companion.service missing — no mDNS name"
	fi
fi

# --- power privileges (Diagnostics SHUT DOWN / REBOOT / RESTART) -------------
# Service user has no seat → polkit refuses systemctl poweroff. Sudoers is
# the appliance path; button_server and the panel both use `sudo -n systemctl`.
if [ -f "${RK_SRC}/deploy/sudoers.d/rk00pi-power" ]; then
	install -d "${ROOTFS_DIR}/etc/sudoers.d"
	install -m 440 "${RK_SRC}/deploy/sudoers.d/rk00pi-power" \
		"${ROOTFS_DIR}/etc/sudoers.d/rk00pi-power"
	# Rewrite the username if the appliance user is not the default.
	if [ "${APP_USER}" != "rk00pi" ]; then
		sed -i "s/^rk00pi /${APP_USER} /" \
			"${ROOTFS_DIR}/etc/sudoers.d/rk00pi-power"
	fi
	echo "  sudoers: /etc/sudoers.d/rk00pi-power (poweroff/reboot/restart)"
fi

# --- systemd unit ------------------------------------------------------------
# Includes RuntimeDirectory=rk00pi for The Button socket (/run/rk00pi/button.sock)
# and SupplementaryGroups=… input for USB-HID touch under kmsdrm.
install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
install -m 644 "${RK_SRC}/deploy/rk00pi.service" \
	"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
if [ "${APP_USER}" != "rk00pi" ]; then
	sed -i "s/^User=rk00pi$/User=${APP_USER}/" \
		"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
fi
# Belt-and-braces: older checkouts may omit `input` from SupplementaryGroups.
if ! grep -qE '^SupplementaryGroups=.*\binput\b' \
	"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"; then
	sed -i 's/^SupplementaryGroups=.*/& input/' \
		"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
	echo "  patched rk00pi.service SupplementaryGroups += input"
fi
# Ensure RuntimeDirectoryMode is open enough for local rk00pi-btn as patch.
if grep -qE '^RuntimeDirectoryMode=0750' \
	"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"; then
	sed -i 's/^RuntimeDirectoryMode=0750/RuntimeDirectoryMode=0755/' \
		"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
	echo "  patched rk00pi.service RuntimeDirectoryMode=0755"
fi
# SDL touch env: app maps FINGER→mouse; disable SDL's duplicate synthesis.
UNIT_FILE="${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
if ! grep -qE '^Environment=SDL_TOUCH_MOUSE_EVENTS=' "${UNIT_FILE}"; then
	if grep -qE '^Environment=SDL_VIDEODRIVER=kmsdrm' "${UNIT_FILE}"; then
		# Portable insert after the kmsdrm line (no GNU sed \\n tricks).
		TMPU="$(mktemp)"
		awk '
			{ print }
			/^Environment=SDL_VIDEODRIVER=kmsdrm$/ {
				print "Environment=SDL_TOUCH_MOUSE_EVENTS=0"
				print "Environment=SDL_MOUSE_TOUCH_EVENTS=0"
			}
		' "${UNIT_FILE}" > "${TMPU}"
		cat "${TMPU}" > "${UNIT_FILE}"
		rm -f "${TMPU}"
	else
		printf '\nEnvironment=SDL_TOUCH_MOUSE_EVENTS=0\nEnvironment=SDL_MOUSE_TOUCH_EVENTS=0\n' \
			>> "${UNIT_FILE}"
	fi
	echo "  patched rk00pi.service SDL_TOUCH_MOUSE_EVENTS=0"
fi

# --- The Button (PiSound) ----------------------------------------------------
# pisound-btn (stage3/02) runs action scripts as root under system python.
# RK-00pi opens a Unix socket; a stdlib client + thin shell wrappers bridge
# the daemon to the app. Gesture→action map lives in config.toml [button.map]:
#   CLICK_1 → play_stop · CLICK_2 → record_toggle
#   HOLD_1S → save_project · HOLD_5S → panic
# (see /opt/rk00pi/docs/USER.md §The Button). ENABLE_RK00PI_BUTTON=0 skips.
PISOUND_CONF="${ROOTFS_DIR}/etc/pisound.conf"
PISOUND_SCRIPTS="${ROOTFS_DIR}/usr/local/pisound/scripts/pisound-btn"
BUTTON_CLIENT="${ROOTFS_DIR}/usr/local/bin/rk00pi-btn"
BUTTON_BACKUP="${ROOTFS_DIR}/etc/pisound.conf.rk00pi.bak"
BUTTON_SRC="${RK_SRC}/deploy/pisound"

set_pisound_action() { # $1 conf path, $2 action id, $3 on-device script path
	local conf="$1" action="$2" script="$3"
	if grep -qE "^${action}[[:space:]]" "${conf}" 2>/dev/null; then
		sed -i "s|^${action}[[:space:]].*|${action} ${script}|" "${conf}"
	else
		printf '%s %s\n' "${action}" "${script}" >> "${conf}"
	fi
}

if [ "${ENABLE_RK00PI_BUTTON:-1}" = "1" ]; then
	if [ ! -f "${BUTTON_SRC}/rk00pi-btn" ]; then
		echo "WARNING: ${BUTTON_SRC}/rk00pi-btn missing — The Button not wired"
	else
		echo "Installing PiSound Button bridge → rk00pi-btn + pisound-btn scripts"
		install -d "$(dirname "${BUTTON_CLIENT}")"
		install -m 755 "${BUTTON_SRC}/rk00pi-btn" "${BUTTON_CLIENT}"
		install -d "${PISOUND_SCRIPTS}"
		install -m 755 "${BUTTON_SRC}"/rk00pi_*.sh "${PISOUND_SCRIPTS}/"

		# Preserve the first pre-RK map so a later uninstall can restore it.
		if [ -f "${PISOUND_CONF}" ] && [ ! -f "${BUTTON_BACKUP}" ]; then
			cp "${PISOUND_CONF}" "${BUTTON_BACKUP}"
		fi
		# Ensure the conf file exists even if the package left it out.
		if [ ! -f "${PISOUND_CONF}" ]; then
			install -d "$(dirname "${PISOUND_CONF}")"
			: > "${PISOUND_CONF}"
		fi

		ON_DEVICE_SCRIPTS=/usr/local/pisound/scripts/pisound-btn
		for action in CLICK_1 CLICK_2 CLICK_3 CLICK_OTHER; do
			set_pisound_action "${PISOUND_CONF}" "${action}" \
				"${ON_DEVICE_SCRIPTS}/rk00pi_click.sh"
		done
		for action in HOLD_1S HOLD_3S HOLD_5S HOLD_OTHER; do
			set_pisound_action "${PISOUND_CONF}" "${action}" \
				"${ON_DEVICE_SCRIPTS}/rk00pi_hold.sh"
		done
		# DOWN/UP stay on pisound's own scripts (held-button LED blink).
		echo "  mapped CLICK_*/HOLD_* → rk00pi_{click,hold}.sh"
		echo "  live map: /etc/rk00pi/config.toml [button.map]"
	fi
else
	echo "ENABLE_RK00PI_BUTTON!=1 — leaving /etc/pisound.conf alone"
fi

# --- helper CLI --------------------------------------------------------------
install -m 755 files/patchbox-rk00pi-status \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-rk00pi-status"
# One-shot field repair + read-only diagnostics for dead touch / The Button.
install -d "${ROOTFS_DIR}/usr/local/sbin" "${ROOTFS_DIR}/usr/local/bin"
install -m 755 files/patchbox-fix-input-button \
	"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-input-button"
install -m 755 files/patchbox-diag-input-button \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-diag-input-button"
install -m 755 files/patchbox-boot-kiosk \
	"${ROOTFS_DIR}/usr/local/sbin/patchbox-boot-kiosk"
# Fits the hub to the MIDI hardware the unit actually has (see the drop-in
# below). Also the read-only "why is this endpoint unbound" diagnostic, so it
# is installed whether or not the boot-time pass is enabled.
install -m 755 files/patchbox-rk00pi-autohub \
	"${ROOTFS_DIR}/usr/local/sbin/patchbox-rk00pi-autohub"

# Brief note for the login user (alongside DISPLAY-PISOUND.txt)
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/RK-00PI.txt" <<EOF
Patchbox OS — RK-00pi (main appliance)
======================================

What boots
  multi-user.target → rk00pi.service  (NOT graphical / LightDM)
  SDL_VIDEODRIVER=kmsdrm fullscreen on the HDMI ${W}x${H} panel
  Pisound = MIDI DIN + 1/4" audio (prefer_pisound=true)
  If you ever land on the Linux desktop instead:
    sudo systemctl set-default multi-user.target
    sudo systemctl disable lightdm
    sudo reboot

The Button (PiSound board)
  1 click     play / stop transport
  2 clicks    record toggle
  hold ~1 s   save project
  hold ~5 s   panic (all notes off)
  Re-map in /etc/rk00pi/config.toml under [button.map]
  Checks:  rk00pi-btn PING · rk00pi-btn --map · rk00pi-btn --list

Paths
  app:     /opt/rk00pi
  data:    /var/lib/rk00pi   (projects, presets, maps, autosave)
  config:  /etc/rk00pi/config.toml
  socket:  /run/rk00pi/button.sock
  unit:    systemctl status rk00pi

Checks
  patchbox-rk00pi-status
  journalctl -u rk00pi -b -n 80
  amidi -l ; aplay -l

MIDI silent? (devices listed on DIAGNOSTICS, nothing plays or records)
  An endpoint binds to an ALSA port by *name*. If the image was built for
  one HAT and this Pi carries another, every DIN endpoint asks for a client
  that is not here and nothing binds — the scan still shows the device names.

  patchbox-rk00pi-autohub            # which endpoints resolve, and why not
  sudo patchbox-rk00pi-autohub --apply && sudo systemctl restart rk00pi
  # on the panel instead: Set -> I/O -> MIDI -> DIN

  The service already runs --apply at every start; the previous hub is kept
  at <project>.autohub.bak and the generated one at
  ${DATA_DIR}/presets/auto.rkhub. To stop it touching the hub at all:
  sudo touch /etc/rk00pi/autohub.disabled

Power (clean reboot / shutdown — no hard unplug)
  On the panel: Set → DIAG → SHUT DOWN or REBOOT (tap twice to confirm)
  Or:  sudo systemctl poweroff / reboot
  App restart only: RESTART on Diagnostics (or systemctl restart rk00pi)

Field repair (touch dead / button dead)
  sudo patchbox-fix-input-button
  # or: sudo patchbox-fix-input-button --dry-run
  # live tap test (ElecLab USB must be plugged):
  sudo patchbox-touch-probe

Update app later (on device, as root)
  cd /opt/rk00pi && git pull   # only if you re-init a git remote
  # or re-flash / re-run deploy/install.sh from a checkout

Gates
  driver ships as "null" — do NOT wire GPIO to eurorack without a
  buffered/level-shifted stage. See /opt/rk00pi/docs/deploy.md

Desktop (optional, not the default)
  Patchbox still ships LXDE/LightDM. Default boot is console + RK-00pi.
  To open the desktop for a session:
    sudo systemctl stop rk00pi && sudo systemctl start lightdm
  To make desktop the boot default again (not recommended for the appliance):
    sudo systemctl set-default graphical.target && sudo systemctl enable lightdm
  Back to kiosk:
    sudo systemctl set-default multi-user.target
    sudo systemctl disable lightdm && sudo systemctl enable rk00pi && sudo reboot

Companion (remote MIDI router UI)
  Default ON for this product image (token auth, no TLS — trusted LAN only).
  Phone:  http://${HOSTNAME}.local:${RK00PI_COMPANION_PORT:-8787}
  Token:  sudo cat /var/lib/rk00pi/companion-token
  Config: /etc/rk00pi/config.toml  [companion]
  Disable:
    sudo sed -i '/^\[companion\]/,/^\[/{s/^enabled = .*/enabled = false/}' \\
      /etc/rk00pi/config.toml && sudo systemctl restart rk00pi

On-device soak (ElecLab + MIDI hub)
  sudo patchbox-soak
  sudo patchbox-soak --touch-live
  ~/SOAK-PROFILE-A.md

SSH
  ssh ${FIRST_USER_NAME}@${HOSTNAME}.local
EOF
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/RK-00PI.txt" 2>/dev/null || true

# --- user, groups, venv, enable unit (inside rootfs) -------------------------
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

# input: USB-HID touch via evdev — required under SDL kmsdrm (without it
# the panel paints but taps do nothing). Also declared in rk00pi.service
# SupplementaryGroups=.
for group in audio gpio render video input; do
	if getent group "\${group}" >/dev/null 2>&1; then
		usermod -aG "\${group}" "\${APP_USER}" || true
	else
		echo "warning: no group '\${group}' — skipped"
	fi
done

chown -R "\${APP_USER}:\${APP_USER}" "\${PREFIX}" "\${DATA_DIR}"
# config readable by service user
chown root:"\${APP_USER}" /etc/rk00pi /etc/rk00pi/config.toml 2>/dev/null || true
chmod 755 /etc/rk00pi
chmod 644 /etc/rk00pi/config.toml

# venv without system-site-packages (stale distro pygame → black panel)
if [ ! -x "\${PREFIX}/venv/bin/python" ]; then
	echo "creating venv at \${PREFIX}/venv"
	sudo -u "\${APP_USER}" python3 -m venv "\${PREFIX}/venv"
fi

PIP="\${PREFIX}/venv/bin/pip"
echo "pip install RK-00pi dependencies (slow under qemu — hang tight)"
sudo -u "\${APP_USER}" "\${PIP}" install --upgrade pip wheel
# Prefer the pinned lock when it builds; fall back package-by-package.
if ! sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir -r "\${PREFIX}/requirements.lock"; then
	echo "requirements.lock failed — installing floors from requirements.txt"
	sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "pygame>=2.5" || {
		echo "ERROR: pygame failed — GUI cannot start"
		exit 1
	}
	for package in "mido>=1.3" "alsa-midi>=1.0" "python-rtmidi>=1.5" "gpiod>=2.1"; do
		sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "\${package}" || \
			echo "warning: optional \${package} not installed"
	done
fi

# Build the RK-424 tape DSP (optional; soft deck still runs without it).
if [ -f "${PREFIX}/native/tape/Makefile" ]; then
	echo "building native tape DSP (librk424.so)"
	if command -v g++ >/dev/null 2>&1; then
		make -C "${PREFIX}/native/tape" clean >/dev/null 2>&1 || true
		if make -C "${PREFIX}/native/tape"; then
			chown -R "${APP_USER}:${APP_USER}" "${PREFIX}/native/tape" || true
			if make -C "${PREFIX}/native/tape" info 2>/dev/null | grep -q "ALSA     = yes"; then
				echo "  tape DSP built with ALSA"
			else
				echo "  tape DSP built WITHOUT ALSA (install libasound2-dev for hw:pisound)"
			fi
		else
			echo "  warning: tape DSP build failed — soft deck only"
		fi
	else
		echo "  warning: g++ missing — skipping tape DSP"
	fi
fi

# Starter project: hub preset (Pimidi 2×2 / Pisound) + optional Warm Bump tape colour.
HUB_PRESET_NAME="${RK00PI_HUB_PRESET:-pimidi-2x2}"
if [ -x "${PREFIX}/venv/bin/python" ] && [ -f "${PREFIX}/core/project.py" ]; then
	echo "seeding ${DATA_DIR}/projects/starter.rkproj (hub=${HUB_PRESET_NAME})"
	sudo -u "${APP_USER}" env PYTHONPATH="${PREFIX}" HUB_PRESET_NAME="${HUB_PRESET_NAME}" \
		"${PREFIX}/venv/bin/python" - <<'PY' || echo "  warning: starter project seed failed"
from pathlib import Path
import os
import sys
sys.path.insert(0, "/opt/rk00pi")
from core.project import Project, load_hub_preset
from core.tape import ColorMode
from core.tape_presets import load_preset
projects = Path("/var/lib/rk00pi/projects")
projects.mkdir(parents=True, exist_ok=True)
starter = projects / "starter.rkproj"
p = Project(name="starter")
hub_name = os.environ.get("HUB_PRESET_NAME", "pimidi-2x2")
hub_path = Path("/var/lib/rk00pi/presets") / f"{hub_name}.rkhub"
if not hub_path.is_file():
    hub_path = Path("/opt/rk00pi/data/presets") / f"{hub_name}.rkhub"
if hub_path.is_file():
    p.hub = load_hub_preset(hub_path)
    print("hub:", hub_path)
else:
    print("warning: hub preset missing", hub_path)
tape_preset = Path("/var/lib/rk00pi/presets/tape/warm-bump.portapreset")
if tape_preset.is_file():
    load_preset(tape_preset).apply_to(p.tape.params)
p.tape.enabled = True
p.tape.color_mode = ColorMode.PER_TRACK
p.tape.monitor = True
p.save(starter)
print("wrote", starter)
PY
fi

# Do not start during image build (no KMS panel). Enable for first boot.
systemctl daemon-reload
if [ "${ENABLE_RK00PI_SERVICE:-1}" = "1" ]; then
	systemctl enable rk00pi.service
	# Appliance boot: console + kiosk, NOT the LXDE desktop.
	# Stage3/04 still ships LightDM for optional lab use, but graphical.target
	# must not win over multi-user — SDL kmsdrm cannot share the panel with X.
	systemctl set-default multi-user.target
	systemctl disable lightdm.service 2>/dev/null || true
	# If something re-enabled graphical (raspi-config, desktop meta), force the symlink.
	ln -sfn /lib/systemd/system/multi-user.target /etc/systemd/system/default.target
	# JACK fights exclusive PCM (when tape uses a card). Hub owns MIDI routing
	# — Patchbox amidiauto *→* races bind_input (EBUSY → unbound din_in).
	systemctl disable jack.service 2>/dev/null || true
	systemctl disable amidiauto.service 2>/dev/null || true
	mkdir -p /etc/systemd/system/rk00pi.service.d
	# Drop-in: fit the hub to this unit's MIDI hardware before the app opens
	# its sequencer clients. The image bakes one hub preset at build time and
	# an endpoint binds by ALSA client *name*, so a build configured for one
	# HAT boots every DIN endpoint unbound on a rig carrying the other — the
	# panel lists the devices and not a note moves. Runs as root (+), never
	# blocks the boot (-), and only rewrites the hub when doing so binds more
	# endpoints than the hub already there.
	if [ "${ENABLE_RK00PI_AUTOHUB:-1}" = "1" ]; then
		cat > /etc/systemd/system/rk00pi.service.d/10-autohub.conf <<'UNIT'
[Service]
ExecStartPre=-+/usr/local/sbin/patchbox-rk00pi-autohub --apply --project /var/lib/rk00pi/projects/starter.rkproj
UNIT
		echo "  autohub drop-in installed (touch /etc/rk00pi/autohub.disabled to opt out)"
	else
		rm -f /etc/systemd/system/rk00pi.service.d/10-autohub.conf
		echo "  ENABLE_RK00PI_AUTOHUB!=1 — hub stays exactly as the preset baked it"
	fi
	# Drop-in: keep desktop audio stacks off the HAT + load starter project
	cat > /etc/systemd/system/rk00pi.service.d/20-tape-starter.conf <<'UNIT'
[Service]
ExecStartPre=+/bin/systemctl stop jack.service
ExecStartPre=+/bin/systemctl stop amidiauto.service
ExecStartPre=-+/usr/bin/pkill -x jackd
ExecStartPre=-+/usr/bin/pkill -u patch -x wireplumber
ExecStartPre=-+/usr/bin/pkill -u patch -x pipewire
ExecStartPre=-+/usr/bin/pkill -u patch -x pipewire-pulse
ExecStart=
ExecStart=/opt/rk00pi/venv/bin/python main.py --fullscreen --config /etc/rk00pi/config.toml --project /var/lib/rk00pi/projects/starter.rkproj
UNIT
	echo "rk00pi.service enabled; multi-user; lightdm/jack/amidiauto disabled; starter hub=${HUB_PRESET_NAME:-pimidi-2x2}"
else
	systemctl disable rk00pi.service 2>/dev/null || true
	echo "rk00pi.service installed but disabled (ENABLE_RK00PI_SERVICE!=1)"
fi

# The Button daemon: package usually enables itself, but be explicit so a
# partial install never leaves a mapped conf with no listener on the GPIO.
if [ "${ENABLE_RK00PI_BUTTON:-1}" = "1" ]; then
	if systemctl cat pisound-btn.service >/dev/null 2>&1; then
		systemctl enable pisound-btn.service
		echo "pisound-btn.service enabled"
	else
		echo "warning: pisound-btn.service not present — The Button will not fire"
	fi
fi
EOF

echo "RK-00pi installed: ${PREFIX}  panel=${W}x${H}  user=${APP_USER}"
