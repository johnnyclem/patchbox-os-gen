#!/usr/bin/env bash
# fix-waveshare79-bootfs.sh — convert a flashed Patchbox SD *boot* partition
# (and optionally the rootfs config) for Waveshare 7.9" HDMI LCD.
#
# Symptom this fixes (Profile D v1 mistake):
#   Logo/console look fine → kiosk shows 3× portrait distorted UI → black.
# Cause: kernel rotate=90 + app 1280×400 while kmsdrm still uses 400-wide mode
#   (1280/400 ≈ 3 scanline wraps). Fix: native 400×1280, no rotate, app 400×1280.
#
# Wiki timings: https://www.waveshare.com/wiki/7.9inch_HDMI_LCD
#
# Usage (macOS, SD card inserted):
#   ./scripts/fix-waveshare79-bootfs.sh
#   ./scripts/fix-waveshare79-bootfs.sh /Volumes/bootfs
#   ./scripts/fix-waveshare79-bootfs.sh /Volumes/bootfs /Volumes/rootfs
#
# If rootfs is mounted, also patches /etc/rk00pi/config.toml display size.
set -euo pipefail

BOOTFS=""
ROOTFS=""
while [ $# -gt 0 ]; do
	case "$1" in
		-h|--help)
			sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			if [ -z "$BOOTFS" ]; then
				BOOTFS=$1
			else
				ROOTFS=$1
			fi
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
if [ -z "$ROOTFS" ]; then
	for cand in /Volumes/rootfs /Volumes/root /media/*/rootfs /media/*/root; do
		if [ -d "${cand}/etc" ]; then
			ROOTFS=$cand
			break
		fi
	done
fi

[ -n "$BOOTFS" ] || { echo "boot partition not found — pass path (e.g. /Volumes/bootfs)"; exit 1; }
CFG="$BOOTFS/config.txt"
CMD="$BOOTFS/cmdline.txt"
[ -f "$CFG" ] || { echo "missing $CFG"; exit 1; }
[ -f "$CMD" ] || { echo "missing $CMD"; exit 1; }

TIMINGS="400 0 70 10 60 1280 0 20 10 12 0 0 0 60 0 43000000 3"
# No rotate — kmsdrm-safe. App must be 400×1280.
VTOKEN="video=HDMI-A-1:400x1280M@60"

TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*|*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*)
			continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_timings=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*)
			continue ;;
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*|dtoverlay=vc4-kms-dpi-hyperpixel4*)
			continue ;;
	esac
	printf '%s\n' "${line}"
done < "$CFG" > "$TMP"

if ! grep -qE '^dtoverlay=vc4-kms-v3d' "$TMP"; then
	echo "dtoverlay=vc4-kms-v3d" >> "$TMP"
fi
if ! grep -qE '^max_framebuffers=' "$TMP"; then
	echo "max_framebuffers=2" >> "$TMP"
fi

cat >> "$TMP" <<EOF

# --- HDMI ultrawide / bar panel (app 400x1280@60; Waveshare 7.9 native) ---
# kmsdrm-safe: no rotate= (see scripts/fix-waveshare79-bootfs.sh)
hdmi_force_hotplug=1
hdmi_ignore_edid=0xa5000080
hdmi_group=2
hdmi_mode=87
hdmi_timings=${TIMINGS}
hdmi_drive=2
# --- end HDMI ultrawide ---
EOF

cp "$TMP" "$CFG"
rm -f "$TMP"
echo "Wrote $CFG"

TMPC="$(mktemp)"
sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' "$CMD" > "${TMPC}.1"
if ! grep -q 'video=HDMI-A-1:' "${TMPC}.1"; then
	sed "s/^/${VTOKEN} /" "${TMPC}.1" > "${TMPC}.2"
else
	sed -E "s#video=HDMI-A-1:[^ ]*#${VTOKEN}#g" "${TMPC}.1" > "${TMPC}.2"
fi
tr -s ' \t' ' ' < "${TMPC}.2" | sed 's/^ //;s/ $//' | tr -d '\n' > "$TMPC"
echo >> "$TMPC"
cp "$TMPC" "$CMD"
rm -f "$TMPC" "${TMPC}.1" "${TMPC}.2"
echo "Wrote $CMD: $(cat "$CMD")"

# App size must match the DRM mode or the UI wraps/blacks.
if [ -n "$ROOTFS" ] && [ -f "$ROOTFS/etc/rk00pi/config.toml" ]; then
	TOML="$ROOTFS/etc/rk00pi/config.toml"
	# Best-effort in-place width/height under [display]
	if grep -qE '^width\s*=' "$TOML"; then
		sed -i.bak -E 's/^width\s*=.*/width = 400/; s/^height\s*=.*/height = 1280/' "$TOML" \
			|| sed -i '' -E 's/^width\s*=.*/width = 400/; s/^height\s*=.*/height = 1280/' "$TOML"
		rm -f "${TOML}.bak" 2>/dev/null || true
		echo "Patched $TOML → width=400 height=1280"
	else
		echo "NOTE: no width= in $TOML — set [display] width=400 height=1280 by hand"
	fi
else
	echo "NOTE: rootfs not mounted — on the Pi after boot run:"
	echo "  sudo sed -i -E 's/^width = .*/width = 400/; s/^height = .*/height = 1280/' /etc/rk00pi/config.toml"
	echo "  sudo systemctl restart rk00pi"
fi

# Drop broken 90° touch matrix if present on rootfs
if [ -n "$ROOTFS" ]; then
	rm -f "$ROOTFS/etc/udev/rules.d/99-waveshare-touch-rotate90.rules" 2>/dev/null || true
fi

echo
echo "Done. Eject, boot."
echo "  Expect a tall 400×1280 UI (transport on top, tabs on bottom)."
echo "  If still black: journalctl -u rk00pi -b --no-pager | tail -80"
