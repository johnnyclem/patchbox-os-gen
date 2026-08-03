# install-ranger-app.sh — the one place a Ranger app's install logic lives.
#
# Sourced (not executed) by each app's thin pi-gen stage:
#
#   . "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
#   install_ranger_app midiranger "MidiRanger" "MIDI matrix, arps and note FX" \
#       "${MIDIRANGER_WIDTH}" "${MIDIRANGER_HEIGHT}"
#
# Layout per app, identical to stage3/13-install-chordranger's by design:
#   /opt/<app>              app + vendored rangerkit + venv
#   /var/lib/<app>          writable data (subdirs from deploy/datadirs.txt)
#   /etc/<app>/config.toml  panel size + paths + MIDI + button/pots maps
#   <app>.service           kiosk unit rendered from ranger.service.template
#
# The stage gates on ENABLE_<APP> before calling. Whether the *service* boots
# is a separate, single knob: RANGER_BOOT_APP names the one kiosk unit to
# enable; everything else is installed disabled and swapped on the device
# with `patchbox-app enable <app>`.
#
# Expects the pi-gen stage environment: BASE_DIR, ROOTFS_DIR, FIRST_USER_NAME,
# HOSTNAME, on_chroot, and the display profile variables.

RANGERKIT_SRC="${BASE_DIR}/apps/rangerkit"

