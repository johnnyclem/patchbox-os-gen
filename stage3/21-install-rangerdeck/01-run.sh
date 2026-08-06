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
