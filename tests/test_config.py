from pathlib import Path

from stoker_builder.config import BuildConfig

ROOT = Path(__file__).resolve().parents[1]


def test_package_and_module_merge() -> None:
    config = BuildConfig.load(ROOT / "config/stoker-build.yaml")
    packages = config.requested_packages()

    assert "ansible-core" in packages
    assert "docker.io" in packages
    assert "docker-cli" in packages
    assert "docker-compose" in packages
    assert "qemu-guest-agent" in packages
    assert "amd64-microcode" in packages
    assert "intel-microcode" in packages
    assert "nftables" in packages
    assert "kea-dhcp4-server" in packages
    assert "bind9" in packages
    assert "bind9-utils" in packages
    assert packages == sorted(set(packages))


def test_only_expected_module_scripts_are_enabled() -> None:
    config = BuildConfig.load(ROOT / "config/stoker-build.yaml")
    assert config.post_install_scripts() == [
        "ansible-controller.sh",
        "containers.sh",
        "network.sh",
    ]


def test_ansible_projects_are_resolved() -> None:
    config = BuildConfig.load(ROOT / "config/stoker-build.yaml")
    projects = config.enabled_ansible_projects()

    assert [project["name"] for project in projects] == [
        "stoker-bootstrap",
        "node-baseline",
    ]
    assert config.ansible_project_source_path(projects[0]).is_dir()
    assert config.ansible_settings()["project_root"] == "/opt/stoker/projects"
