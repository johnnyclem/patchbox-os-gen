#!/bin/bash -e

# shellcheck disable=SC2119
run_sub_stage()
{
	log "Begin ${SUB_STAGE_DIR}"
	pushd "${SUB_STAGE_DIR}" > /dev/null
	for i in {00..99}; do
		if [ -f "${i}-debconf" ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-debconf"
			on_chroot << EOF
debconf-set-selections <<SELEOF
$(cat "${i}-debconf")
SELEOF
EOF

			log "End ${SUB_STAGE_DIR}/${i}-debconf"
		fi
		if [ -f "${i}-packages-nr" ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-packages-nr"
			PACKAGES="$(sed -f "${SCRIPT_DIR}/remove-comments.sed" < "${i}-packages-nr")"
			if [ -n "$PACKAGES" ]; then
				on_chroot << EOF
apt-get -o Acquire::Retries=3 install --no-install-recommends -y $PACKAGES
EOF
				if [ "${USE_QCOW2}" = "1" ]; then
					on_chroot << EOF
apt-get clean
EOF
				fi
			fi
			log "End ${SUB_STAGE_DIR}/${i}-packages-nr"
		fi
		if [ -f "${i}-packages" ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-packages"
			PACKAGES="$(sed -f "${SCRIPT_DIR}/remove-comments.sed" < "${i}-packages")"
			if [ -n "$PACKAGES" ]; then
				on_chroot << EOF
apt-get -o Acquire::Retries=3 install -y $PACKAGES
EOF
				if [ "${USE_QCOW2}" = "1" ]; then
					on_chroot << EOF
apt-get clean
EOF
				fi
			fi
			log "End ${SUB_STAGE_DIR}/${i}-packages"
		fi
		if [ -d "${i}-patches" ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-patches"
			pushd "${STAGE_WORK_DIR}" > /dev/null
			if [ "${CLEAN}" = "1" ]; then
				rm -rf .pc
				rm -rf ./*-pc
			fi
			QUILT_PATCHES="${SUB_STAGE_DIR}/${i}-patches"
			SUB_STAGE_QUILT_PATCH_DIR="$(basename "$SUB_STAGE_DIR")-pc"
			mkdir -p "$SUB_STAGE_QUILT_PATCH_DIR"
			ln -snf "$SUB_STAGE_QUILT_PATCH_DIR" .pc
			quilt upgrade
			if [ -e "${SUB_STAGE_DIR}/${i}-patches/EDIT" ]; then
				echo "Dropping into bash to edit patches..."
				bash
			fi
			RC=0
			quilt push -a || RC=$?
			case "$RC" in
				0|2)
					;;
				*)
					false
					;;
			esac
			popd > /dev/null
			log "End ${SUB_STAGE_DIR}/${i}-patches"
		fi
		if [ -x ${i}-run.sh ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-run.sh"
			./${i}-run.sh
			log "End ${SUB_STAGE_DIR}/${i}-run.sh"
		fi
		if [ -f ${i}-run-chroot.sh ]; then
			log "Begin ${SUB_STAGE_DIR}/${i}-run-chroot.sh"
			on_chroot < ${i}-run-chroot.sh
			log "End ${SUB_STAGE_DIR}/${i}-run-chroot.sh"
		fi
	done
	popd > /dev/null
	log "End ${SUB_STAGE_DIR}"
}


run_stage(){
	log "Begin ${STAGE_DIR}"
	STAGE="$(basename "${STAGE_DIR}")"

	pushd "${STAGE_DIR}" > /dev/null

	STAGE_WORK_DIR="${WORK_DIR}/${STAGE}"
	ROOTFS_DIR="${STAGE_WORK_DIR}"/rootfs

	if [ "${USE_QCOW2}" = "1" ]; then
		if [ ! -f SKIP ]; then
			load_qimage
		fi
	else
		# make sure we are not umounting during export-image stage
		if [ "${USE_QCOW2}" = "0" ] && [ "${NO_PRERUN_QCOW2}" = "0" ]; then
			unmount "${WORK_DIR}/${STAGE}"
		fi
	fi

	if [ ! -f SKIP_IMAGES ]; then
		if [ -f "${STAGE_DIR}/EXPORT_IMAGE" ]; then
			EXPORT_DIRS="${EXPORT_DIRS} ${STAGE_DIR}"
		fi
	fi
	if [ ! -f SKIP ]; then
		if [ "${CLEAN}" = "1" ] && [ "${USE_QCOW2}" = "0" ] ; then
			if [ -d "${ROOTFS_DIR}" ]; then
				rm -rf "${ROOTFS_DIR}"
			fi
		fi
		if [ -x prerun.sh ]; then
			log "Begin ${STAGE_DIR}/prerun.sh"
			./prerun.sh
			log "End ${STAGE_DIR}/prerun.sh"
		fi
		for SUB_STAGE_DIR in "${STAGE_DIR}"/*; do
			if [ -d "${SUB_STAGE_DIR}" ] && [ ! -f "${SUB_STAGE_DIR}/SKIP" ]; then
				run_sub_stage
			fi
		done
	fi

	if [ "${USE_QCOW2}" = "1" ]; then
		unload_qimage
	else
		# make sure we are not umounting during export-image stage
		if [ "${USE_QCOW2}" = "0" ] && [ "${NO_PRERUN_QCOW2}" = "0" ]; then
			unmount "${WORK_DIR}/${STAGE}"
		fi
	fi

	PREV_STAGE="${STAGE}"
	PREV_STAGE_DIR="${STAGE_DIR}"
	PREV_ROOTFS_DIR="${ROOTFS_DIR}"
	popd > /dev/null
	log "End ${STAGE_DIR}"
}

if [ "$(id -u)" != "0" ]; then
	echo "Please run as root" 1>&2
	exit 1
fi

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $BASE_DIR = *" "* ]]; then
	echo "There is a space in the base path of pi-gen"
	echo "This is not a valid setup supported by debootstrap."
	echo "Please remove the spaces, or move pi-gen directory to a base path without spaces" 1>&2
	exit 1
fi

export BASE_DIR

if [ -f config ]; then
	# shellcheck disable=SC1091
	source config
fi

while getopts "c:" flag
do
	case "$flag" in
		c)
			EXTRA_CONFIG="$OPTARG"
			# shellcheck disable=SC1090
			source "$EXTRA_CONFIG"
			;;
		*)
			;;
	esac
done

term() {
	if [ "${USE_QCOW2}" = "1" ]; then
		log "Unloading image"
		unload_qimage
	fi
}

trap term EXIT INT TERM

export PI_GEN=${PI_GEN:-pi-gen}
export PI_GEN_REPO=${PI_GEN_REPO:-https://github.com/RPi-Distro/pi-gen}
export PI_GEN_RELEASE=${PI_GEN_RELEASE:-Raspberry Pi reference}

if [ -z "${IMG_NAME}" ]; then
	echo "IMG_NAME not set" 1>&2
	exit 1
fi

export USE_QEMU="${USE_QEMU:-0}"
export IMG_DATE="${IMG_DATE:-"$(date +%Y-%m-%d)"}"
export IMG_FILENAME="${IMG_FILENAME:-"${IMG_DATE}-${IMG_NAME}"}"
export ARCHIVE_FILENAME="${ARCHIVE_FILENAME:-"image_${IMG_DATE}-${IMG_NAME}"}"

export SCRIPT_DIR="${BASE_DIR}/scripts"
export WORK_DIR="${WORK_DIR:-"${BASE_DIR}/work/${IMG_NAME}"}"
export DEPLOY_DIR=${DEPLOY_DIR:-"${BASE_DIR}/deploy"}

# DEPLOY_ZIP was deprecated in favor of DEPLOY_COMPRESSION
# This preserve the old behavior with DEPLOY_ZIP=0 where no archive was created
if [ -z "${DEPLOY_COMPRESSION}" ] && [ "${DEPLOY_ZIP:-1}" = "0" ]; then
	echo "DEPLOY_ZIP has been deprecated in favor of DEPLOY_COMPRESSION"
	echo "Similar behavior to DEPLOY_ZIP=0 can be obtained with DEPLOY_COMPRESSION=none"
	echo "Please update your config file"
	DEPLOY_COMPRESSION=none
fi
export DEPLOY_COMPRESSION=${DEPLOY_COMPRESSION:-zip}
export COMPRESSION_LEVEL=${COMPRESSION_LEVEL:-6}
export LOG_FILE="${WORK_DIR}/build.log"

export TARGET_HOSTNAME=${TARGET_HOSTNAME:-raspberrypi}

export FIRST_USER_NAME=${FIRST_USER_NAME:-pi}
export FIRST_USER_PASS
export DISABLE_FIRST_BOOT_USER_RENAME=${DISABLE_FIRST_BOOT_USER_RENAME:-0}
export RELEASE=${RELEASE:-bookworm} # Don't forget to update stage0/prerun.sh
export WPA_COUNTRY
export WPA_ESSID
export WPA_PASSWORD
export ENABLE_SSH="${ENABLE_SSH:-0}"
export PUBKEY_ONLY_SSH="${PUBKEY_ONLY_SSH:-0}"

# Patchbox-specific toggles for background services and product defaults.
# Defaults preserve existing product behavior; see README for hardening.
export ENABLE_WIFI_HOTSPOT="${ENABLE_WIFI_HOTSPOT:-1}"
export ENABLE_VNC="${ENABLE_VNC:-1}"
export ENABLE_TELEMETRY="${ENABLE_TELEMETRY:-1}"
export PISOUND_GIT_REF="${PISOUND_GIT_REF:-patchbox}"
export HOTSPOT_PASSPHRASE="${HOTSPOT_PASSPHRASE:-blokaslabs}"
export ENABLE_FIRST_LOGIN_PASSWORD_CHANGE="${ENABLE_FIRST_LOGIN_PASSWORD_CHANGE:-1}"
export ENABLE_HDMI_ULTRAWIDE="${ENABLE_HDMI_ULTRAWIDE:-1}"
export HDMI_WIDTH="${HDMI_WIDTH:-1280}"
export HDMI_HEIGHT="${HDMI_HEIGHT:-400}"
export HDMI_REFRESH="${HDMI_REFRESH:-60}"
export HDMI_NATIVE_WIDTH="${HDMI_NATIVE_WIDTH:-}"
export HDMI_NATIVE_HEIGHT="${HDMI_NATIVE_HEIGHT:-}"
export HDMI_ROTATE="${HDMI_ROTATE:-}"
export HDMI_TIMINGS="${HDMI_TIMINGS:-}"
export HDMI_CONNECTOR="${HDMI_CONNECTOR:-HDMI-A-1}"
export ENABLE_HYPERPIXEL4="${ENABLE_HYPERPIXEL4:-0}"
export HYPERPIXEL_WIDTH="${HYPERPIXEL_WIDTH:-800}"
export HYPERPIXEL_HEIGHT="${HYPERPIXEL_HEIGHT:-480}"
export HYPERPIXEL_REFRESH="${HYPERPIXEL_REFRESH:-60}"
export HYPERPIXEL_ROTATE="${HYPERPIXEL_ROTATE:-left}"
export HYPERPIXEL_CMDLINE_VIDEO="${HYPERPIXEL_CMDLINE_VIDEO:-0}"
export HYPERPIXEL_KEEP_PIMIDI="${HYPERPIXEL_KEEP_PIMIDI:-0}"
export ENABLE_PIMIDI="${ENABLE_PIMIDI:-0}"
export PIMIDI_SEL="${PIMIDI_SEL:-0}"
export ENABLE_RK00PI="${ENABLE_RK00PI:-1}"
export ENABLE_RK00PI_SERVICE="${ENABLE_RK00PI_SERVICE:-1}"
export ENABLE_RK00PI_BUTTON="${ENABLE_RK00PI_BUTTON:-1}"
export ENABLE_RK00PI_AUTOHUB="${ENABLE_RK00PI_AUTOHUB:-1}"
export ENABLE_RK00PI_COMPANION="${ENABLE_RK00PI_COMPANION:-1}"
export RK00PI_COMPANION_BIND="${RK00PI_COMPANION_BIND:-0.0.0.0}"
export RK00PI_COMPANION_PORT="${RK00PI_COMPANION_PORT:-8787}"
export RK00PI_COMPANION_ADVERTISE="${RK00PI_COMPANION_ADVERTISE:-1}"
export RK00PI_HUB_PRESET="${RK00PI_HUB_PRESET:-}"
export RK00PI_WIDTH="${RK00PI_WIDTH:-}"
export RK00PI_HEIGHT="${RK00PI_HEIGHT:-}"
# ChordRanger + Ranger suite. Stages only see *exported* vars — without
# these, ENABLE_* is empty in stage3 and every Ranger install is skipped
# (Aug 2026 image: full-screen RK-00pi, no deck, no tiles).
export ENABLE_CHORDRANGER="${ENABLE_CHORDRANGER:-1}"
export ENABLE_CHORDRANGER_SERVICE="${ENABLE_CHORDRANGER_SERVICE:-0}"
export CHORDRANGER_WIDTH="${CHORDRANGER_WIDTH:-}"
export CHORDRANGER_HEIGHT="${CHORDRANGER_HEIGHT:-}"
export RANGER_BOOT_APP="${RANGER_BOOT_APP:-rk00pi}"
export ENABLE_MIDIRANGER="${ENABLE_MIDIRANGER:-1}"
export ENABLE_GENRANGER="${ENABLE_GENRANGER:-1}"
export ENABLE_PHRASERANGER="${ENABLE_PHRASERANGER:-1}"
export ENABLE_SCENERANGER="${ENABLE_SCENERANGER:-1}"
export ENABLE_GROOVERANGER="${ENABLE_GROOVERANGER:-1}"
export ENABLE_SYNTHRANGER="${ENABLE_SYNTHRANGER:-1}"
export ENABLE_RANGERDECK="${ENABLE_RANGERDECK:-1}"
export MIDIRANGER_WIDTH="${MIDIRANGER_WIDTH:-}"
export MIDIRANGER_HEIGHT="${MIDIRANGER_HEIGHT:-}"
export GENRANGER_WIDTH="${GENRANGER_WIDTH:-}"
export GENRANGER_HEIGHT="${GENRANGER_HEIGHT:-}"
export PHRASERANGER_WIDTH="${PHRASERANGER_WIDTH:-}"
export PHRASERANGER_HEIGHT="${PHRASERANGER_HEIGHT:-}"
export SCENERANGER_WIDTH="${SCENERANGER_WIDTH:-}"
export SCENERANGER_HEIGHT="${SCENERANGER_HEIGHT:-}"
export GROOVERANGER_WIDTH="${GROOVERANGER_WIDTH:-}"
export GROOVERANGER_HEIGHT="${GROOVERANGER_HEIGHT:-}"
export SYNTHRANGER_WIDTH="${SYNTHRANGER_WIDTH:-}"
export SYNTHRANGER_HEIGHT="${SYNTHRANGER_HEIGHT:-}"
export RANGERDECK_WIDTH="${RANGERDECK_WIDTH:-}"
export RANGERDECK_HEIGHT="${RANGERDECK_HEIGHT:-}"
export ENABLE_WAVESHARE_DPI="${ENABLE_WAVESHARE_DPI:-0}"
export WAVESHARE_WIDTH="${WAVESHARE_WIDTH:-640}"
export WAVESHARE_HEIGHT="${WAVESHARE_HEIGHT:-480}"
export WAVESHARE_REFRESH="${WAVESHARE_REFRESH:-60}"
export WAVESHARE_KEEP_PIMIDI="${WAVESHARE_KEEP_PIMIDI:-0}"
export ENABLE_INKY="${ENABLE_INKY:-0}"
export ENABLE_INKY_UI="${ENABLE_INKY_UI:-0}"
export ENABLE_INKY_STATUS_SERVICE="${ENABLE_INKY_STATUS_SERVICE:-0}"
export ENABLE_RASPIAUDIO="${ENABLE_RASPIAUDIO:-0}"
export RASPIAUDIO_OVERLAY="${RASPIAUDIO_OVERLAY:-wm8960-soundcard}"
export RASPBIAN_MIRROR="${RASPBIAN_MIRROR:-http://mirrors.ocf.berkeley.edu/raspbian/raspbian}"

# One panel, one boot unit. When the deck (or any other Ranger) owns boot,
# do not also enable rk00pi.service in stage 10 — install-ranger-app would
# disable it later, but a half-built / CONTINUE image can strand both.
if [ "${RANGER_BOOT_APP}" != "rk00pi" ] && [ "${ENABLE_RK00PI_SERVICE}" = "1" ]; then
	echo "NOTE: RANGER_BOOT_APP=${RANGER_BOOT_APP} → forcing ENABLE_RK00PI_SERVICE=0"
	ENABLE_RK00PI_SERVICE=0
	export ENABLE_RK00PI_SERVICE
fi
if [ "${RANGER_BOOT_APP}" = "chordranger" ] || [ "${ENABLE_CHORDRANGER_SERVICE}" = "1" ]; then
	ENABLE_CHORDRANGER_SERVICE=1
	export ENABLE_CHORDRANGER_SERVICE
	if [ "${RANGER_BOOT_APP}" = "rk00pi" ]; then
		RANGER_BOOT_APP=chordranger
		export RANGER_BOOT_APP
	fi
fi

# DPI panels own the header / primary connector. Forced HDMI bar modes fight
# pinmux and kiosk geometry. Mutual exclusion so config.local leftovers cannot
# re-enable Profile A mid-build.
if [ "${ENABLE_HYPERPIXEL4}" = "1" ] && [ "${ENABLE_HDMI_ULTRAWIDE}" = "1" ]; then
	echo "NOTE: ENABLE_HYPERPIXEL4=1 → forcing ENABLE_HDMI_ULTRAWIDE=0 (DPI owns panel)"
	ENABLE_HDMI_ULTRAWIDE=0
	export ENABLE_HDMI_ULTRAWIDE
fi
if [ "${ENABLE_WAVESHARE_DPI}" = "1" ]; then
	if [ "${ENABLE_HDMI_ULTRAWIDE}" = "1" ]; then
		echo "NOTE: ENABLE_WAVESHARE_DPI=1 → forcing ENABLE_HDMI_ULTRAWIDE=0"
		ENABLE_HDMI_ULTRAWIDE=0
		export ENABLE_HDMI_ULTRAWIDE
	fi
	if [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
		echo "NOTE: ENABLE_WAVESHARE_DPI=1 → forcing ENABLE_HYPERPIXEL4=0 (one DPI panel)"
		ENABLE_HYPERPIXEL4=0
		export ENABLE_HYPERPIXEL4
	fi
fi

echo "========================================"
echo " Patchbox display profile (build.sh)"
if [ "${ENABLE_WAVESHARE_DPI}" = "1" ]; then
	echo "  Waveshare 3.5 DPI  ${WAVESHARE_WIDTH}x${WAVESHARE_HEIGHT}"
	echo "  keep_pimidi=${WAVESHARE_KEEP_PIMIDI}  (dtoverlay=waveshare-35dpi)"
elif [ "${ENABLE_HYPERPIXEL4}" = "1" ]; then
	echo "  HyperPixel 4  ${HYPERPIXEL_WIDTH}x${HYPERPIXEL_HEIGHT}  rotate=${HYPERPIXEL_ROTATE}"
	echo "  stage 12 will write dtoverlay=vc4-kms-dpi-hyperpixel4"
else
	if [ "${ENABLE_HDMI_ULTRAWIDE}" = "1" ]; then
		if [ -n "${HDMI_TIMINGS}" ]; then
			echo "  Waveshare 7.9 HDMI  native ${HDMI_NATIVE_WIDTH:-400}x${HDMI_NATIVE_HEIGHT:-1280}"
			echo "  rotate=${HDMI_ROTATE:-none} → app ${HDMI_WIDTH}x${HDMI_HEIGHT}"
		else
			echo "  HDMI ultrawide  ${HDMI_WIDTH}x${HDMI_HEIGHT}"
			echo "  ENABLE_HYPERPIXEL4=0 / WAVESHARE_DPI=0 — hdmi_cvt bar"
		fi
	else
		echo "  stock display path (no HyperPixel, no Waveshare, no forced HDMI bar)"
	fi
fi
echo "  RK00PI panel: ${RK00PI_WIDTH:-auto}x${RK00PI_HEIGHT:-auto}"
echo "  boot app: ${RANGER_BOOT_APP}  (rk00pi service=${ENABLE_RK00PI_SERVICE})"
echo "  rangers: deck=${ENABLE_RANGERDECK} chord=${ENABLE_CHORDRANGER}" \
	"midi=${ENABLE_MIDIRANGER} gen=${ENABLE_GENRANGER}" \
	"phrase=${ENABLE_PHRASERANGER} scene=${ENABLE_SCENERANGER}" \
	"groove=${ENABLE_GROOVERANGER} synth=${ENABLE_SYNTHRANGER}"
echo "========================================"

export LOCALE_DEFAULT="${LOCALE_DEFAULT:-en_GB.UTF-8}"

export KEYBOARD_KEYMAP="${KEYBOARD_KEYMAP:-gb}"
export KEYBOARD_LAYOUT="${KEYBOARD_LAYOUT:-English (UK)}"

export TIMEZONE_DEFAULT="${TIMEZONE_DEFAULT:-Europe/London}"

export GIT_HASH=${GIT_HASH:-"$(git rev-parse HEAD)"}

export PUBKEY_SSH_FIRST_USER

export CLEAN
export IMG_NAME
export APT_PROXY

export HOSTNAME
export RT_KERNEL_VERSION

export STAGE
export STAGE_DIR
export STAGE_WORK_DIR
export PREV_STAGE
export PREV_STAGE_DIR
export ROOTFS_DIR
export PREV_ROOTFS_DIR
export IMG_SUFFIX
export NOOBS_NAME
export NOOBS_DESCRIPTION
export EXPORT_DIR
export EXPORT_ROOTFS_DIR

export QUILT_PATCHES
export QUILT_NO_DIFF_INDEX=1
export QUILT_NO_DIFF_TIMESTAMPS=1
export QUILT_REFRESH_ARGS="-p ab"

# shellcheck source=scripts/common
source "${SCRIPT_DIR}/common"
# shellcheck source=scripts/dependencies_check
source "${SCRIPT_DIR}/dependencies_check"

export NO_PRERUN_QCOW2="${NO_PRERUN_QCOW2:-1}"
export USE_QCOW2="${USE_QCOW2:-0}"
export BASE_QCOW2_SIZE=${BASE_QCOW2_SIZE:-12G}
source "${SCRIPT_DIR}/qcow2_handling"
if [ "${USE_QCOW2}" = "1" ]; then
	NO_PRERUN_QCOW2=1
else
	NO_PRERUN_QCOW2=0
fi

export NO_PRERUN_QCOW2="${NO_PRERUN_QCOW2:-1}"

if [ "$SETFCAP" != "1" ]; then
	export CAPSH_ARG="--drop=cap_setfcap"
fi

dependencies_check "${BASE_DIR}/depends"

#check username is valid
if [[ ! "$FIRST_USER_NAME" =~ ^[a-z][-a-z0-9_]*$ ]]; then
	echo "Invalid FIRST_USER_NAME: $FIRST_USER_NAME"
	exit 1
fi

if [[ "$DISABLE_FIRST_BOOT_USER_RENAME" == "1" ]] && [ -z "${FIRST_USER_PASS}" ]; then
	echo "To disable user rename on first boot, FIRST_USER_PASS needs to be set"
	echo "Not setting FIRST_USER_PASS makes your system vulnerable and open to cyberattacks"
	exit 1
fi

if [[ "$DISABLE_FIRST_BOOT_USER_RENAME" == "1" ]]; then
	echo "User rename on the first boot is disabled"
	echo "Be advised of the security risks linked to shipping a device with default username/password set."
fi

if [[ -n "${APT_PROXY}" ]] && ! curl --silent "${APT_PROXY}" >/dev/null ; then
	echo "Could not reach APT_PROXY server: ${APT_PROXY}"
	exit 1
fi

if [[ -n "${WPA_PASSWORD}" && ${#WPA_PASSWORD} -lt 8 || ${#WPA_PASSWORD} -gt 63  ]] ; then
	echo "WPA_PASSWORD" must be between 8 and 63 characters
	exit 1
fi

if [[ "${PUBKEY_ONLY_SSH}" = "1" && -z "${PUBKEY_SSH_FIRST_USER}" ]]; then
	echo "Must set 'PUBKEY_SSH_FIRST_USER' to a valid SSH public key if using PUBKEY_ONLY_SSH"
	exit 1
fi

mkdir -p "${WORK_DIR}"
log "Begin ${BASE_DIR}"

STAGE_LIST=${STAGE_LIST:-${BASE_DIR}/stage*}

for STAGE_DIR in $STAGE_LIST; do
	STAGE_DIR=$(realpath "${STAGE_DIR}")
	run_stage
done

CLEAN=1
for EXPORT_DIR in ${EXPORT_DIRS}; do
	STAGE_DIR=${BASE_DIR}/export-image
	# shellcheck source=/dev/null
	source "${EXPORT_DIR}/EXPORT_IMAGE"
	EXPORT_ROOTFS_DIR=${WORK_DIR}/$(basename "${EXPORT_DIR}")/rootfs
	if [ "${USE_QCOW2}" = "1" ]; then
		USE_QCOW2=0
		EXPORT_NAME="${IMG_FILENAME}${IMG_SUFFIX}"
		echo "------------------------------------------------------------------------"
		echo "Running export stage for ${EXPORT_NAME}"
		rm -f "${WORK_DIR}/export-image/${EXPORT_NAME}.img" || true
		rm -f "${WORK_DIR}/export-image/${EXPORT_NAME}.qcow2" || true
		rm -f "${WORK_DIR}/${EXPORT_NAME}.img" || true
		rm -f "${WORK_DIR}/${EXPORT_NAME}.qcow2" || true
		EXPORT_STAGE=$(basename "${EXPORT_DIR}")
		for s in $STAGE_LIST; do
			TMP_LIST=${TMP_LIST:+$TMP_LIST }$(basename "${s}")
		done
		FIRST_STAGE=${TMP_LIST%% *}
		FIRST_IMAGE="image-${FIRST_STAGE}.qcow2"

		pushd "${WORK_DIR}" > /dev/null
		echo "Creating new base "${EXPORT_NAME}.qcow2" from ${FIRST_IMAGE}"
		cp "./${FIRST_IMAGE}" "${EXPORT_NAME}.qcow2"

		ARR=($TMP_LIST)
		# rebase stage images to new export base
		for CURR_STAGE in "${ARR[@]}"; do
			if [ "${CURR_STAGE}" = "${FIRST_STAGE}" ]; then
				PREV_IMG="${EXPORT_NAME}"
				continue
			fi
		echo "Rebasing image-${CURR_STAGE}.qcow2 onto ${PREV_IMG}.qcow2"
			qemu-img rebase -f qcow2 -u -b ${PREV_IMG}.qcow2 image-${CURR_STAGE}.qcow2
			if [ "${CURR_STAGE}" = "${EXPORT_STAGE}" ]; then
				break
			fi
			PREV_IMG="image-${CURR_STAGE}"
		done

		# commit current export stage into base export image
		echo "Committing image-${EXPORT_STAGE}.qcow2 to ${EXPORT_NAME}.qcow2"
		qemu-img commit -f qcow2 -p -b "${EXPORT_NAME}.qcow2" image-${EXPORT_STAGE}.qcow2

		# rebase stage images back to original first stage for easy re-run
		for CURR_STAGE in "${ARR[@]}"; do
			if [ "${CURR_STAGE}" = "${FIRST_STAGE}" ]; then
				PREV_IMG="image-${CURR_STAGE}"
				continue
			fi
		echo "Rebasing back image-${CURR_STAGE}.qcow2 onto ${PREV_IMG}.qcow2"
			qemu-img rebase -f qcow2 -u -b ${PREV_IMG}.qcow2 image-${CURR_STAGE}.qcow2
			if [ "${CURR_STAGE}" = "${EXPORT_STAGE}" ]; then
				break
			fi
			PREV_IMG="image-${CURR_STAGE}"
		done
		popd > /dev/null

		mkdir -p "${WORK_DIR}/export-image/rootfs"
		mv "${WORK_DIR}/${EXPORT_NAME}.qcow2" "${WORK_DIR}/export-image/"
		echo "Mounting image ${WORK_DIR}/export-image/${EXPORT_NAME}.qcow2 to rootfs ${WORK_DIR}/export-image/rootfs"
		mount_qimage "${WORK_DIR}/export-image/${EXPORT_NAME}.qcow2" "${WORK_DIR}/export-image/rootfs"

		CLEAN=0
		run_stage
		CLEAN=1
		USE_QCOW2=1

	else
		run_stage
	fi
	if [ "${USE_QEMU}" != "1" ]; then
		if [ -e "${EXPORT_DIR}/EXPORT_NOOBS" ]; then
			# shellcheck source=/dev/null
			source "${EXPORT_DIR}/EXPORT_NOOBS"
			STAGE_DIR="${BASE_DIR}/export-noobs"
			if [ "${USE_QCOW2}" = "1" ]; then
				USE_QCOW2=0
				run_stage
				USE_QCOW2=1
			else
				run_stage
			fi
		fi
	fi
done

if [ -x postrun.sh ]; then
	log "Begin postrun.sh"
	cd "${BASE_DIR}"
	./postrun.sh
	log "End postrun.sh"
fi

if [ "${USE_QCOW2}" = "1" ]; then
	unload_qimage
fi

log "End ${BASE_DIR}"
