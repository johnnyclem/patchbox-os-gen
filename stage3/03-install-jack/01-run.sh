#!/bin/bash -e

install -m 644 -D files/95-patchbox-audio.conf "${ROOTFS_DIR}/etc/security/limits.d/95-patchbox-audio.conf"
