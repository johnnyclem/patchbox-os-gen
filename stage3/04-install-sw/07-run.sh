#!/bin/bash -e

cp -p files/patchbox-first-run.sh "${ROOTFS_DIR}/etc/profile.d/"
cp -p files/21-patchbox-useful-resources "${ROOTFS_DIR}/etc/update-motd.d/"
rm -f "${ROOTFS_DIR}/etc/motd"
rm -f "${ROOTFS_DIR}/etc/profile.d/sshpwd.sh" "${ROOTFS_DIR}/etc/profile.d/wifi-country.sh"
