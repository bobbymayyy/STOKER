# STOKER ISO Builder

STOKER ISO Builder compiles a Debian 13 `amd64` netinst ISO from declarative YAML. It renders the preseed, resolves package dependencies with APT, creates an embedded offline repository, injects installer and controller tooling, regenerates checksums, and writes a new hybrid ISO while replaying the source image's recognized boot equipment.

## What v0.1.4 builds

- One `stoker` administrator account with direct root login disabled
- First fixed, non-removable, non-USB installation disk selected by `select-install-disk.sh`
- Optional wipe of every eligible fixed disk
- UEFI-required GPT installation
- Debian `atomic` partition recipe
- Encrypted LVM with `/` receiving the bulk of available space
- Offline package repository generated from enabled package groups and modules
- QEMU guest-agent plus AMD and Intel microcode available to finish-stage hardware detection
- Ansible controller, Docker Engine, Docker CLI, Compose, BIND9, Kea DHCPv4, and routing enabled by default
- Shared automatic network roles: the installer DHCP interface is upstream and the next physical interface is downstream
- Runtime-selectable nftables masquerading without rebuilding the ISO
- Versioned embedded Ansible projects with atomic activation links
- Git project synchronization, validation, execution, rollback, and verified USB bundle import
- Production and discovered inventory skeletons plus node enrollment tooling
- BIOS and UEFI unattended boot entries
- Build, package, project, and file-integrity manifests

## Build-host setup

On a Debian-family build host:

```sh
./scripts/bootstrap-build-host.sh
```

The essential tools are Python 3, PyYAML, Jinja2, jsonschema, Ansible Core, Git, APT, `dpkg-deb`, `dpkg-scanpackages` or `apt-ftparchive`, the Debian archive keyring, and `xorriso`.

## Quick start

1. Put the original Debian Trixie netinst ISO at the configured path:

   ```sh
   cp ~/Downloads/debian-13*-amd64-netinst.iso \
      cache/iso/debian-13-amd64-netinst.iso
   ```

2. Create the secret environment file:

   ```sh
   cp .env.example .env
   mkpasswd -m yescrypt
   ```

   Put the resulting hash in `STOKER_PASSWORD_HASH` and choose a build-specific `STOKER_LUKS_PASSPHRASE`.

3. Validate the YAML:

   ```sh
   ./build.sh -c config/stoker-build.yaml validate
   ```

4. Build everything:

   ```sh
   ./build.sh -c config/stoker-build.yaml all
   ```

The final ISO and sidecar manifests appear under `output/`.

The builder is designed to run as your normal user. During extraction it adds owner-write permission to the copied ISO filesystem tree. Do not run the whole build with `sudo`. Build-host packages may still be installed with `sudo` through `scripts/bootstrap-build-host.sh`.


## Integrated DNS, DHCP, and routing

The `routing`, `dhcp`, and `dns` modules share one renderer. This prevents BIND, Kea, ifupdown, and nftables from independently guessing interface names or subnet values.

With the shipped configuration:

- the interface already configured for DHCP is the upstream/potential-Internet interface;
- the next physical interface is assigned `192.168.88.1/24`;
- Kea serves `192.168.88.100` through `192.168.88.200` on only that downstream interface;
- DHCP clients receive the STOKER appliance as gateway and DNS server;
- BIND permits recursion only from localhost and `192.168.88.0/24`, then forwards to `1.1.1.1` and `9.9.9.9`;
- IPv4 forwarding is prepared, while the isolated STOKER nftables masquerade table remains disabled.

Inspect the resolved roles after installation:

```sh
sudo stoker-network-config status
```

Toggle NAT at runtime without editing nftables by hand:

```sh
sudo stoker-nat enable
sudo stoker-nat status
sudo stoker-nat disable
sudo stoker-nat reset   # return to modules.yaml enable_nat value
```

To pin interface names instead of using discovery, set `routing.configuration.upstream_interface` and `dhcp.configuration.interface` in `config/modules.yaml`, then rebuild. On an installed appliance, edit `/etc/stoker/modules.yaml`, run `sudo stoker-network-config apply` to validate and render it, then reboot so ifupdown and the services consume the new roles cleanly.

## Adding Ansible projects to the ISO

Declare projects in `config/ansible-projects.yaml`:

```yaml
projects:
  - name: site-services
    enabled: true
    source: local
    path: ../ansible/site-services
    version: "1.0.0"
    resolve_dependencies: true
    default_playbook: deploy
```

Local projects are copied into the appliance as immutable revisions:

```text
/opt/stoker/.versions/projects/site-services/1.0.0/
/opt/stoker/projects/site-services -> ../.versions/projects/site-services/1.0.0
```

A local project must contain a `playbooks/` directory. A combined `requirements.yml` may define `roles` and `collections` lists. With `resolve_dependencies: true`, the builder vendors them into that immutable revision and writes `.stoker/dependencies.lock`.

Git projects may be declared for runtime synchronization:

```yaml
  - name: incident-response
    enabled: true
    source: git
    repository: ssh://gitea@gitea.example/STOKER/incident-response.git
    ref: stable
    embed: false
    resolve_dependencies: true
    default_playbook: deploy
```

Set `embed: true` to clone and embed the configured Git revision during the ISO render stage. Build-time Git credentials must already be available to the normal build user.

