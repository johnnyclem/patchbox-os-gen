#!/usr/bin/env bash
# live-fix-waveshare79.sh — run ON the Pi (or scp + sudo bash).
#
# The 2026-08-09 image advertised patchbox-setup in the MOTD but never
# installed it (stage3/22-install-setup/01-run.sh was not executable, so
# pi-gen skipped the whole stage). This script applies the Waveshare 7.9″
# HDMI timings without needing patchbox-setup.
#
#   scp scripts/live-fix-waveshare79.sh patch@patchbox.local:/tmp/
#   ssh patch@patchbox.local 'sudo bash /tmp/live-fix-waveshare79.sh && sudo reboot'
#
# Or paste the body into an SSH session as root.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
	echo "run as root: sudo bash $0" >&2
	exit 1
fi

BOOT_CFG=""
BOOT_CMD=""
for d in /boot/firmware /boot; do
	if [ -f "${d}/config.txt" ] && [ -f "${d}/cmdline.txt" ]; then
		BOOT_CFG="${d}/config.txt"
		BOOT_CMD="${d}/cmdline.txt"
		break
	fi
done
[ -n "${BOOT_CFG}" ] || { echo "no /boot/firmware/config.txt" >&2; exit 1; }

TIMINGS="400 0 70 10 60 1280 0 20 10 12 0 0 0 60 0 43000000 3"
VTOKEN="video=HDMI-A-1:400x1280M@60"

echo "=== before ==="
grep -nE 'hdmi_|dtoverlay=vc4' "${BOOT_CFG}" || true
echo "cmdline: $(cat "${BOOT_CMD}")"
echo

TMP="$(mktemp)"
while IFS= read -r line || [ -n "${line}" ]; do
	s="${line#"${line%%[![:space:]]*}"}"
	case "${s}" in
		*'--- HDMI ultrawide'*|*'--- end HDMI ultrawide'*|*'--- Waveshare 3.5 DPI'*|*'--- end Waveshare'*) continue ;;
		*'--- HyperPixel 4'*|*'--- end HyperPixel 4'*) continue ;;
		hdmi_group=*|hdmi_mode=*|hdmi_cvt=*|hdmi_timings=*|hdmi_drive=*|hdmi_force_hotplug=*|hdmi_ignore_edid=*) continue ;;
		dtoverlay=waveshare-35dpi*|dtoverlay=waveshare-touch-35dpi*|dtoverlay=vc4-kms-DPI-35inch*) continue ;;
		dtoverlay=vc4-kms-dpi-hyperpixel4*|dtoverlay=vc4-kms-dpi-hyperpixel4sq*|dtoverlay=vc4-kms-dpi-generic*) continue ;;
	esac
	printf '%s\n' "${line}"
done < "${BOOT_CFG}" > "${TMP}"

grep -qE '^dtoverlay=vc4-kms-v3d' "${TMP}" || echo "dtoverlay=vc4-kms-v3d" >> "${TMP}"
grep -qE '^max_framebuffers=' "${TMP}" || echo "max_framebuffers=2" >> "${TMP}"

cat >> "${TMP}" <<EOF

# --- HDMI ultrawide (Waveshare 7.9 native 400x1280; app landscape 1280x400) ---
hdmi_force_hotplug=1
hdmi_ignore_edid=0xa5000080
hdmi_group=2
hdmi_mode=87
hdmi_timings=${TIMINGS}
hdmi_drive=2
# --- end HDMI ultrawide ---
EOF
cp "${TMP}" "${BOOT_CFG}"
rm -f "${TMP}"
echo "Wrote ${BOOT_CFG}"

TMPC="$(mktemp)"
sed -E 's/ *video=HDMI-A-[12]:[^ ]*//g; s/ *video=DPI-1:[^ ]*//g' "${BOOT_CMD}" > "${TMPC}.1"
if ! grep -q 'video=HDMI-A-1:' "${TMPC}.1"; then
	sed "s/^/${VTOKEN} /" "${TMPC}.1" > "${TMPC}.2"
else
	sed -E "s#video=HDMI-A-1:[^ ]*#${VTOKEN}#g" "${TMPC}.1" > "${TMPC}.2"
fi
tr -s ' \t' ' ' < "${TMPC}.2" | sed 's/^ //;s/ $//' | tr -d '\n' > "${TMPC}"
echo >> "${TMPC}"
cp "${TMPC}" "${BOOT_CMD}"
rm -f "${TMPC}" "${TMPC}.1" "${TMPC}.2"
echo "Wrote ${BOOT_CMD}: $(cat "${BOOT_CMD}")"

# App panel size: landscape 1280×400 (DRM stays 400×1280 — no kernel rotate).
for cfg in /etc/rk00pi/config.toml /etc/rangerdeck/config.toml \
	/etc/chordranger/config.toml /etc/midiranger/config.toml \
	/etc/genranger/config.toml /etc/phraseranger/config.toml \
	/etc/sceneranger/config.toml /etc/grooveranger/config.toml \
	/etc/synthranger/config.toml; do
	[ -f "${cfg}" ] || continue
	sed -i -E 's/^width[[:space:]]*=.*/width = 1280/' "${cfg}"
	sed -i -E 's/^height[[:space:]]*=.*/height = 400/' "${cfg}"
	if grep -qE '^rotation[[:space:]]*=' "${cfg}"; then
		sed -i -E 's/^rotation[[:space:]]*=.*/rotation = 90/' "${cfg}"
	fi
	echo "  panel 1280x400 → ${cfg}"
done

# Kiosk hygiene: LightDM steals DRM from SDL kmsdrm.
systemctl set-default multi-user.target 2>/dev/null || true
systemctl disable lightdm.service 2>/dev/null || true
ln -sfn /lib/systemd/system/multi-user.target /etc/systemd/system/default.target
systemctl disable jack.service 2>/dev/null || true
systemctl disable amidiauto.service 2>/dev/null || true

# Prefer the bake-time boot app if present
if systemctl cat rangerdeck.service >/dev/null 2>&1; then
	if [ -x /usr/local/bin/patchbox-app ]; then
		/usr/local/bin/patchbox-app enable rangerdeck 2>/dev/null || true
	else
		systemctl enable rangerdeck.service 2>/dev/null || true
	fi
	echo "boot app: rangerdeck (enabled)"
elif systemctl cat rk00pi.service >/dev/null 2>&1; then
	if [ -x /usr/local/bin/patchbox-app ]; then
		/usr/local/bin/patchbox-app enable rk00pi 2>/dev/null || true
	else
		systemctl enable rk00pi.service 2>/dev/null || true
	fi
	echo "boot app: rk00pi (enabled)"
fi

echo
echo "=== after ==="
grep -nE 'hdmi_|dtoverlay=vc4' "${BOOT_CFG}" || true
echo "cmdline: $(cat "${BOOT_CMD}")"
echo
echo "Done. Reboot for the new mode:"
echo "  sudo reboot"
echo
echo "After reboot, if still black try the other HDMI port (Pi 5: A-1 vs A-2)."
echo "patchbox-setup will appear after you rebuild with the fixed stage3/22."
