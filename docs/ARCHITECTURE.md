# Architecture

## Compiler model

The YAML files are source code. The preseed, APT repository, versioned Ansible projects, runtime controller commands, boot entries, checksums, and final ISO are generated artifacts.

```text
config/*.yaml + ansible/*
      |
      +--> schema and referenced-config validation
      +--> package/module merge
      +--> Ansible project catalog resolution
      +--> immutable project revision staging
      +--> Jinja preseed rendering
      +--> isolated APT dependency resolution
      +--> embedded APT repository
      +--> source ISO extraction
      +--> payload and boot-entry injection
      +--> checksum regeneration
      +--> xorriso source-image update + boot replay
      `--> validation and release manifests
```

## Ansible project control plane

STOKER separates project identity from project revisions:

```text
/opt/stoker/projects/<name>              active symlink
/opt/stoker/.versions/projects/<name>/  immutable revisions
/opt/stoker/.staging/projects/          untrusted temporary work
```

A new Git or USB revision moves through this state machine:

```text
fetch/import
    -> checksum and archive safety checks
    -> revision-local dependency resolution or lock verification
    -> Ansible syntax validation
    -> optional ansible-lint
    -> atomic symlink activation
    -> old-revision pruning
```

Failed validation never moves the active link. Each revision carries its own `.stoker` dependency tree and lock, so rollback validates and reactivates the same project plus dependency set.

Projects remain on the controller. Ansible transfers temporary modules and declared artifacts to managed nodes over SSH rather than copying the entire project repository to every node.

## Trust boundaries

### Build host

Remote Debian repositories must pass normal APT signature verification. Repository definitions point to the Debian archive keyring with `signed-by=`.

Local Ansible project sources and build-time Git credentials are trusted build inputs.

### Installation media

The package pool, project revisions, runtime project catalog, and indexes are placed on the same ISO as the generated preseed. The target copies the payload into its installed root.

### Runtime Git

The configured Git transport authenticates the remote. SSH repositories should use managed host keys and controller-local private keys generated after installation.

### Offline imports

The manifest SHA-256 protects integrity, not publisher identity. Operational deployments should add detached signature verification around the bundle delivery process when provenance must be cryptographically established.

### Installed appliance

The generated build manifest contains no passwords or passphrases. The ISO itself is sensitive because the installer must be able to read the initial LUKS passphrase.

Secrets are stored separately under `/etc/stoker/secrets/`; they are not part of project repositories or normal rootfs overlays.

## Disk selection

The preseed sets policy values through Debconf. `select-install-disk.sh` owns the mechanism:

1. Enumerate `/sys/block`.
2. Exclude virtual, optical, removable, and USB-backed devices.
3. Select the first device in deterministic lexical order.
4. Refuse legacy BIOS boot when UEFI is required.
5. Clear signatures on the selected disk, or every eligible fixed disk when explicitly configured.
6. Set `partman-auto/disk` and `grub-installer/bootdev`.

This prevents the preseed and helper script from developing competing disk-selection logic.

## ISO reconstruction

The source ISO remains immutable. `xorriso` loads it as the input image and writes a separate output image. The extracted tree is supplied with `-update_r`, while `-boot_image any replay` reconstructs recognizable BIOS/UEFI boot provisions and system-area structures.
