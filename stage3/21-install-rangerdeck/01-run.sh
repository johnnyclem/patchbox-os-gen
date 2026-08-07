#!/bin/bash -e
# Install RangerDeck — the Ranger Suite launcher.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_RANGERDECK; whether the *service* boots is RANGER_BOOT_APP's call
# (config.rangers sets RANGER_BOOT_APP=rangerdeck for the launcher build).

if [ "${ENABLE_RANGERDECK}" != "1" ]; then
	echo "ENABLE_RANGERDECK!=1 — skipping RangerDeck install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app rangerdeck "RangerDeck" \
	"Ranger Suite launcher" \
	"${RANGERDECK_WIDTH}" "${RANGERDECK_HEIGHT}"

# POWER tile + channel updates: passwordless systemctl + patchbox-ranger-update.
# Same pattern as stage3/10-install-rk00pi's rk00pi-power sudoers.
SUDOERS_SRC="${BASE_DIR}/apps/rangerdeck/deploy/sudoers.d/rangerdeck-power"
if [ -f "${SUDOERS_SRC}" ]; then
	install -d "${ROOTFS_DIR}/etc/sudoers.d"
	install -m 440 "${SUDOERS_SRC}" \
		"${ROOTFS_DIR}/etc/sudoers.d/rangerdeck-power"
	# visudo-style sanity: drop the file rather than brick sudo if corrupt.
	if command -v visudo >/dev/null 2>&1; then
		if ! visudo -cf "${ROOTFS_DIR}/etc/sudoers.d/rangerdeck-power" \
			>/dev/null 2>&1; then
			echo "WARNING: rangerdeck-power sudoers failed visudo — removed"
			rm -f "${ROOTFS_DIR}/etc/sudoers.d/rangerdeck-power"
		else
			echo "  sudoers: /etc/sudoers.d/rangerdeck-power (power + update)"
		fi
	else
		echo "  sudoers: /etc/sudoers.d/rangerdeck-power (power + update)"
	fi
fi

UPDATE_SRC="${BASE_DIR}/apps/rangerdeck/deploy/patchbox-ranger-update"
if [ -f "${UPDATE_SRC}" ]; then
	install -d "${ROOTFS_DIR}/usr/local/sbin"
	install -m 755 "${UPDATE_SRC}" \
		"${ROOTFS_DIR}/usr/local/sbin/patchbox-ranger-update"
	echo "  update: /usr/local/sbin/patchbox-ranger-update"
fi
# git is needed for apply (shallow clone); check-only uses HTTPS JSON.
on_chroot <<'EOF'
set -e
if ! command -v git >/dev/null 2>&1; then
	apt-get install -y git
fi
EOF