## Controller project commands

After installation:

```sh
stoker project list
stoker project status node-baseline
stoker project validate node-baseline
stoker project run node-baseline validate --inventory discovered
sudo stoker project sync incident-response
sudo stoker project sync --all
sudo stoker project rollback incident-response
```

Compatibility wrappers are also installed:

```sh
stoker-project-run node-baseline deploy --inventory production
sudo stoker-project-sync --all
sudo stoker-project-import /media/usb/STOKER_PROJECTS
```

Playbook output is streamed to the terminal and written under `/opt/stoker/logs/ansible/`.

## Enrolling managed nodes

Add a node to the generated `discovered` inventory:

```sh
sudo stoker-node-enroll node01 192.168.88.101 --user stoker
ansible -i /opt/stoker/inventory/discovered/hosts.yaml \
  node01 -m ansible.builtin.ping
stoker project run node-baseline deploy \
  --inventory discovered --limit node01
```

SSH keys and vaulted credentials are intentionally not embedded. The installer generates a unique Ed25519 controller key at `/home/stoker/.ssh/id_ed25519`; place vault passwords and other controller secrets under `/etc/stoker/secrets/`.

## Offline project bundles

Create a bundle on a trusted workstation:

```sh
./scripts/create-project-bundle.py ./STOKER_PROJECTS \
  node-baseline=./ansible/node-baseline \
  incident-response=../incident-response
```

The bundle contains `manifest.yaml`, compressed project archives, revision-local Galaxy dependencies, dependency locks, and SHA-256 values. The bundle creator resolves dependencies by default. Import verifies every archive before extraction, rejects traversal links and special files, validates the playbooks, then atomically activates the new revision.

Use `--no-resolve-dependencies` only when a project already carries a matching `.stoker/dependencies.lock` tree. Only projects already declared in `/etc/stoker/ansible-projects.yaml` may be imported. This makes the configuration an explicit allowlist rather than a USB-shaped execution lottery.

## Development render without secrets

Template work can use placeholders:

```sh
./build.sh \
  -c config/stoker-build.yaml \
  --allow-placeholder-secrets \
  render
```

A real `all` build should not use placeholder secrets.

## Individual stages

```text
validate     Validate the main schema and referenced YAML
render       Render preseed, controller projects, and generated manifests
resolve      Resolve and download requested packages and dependencies
repository   Build the embedded APT repository
extract      Extract the original ISO and record boot reports
inject       Add STOKER content and unattended boot entries
checksum     Regenerate STOKER SHA-256 and Debian-style md5sum.txt
package      Update the original ISO tree and replay its boot equipment
verify       Check boot metadata, embedded payload, and write ISO SHA-256
all          Run the complete pipeline
clean        Remove the disposable work directory
```

The stages are resumable. Package downloads remain in `work/apt/` until `clean` is run.

## Configuration map

- `config/stoker-build.yaml`: build, installer, disk, boot, and output policy
- `config/repositories.yaml`: package sources used only by the build host
- `config/packages.yaml`: reusable package groups
- `config/modules.yaml`: enabled appliance modules, packages, scripts, and module configuration
- `config/ansible-projects.yaml`: controller paths, validation policy, and project sources
- `ansible/`: built-in Ansible project sources
- `scripts/runtime/`: installed controller CLI and compatibility wrappers
- `scripts/select-install-disk.sh`: installer-time disk selection and wipe policy
- `scripts/install-offline-packages.sh`: target provisioning from the embedded repository
- `scripts/modules/`: enabled module installers
- `overlays/rootfs/`: files copied into the installed operating system
- `overlays/iso/`: arbitrary files copied into the ISO filesystem

See `docs/CONFIGURATION.md` for field details.

## Boot preservation

The builder does not invent a static `mkisofs` command. It:

1. Loads the original ISO with `xorriso -indev`.
2. Extracts and updates its filesystem tree.
3. Writes the modified image to a separate output.
4. Uses `-boot_image any replay` so `xorriso` recreates recognized El Torito and system-area boot provisions from the source image.

Source boot reports are retained under `logs/` in plain, command, and `as_mkisofs` forms.

## Package trust model

Package downloads on the build host remain signature-verified against the configured archive keyring. The finished appliance uses a `Trusted: yes` source only for the read-only repository copied from its own installation ISO. This avoids disabling authentication globally or running `dpkg -i` against an unordered directory.

Ansible project imports use manifest SHA-256 verification. Git synchronization relies on the configured Git transport and host-key policy. Use SSH repositories with pinned host keys for operational controllers.

## Secret warning

The rendered preseed inside the ISO necessarily contains the initial LUKS passphrase and the `stoker` password hash. Treat each generated ISO as sensitive. Use a unique LUKS passphrase per build, securely destroy obsolete images, or add first-boot LUKS rekeying later.

The release directory receives only a **redacted** preseed copy. The unredacted generated preseed remains under `work/generated/` and inside the ISO.

## Current boundaries

- Debian 13 `amd64` netinst layout only
- Known Debian kernel/initrd paths under `/install.amd`
- ISO-local repository uses `Trusted: yes` in v0.1
- Runtime Git synchronization is CLI-driven, not scheduled
- Automated QEMU install assertions are not yet implemented
- The automatic network-role policy requires at least two non-loopback interfaces when DHCP is enabled
