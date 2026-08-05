#!/usr/bin/env bash
# Note: Avoid usage of arrays as MacOS users have an older version of bash (v3.x) which does not supports arrays
set -eu

DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"

BUILD_OPTS="$*"

# Allow user to override docker command
DOCKER=${DOCKER:-docker}

# Ensure that default docker command is not set up in rootless mode
if \
  ! ${DOCKER} ps    >/dev/null 2>&1 || \
    ${DOCKER} info 2>/dev/null | grep -q rootless \
; then
	DOCKER="sudo ${DOCKER}"
fi
if ! ${DOCKER} ps >/dev/null; then
	echo "error connecting to docker:"
	${DOCKER} ps
	exit 1
fi

CONFIG_FILE=""
if [ -f "${DIR}/config" ]; then
	CONFIG_FILE="${DIR}/config"
fi

while getopts "c:" flag
do
	case "${flag}" in
		c)
			CONFIG_FILE="${OPTARG}"
			;;
		*)
			;;
	esac
done

# Footgun fix: `./build-docker.sh config.hyperpixel4-pimidi` (no -c) used to be
# silently ignored by getopts, so the default HDMI profile was built instead.
# Treat a bare path that exists as a file as -c <path>.
shift $((OPTIND - 1)) || true
for _arg in "$@"; do
	case "${_arg}" in
		-*) continue ;;
	esac
	_cand="${_arg}"
	if [ ! -f "${_cand}" ] && [ -f "${DIR}/${_cand}" ]; then
		_cand="${DIR}/${_cand}"
	fi
	if [ -f "${_cand}" ]; then
		echo "Note: treating '${_arg}' as config file (same as -c ${_cand})"
		CONFIG_FILE="${_cand}"
		break
	fi
done

# Ensure that the configuration file is an absolute path (required for docker
# bind-mounts — a relative path becomes a named volume and /config is empty).
if [ -n "${CONFIG_FILE}" ]; then
	if test -x /usr/bin/realpath; then
		CONFIG_FILE=$(realpath -s "$CONFIG_FILE" 2>/dev/null || realpath "$CONFIG_FILE")
	elif [ -f "${CONFIG_FILE}" ]; then
		CONFIG_FILE="$(cd "$(dirname "${CONFIG_FILE}")" && pwd)/$(basename "${CONFIG_FILE}")"
	fi
fi

# Ensure that the configuration file is present
if test -z "${CONFIG_FILE}" || [ ! -f "${CONFIG_FILE}" ]; then
	echo "Configuration file need to be present in '${DIR}/config' or path passed as parameter"
	exit 1
fi

# Layer configs the same way container build.sh does:
#   1) base product config (IMG_NAME, defaults, config.local)
#   2) profile overlay from -c (waveshare / hyperpixel / …)
# Profile-only files (config.waveshare35-pimidi) intentionally omit IMG_NAME.
BASE_CONFIG="${DIR}/config"
_base_abs=""
_cfg_abs=""
if [ -f "${BASE_CONFIG}" ]; then
	if test -x /usr/bin/realpath; then
		_base_abs=$(realpath -s "${BASE_CONFIG}" 2>/dev/null || realpath "${BASE_CONFIG}")
	else
		_base_abs="$(cd "$(dirname "${BASE_CONFIG}")" && pwd)/$(basename "${BASE_CONFIG}")"
	fi
fi
if test -x /usr/bin/realpath; then
	_cfg_abs=$(realpath -s "${CONFIG_FILE}" 2>/dev/null || realpath "${CONFIG_FILE}")
else
	_cfg_abs="${CONFIG_FILE}"
fi

if [ -n "${_base_abs}" ] && [ -f "${_base_abs}" ]; then
	# shellcheck disable=SC1090
	source "${_base_abs}"
fi
if [ -n "${_cfg_abs}" ] && [ -f "${_cfg_abs}" ] && [ "${_cfg_abs}" != "${_base_abs}" ]; then
	# shellcheck disable=SC1090
	source "${_cfg_abs}"
	echo "  (base config + profile overlay: $(basename "${_cfg_abs}"))"
elif [ -z "${_base_abs}" ] || [ ! -f "${_base_abs}" ]; then
	# No base config in tree — profile must be a full config.
	# shellcheck disable=SC1090
	source "${CONFIG_FILE}"
fi

# Profile sanity: path/name must match the display toggle it implies.
_cfg_base="$(basename "${CONFIG_FILE}")"
if echo "${_cfg_base}" | grep -qi 'hyperpixel'; then
	if [ "${ENABLE_HYPERPIXEL4:-0}" != "1" ]; then
		echo "ERROR: config '${CONFIG_FILE}' looks like a HyperPixel profile" 1>&2
		echo "       but ENABLE_HYPERPIXEL4='${ENABLE_HYPERPIXEL4:-}' (expected 1)." 1>&2
		exit 1
	fi
