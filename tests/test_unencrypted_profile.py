from pathlib import Path

from stoker_builder.builder import StokerBuilder
from stoker_builder.config import BuildConfig

ROOT = Path(__file__).resolve().parents[1]


def test_unencrypted_profile_renders_plain_lvm(tmp_path) -> None:
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
        "encryption: luks": "encryption: none",
    }
    for old, new in replacements.items():
        original = original.replace(old, new)
    config_path.write_text(original, encoding="utf-8")

    config = BuildConfig.load(config_path)
    builder = StokerBuilder(config, allow_placeholder_secrets=True)
    preseed = builder.render().read_text(encoding="utf-8")

    assert "partman-auto/method string lvm" in preseed
    assert "partman-auto/method string crypto" not in preseed
    assert "partman-crypto/passphrase" not in preseed
    assert "partman-crypto/confirm" not in preseed
