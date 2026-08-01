#!/bin/bash -e

install -v -d					"${ROOTFS_DIR}/etc/wpa_supplicant"
install -v -m 600 files/wpa_supplicant.conf	"${ROOTFS_DIR}/etc/wpa_supplicant/"

# Pre-seed client WiFi when WPA_ESSID is set at build time.
# Bookworm uses NetworkManager; also keep wpa_supplicant.conf for tools that
# still read it. Country code unblocks the radio (rfkill).
if [ -n "${WPA_COUNTRY}" ]; then
	on_chroot <<- EOF
		SUDO_USER="${FIRST_USER_NAME}" raspi-config nonint do_wifi_country "${WPA_COUNTRY}"
	EOF
fi

# Disable wifi on 5GHz models if WPA_COUNTRY is not set (radiate-safe default).
# When country + SSID are set, unblock WLAN.
mkdir -p "${ROOTFS_DIR}/var/lib/systemd/rfkill/"
if [ -n "$WPA_COUNTRY" ]; then
	echo 0 > "${ROOTFS_DIR}/var/lib/systemd/rfkill/platform-3f300000.mmcnr:wlan"
	echo 0 > "${ROOTFS_DIR}/var/lib/systemd/rfkill/platform-fe300000.mmcnr:wlan"
	# Pi 5 / newer platform paths (best-effort)
	echo 0 > "${ROOTFS_DIR}/var/lib/systemd/rfkill/platform-1001100000.mmc:wlan" 2>/dev/null || true
else
	echo 1 > "${ROOTFS_DIR}/var/lib/systemd/rfkill/platform-3f300000.mmcnr:wlan"
	echo 1 > "${ROOTFS_DIR}/var/lib/systemd/rfkill/platform-fe300000.mmcnr:wlan"
fi

if [ -n "${WPA_ESSID}" ]; then
	if [ -z "${WPA_PASSWORD}" ]; then
		echo "WARNING: WPA_ESSID is set but WPA_PASSWORD is empty — open network profile"
	fi
	if [ -z "${WPA_COUNTRY}" ]; then
		echo "WARNING: WPA_COUNTRY unset — WLAN may stay rfkill-blocked on Bookworm"
	fi

	# --- wpa_supplicant network block ---
	{
		echo "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev"
		echo "update_config=1"
		if [ -n "${WPA_COUNTRY}" ]; then
			echo "country=${WPA_COUNTRY}"
		fi
		echo ""
		echo "network={"
		echo "	ssid=\"${WPA_ESSID}\""
		if [ -n "${WPA_PASSWORD}" ]; then
			echo "	psk=\"${WPA_PASSWORD}\""
			echo "	key_mgmt=WPA-PSK"
		else
			echo "	key_mgmt=NONE"
		fi
		echo "}"
	} > "${ROOTFS_DIR}/etc/wpa_supplicant/wpa_supplicant.conf"
	chmod 600 "${ROOTFS_DIR}/etc/wpa_supplicant/wpa_supplicant.conf"

	# --- NetworkManager keyfile (Bookworm desktop / NM stack) ---
	install -d -m 700 "${ROOTFS_DIR}/etc/NetworkManager/system-connections"
	# Stable UUID so rebuilds overwrite cleanly
	UUID="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
	NM_FILE="${ROOTFS_DIR}/etc/NetworkManager/system-connections/preconfigured.nmconnection"
	{
		echo "[connection]"
		echo "id=preconfigured"
		echo "uuid=${UUID}"
		echo "type=wifi"
		echo "autoconnect=true"
		echo "autoconnect-priority=100"
		echo ""
		echo "[wifi]"
		echo "mode=infrastructure"
		echo "ssid=${WPA_ESSID}"
		echo ""
		if [ -n "${WPA_PASSWORD}" ]; then
			echo "[wifi-security]"
			echo "key-mgmt=wpa-psk"
			echo "psk=${WPA_PASSWORD}"
			echo ""
		fi
		echo "[ipv4]"
		echo "method=auto"
		echo ""
		echo "[ipv6]"
		echo "method=auto"
	} > "${NM_FILE}"
	chmod 600 "${NM_FILE}"

	# Ensure NM does not leave wireless disabled
	install -d "${ROOTFS_DIR}/etc/NetworkManager/conf.d"
	cat > "${ROOTFS_DIR}/etc/NetworkManager/conf.d/10-globally-managed-devices.conf" <<'EOF'
[keyfile]
unmanaged-devices=*,except:type:wifi,except:type:gsm,except:type:cdma,except:type:wwan,except:type:ethernet,except:type:vlan
EOF

	# Unblock wireless in NM state if we previously would have disabled it
	install -d "${ROOTFS_DIR}/var/lib/NetworkManager"
	cat > "${ROOTFS_DIR}/var/lib/NetworkManager/NetworkManager.state" <<'EOF'
[main]
NetworkingEnabled=true
WirelessEnabled=true
WWANEnabled=true
EOF

	echo "Preconfigured WiFi SSID='${WPA_ESSID}' (country=${WPA_COUNTRY:-unset})"
fi
