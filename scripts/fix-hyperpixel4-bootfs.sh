#!/usr/bin/env bash
# fix-hyperpixel4-bootfs.sh — convert a flashed Patchbox SD *boot* partition
# from HDMI Profile A → HyperPixel 4 DPI, without booting the Pi.
#
# Why: image_2026-08-03 and other Profile A builds force HDMI 1280×400 +
# Pimidi. HyperPixel never gets dtoverlay=vc4-kms-dpi-hyperpixel4, so you
# only see backlight then black.
#
# Usage (macOS, SD card inserted):
#   ./scripts/fix-hyperpixel4-bootfs.sh
#   ./scripts/fix-hyperpixel4-bootfs.sh /Volumes/bootfs
#   ./scripts/fix-hyperpixel4-bootfs.sh --rotate 270 /Volumes/bootfs
#   ./scripts/fix-hyperpixel4-bootfs.sh --rotate none /Volumes/bootfs  # black-screen only
#
# Default --rotate is left/270 so the FB is landscape 800×480 (matches the app).
# none leaves a portrait 480×800 mode (panel may paint but UI is sideways).
#
# Then eject the card, boot the Pi, and run: patchbox-hyperpixel-status
set -euo pipefail

ROT="left"
BOOTFS=""

while [ $# -gt 0 ]; do
	case "$1" in
		--rotate) ROT=$2; shift 2 ;;
		-h|--help)
			sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
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
[ -f "$CFG" ] || { echo "missing $CFG"; exit 1; }

TS=$(date +%Y%m%d%H%M%S)
cp -a "$CFG" "${CFG}.bak.${TS}"
[ -f "$CMD" ] && cp -a "$CMD" "${CMD}.bak.${TS}"

echo "target: $BOOTFS"
echo "before (display lines):"
grep -nE 'hyperpixel|hdmi_|pimidi|i2c_arm|vc4-kms' "$CFG" || true

OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4"
case "$ROT" in
	none|"") OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4" ;;
	0|normal) OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=0" ;;
	90|right) OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=90" ;;
	180|inverted) OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=180" ;;
	270|left) OVERLAY="dtoverlay=vc4-kms-dpi-hyperpixel4,rotate=270" ;;
	*) echo "bad --rotate $ROT"; exit 1 ;;
esac

TMP=$(mktemp)
while IFS= read -r line || [ -n "$line" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "$s" in
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			continue ;;
		dtoverlay=pimidi*|dtparam=i2c_arm=*|dtparam=spi=on)
			continue ;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*|*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*|*'--- Pimidi'*|*'--- end Pimidi'*)
			continue ;;
	esac
	printf '%s\n' "$line"
done < "$CFG" > "$TMP"

grep -qE '^dtoverlay=vc4-kms-v3d' "$TMP" || echo "dtoverlay=vc4-kms-v3d" >> "$TMP"
grep -qE '^max_framebuffers=' "$TMP" || echo "max_framebuffers=2" >> "$TMP"

cat >> "$TMP" <<EOF

# --- HyperPixel 4 (bootfs fix ${TS}) ---
# https://learn.pimoroni.com/getting-started-with-hyperpixel-4
${OVERLAY}
# --- end HyperPixel 4 ---
EOF
cat "$TMP" > "$CFG"
rm -f "$TMP"

if [ -f "$CMD" ]; then
	# portable: no sed -i
	tr -d '\n' < "$CMD" | sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' | tr -s ' ' | sed 's/^ //;s/ $//' > "${CMD}.1"
	# ensure newline
	{ cat "${CMD}.1"; echo; } > "$CMD"
	rm -f "${CMD}.1"
fi

# Confirm dtbo present
if [ -f "$BOOTFS/overlays/vc4-kms-dpi-hyperpixel4.dtbo" ]; then
	echo "dtbo OK: overlays/vc4-kms-dpi-hyperpixel4.dtbo"
else
	echo "WARNING: overlays/vc4-kms-dpi-hyperpixel4.dtbo missing on bootfs"
fi

echo
echo "after:"
grep -nE 'hyperpixel|hdmi_|pimidi|i2c_arm|vc4-kms' "$CFG" || true
[ -f "$CMD" ] && echo "cmdline: $(tr -d '\n' < "$CMD")"
echo
echo "Wrote ${OVERLAY}  (rotate=${ROT})"
echo "Eject the SD card, boot the Pi."
echo "Expect landscape: DPI modes include 800x480, app size 800x480."
echo "If still black: re-run with --rotate none, then on-device:"
echo "  sudo patchbox-fix-hyperpixel4 --rotate 270 && sudo reboot"
echo "If paints but UI is sideways: sudo patchbox-fix-hyperpixel4 --rotate 270"
