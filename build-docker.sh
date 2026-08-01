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

# Ensure that the configuration file is an absolute path
if test -x /usr/bin/realpath; then
	CONFIG_FILE=$(realpath -s "$CONFIG_FILE" || realpath "$CONFIG_FILE")
fi

# Ensure that the confguration file is present
if test -z "${CONFIG_FILE}"; then
	echo "Configuration file need to be present in '${DIR}/config' or path passed as parameter"
	exit 1
else
	# shellcheck disable=SC1090
	source ${CONFIG_FILE}
fi

CONTAINER_NAME=${CONTAINER_NAME:-pigen_work}
CONTINUE=${CONTINUE:-0}
PRESERVE_CONTAINER=${PRESERVE_CONTAINER:-0}
PIGEN_DOCKER_OPTS=${PIGEN_DOCKER_OPTS:-""}

if [ -z "${IMG_NAME}" ]; then
	echo "IMG_NAME not set in 'config'" 1>&2
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

# Modify original build-options to allow config file to be mounted in the docker container
BUILD_OPTS="$(echo "${BUILD_OPTS:-}" | sed -E 's@\-c\s?([^ ]+)@-c /config@')"

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
  -e "ENABLE_RK00PI=${ENABLE_RK00PI:-}" \
  -e "ENABLE_RK00PI_SERVICE=${ENABLE_RK00PI_SERVICE:-}" \
  -e "RK00PI_WIDTH=${RK00PI_WIDTH:-}" \
  -e "RK00PI_HEIGHT=${RK00PI_HEIGHT:-}" \
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
