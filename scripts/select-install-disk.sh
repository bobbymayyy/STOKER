#!/bin/sh
set -eu

LOG_TAG=stoker-disk-select
log() {
    logger -t "$LOG_TAG" -- "$*" 2>/dev/null || true
    printf '%s: %s\n' "$LOG_TAG" "$*" >&2
}
fatal() {
    log "ERROR: $*"
    exit 1
}

WIPE_ALL=false
REQUIRE_UEFI=true

while [ "$#" -gt 0 ]; do
    case "$1" in
        --wipe-all-fixed-disks=*) WIPE_ALL=${1#*=} ;;
        --require-uefi=*) REQUIRE_UEFI=${1#*=} ;;
        *) fatal "Unknown argument: $1" ;;
    esac
    shift
done

validate_bool() {
    name=$1
    value=$2
    case "$value" in
        true|false) return 0 ;;
        *) fatal "$name must be true or false, not: $value" ;;
    esac
}

validate_bool wipe-all-fixed-disks "$WIPE_ALL"
validate_bool require-uefi "$REQUIRE_UEFI"

if [ "$REQUIRE_UEFI" = true ] && [ ! -d /sys/firmware/efi ]; then
    fatal "Installer was not booted in UEFI mode, but UEFI is required"
fi

is_candidate() {
    sys_block=$1
    dev=$(basename "$sys_block")

    case "$dev" in
        loop*|ram*|fd*|sr*|md*|dm-*|zram*|nbd*) return 1 ;;
    esac

    [ -r "$sys_block/removable" ] || return 1
    [ "$(cat "$sys_block/removable")" = 0 ] || return 1

    device_path=$(readlink -f "$sys_block/device" 2>/dev/null || true)
    case "$device_path" in
        *'/usb'*|*'/usb-storage/'*) return 1 ;;
    esac

    [ -b "/dev/$dev" ] || return 1
    return 0
}

CANDIDATES=""
for sys_block in /sys/block/*; do
    if is_candidate "$sys_block"; then
        dev=$(basename "$sys_block")
        CANDIDATES="${CANDIDATES}${CANDIDATES:+ }/dev/$dev"
    fi
done

[ -n "$CANDIDATES" ] || fatal "No fixed non-USB installation disk was found"

# Use a deterministic lexical order among eligible fixed disks.
SELECTED=$(printf '%s\n' $CANDIDATES | LC_ALL=C sort | head -n 1)
[ -b "$SELECTED" ] || fatal "Selected device is not a block device: $SELECTED"

wipe_device() {
    disk=$1
    log "Clearing existing signatures from $disk"
    if command -v wipefs >/dev/null 2>&1; then
        wipefs --all --force "$disk" || fatal "wipefs failed for $disk"
    else
        # Installer fallback: clear the first and final 4 MiB, where partition
        # tables and common metadata normally live.
        dev=$(basename "$disk")
        sectors=$(cat "/sys/class/block/$dev/size" 2>/dev/null || printf 0)
        dd if=/dev/zero of="$disk" bs=1M count=4 conv=fsync 2>/dev/null
        if [ "$sectors" -gt 8192 ]; then
            seek=$((sectors / 2048 - 4))
            dd if=/dev/zero of="$disk" bs=1M seek="$seek" count=4 conv=fsync 2>/dev/null
        fi
    fi
}

if [ "$WIPE_ALL" = true ]; then
    for disk in $CANDIDATES; do
        wipe_device "$disk"
    done
else
    wipe_device "$SELECTED"
fi

# debconf-set is the Debian Installer utility intended for preseed command
# hooks. Do not source confmodule here: this script runs beneath preseed's
# existing frontend, and opening another protocol conversation can desynchronize
# cdebconf and leak reply values into main-menu.
command -v debconf-set >/dev/null 2>&1 || fatal "debconf-set is unavailable"
debconf-set partman-auto/disk "$SELECTED"
debconf-set grub-installer/bootdev "$SELECTED"

log "Selected installation disk: $SELECTED"
log "Eligible fixed disks: $CANDIDATES"
log "Wipe-all policy: $WIPE_ALL"
exit 0
