# Configuration

## `stoker-build.yaml`

### `source_iso`

`path` is resolved relative to the main YAML file. `expected_sha256` is optional but recommended for a pinned build recipe.

### `installer.account`

`password_hash_env` names the environment variable containing a `crypt(3)` hash. The sample uses a yescrypt hash generated with `mkpasswd -m yescrypt`.

Only the `stoker` account is created. The schema requires direct root login to remain disabled.

### `installer.disk`

- `wipe_all_fixed_disks: false` wipes only the selected installation disk.
- `wipe_all_fixed_disks: true` wipes every eligible fixed non-USB disk.
- `require_uefi: true` causes the selector to stop before partitioning when the installer was not booted through UEFI.
- `recipe: atomic` avoids separate `/home`, `/var`, `/tmp`, and log filesystems.
- `guided_size: max` allocates the available LVM space rather than retaining a large unused reserve.
- `erase_before_encryption: false` skips the installer’s lengthy full-disk random overwrite. Existing signatures are still cleared by the selector.

### `boot.kernel_arguments`

Arguments are added to both generated ISOLINUX and GRUB entries. The default points Debian Installer to `/cdrom/stoker/preseed.cfg` and enables automatic, critical-priority installation.

### `paths.ansible_projects`

Points to the Ansible project catalog, normally `config/ansible-projects.yaml`. The path is resolved relative to the main build YAML.

## `repositories.yaml`

These sources are used only to download packages during the build. With `build.verify_downloads: true`, every enabled repository must provide a valid `signed_by` keyring path on the build host.

## `packages.yaml`

Every enabled group contributes package names. `exclude` removes names after all groups and modules are merged.

## `modules.yaml`

Each enabled module may define:

- `packages`: added to the shared APT dependency solution
- `post_install_script`: simple filename from `scripts/modules/`
- `configuration`: copied into the generated module manifest

Module scripts run inside the installed target after package installation and root filesystem overlay application. The network modules all select `network.sh`; duplicate script names are de-duplicated, so the shared renderer runs once.

### Network role selection

```yaml
routing:
  configuration:
    upstream_interface: auto
    enable_ipv4_forwarding: true
    enable_nat: false

dhcp:
  configuration:
    interface: auto
    subnet: 192.168.88.0/24
    gateway: 192.168.88.1
    pool_start: 192.168.88.100
    pool_end: 192.168.88.200
    dns_servers: [192.168.88.1]
```

`upstream_interface: auto` first selects an interface configured with `inet dhcp`, then falls back to the current default route, then to the first physical interface. `dhcp.interface: auto` selects the next physical interface after upstream. Explicit Linux interface names may be used for either field. Upstream and downstream must be different.

The downstream gateway and prefix are written as both `auto` and `allow-hotplug` configuration in `/etc/network/interfaces.d/90-stoker-downstream`. The renderer also ensures `/etc/network/interfaces` includes `interfaces.d`. Resolved roles are stored in `/etc/stoker/network-roles.env`.

### Kea DHCPv4

The DHCP mapping renders `/etc/kea/kea-dhcp4.conf` with:

- only the resolved downstream interface;
- a persistent memfile lease database;
- the configured pool, gateway, DNS servers, and optional domain name;
- configurable renew, rebind, valid-lifetime, and max-valid-lifetime timers.

The build validator requires the gateway and pool to be inside the IPv4 subnet, rejects a pool containing the gateway, and checks timer ordering.

### BIND9 forwarding

```yaml
dns:
  configuration:
    recursion: true
    forwarders: [1.1.1.1, 9.9.9.9]
    forward_policy: only
```

The renderer writes `/etc/bind/named.conf.options`. Queries and recursion are allowed only from localhost and the configured downstream subnet. `forward_policy` accepts `only` or `first`; it is emitted only when forwarders are present.

### Routing and runtime NAT

The renderer writes `net.ipv4.ip_forward` under `/etc/sysctl.d/` and an `/etc/nftables.conf` that replaces only the `ip stoker_nat` table. It deliberately does not flush the global ruleset, preserving Docker and administrator-owned tables. Masquerading is omitted while `enable_nat: false`.

Runtime control is available without rebuilding:

```sh
sudo stoker-nat enable
sudo stoker-nat disable
sudo stoker-nat reset
sudo stoker-nat status
```

The override is stored in `/etc/stoker/nat.mode`; `reset` removes it and returns to the `modules.yaml` default.

### Boot ordering

`stoker-network-config.service` is enabled from `multi-user.target` and ordered before `network-pre.target` and `networking.service`. Drop-ins order nftables, BIND, and Kea after the renderer. At boot, the service reapplies sysctl and nftables state before network services start.

## `ansible-projects.yaml`

### Controller paths

The `ansible` mapping defines absolute installed paths:

- `project_root`: active project links
- `versions_root`: immutable project revisions
- `staging_root`: temporary Git and import work
- `inventory_root`: controller inventories
- `roles_root`: shared Galaxy roles
- `collections_root`: shared Galaxy collections
- `artifacts_root`: large files distributed by playbooks
- `logs_root`: playbook execution logs
- `secrets_root`: vault passwords, SSH material, and other local secrets

`default_inventory` names the inventory used when `stoker project run` receives no `--inventory`. `retain_versions` limits stored project revisions after successful activation.

### Validation

```yaml
validation:
  syntax_check: true
  lint: false
```

Syntax checks run before Git or imported revisions become active. Linting can be enabled when projects are ready to treat `ansible-lint` findings as deployment blockers.

### Local projects

```yaml
- name: node-baseline
  enabled: true
  source: local
  path: ../ansible/node-baseline
  version: "0.1.4"
  resolve_dependencies: true
  default_playbook: deploy
```

Local paths are resolved relative to `ansible-projects.yaml`. `version` becomes the immutable revision directory name.

### Git projects

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

With `embed: false`, only repository metadata is placed on the appliance and the first checkout is performed by `sudo stoker project sync NAME`. With `embed: true`, the builder clones `ref` during render and preserves the configured Git source for later synchronization. `resolve_dependencies` controls build-time Galaxy vendoring for embedded revisions.

## Project repository shape

```text
project-name/
├── README.md
├── requirements.yml
└── playbooks/
    ├── deploy.yml
    ├── validate.yml
    └── rollback.yml
```

`requirements.yml` may contain `roles` and `collections` arrays. Dependencies are installed under `.stoker/roles` and `.stoker/collections` inside the immutable project revision, with the controller-wide roots retained as shared fallbacks. `.stoker/dependencies.lock` binds the requirement-file hash to the vendored tree, keeping rollback dependencies attached to the revision that declared them.

## Inventories

The ISO includes:

```text
/opt/stoker/inventory/production/hosts.yaml
/opt/stoker/inventory/discovered/hosts.yaml
```

`stoker-node-enroll` writes to `discovered` by default. Production inventory remains a deliberate promotion target.

## Offline bundle manifest

```yaml
format: 1
projects:
  - name: node-baseline
    archive: node-baseline.tar.gz
    sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    revision: 7f3c9c2a88b1
```

The importer requires an allowlisted project name, a 64-character SHA-256 digest, and a safe revision label. Archive symlinks, devices, hard links, and path traversal entries are rejected.

## Overlays

`overlays/iso/` merges into the ISO root before checksum generation. `overlays/rootfs/` becomes `/` on the installed appliance.
