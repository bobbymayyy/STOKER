# Changelog

## 0.1.4 hotfix

- Mark module execution as Debian Installer context and defer only the kernel-bound `nft -c` validation until first boot. The installer kernel can return exit code 3 because its nf_tables Netlink protocol is unavailable even when the generated rules are valid and the installed Trixie kernel supports them.
- Keep BIND `named-checkconf` and Kea `-t` configuration validation active during installation.
- Add regressions proving installer provisioning skips nftables validation while normal runtime application still performs it.

## 0.1.4

- Enable the selected DNS and DHCP module configuration from the supplied config profile.
- Add a shared network renderer so ifupdown, Kea, BIND, sysctl, and nftables use one resolved upstream/downstream role map.
- Resolve the installer DHCP interface as upstream and the next physical interface as downstream when interface values are `auto`.
- Configure the downstream interface with the DHCP gateway address and subnet prefix.
- Render and validate a complete Kea DHCPv4 configuration with interface binding, pool, options, lease storage, and timers.
- Render BIND9 forwarding, recursion ACLs, downstream client scope, and `forward only`/`forward first` policy from `modules.yaml`.
- Prepare IPv4 forwarding with NAT disabled by default and add `stoker-nat enable|disable|reset|status` for runtime masquerading control without flushing Docker or administrator-owned nftables tables.
- Add boot ordering and service drop-ins so network roles are rendered before ifupdown, nftables, Kea, and BIND.
- Expand installed-appliance validation for network roles, Kea, BIND, nftables, forwarding, and service enablement.
- Validate network module IP ranges, interfaces, booleans, forwarders, and DHCP timer ordering during the build.
- Add network rendering and NAT regression tests.

## 0.1.3

- Preserve Debian Installer debconf stdin while iterating module scripts, preventing manifest entries from being consumed as protocol return codes.
- Resolve `root:stoker` ownership inside the target chroot instead of the installer runtime, preventing the final provisioning `chown` failure.
- Install `docker-cli` explicitly so `--no-install-recommends` cannot produce a daemon-only Docker installation.
- Validate that the Docker client and enabled Docker service exist on the installed appliance.
- Pass disk policy to `select-install-disk.sh` as rendered arguments instead of custom debconf lookups.
- Use Debian Installer's `debconf-set` helper without sourcing `confmodule` in the nested disk-selection hook, preventing cdebconf protocol desynchronization and garbage main-menu entries.
- Retain the target-side CD-ROM source cleanup before the embedded repository's `apt-get update`.
- Embed QEMU guest-agent and AMD/Intel microcode packages so Debian finish-stage hardware detection does not query packages absent from the offline repository.
- Add regression tests for Docker CLI inclusion, debconf-safe disk selection, rendered installer arguments, and CD-ROM cleanup ordering.

## 0.1.2

- Add declarative `config/ansible-projects.yaml` project catalog.
- Embed local or selected Git Ansible projects as immutable controller revisions.
- Add atomic active-project symlinks and retained revision history.
- Add `stoker project` list, status, validate, run, sync, import, and rollback commands.
- Add compatibility wrappers for project run, sync, and import workflows.
- Add verified offline bundle creation and import with safe archive extraction.
- Add production and discovered inventory skeletons, `stoker-node-enroll`, and a unique install-time Ed25519 controller key.
- Add built-in `stoker-bootstrap` and `node-baseline` projects.
- Add Ansible execution logs, revision-local Galaxy dependency trees and locks, plus shared roles, collections, artifacts, and secrets paths.
- Add Git, rsync, zstd, OpenSSH client, and ansible-lint to the controller payload.

## 0.1.1

- Normalize owner-write permissions after `xorriso` extraction so boot files and checksum manifests can be patched without running the builder as root.

## 0.1.0

- Declarative YAML build configuration and JSON Schema validation
- Jinja-generated STOKER preseed
- Single locked-root `stoker` administrator model
- External non-USB fixed-disk selector retained as the disk authority
- GPT, UEFI, encrypted LVM, and Debian atomic partition recipe
- Isolated APT dependency resolution with verified Debian repositories
- Embedded offline APT repository with Packages and Release metadata
- Module package/script aggregation
- ISOLINUX and GRUB unattended boot entry injection
- Debian-style `md5sum.txt` and STOKER SHA-256 manifest regeneration
- Source ISO boot-report capture and `xorriso` boot replay packaging
- Release manifests and redacted preseed output