resolve_panel_geometry() { # $1 explicit width, $2 explicit height
	# An explicit override wins, then the HyperPixel profile, then the HDMI
	# bar — the same order stage3/10-install-rk00pi established, so no two
	# apps ever disagree about what they are drawing on.
	if [ -n "${1}" ] && [ -n "${2}" ]; then
		RANGER_W="${1}"
		RANGER_H="${2}"
	elif [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
		RANGER_W="${HYPERPIXEL_WIDTH:-800}"
		RANGER_H="${HYPERPIXEL_HEIGHT:-480}"
	else
		RANGER_W="${HDMI_WIDTH:-1280}"
		RANGER_H="${HDMI_HEIGHT:-400}"
	fi
}

kiosk_conflicts_for() { # $1 app -> "a.service b.service ..." minus the app
	grep -Ev '^\s*(#|$)' "${RANGERKIT_SRC}/deploy/kiosk-units.txt" \
		| grep -vx "${1}" \
		| sed 's/$/.service/' \
		| tr '\n' ' ' \
		| sed 's/ $//'
}

install_ranger_app() { # $1 app, $2 title, $3 description, $4 width, $5 height
	local APP="$1" APP_TITLE="$2" DESCRIPTION="$3"
	local APP_SRC="${BASE_DIR}/apps/${APP}"
	local PREFIX="/opt/${APP}"
	local DATA_DIR="/var/lib/${APP}"
	local CONFIG_DIR="/etc/${APP}"
	local APP_USER="${APP}"

	if [ ! -f "${APP_SRC}/main.py" ] || [ ! -f "${APP_SRC}/deploy/config.toml" ]; then
		echo "ERROR: ${APP} source missing or incomplete at ${APP_SRC}"
		return 1
	fi
	if [ ! -d "${RANGERKIT_SRC}" ]; then
		echo "ERROR: rangerkit missing at ${RANGERKIT_SRC}"
		return 1
	fi

	resolve_panel_geometry "${4}" "${5}"
	echo "Installing ${APP_TITLE} → ${PREFIX} (${RANGER_W}x${RANGER_H} panel)"

	# --- app tree + vendored rangerkit ---------------------------------------
	install -d "${ROOTFS_DIR}${PREFIX}"
	if command -v rsync >/dev/null 2>&1; then
		rsync -a --delete \
			--exclude '.git/' \
			--exclude 'venv/' \
			--exclude '__pycache__/' \
			--exclude '*.pyc' \
			--exclude '.pytest_cache/' \
			--exclude 'data/projects/' \
			"${APP_SRC}/" "${ROOTFS_DIR}${PREFIX}/"
		# Each app carries its own frozen copy of the kit, so one app can be
		# updated or rolled back without moving the ground under its siblings.
		rsync -a --delete \
			--exclude '__pycache__/' --exclude '*.pyc' \
			--exclude 'tests/' --exclude 'ci/' --exclude 'deploy/' \
			--exclude 'docs/' \
			"${RANGERKIT_SRC}/" "${ROOTFS_DIR}${PREFIX}/rangerkit/"
	else
		# Fallback: selective copy (rsync is in 00-packages for the rootfs,
		# and a macOS host building under Docker may not have it either).
		cp -a "${APP_SRC}/main.py" "${APP_SRC}/requirements.txt" \
			"${APP_SRC}/requirements.lock" "${APP_SRC}/README.md" \
			"${ROOTFS_DIR}${PREFIX}/" 2>/dev/null || true
		local d
		for d in core gui data deploy docs bench tests; do
			if [ -d "${APP_SRC}/${d}" ]; then
				rm -rf "${ROOTFS_DIR}${PREFIX:?}/${d}"
				cp -a "${APP_SRC}/${d}" "${ROOTFS_DIR}${PREFIX}/"
			fi
		done
		rm -rf "${ROOTFS_DIR}${PREFIX:?}/rangerkit"
		cp -a "${RANGERKIT_SRC}" "${ROOTFS_DIR}${PREFIX}/rangerkit"
		rm -rf "${ROOTFS_DIR}${PREFIX}/rangerkit/tests" \
			"${ROOTFS_DIR}${PREFIX}/rangerkit/ci" \
			"${ROOTFS_DIR}${PREFIX}/rangerkit/deploy" \
			"${ROOTFS_DIR}${PREFIX}/rangerkit/docs"
		find "${ROOTFS_DIR}${PREFIX}" -type d -name '__pycache__' \
			-exec rm -rf {} + 2>/dev/null || true
	fi

	# Record which commit was baked, so a unit in the field can be asked what
	# it is running instead of being guessed at from a directory listing.
	if [ -d "${BASE_DIR}/.git" ] || [ -f "${BASE_DIR}/.git" ]; then
		git -C "${BASE_DIR}" rev-parse HEAD 2>/dev/null \
			> "${ROOTFS_DIR}${PREFIX}/.patchbox-source-commit" || true
	fi

	# --- data partition ------------------------------------------------------
	install -d "${ROOTFS_DIR}${DATA_DIR}"
	if [ -f "${APP_SRC}/deploy/datadirs.txt" ]; then
		local subdir
		while IFS= read -r subdir; do
			case "${subdir}" in ''|'#'*) continue ;; esac
			install -d "${ROOTFS_DIR}${DATA_DIR}/${subdir}"
		done < "${APP_SRC}/deploy/datadirs.txt"
	else
		install -d "${ROOTFS_DIR}${DATA_DIR}/projects" \
			"${ROOTFS_DIR}${DATA_DIR}/presets"
	fi

	# --- config.toml for this panel ------------------------------------------
	install -d "${ROOTFS_DIR}${CONFIG_DIR}"
	install -m 644 "${APP_SRC}/deploy/config.toml" \
		"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"
	sed -i \
		-e "s/^width = .*/width = ${RANGER_W}/" \
		-e "s/^height = .*/height = ${RANGER_H}/" \
		-e "s|^data_dir = .*|data_dir = \"${DATA_DIR}\"|" \
		-e "s|^presets_dir = .*|presets_dir = \"${DATA_DIR}/presets\"|" \
		"${ROOTFS_DIR}${CONFIG_DIR}/config.toml"

	# --- systemd unit from the shared template -------------------------------
	local CONFLICTS
	CONFLICTS="$(kiosk_conflicts_for "${APP}")"
	install -d "${ROOTFS_DIR}/usr/lib/systemd/system"
	sed \
		-e "s/@APP@/${APP}/g" \
		-e "s/@APP_TITLE@/${APP_TITLE}/g" \
		-e "s/@DESCRIPTION@/${DESCRIPTION}/g" \
		-e "s/@KIOSK_CONFLICTS@/${CONFLICTS}/g" \
		"${RANGERKIT_SRC}/deploy/ranger.service.template" \
		> "${ROOTFS_DIR}/usr/lib/systemd/system/${APP}.service"
	chmod 644 "${ROOTFS_DIR}/usr/lib/systemd/system/${APP}.service"

	# --- The Button bridge ---------------------------------------------------
	# Client and wrappers are always installed; /etc/pisound.conf is only
	# rewritten by `patchbox-app enable`, so installing a new app never
	# silently steals the button from whichever app currently boots.
	local BUTTON_SRC="${APP_SRC}/deploy/pisound"
	if [ -f "${BUTTON_SRC}/${APP}-btn" ]; then
		install -d "${ROOTFS_DIR}/usr/local/bin"
		install -m 755 "${BUTTON_SRC}/${APP}-btn" \
			"${ROOTFS_DIR}/usr/local/bin/${APP}-btn"
		install -d "${ROOTFS_DIR}/usr/local/pisound/scripts/pisound-btn"
		install -m 755 "${BUTTON_SRC}/${APP}"_*.sh \
			"${ROOTFS_DIR}/usr/local/pisound/scripts/pisound-btn/"
		echo "  button client + wrappers installed"
	else
		echo "  note: ${BUTTON_SRC}/${APP}-btn missing — button not wired"
	fi

	# --- note for the login user ---------------------------------------------
	local APP_UPPER
	APP_UPPER="$(echo "${APP}" | tr '[:lower:]' '[:upper:]')"
	install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
	cat > "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/${APP_UPPER}.txt" <<EOF
Patchbox OS — ${APP_TITLE} (${DESCRIPTION})
============================================================

One panel, one app at a time
  Every Ranger app (and RK-00pi) takes the display under SDL kmsdrm, so
  exactly one runs. Swap with:

    patchbox-app status
    sudo patchbox-app enable ${APP}
    sudo patchbox-app disable          # back to the default app

Paths
  app:     ${PREFIX}
  data:    ${DATA_DIR}
  config:  ${CONFIG_DIR}/config.toml
  socket:  /run/${APP}/button.sock
  unit:    systemctl status ${APP}

Checks
  patchbox-app status
  journalctl -u ${APP} -b -n 80
  amidi -l ; aplay -l

Run it by hand (with the service stopped)
  sudo systemctl stop ${APP}
  sudo -u ${APP_USER} ${PREFIX}/venv/bin/python ${PREFIX}/main.py \\
      --config ${CONFIG_DIR}/config.toml --fullscreen

SSH
  ssh ${FIRST_USER_NAME}@${HOSTNAME}.local
EOF
	chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/${APP_UPPER}.txt" \
		2>/dev/null || true

	# --- user, groups, venv, unit (inside the rootfs) ------------------------
	local BOOT_THIS=0
	[ "${RANGER_BOOT_APP:-rk00pi}" = "${APP}" ] && BOOT_THIS=1
	# shellcheck disable=SC2086
	on_chroot << EOF
set -e
APP='${APP}'
APP_USER='${APP_USER}'
PREFIX='${PREFIX}'
DATA_DIR='${DATA_DIR}'
CONFIG_DIR='${CONFIG_DIR}'

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
chown root:"\${APP_USER}" "\${CONFIG_DIR}" "\${CONFIG_DIR}/config.toml" 2>/dev/null || true
chmod 755 "\${CONFIG_DIR}"
chmod 644 "\${CONFIG_DIR}/config.toml"

# venv without system-site-packages: a stale distro pygame is the classic
# cause of a black panel that logs nothing useful.
if [ ! -x "\${PREFIX}/venv/bin/python" ]; then
	echo "creating venv at \${PREFIX}/venv"
	sudo -u "\${APP_USER}" python3 -m venv "\${PREFIX}/venv"
fi

PIP="\${PREFIX}/venv/bin/pip"
echo "pip install \${APP} dependencies (slow under qemu — hang tight)"
sudo -u "\${APP_USER}" "\${PIP}" install --upgrade pip wheel
if ! sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir -r "\${PREFIX}/requirements.lock"; then
	echo "requirements.lock failed — installing floors from requirements.txt"
	while IFS= read -r floor; do
		case "\${floor}" in ''|'#'*) continue ;; esac
		if printf '%s' "\${floor}" | grep -q '^pygame'; then
			sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "\${floor}" || {
				echo "ERROR: pygame failed — the panel cannot start"
				exit 1
			}
		else
			sudo -u "\${APP_USER}" "\${PIP}" install --no-cache-dir "\${floor}" || \
				echo "warning: optional \${floor} not installed"
		fi
	done < "\${PREFIX}/requirements.txt"
fi

# Smoke test the import path while we still have a build log to read it in.
sudo -u "\${APP_USER}" "\${PREFIX}/venv/bin/python" - <<PY || echo "warning: import smoke test failed"
import sys
sys.path.insert(0, "\${PREFIX}")
import rangerkit.enginebase
import core.engine
print("  \${APP}: core + rangerkit import ok")
PY

systemctl daemon-reload
if [ "${BOOT_THIS}" = "1" ]; then
	# This app boots: stand every sibling kiosk unit down first so nothing
	# races it for the panel. (patchbox-app enable does the same on-device.)
	for unit in ${CONFLICTS}; do
		systemctl disable "\${unit}" 2>/dev/null || true
	done
	systemctl enable "\${APP}.service"
	systemctl set-default multi-user.target
	echo "\${APP}.service enabled (siblings disabled)"
else
	systemctl disable "\${APP}.service" 2>/dev/null || true
	echo "\${APP}.service installed but not enabled"
	echo "  enable on the device with: sudo patchbox-app enable \${APP}"
fi
EOF

	echo "${APP_TITLE} installed: ${PREFIX}  panel=${RANGER_W}x${RANGER_H}  user=${APP_USER}"
}
