from pathlib import Path

from stoker_builder.util import make_tree_owner_writable


def test_make_tree_owner_writable(tmp_path: Path) -> None:
    directory = tmp_path / "iso-root" / "isolinux"
    directory.mkdir(parents=True)
    target = directory / "txt.cfg"
    target.write_text("default install\n", encoding="utf-8")

    target.chmod(0o444)
    directory.chmod(0o555)

    make_tree_owner_writable(tmp_path / "iso-root")

    assert target.stat().st_mode & 0o200
    assert directory.stat().st_mode & 0o200
    target.write_text("patched\n", encoding="utf-8")
