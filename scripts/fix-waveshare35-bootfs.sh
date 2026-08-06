#!/usr/bin/env bash
# fix-waveshare35-bootfs.sh — convert a flashed Patchbox SD *boot* partition
# from HDMI Profile A → Waveshare 3.5" DPI 640×480, without booting the Pi.
#
# Why: deploy/2026-08-06-Patchbox.img (and other Profile A / Rangers builds)
# force HDMI 1280×400. The Waveshare stage is skipped
#   ENABLE_WAVESHARE_DPI!=1 — skipping Waveshare 3.5 DPI setup
# so there is no dtoverlay=waveshare-35dpi, no vendor DTBOs, and the GPIO
# panel stays completely dark (DPI is not HDMI).
#
# Usage (macOS, SD card inserted):
#   ./scripts/fix-waveshare35-bootfs.sh
#   ./scripts/fix-waveshare35-bootfs.sh /Volumes/bootfs
#   ./scripts/fix-waveshare35-bootfs.sh --keep-pimidi /Volumes/bootfs
#
# Default strips dtoverlay=pimidi so the panel can light on first boot.
# Pimidi under this DPI HAT is experimental (pinmux fight). Pass
# --keep-pimidi only after the glass paints, if you need TRS MIDI on the
# same header.
#
# Then eject the card, boot the Pi. On-device checks:
#   patchbox-display-status          # if helpers were on the image
#   ls /sys/class/drm/card*-DPI-1
#   sudo pinctrl set 18 op dh        # force backlight if image is there but dark
set -euo pipefail

KEEP_PIMIDI=0
BOOTFS=""
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OVL_SRC="${ROOT}/stage3/08-install-waveshare-dpi/files/overlays"

while [ $# -gt 0 ]; do
	case "$1" in
		--keep-pimidi) KEEP_PIMIDI=1; shift ;;
		--no-pimidi) KEEP_PIMIDI=0; shift ;;
		-h|--help)
			sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			BOOTFS=$1
			shift
			;;
	esac
done

if [ -z "$BOOTFS" ]; then
	for cand in /Volumes/bootfs /Volumes/boot /media/*/bootfs /media/*/boot; do
		if [ -f "${cand}/config.txt" ]; then
			BOOTFS=$cand
			break
		fi
	done
fi

[ -n "$BOOTFS" ] || { echo "boot partition not found — pass path (e.g. /Volumes/bootfs)"; exit 1; }
CFG="$BOOTFS/config.txt"
CMD="$BOOTFS/cmdline.txt"
OVL_DST="$BOOTFS/overlays"
[ -f "$CFG" ] || { echo "missing $CFG"; exit 1; }
[ -d "$OVL_SRC" ] || { echo "missing vendor overlays at $OVL_SRC"; exit 1; }

TS=$(date +%Y%m%d%H%M%S)
cp -a "$CFG" "${CFG}.bak.${TS}"
[ -f "$CMD" ] && cp -a "$CMD" "${CMD}.bak.${TS}"

echo "target: $BOOTFS"
echo "keep_pimidi=${KEEP_PIMIDI}"
echo "before (display lines):"
grep -nE 'waveshare|hyperpixel|hdmi_|pimidi|i2c_arm|vc4-kms|dpi' "$CFG" || true

# Install vendor DTBOs (Profile A images never had these)
mkdir -p "$OVL_DST"
for f in waveshare-35dpi.dtbo waveshare-touch-35dpi.dtbo vc4-kms-DPI-35inch.dtbo \
	waveshare-35dpi-3b-4b.dtbo waveshare-35dpi-3b.dtbo waveshare-35dpi-4b.dtbo; do
	if [ -f "$OVL_SRC/$f" ]; then
		cp -f "$OVL_SRC/$f" "$OVL_DST/$f"
		echo "  installed overlays/$f"
	else
		echo "  WARNING: missing source $OVL_SRC/$f"
	fi
done

