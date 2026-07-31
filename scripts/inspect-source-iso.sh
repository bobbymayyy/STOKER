#!/bin/sh
set -eu

ISO=${1:?Usage: inspect-source-iso.sh PATH_TO_ISO}
command -v xorriso >/dev/null 2>&1 || {
    printf 'xorriso is required\n' >&2
    exit 1
}

printf '%s\n' '=== El Torito and system-area replay commands ==='
xorriso -indev "$ISO" \
    -report_el_torito cmd \
    -report_system_area cmd \
    -end

printf '%s\n' '=== mkisofs-compatible reconstruction options ==='
xorriso -indev "$ISO" \
    -report_el_torito as_mkisofs \
    -report_system_area as_mkisofs \
    -end
