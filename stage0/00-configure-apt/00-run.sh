#!/bin/bash -e

# Default away from raspbian.raspberrypi.com — that host (93.93.128.193)
# frequently times out mid-build. Override with RASPBIAN_MIRROR in config.
RASPBIAN_MIRROR="${RASPBIAN_MIRROR:-http://mirrors.ocf.berkeley.edu/raspbian/raspbian}"
# Trim trailing slash for consistent sed replacement
RASPBIAN_MIRROR="${RASPBIAN_MIRROR%/}"

install -m 644 files/sources.list "${ROOTFS_DIR}/etc/apt/"
install -m 644 files/raspi.list "${ROOTFS_DIR}/etc/apt/sources.list.d/"
install -m 644 files/80retries "${ROOTFS_DIR}/etc/apt/apt.conf.d/80retries"
sed -i "s|RASPBIAN_MIRROR|${RASPBIAN_MIRROR}|g" "${ROOTFS_DIR}/etc/apt/sources.list"
sed -i "s/RELEASE/${RELEASE}/g" "${ROOTFS_DIR}/etc/apt/sources.list"
sed -i "s/RELEASE/${RELEASE}/g" "${ROOTFS_DIR}/etc/apt/sources.list.d/raspi.list"

if [ -n "$APT_PROXY" ]; then
	install -m 644 files/51cache "${ROOTFS_DIR}/etc/apt/apt.conf.d/51cache"
	sed "${ROOTFS_DIR}/etc/apt/apt.conf.d/51cache" -i -e "s|APT_PROXY|${APT_PROXY}|"
else
	rm -f "${ROOTFS_DIR}/etc/apt/apt.conf.d/51cache"
fi

cat files/raspberrypi.gpg.key | gpg --dearmor > "${STAGE_WORK_DIR}/raspberrypi-archive-stable.gpg"
install -m 644 "${STAGE_WORK_DIR}/raspberrypi-archive-stable.gpg" "${ROOTFS_DIR}/etc/apt/trusted.gpg.d/"
on_chroot << EOF
dpkg --add-architecture arm64
apt-get update
apt-get -o Acquire::Retries=5 dist-upgrade -y
EOF