TMP=$(mktemp)
while IFS= read -r line || [ -n "$line" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "$s" in
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*)
			continue ;;
		dtoverlay=vc4-kms-DPI-35inch*|dtoverlay=waveshare-35dpi-3b*|dtoverlay=waveshare-35dpi-4b*)
			continue ;;
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*|dtoverlay=vc4-kms-dpi-generic*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			continue ;;
		dtoverlay=spi0-0cs*|dtoverlay=wm8960-soundcard*|dtoverlay=googlevoicehat*)
			continue ;;
		dtparam=spi=on)
			echo "#dtparam=spi=on"
			continue ;;
		dtparam=i2s=on)
			echo "#dtparam=i2s=on"
			continue ;;
		dtoverlay=pimidi*|dtparam=i2c_arm=*|dtparam=i2c_arm_baudrate=*)
			if [ "${KEEP_PIMIDI}" = "1" ]; then
				:
			else
				continue
			fi
			;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*)
			continue ;;
		*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*)
			continue ;;
		*'--- Pimidi'*|*'--- end Pimidi'*)
			if [ "${KEEP_PIMIDI}" = "1" ]; then
				:
			else
				continue
			fi
			;;
	esac
	printf '%s\n' "$line"
done < "$CFG" > "$TMP"

grep -qE '^dtoverlay=vc4-kms-v3d' "$TMP" || echo "dtoverlay=vc4-kms-v3d" >> "$TMP"
grep -qE '^dtparam=i2c_arm=on' "$TMP" || echo "dtparam=i2c_arm=on" >> "$TMP"
grep -qE '^max_framebuffers=' "$TMP" || echo "max_framebuffers=2" >> "$TMP"

cat >> "$TMP" <<EOF

# --- Waveshare 3.5 DPI LCD (bootfs fix ${TS}) ---
# Bookworm: https://www.waveshare.com/wiki/3.5inch_DPI_LCD
# DTBO files installed to overlays/ by fix-waveshare35-bootfs.sh
dtoverlay=waveshare-35dpi
dtoverlay=waveshare-touch-35dpi
# Fallback if still black after reboot (uncomment ONE line):
#dtoverlay=vc4-kms-DPI-35inch
#dtoverlay=waveshare-35dpi-3b-4b
# --- end Waveshare ---
EOF
cat "$TMP" > "$CFG"
rm -f "$TMP"

if [ -f "$CMD" ]; then
	# portable: no sed -i — strip forced HDMI bar modes, force DPI-1 640×480
	tr -d '\n' < "$CMD" \
		| sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' \
		| tr -s ' ' | sed 's/^ //;s/ $//' > "${CMD}.1"
	# Prepend DPI mode (Waveshare Bookworm lite rotation path)
	{ printf 'video=DPI-1:640x480M@60 '; cat "${CMD}.1"; echo; } > "$CMD"
	rm -f "${CMD}.1"
fi

echo
echo "after:"
grep -nE 'waveshare|hyperpixel|hdmi_|pimidi|i2c_arm|vc4-kms|dpi' "$CFG" || true
[ -f "$CMD" ] && echo "cmdline: $(tr -d '\n' < "$CMD")"
echo
echo "Wrote dtoverlay=waveshare-35dpi + waveshare-touch-35dpi  (keep_pimidi=${KEEP_PIMIDI})"
echo "Eject the SD card, boot the Pi (wait ~30s for first paint)."
echo
echo "If still black after boot (SSH):"
echo "  1) sudo pinctrl set 18 op dh"
echo "  2) ls /sys/class/drm/card*-*  # look for DPI-1 status=connected"
echo "  3) dmesg | grep -iE 'dpi|waveshare|panel|goodix|vc4'"
echo "  4) uncomment dtoverlay=vc4-kms-DPI-35inch in config.txt, reboot"
echo "  5) if you used --keep-pimidi, re-run WITHOUT it (Pimidi pinmux fight)"
echo
echo "Proper re-bake later:  ./build-docker.sh -c config.waveshare35-pimidi"
