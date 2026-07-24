#!/bin/bash -e

# Opt-in PREEMPT_RT kernel install. Off by default: the stock kernel plus
# threadirqs + IRQ priorities + rtprio/memlock limits (see
# stage1/00-boot-files, stage3/02-install-pisound, stage3/03-install-jack)
# already delivers most of the latency win with far less driver-compat and
# thermal/throughput risk. Set RT_KERNEL_VERSION to a package name available
# in the configured apt repos (verify with `apt-cache policy <name>` in a
# chroot first) to install it.
if [ -z "${RT_KERNEL_VERSION}" ]; then
	exit 0
fi

on_chroot << EOF
	apt-get update
	apt-get install -y "${RT_KERNEL_VERSION}"
EOF