fi
if echo "${_cfg_base}" | grep -qi 'waveshare'; then
	if [ "${ENABLE_WAVESHARE_DPI:-0}" != "1" ]; then
		echo "ERROR: config '${CONFIG_FILE}' looks like a Waveshare profile" 1>&2
		echo "       but ENABLE_WAVESHARE_DPI='${ENABLE_WAVESHARE_DPI:-}' (expected 1)." 1>&2
		exit 1
	fi
fi

# DPI panels own the primary display path — never bake forced HDMI bar modes.
if [ "${ENABLE_HYPERPIXEL4:-0}" = "1" ] && [ "${ENABLE_HDMI_ULTRAWIDE:-0}" = "1" ]; then
	echo "NOTE: ENABLE_HYPERPIXEL4=1 → forcing ENABLE_HDMI_ULTRAWIDE=0 (DPI owns panel)"
	ENABLE_HDMI_ULTRAWIDE=0
fi
if [ "${ENABLE_WAVESHARE_DPI:-0}" = "1" ]; then
	if [ "${ENABLE_HDMI_ULTRAWIDE:-0}" = "1" ]; then
		echo "NOTE: ENABLE_WAVESHARE_DPI=1 → forcing ENABLE_HDMI_ULTRAWIDE=0"
		ENABLE_HDMI_ULTRAWIDE=0
	fi
	if [ "${ENABLE_HYPERPIXEL4:-0}" = "1" ]; then
		echo "NOTE: ENABLE_WAVESHARE_DPI=1 → forcing ENABLE_HYPERPIXEL4=0"
		ENABLE_HYPERPIXEL4=0
	fi
fi

echo "========================================"
echo " Patchbox OS image build"
echo "  config: ${CONFIG_FILE}"
if [ "${ENABLE_WAVESHARE_DPI:-0}" = "1" ]; then
	echo "  display: Waveshare 3.5 DPI  ${WAVESHARE_WIDTH:-640}x${WAVESHARE_HEIGHT:-480}"
	echo "           keep_pimidi=${WAVESHARE_KEEP_PIMIDI:-0}"
elif [ "${ENABLE_HYPERPIXEL4:-0}" = "1" ]; then
	echo "  display: HyperPixel 4  ${HYPERPIXEL_WIDTH:-800}x${HYPERPIXEL_HEIGHT:-480}"
	echo "           rotate=${HYPERPIXEL_ROTATE:-left}  (dtoverlay=vc4-kms-dpi-hyperpixel4)"
else
	if [ "${ENABLE_HDMI_ULTRAWIDE:-0}" = "1" ]; then
		echo "  display: HDMI ultrawide  ${HDMI_WIDTH:-1280}x${HDMI_HEIGHT:-400}"
		echo "           (no DPI overlay)"
	else
		echo "  display: stock / none forced"
	fi
fi
echo "  pimidi:  ENABLE_PIMIDI=${ENABLE_PIMIDI:-0}  sel=${PIMIDI_SEL:-0}"
echo "  panel:   RK00PI ${RK00PI_WIDTH:-auto}x${RK00PI_HEIGHT:-auto}"
echo "========================================"

CONTAINER_NAME=${CONTAINER_NAME:-pigen_work}
CONTINUE=${CONTINUE:-0}
PRESERVE_CONTAINER=${PRESERVE_CONTAINER:-0}
PIGEN_DOCKER_OPTS=${PIGEN_DOCKER_OPTS:-""}

if [ -z "${IMG_NAME:-}" ]; then
	echo "IMG_NAME not set — base '${DIR}/config' must define it (or use a full profile)." 1>&2
	echo 1>&2
	exit 1
fi

# Ensure the Git Hash is recorded before entering the docker container
GIT_HASH=${GIT_HASH:-"$(git rev-parse HEAD)"}

CONTAINER_EXISTS=$(${DOCKER} ps -a --filter name="${CONTAINER_NAME}" -q)
CONTAINER_RUNNING=$(${DOCKER} ps --filter name="${CONTAINER_NAME}" -q)
if [ "${CONTAINER_RUNNING}" != "" ]; then
	echo "The build is already running in container ${CONTAINER_NAME}. Aborting."
	exit 1
fi
if [ "${CONTAINER_EXISTS}" != "" ] && [ "${CONTINUE}" != "1" ]; then
	echo "Container ${CONTAINER_NAME} already exists and you did not specify CONTINUE=1. Aborting."
	echo "You can delete the existing container like this:"
	echo "  ${DOCKER} rm -v ${CONTAINER_NAME}"
	exit 1
fi

