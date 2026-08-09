#!/bin/bash -e
# First-boot / field setup: patchbox-setup + Patchbox modules for
# rangerdeck / rk00pi, so a burned image can be configured like MODEP.
#
# Always runs (no ENABLE_ gate): every product image should be able to
# pick display, MIDI, ranger tiles, and the default boot app without
# rebuilding.

echo "Installing patchbox-setup + ranger/rk00pi modules"

install -d "${ROOTFS_DIR}/usr/local/bin"
install -m 755 files/patchbox-setup \
	"${ROOTFS_DIR}/usr/local/bin/patchbox-setup"

install -d "${ROOTFS_DIR}/usr/local/sbin"
# Symlink for people who look under sbin for "system" tools
ln -sfn /usr/local/bin/patchbox-setup \
	"${ROOTFS_DIR}/usr/local/sbin/patchbox-setup"

# --- Patchbox modules (appear in `patchbox` → modules, like MODEP) ---------
# Source lives in repo-root modules/ — NOT under deploy/ (gitignored +
# dockerignored, so a path there never reaches the pi-gen image).
MODULES_SRC="${BASE_DIR}/modules"
MODULES_DST="${ROOTFS_DIR}/usr/local/patchbox-modules"
install -d "${MODULES_DST}"

if [ ! -d "${MODULES_SRC}" ]; then
	echo "WARNING: ${MODULES_SRC} missing — rangerdeck/rk00pi modules not shipped"
else
	for mod in rangerdeck rk00pi; do
		if [ ! -f "${MODULES_SRC}/${mod}/patchbox-module.json" ]; then
			echo "WARNING: module source missing: ${MODULES_SRC}/${mod}"
			continue
		fi
		install -d "${MODULES_DST}/${mod}"
		install -m 644 "${MODULES_SRC}/${mod}/patchbox-module.json" \
			"${MODULES_DST}/${mod}/"
		for script in install.sh launch.sh stop.sh; do
			if [ -f "${MODULES_SRC}/${mod}/${script}" ]; then
				install -m 755 "${MODULES_SRC}/${mod}/${script}" \
					"${MODULES_DST}/${mod}/"
			fi
		done
		echo "  module: /usr/local/patchbox-modules/${mod}"
	done
fi

# --- Always-on display helpers (so display set works without re-bake) ------
# Overlays + fix scripts from the profile stages, even when that profile
# was not the bake-time panel.
WS_FILES="${BASE_DIR}/stage3/08-install-waveshare-dpi/files"
HP_FILES="${BASE_DIR}/stage3/12-install-hyperpixel4/files"
HDMI_FILES="${BASE_DIR}/stage3/09-hdmi-ultrawide/files"

if [ -d "${WS_FILES}/overlays" ]; then
	install -d "${ROOTFS_DIR}/boot/firmware/overlays"
	install -m 644 "${WS_FILES}/overlays/"*.dtbo \
		"${ROOTFS_DIR}/boot/firmware/overlays/" 2>/dev/null || true
	echo "  waveshare dtbo overlays installed (for on-device switch)"
fi
if [ -f "${WS_FILES}/patchbox-fix-waveshare-dpi" ]; then
	install -m 755 "${WS_FILES}/patchbox-fix-waveshare-dpi" \
		"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-waveshare-dpi"
fi
if [ -f "${HP_FILES}/patchbox-fix-hyperpixel4" ]; then
	install -m 755 "${HP_FILES}/patchbox-fix-hyperpixel4" \
		"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-hyperpixel4"
fi
if [ -f "${HP_FILES}/patchbox-hyperpixel-status" ]; then
	install -m 755 "${HP_FILES}/patchbox-hyperpixel-status" \
		"${ROOTFS_DIR}/usr/local/bin/patchbox-hyperpixel-status"
fi
# HDMI status tool may already be installed by stage 09; install if missing
if [ -f "${HDMI_FILES}/patchbox-display-status" ] \
	&& [ ! -f "${ROOTFS_DIR}/usr/local/bin/patchbox-display-status" ]; then
	install -m 755 "${HDMI_FILES}/patchbox-display-status" \
		"${ROOTFS_DIR}/usr/local/bin/patchbox-display-status"
fi
if [ -f "${HDMI_FILES}/patchbox-touch-probe" ] \
	&& [ ! -f "${ROOTFS_DIR}/usr/local/bin/patchbox-touch-probe" ]; then
	install -m 755 "${HDMI_FILES}/patchbox-touch-probe" \
		"${ROOTFS_DIR}/usr/local/bin/patchbox-touch-probe"
fi
# Waveshare 7.9 field fixer (native 400×1280, no kernel rotate)
if [ -f "${BASE_DIR}/scripts/fix-waveshare79-bootfs.sh" ]; then
	install -m 755 "${BASE_DIR}/scripts/fix-waveshare79-bootfs.sh" \
		"${ROOTFS_DIR}/usr/local/sbin/patchbox-fix-waveshare79"
	echo "  field fix: patchbox-fix-waveshare79"
