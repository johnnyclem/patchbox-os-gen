#!/bin/sh
# Raise the realtime scheduling priority of IRQ kernel threads that service
# audio/USB hardware, so they preempt non-audio work under load. Requires
# threadirqs on the kernel cmdline (see stage1/00-boot-files/files/cmdline.txt)
# to make IRQ handlers schedulable threads in the first place. Priority is
# kept below JACK's own rtprio ceiling (95, see 03-install-jack).
set -e

PRIO=90
PATTERN='irq/.*-(snd|xhci_hcd|dwc_otg|usb|pisound)'

ps -eo pid=,comm= | awk -v pat="$PATTERN" '$2 ~ pat { print $1 }' | while read -r pid; do
	chrt -f -p "$PRIO" "$pid" 2>/dev/null || true
done
