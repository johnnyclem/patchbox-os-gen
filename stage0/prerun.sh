#!/bin/bash -e

if [ "$RELEASE" != "bookworm" ]; then
	echo "WARNING: RELEASE does not match the intended option for this branch."
	echo "         Please check the relevant README.md section."
fi

if [ ! -d "${ROOTFS_DIR}" ] || [ "${USE_QCOW2}" = "1" ]; then
	# Match stage0/00-configure-apt default; override via RASPBIAN_MIRROR in config.
	RASPBIAN_MIRROR="${RASPBIAN_MIRROR:-http://mirrors.ocf.berkeley.edu/raspbian/raspbian}"
	RASPBIAN_MIRROR="${RASPBIAN_MIRROR%/}"
	bootstrap ${RELEASE} "${ROOTFS_DIR}" "${RASPBIAN_MIRROR}/"
fi
