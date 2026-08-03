#!/bin/bash -e
# Ranger family shared tooling: the patchbox-app kiosk switcher.
#
# rangerkit itself (apps/rangerkit) is NOT installed standalone — each Ranger
# app's install stage vendors its own frozen copy into /opt/<app>/rangerkit,
# so one app can be updated or rolled back without moving the ground under
# its siblings. This stage only ships what is genuinely global: the CLI that
# swaps which kiosk app owns the panel.
#
# Installed whenever any Ranger app (or RK-00pi/ChordRanger) is, i.e. always:
# the CLI is harmless without apps and the image is not built without them.

install -d "${ROOTFS_DIR}/usr/local/bin"
install -m 755 files/patchbox-app "${ROOTFS_DIR}/usr/local/bin/patchbox-app"
echo "patchbox-app installed (kiosk switcher for the Ranger family)"
