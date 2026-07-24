#!/bin/bash -e

install -d "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d"
install -m 644 files/noclear.conf "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d/noclear.conf"
install -v -m 644 files/fstab "${ROOTFS_DIR}/etc/fstab"

on_chroot << EOF
if ! id -u ${FIRST_USER_NAME} >/dev/null 2>&1; then
	adduser --disabled-password --gecos "" ${FIRST_USER_NAME}
fi

if [ -n "${FIRST_USER_PASS}" ]; then
	echo "${FIRST_USER_NAME}:${FIRST_USER_PASS}" | chpasswd
fi
if [ "${ENABLE_FIRST_LOGIN_PASSWORD_CHANGE}" = "1" ]; then
	chage -d 0 ${FIRST_USER_NAME}
fi
# root stays locked (debootstrap default); export-image/05-finalise already
# locks it again defensively (`usermod --pass='*' root`). Previously this
# script set a temporary root:root password here, which meant any
# intermediate/aborted build artifact carried a known root password until
# the finalise stage ran.
EOF