# Modify original build-options so the container uses the bind-mounted config.
# Use POSIX character class (macOS BSD sed has no \s).
BUILD_OPTS="$(echo "${BUILD_OPTS:-}" | sed -E 's|-c[[:space:]]*[^[:space:]]+|-c /config|')"
# Always pass -c /config when we have a config file (env-only invocations).
case " ${BUILD_OPTS} " in
	*" -c "*|*" -c"*) ;;
	*) BUILD_OPTS="${BUILD_OPTS} -c /config" ;;
esac

# Check the arch of the machine we're running on.
# On x86_64, use a 32-bit (i386) base image so setarch linux32 works for armhf
# debootstrap. On aarch64/arm64 (e.g. Apple Silicon + Colima), use native
# arm64 debian — scripts/common falls back when setarch linux32 is unavailable,
# and qemu-user-static handles armhf. Using i386 on arm64 would require nested
# x86 emulation and is much slower.
case "$(uname -m)" in
  x86_64)
    BASE_IMAGE=i386/debian:bullseye
    ;;
  aarch64|arm64)
    BASE_IMAGE=debian:bullseye
    ;;
  *)
    BASE_IMAGE=debian:bullseye
    ;;
esac
${DOCKER} build --build-arg BASE_IMAGE=${BASE_IMAGE} -t pi-gen "${DIR}"

if [ "${CONTAINER_EXISTS}" != "" ]; then
  DOCKER_CMDLINE_NAME="${CONTAINER_NAME}_cont"
  DOCKER_CMDLINE_PRE="--rm"
  DOCKER_CMDLINE_POST="--volumes-from=${CONTAINER_NAME}"
else
  DOCKER_CMDLINE_NAME="${CONTAINER_NAME}"
  DOCKER_CMDLINE_PRE=""
  DOCKER_CMDLINE_POST=""
fi

# Check if binfmt_misc is required on the host.
# Native arm hosts can skip host-side qemu for arm64 guests, but this project
# still bootstraps armhf (32-bit), so binfmt + qemu-arm must work *inside*
# the container. Ensure container-side binfmt is registered below.
binfmt_misc_required=1
case $(uname -m) in
  aarch64|arm64)
    # Still need qemu-arm for armhf userland; rely on container setup.
    binfmt_misc_required=0
    ;;
  arm*)
    binfmt_misc_required=0
    ;;
esac

# Check if qemu-arm-static and /proc/sys/fs/binfmt_misc are present
if [[ "${binfmt_misc_required}" == "1" ]]; then
  if ! qemu_arm=$(which qemu-arm-static) ; then
    echo "qemu-arm-static not found (please install qemu-user-static)"
    exit 1
  fi
  if [ ! -f /proc/sys/fs/binfmt_misc/register ]; then
    echo "binfmt_misc required but not mounted, trying to mount it..."
    if ! mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc ; then
        echo "mounting binfmt_misc failed"
        exit 1
    fi
    echo "binfmt_misc mounted"
  fi
  if ! grep -q "^interpreter ${qemu_arm}" /proc/sys/fs/binfmt_misc/qemu-arm* ; then
    # Register qemu-arm for binfmt_misc
    reg="echo ':qemu-arm-rpi:M::"\
"\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:"\
"\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:"\
"${qemu_arm}:F' > /proc/sys/fs/binfmt_misc/register"
    echo "Registering qemu-arm for binfmt_misc..."
    sudo bash -c "${reg}" 2>/dev/null || true
  fi
fi

# On arm64 Docker hosts (Apple Silicon + Colima, etc.), ensure arm/armhf
# binfmt handlers exist in the kernel before debootstrap runs armhf binaries.
case $(uname -m) in
  aarch64|arm64)
    echo "Ensuring qemu arm/armhf binfmt is registered for armhf rootfs..."
    ${DOCKER} run --privileged --rm tonistiigi/binfmt --install arm >/dev/null
    ;;
esac

# Optional secrets file (WiFi SSID/password). Prefer bind-mount over image COPY.
CONFIG_LOCAL_MOUNT=""
if [ -f "${DIR}/config.local" ]; then
	CONFIG_LOCAL_MOUNT="--volume ${DIR}/config.local:/pi-gen/config.local:ro"
fi

