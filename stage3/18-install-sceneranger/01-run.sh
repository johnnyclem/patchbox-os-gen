#!/bin/bash -e
# Install SceneRanger — the session clip-launcher appliance.
#
# All the actual logic lives in apps/rangerkit/deploy/install-ranger-app.sh,
# shared by every Ranger stage; this file only names the app. Gated on
# ENABLE_SCENERANGER; whether the *service* boots is RANGER_BOOT_APP's call.

if [ "${ENABLE_SCENERANGER}" != "1" ]; then
	echo "ENABLE_SCENERANGER!=1 — skipping SceneRanger install"
	exit 0
fi

# shellcheck source=/dev/null
. "${BASE_DIR}/apps/rangerkit/deploy/install-ranger-app.sh"
install_ranger_app sceneranger "SceneRanger" \
	"Session clip launcher — scenes, follow actions, chains" \
	"${SCENERANGER_WIDTH}" "${SCENERANGER_HEIGHT}"
