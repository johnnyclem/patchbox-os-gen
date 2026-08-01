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

W="${RK00PI_WIDTH:-${HDMI_WIDTH:-1280}}"
H="${RK00PI_HEIGHT:-${HDMI_HEIGHT:-400}}"
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

# --- systemd unit ------------------------------------------------------------
# Includes RuntimeDirectory=rk00pi for The Button socket (/run/rk00pi/button.sock).
install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
install -m 644 "${RK_SRC}/deploy/rk00pi.service" \
	"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
if [ "${APP_USER}" != "rk00pi" ]; then
	sed -i "s/^User=rk00pi$/User=${APP_USER}/" \
		"${ROOTFS_DIR}/usr/lib/systemd/system/rk00pi.service"
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

# Brief note for the login user (alongside DISPLAY-PISOUND.txt)
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/RK-00PI.txt" <<EOF
Patchbox OS — RK-00pi (main appliance)
======================================

What boots
  multi-user.target → rk00pi.service
  SDL_VIDEODRIVER=kmsdrm fullscreen on the HDMI ${W}x${H} panel
  Pisound = MIDI DIN + 1/4" audio (prefer_pisound=true)

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

Update app later (on device, as root)
  cd /opt/rk00pi && git pull   # only if you re-init a git remote
  # or re-flash / re-run deploy/install.sh from a checkout

Gates
  driver ships as "null" — do NOT wire GPIO to eurorack without a
  buffered/level-shifted stage. See /opt/rk00pi/docs/deploy.md

Desktop (optional)
  Patchbox still ships the LXDE stack. Default boot is console + RK-00pi.
  To open the desktop:  sudo systemctl start lightdm
  (kmsdrm and X cannot both own the panel — stop rk00pi first if needed)

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

for group in audio gpio render video; do
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

# Do not start during image build (no KMS panel). Enable for first boot.
systemctl daemon-reload
if [ "${ENABLE_RK00PI_SERVICE:-1}" = "1" ]; then
	systemctl enable rk00pi.service
	# Console + kiosk is already multi-user (stage3/01-misc-config).
	systemctl set-default multi-user.target
	echo "rk00pi.service enabled (WantedBy=multi-user.target)"
else
	systemctl disable rk00pi.service 2>/dev/null || true
	echo "rk00pi.service installed but disabled (ENABLE_RK00PI_SERVICE!=1)"
fi
EOF

echo "RK-00pi installed: ${PREFIX}  panel=${W}x${H}  user=${APP_USER}"
