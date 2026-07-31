from pathlib import Path

from stoker_builder.builder import StokerBuilder
from stoker_builder.config import BuildConfig

ROOT = Path(__file__).resolve().parents[1]


def test_rendered_preseed_uses_stoker_and_disk_helper(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "stoker-build.yaml"
    original = (ROOT / "config/stoker-build.yaml").read_text(encoding="utf-8")
    original = original.replace("../work", str(tmp_path / "work"))
    original = original.replace("../output", str(tmp_path / "output"))
    original = original.replace("../logs", str(tmp_path / "logs"))
    original = original.replace("../templates", str(ROOT / "templates"))
    original = original.replace("../scripts", str(ROOT / "scripts"))
    original = original.replace("../overlays", str(ROOT / "overlays"))
    original = original.replace("repositories.yaml", str(ROOT / "config/repositories.yaml"))
    original = original.replace("packages.yaml", str(ROOT / "config/packages.yaml"))
    original = original.replace("modules.yaml", str(ROOT / "config/modules.yaml"))
    original = original.replace("ansible-projects.yaml", str(ROOT / "config/ansible-projects.yaml"))
    config_path.write_text(original, encoding="utf-8")

    config = BuildConfig.load(config_path)
    builder = StokerBuilder(config, allow_placeholder_secrets=True)
    preseed = builder.render().read_text(encoding="utf-8")

    assert "passwd/username string stoker" in preseed
    assert "select-install-disk.sh" in preseed
    assert "--wipe-all-fixed-disks=false" in preseed
    assert "--require-uefi=true" in preseed
    assert "stoker/wipe_all_fixed_disks" not in preseed
    assert "stoker/require_uefi" not in preseed
    assert "partman-auto/choose_recipe select atomic" in preseed
    assert "partman-partitioning/choose_label select gpt" in preseed
    assert "nerdadmin" not in preseed
    assert "defender" not in preseed


def test_render_stages_versioned_ansible_projects(tmp_path) -> None:
    config_path = tmp_path / "stoker-build.yaml"
    original = (ROOT / "config/stoker-build.yaml").read_text(encoding="utf-8")
    replacements = {
        "../work": str(tmp_path / "work"),
        "../output": str(tmp_path / "output"),
        "../logs": str(tmp_path / "logs"),
        "../templates": str(ROOT / "templates"),
        "../scripts": str(ROOT / "scripts"),
        "../overlays": str(ROOT / "overlays"),
        "repositories.yaml": str(ROOT / "config/repositories.yaml"),
        "packages.yaml": str(ROOT / "config/packages.yaml"),
        "modules.yaml": str(ROOT / "config/modules.yaml"),
        "ansible-projects.yaml": str(ROOT / "config/ansible-projects.yaml"),
    }
    for old, new in replacements.items():
        original = original.replace(old, new)
    config_path.write_text(original, encoding="utf-8")

    config = BuildConfig.load(config_path)
    builder = StokerBuilder(config, allow_placeholder_secrets=True)
    builder.render()

    rootfs = tmp_path / "work/generated/rootfs"
    active = rootfs / "opt/stoker/projects/node-baseline"
    assert active.is_symlink()
    assert active.resolve().name == "0.1.4"
    assert (active.resolve() / "playbooks/deploy.yml").is_file()
    assert (active.resolve() / ".stoker/dependencies.lock").is_file()
    assert (rootfs / "usr/local/sbin/stoker").stat().st_mode & 0o111
    assert (rootfs / "etc/stoker/ansible-projects.yaml").is_file()
    assert (rootfs / "usr/local/sbin/stoker-network-config").stat().st_mode & 0o111
    assert (rootfs / "usr/local/sbin/stoker-nat").stat().st_mode & 0o111