fi

# --- Seed patchbox module state for the bake-time boot app -----------------
# So `patchbox module active` and switching to MODEP correctly stop our
# kiosk instead of racing two DRM masters.
STATE_DIR="${ROOTFS_DIR}/var/patchbox"
install -d "${STATE_DIR}"
BOOT_APP="${RANGER_BOOT_APP:-rk00pi}"
ACTIVE_PATH=""
case "${BOOT_APP}" in
	rangerdeck)
		if [ -d "${MODULES_DST}/rangerdeck" ]; then
			ACTIVE_PATH="/usr/local/patchbox-modules/rangerdeck/"
		fi
		;;
	rk00pi)
		if [ -d "${MODULES_DST}/rk00pi" ]; then
			ACTIVE_PATH="/usr/local/patchbox-modules/rk00pi/"
		fi
		;;
esac

# Minimal state file: mark both modules installed; set active when known.
python3 - "${STATE_DIR}/state.json" "${ACTIVE_PATH}" <<'PY' || true
import json, sys
path, active = sys.argv[1], sys.argv[2]
modules = {
    "/usr/local/patchbox-modules/rangerdeck/": {
        "installed": True,
        "version": "1.0.0",
    },
    "/usr/local/patchbox-modules/rk00pi/": {
        "installed": True,
        "version": "1.0.0",
    },
}
data = {
    "type": "PatchboxModuleManagerStateFile",
    "modules": modules,
    "active_module": active or None,
}
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("  patchbox state: active_module =", active or "none")
PY

# --- User-facing docs ------------------------------------------------------
install -d "${ROOTFS_DIR}/home/${FIRST_USER_NAME}"
install -m 644 files/SETUP.txt \
	"${ROOTFS_DIR}/home/${FIRST_USER_NAME}/SETUP.txt"
chown 1000:1000 "${ROOTFS_DIR}/home/${FIRST_USER_NAME}/SETUP.txt" \
	2>/dev/null || true

# MOTD pointer (idempotent append)
MOTD="${ROOTFS_DIR}/etc/update-motd.d/22-patchbox-setup"
cat > "${MOTD}" <<'EOF'
#!/bin/sh
echo "Rangers / RK-00pi setup:  sudo patchbox-setup wizard"
echo "Status:                   patchbox-setup status"
echo "Docs:                     ~/SETUP.txt"
echo
EOF
chmod 755 "${MOTD}"

# Do NOT auto-launch the interactive setup wizard on login.
# An interactive `sudo patchbox-setup wizard` on console-autologin races the
# kiosk for the TTY (and confuses headless boots). MOTD + ~/SETUP.txt point
# operators at the command; first-run only prints a one-shot reminder.
FIRST_RUN="${ROOTFS_DIR}/etc/profile.d/zz-patchbox-setup-hint.sh"
cat > "${FIRST_RUN}" <<'EOF'
#!/bin/sh
# One-shot reminder — never blocks the kiosk or runs sudo prompts.
if [ ! -e ~/.config/patchbox-setup-hint-shown ]; then
	mkdir -p ~/.config 2>/dev/null || true
	touch ~/.config/patchbox-setup-hint-shown 2>/dev/null || true
	if [ -x /usr/local/bin/patchbox-setup ]; then
		echo
		echo ">>> Display / MIDI / Rangers / boot app:"
		echo ">>>   sudo patchbox-setup wizard"
		echo ">>>   patchbox-setup status"
		echo ">>> Docs: ~/SETUP.txt"
		echo
	fi
fi
EOF
chmod 644 "${FIRST_RUN}"

# State dir for the tool
install -d "${ROOTFS_DIR}/var/lib/patchbox-setup"
install -d "${ROOTFS_DIR}/var/lib/rangerdeck"

# Seed enabled-apps from bake-time ENABLE_* flags so a partial suite image
# only shows what was installed.
ENABLED_LIST=""
for app in chordranger midiranger genranger phraseranger sceneranger grooveranger synthranger; do
	var="ENABLE_$(echo "${app}" | tr '[:lower:]' '[:upper:]')"
	# indirect expand: ENABLE_CHORDRANGER etc.
	eval "val=\${${var}:-1}"
	if [ "${val}" = "1" ]; then
		ENABLED_LIST="${ENABLED_LIST}${ENABLED_LIST:+ }${app}"
	fi
done
if [ -n "${ENABLED_LIST}" ]; then
	# shellcheck disable=SC2086
	printf '%s\n' ${ENABLED_LIST} > \
		"${ROOTFS_DIR}/var/lib/rangerdeck/enabled-apps.txt"
	echo "  ranger tiles seed: ${ENABLED_LIST}"
fi

echo "patchbox-setup installed — first boot: sudo patchbox-setup wizard"