trap 'echo "got CTRL+C... please wait 5s" && ${DOCKER} stop -t 5 ${DOCKER_CMDLINE_NAME}' SIGINT SIGTERM
time ${DOCKER} run \
  $DOCKER_CMDLINE_PRE \
  --name "${DOCKER_CMDLINE_NAME}" \
  --privileged \
  --cap-add=ALL \
  -v /dev:/dev \
  -v /lib/modules:/lib/modules \
  ${PIGEN_DOCKER_OPTS} \
  --volume "${CONFIG_FILE}":/config:ro \
  ${CONFIG_LOCAL_MOUNT} \
  -e "GIT_HASH=${GIT_HASH}" \
  -e "WPA_COUNTRY=${WPA_COUNTRY:-}" \
  -e "WPA_ESSID=${WPA_ESSID:-}" \
  -e "WPA_PASSWORD=${WPA_PASSWORD:-}" \
  -e "ENABLE_WIFI_HOTSPOT=${ENABLE_WIFI_HOTSPOT:-}" \
  -e "ENABLE_SSH=${ENABLE_SSH:-}" \
  -e "ENABLE_HDMI_ULTRAWIDE=${ENABLE_HDMI_ULTRAWIDE:-}" \
  -e "HDMI_WIDTH=${HDMI_WIDTH:-}" \
  -e "HDMI_HEIGHT=${HDMI_HEIGHT:-}" \
  -e "HDMI_REFRESH=${HDMI_REFRESH:-}" \
  -e "ENABLE_HYPERPIXEL4=${ENABLE_HYPERPIXEL4:-}" \
  -e "HYPERPIXEL_WIDTH=${HYPERPIXEL_WIDTH:-}" \
  -e "HYPERPIXEL_HEIGHT=${HYPERPIXEL_HEIGHT:-}" \
  -e "HYPERPIXEL_REFRESH=${HYPERPIXEL_REFRESH:-}" \
  -e "HYPERPIXEL_ROTATE=${HYPERPIXEL_ROTATE:-}" \
  -e "HYPERPIXEL_CMDLINE_VIDEO=${HYPERPIXEL_CMDLINE_VIDEO:-}" \
  -e "HYPERPIXEL_KEEP_PIMIDI=${HYPERPIXEL_KEEP_PIMIDI:-}" \
  -e "ENABLE_PIMIDI=${ENABLE_PIMIDI:-}" \
  -e "PIMIDI_SEL=${PIMIDI_SEL:-}" \
  -e "ENABLE_RK00PI=${ENABLE_RK00PI:-}" \
  -e "ENABLE_RK00PI_SERVICE=${ENABLE_RK00PI_SERVICE:-}" \
  -e "ENABLE_RK00PI_BUTTON=${ENABLE_RK00PI_BUTTON:-}" \
  -e "ENABLE_RK00PI_AUTOHUB=${ENABLE_RK00PI_AUTOHUB:-}" \
  -e "ENABLE_RK00PI_COMPANION=${ENABLE_RK00PI_COMPANION:-}" \
  -e "RK00PI_COMPANION_BIND=${RK00PI_COMPANION_BIND:-}" \
  -e "RK00PI_COMPANION_PORT=${RK00PI_COMPANION_PORT:-}" \
  -e "RK00PI_COMPANION_ADVERTISE=${RK00PI_COMPANION_ADVERTISE:-}" \
  -e "RK00PI_HUB_PRESET=${RK00PI_HUB_PRESET:-}" \
  -e "RK00PI_WIDTH=${RK00PI_WIDTH:-}" \
  -e "RK00PI_HEIGHT=${RK00PI_HEIGHT:-}" \
  -e "ENABLE_WAVESHARE_DPI=${ENABLE_WAVESHARE_DPI:-}" \
  -e "WAVESHARE_WIDTH=${WAVESHARE_WIDTH:-}" \
  -e "WAVESHARE_HEIGHT=${WAVESHARE_HEIGHT:-}" \
  -e "WAVESHARE_REFRESH=${WAVESHARE_REFRESH:-}" \
  -e "WAVESHARE_KEEP_PIMIDI=${WAVESHARE_KEEP_PIMIDI:-}" \
  -e "RASPBIAN_MIRROR=${RASPBIAN_MIRROR:-}" \
  $DOCKER_CMDLINE_POST \
  pi-gen \
  bash -e -o pipefail -c "
    dpkg-reconfigure qemu-user-static &&
    # binfmt_misc is sometimes not mounted with debian bullseye image
    (mount binfmt_misc -t binfmt_misc /proc/sys/fs/binfmt_misc || true) &&
    cd /pi-gen; ./build.sh ${BUILD_OPTS} &&
    rsync -av work/*/build.log deploy/
  " &
  wait "$!"

# Ensure that deploy/ is always owned by calling user
echo "copying results from deploy/"
${DOCKER} cp "${CONTAINER_NAME}":/pi-gen/deploy - | tar -xf -

echo "copying log from container ${CONTAINER_NAME} to deploy/"
${DOCKER} logs --timestamps "${CONTAINER_NAME}" &>deploy/build-docker.log

ls -lah deploy

# cleanup
if [ "${PRESERVE_CONTAINER}" != "1" ]; then
	${DOCKER} rm -v "${CONTAINER_NAME}"
fi

echo "Done! Your image(s) should be in deploy/"
