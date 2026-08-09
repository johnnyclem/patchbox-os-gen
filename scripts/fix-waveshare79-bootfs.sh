#!/usr/bin/env bash
# fix-waveshare79-bootfs.sh — Waveshare 7.9" HDMI: native DRM + software landscape.
#
# Boot:  video=HDMI-A-1:400x1280M@60  (NO kernel rotate)
# App:   width=1280 height=400 rotation=90  (software orient in rk00pi)
#
# Usage:
#   ./scripts/fix-waveshare79-bootfs.sh
#   ./scripts/fix-waveshare79-bootfs.sh /Volumes/bootfs /Volumes/rootfs
set -euo pipefail

BOOTFS=""
ROOTFS=""
while [ $# -gt 0 ]; do
	case "$1" in
		-h|--help)
			sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*)
			if [ -z "$BOOTFS" ]; then BOOTFS=$1; else ROOTFS=$1; fi
			shift
			;;
	esac
done

if [ -z "$BOOTFS" ]; then
	for cand in /Volumes/bootfs /Volumes/boot /media/*/bootfs /media/*/boot; do
		[ -f "${cand}/config.txt" ] && BOOTFS=$cand && break
	done
fi
if [ -z "$ROOTFS" ]; then
	for cand in /Volumes/rootfs /Volumes/root /media/*/rootfs /media/*/root; do
		[ -d "${cand}/etc" ] && ROOTFS=$cand && break
	done
fi

[ -n "$BOOTFS" ] || { echo "boot partition not found"; exit 1; }
CFG="$BOOTFS/config.txt"
CMD="$BOOTFS/cmdline.txt"
[ -f "$CFG" ] && [ -f "$CMD" ] || { echo "missing config.txt or cmdline.txt"; exit 1; }

TIMINGS="400 0 70 10 60 1280 0 20 10 12 0 0 0 60 0 43000000 3"
VTOKEN="video=HDMI-A-1:400x1280M@60"

TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*|*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*) continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_timings=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*) continue ;;
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*|dtoverlay=vc4-kms-dpi-hyperpixel4*) continue ;;
	esac
	printf '%s\n' "${line}"
done < "$CFG" > "$TMP"
grep -qE '^dtoverlay=vc4-kms-v3d' "$TMP" || echo "dtoverlay=vc4-kms-v3d" >> "$TMP"
grep -qE '^max_framebuffers=' "$TMP" || echo "max_framebuffers=2" >> "$TMP"
cat >> "$TMP" <<EOF

# --- HDMI ultrawide (Waveshare 7.9 native 400x1280; app rotates in software) ---
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

if [ -n "$ROOTFS" ] && [ -f "$ROOTFS/etc/rk00pi/config.toml" ]; then
	TOML="$ROOTFS/etc/rk00pi/config.toml"
	# Logical landscape + software rotation
	if grep -qE '^width\s*=' "$TOML"; then
		sed -i.bak \
			-e 's/^width\s*=.*/width = 1280/' \
			-e 's/^height\s*=.*/height = 400/' \
			-e 's/^rotation\s*=.*/rotation = 90/' \
			"$TOML" 2>/dev/null \
		|| sed -i '' \
			-e 's/^width\s*=.*/width = 1280/' \
			-e 's/^height\s*=.*/height = 400/' \
			-e 's/^rotation\s*=.*/rotation = 90/' \
			"$TOML"
		rm -f "${TOML}.bak" 2>/dev/null || true
		echo "Patched $TOML → 1280×400 rotation=90"
	else
		echo "NOTE: add under [display]: width=1280 height=400 rotation=90"
	fi
	rm -f "$ROOTFS/etc/udev/rules.d/99-waveshare-touch-rotate90.rules" 2>/dev/null || true
else
	echo "NOTE: rootfs not mounted — on the Pi run:"
	echo "  sudo sed -i -E 's/^width = .*/width = 1280/; s/^height = .*/height = 400/; s/^rotation = .*/rotation = 90/' /etc/rk00pi/config.toml"
	echo "  sudo systemctl restart rk00pi"
fi

echo
echo "Done. Eject and boot. Expect a landscape 1280×400 bar UI."
echo "If the bar is upside-down or mirrored, try rotation = 270 in config.toml."
