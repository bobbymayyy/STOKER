from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_disk_selector_avoids_nested_confmodule_protocol() -> None:
    script_path = ROOT / "scripts/select-install-disk.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(["sh", "-n", str(script_path)], check=True)

    assert ". /usr/share/debconf/confmodule" not in script
    assert "db_get " not in script
    assert "db_set " not in script
    assert "$(get_bool" not in script
    assert "debconf-set partman-auto/disk" in script
    assert "debconf-set grub-installer/bootdev" in script
    assert "--wipe-all-fixed-disks=*" in script
    assert "--require-uefi=*" in script


def test_disk_selector_rejects_bad_policy_without_stdout_leakage() -> None:
    script_path = ROOT / "scripts/select-install-disk.sh"
    result = subprocess.run(
        [str(script_path), "--wipe-all-fixed-disks=banana"],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "must be true or false" in result.stderr


def test_target_cdrom_source_is_disabled_before_apt_update() -> None:
    script_path = ROOT / "scripts/install-offline-packages.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(["sh", "-n", str(script_path)], check=True)

    cleanup = "sed -i '/^[[:space:]]*deb[[:space:]].*cdrom:/d'"
    apt_update = "in-target apt-get update"
    assert cleanup in script
    assert script.index(cleanup) < script.index(apt_update)


def test_installation_validator_catches_daemon_only_docker() -> None:
    validator = (ROOT / "scripts/validate-installation.sh").read_text(
        encoding="utf-8"
    )

    assert "check 'Docker CLI exists' command -v docker" in validator
    assert "check 'Docker service is enabled' systemctl is-enabled docker.service" in validator


def test_module_manifest_preserves_debconf_stdin() -> None:
    script_path = ROOT / "scripts/install-offline-packages.sh"
    script = script_path.read_text(encoding="utf-8")

    subprocess.run(["sh", "-n", str(script_path)], check=True)

    assert "while IFS= read -r script <&3; do" in script
    assert 'done 3< "$MODULE_MANIFEST"' in script
    assert 'done < "$MODULE_MANIFEST"' not in script
    assert 'STOKER_INSTALLER_CONTEXT=1 "$dst"' in script


def test_target_ownership_is_resolved_inside_chroot() -> None:
    script = (ROOT / "scripts/install-offline-packages.sh").read_text(
        encoding="utf-8"
    )

    assert "in-target chown -R root:stoker /opt/stoker" in script
    assert 'chown -R root:stoker "$TARGET/opt/stoker"' not in script


def test_network_modules_share_renderer_and_validate_services() -> None:
    network_installer = (ROOT / "scripts/modules/network.sh").read_text(encoding="utf-8")
    validator = (ROOT / "scripts/validate-installation.sh").read_text(encoding="utf-8")

    subprocess.run(["sh", "-n", str(ROOT / "scripts/modules/network.sh")], check=True)
    subprocess.run(["sh", "-n", str(ROOT / "scripts/validate-installation.sh")], check=True)

    assert "/usr/local/sbin/stoker-network-config apply" in network_installer
    assert "kea-dhcp4 -t /etc/kea/kea-dhcp4.conf" in validator
    assert "named-checkconf" in validator
    assert "nft -c -f /etc/nftables.conf" in validator
    assert "systemctl is-enabled stoker-network-config.service" in validator
