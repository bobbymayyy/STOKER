#!/bin/sh
set -eu

ISO_ROOT=/cdrom/stoker
TARGET=/target
REPO_TARGET=/opt/stoker/repo
PACKAGE_MANIFEST="$ISO_ROOT/manifests/install-packages.txt"
MODULE_MANIFEST="$ISO_ROOT/manifests/post-install-scripts.txt"

log() {
    logger -t stoker-provision -- "$*" 2>/dev/null || true
    printf 'stoker-provision: %s\n' "$*" >&2
}
fatal() {
    log "ERROR: $*"
    exit 1
}

[ -d "$TARGET" ] || fatal "Target root is not mounted"
[ -d "$ISO_ROOT/repo" ] || fatal "Embedded repository is missing"
[ -f "$PACKAGE_MANIFEST" ] || fatal "Package manifest is missing"

log "Copying embedded APT repository"
mkdir -p "$TARGET$REPO_TARGET"
cp -a "$ISO_ROOT/repo/." "$TARGET$REPO_TARGET/"

mkdir -p "$TARGET/etc/apt/sources.list.d"
[ -f "$ISO_ROOT/config/repository.sources" ] || fatal "Generated repository source is missing"
cp "$ISO_ROOT/config/repository.sources" "$TARGET/etc/apt/sources.list.d/stoker.sources"

# Target APT cannot refresh the installer CD-ROM source from inside /target.
# Disable it before apt-get update; the appliance retains its copied offline
# repository at /opt/stoker/repo.
sed -i '/^[[:space:]]*deb[[:space:]].*cdrom:/d' "$TARGET/etc/apt/sources.list" 2>/dev/null || true

log "Installing packages from the embedded repository"
in-target apt-get update
PACKAGES=$(grep -Ev '^[[:space:]]*(#|$)' "$PACKAGE_MANIFEST" | tr '\n' ' ')
[ -n "$PACKAGES" ] || fatal "Package manifest is empty"
in-target env DEBIAN_FRONTEND=noninteractive apt-get \
    -y --no-install-recommends install $PACKAGES

if [ -d "$ISO_ROOT/rootfs" ]; then
    log "Applying target root filesystem overlay"
    cp -a "$ISO_ROOT/rootfs/." "$TARGET/"
fi

for directory in compose inventory projects .versions/projects .staging/projects roles collections artifacts images backups config logs; do
    mkdir -p "$TARGET/opt/stoker/$directory"
done

if [ -f "$MODULE_MANIFEST" ]; then
    # Keep the manifest on a dedicated descriptor. in-target uses stdin for
    # Debian Installer's debconf passthrough protocol during chroot setup, so
    # redirecting the whole loop from the manifest corrupts that protocol and
    # causes later script names to be consumed as debconf return codes.
    while IFS= read -r script <&3; do
        case "$script" in ''|'#'*) continue ;; esac
        case "$script" in
            *[!A-Za-z0-9._-]*) fatal "Unsafe module script name: $script" ;;
        esac
        src="$ISO_ROOT/scripts/modules/$script"
        dst="/usr/local/lib/stoker/modules/$script"
        [ -f "$src" ] || fatal "Enabled module script is missing: $script"
        mkdir -p "$TARGET/usr/local/lib/stoker/modules"
        cp "$src" "$TARGET$dst"
        chmod 0755 "$TARGET$dst"
        log "Running module installer: $script"
        # The Debian Installer kernel may not expose nf_tables netlink support even
        # though the installed Trixie kernel will. Mark this invocation so the
        # renderer performs userspace configuration checks now and defers the
        # kernel-bound nftables check/apply until first boot.
        in-target env DEBIAN_FRONTEND=noninteractive STOKER_INSTALLER_CONTEXT=1 "$dst"
    done 3< "$MODULE_MANIFEST"
fi

if in-target getent group docker >/dev/null 2>&1; then
    in-target usermod --append --groups docker stoker
fi
# Ownership names belong to the installed system, not the installer runtime.
# Resolve root:stoker inside /target so BusyBox does not reject the target-only
# stoker group.
in-target chown -R root:stoker /opt/stoker
in-target chmod 0750 /opt/stoker
in-target sh -c 'chmod 0770 /opt/stoker/logs /opt/stoker/logs/ansible 2>/dev/null || true'

log "STOKER offline provisioning completed"
