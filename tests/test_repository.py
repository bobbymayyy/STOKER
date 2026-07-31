from pathlib import Path

from stoker_builder.repository import _release_file


def test_release_file_contains_modern_checksums(tmp_path: Path) -> None:
    binary = tmp_path / "main/binary-amd64"
    binary.mkdir(parents=True)
    (binary / "Packages").write_text("Package: example\n", encoding="utf-8")

    release = _release_file(
        tmp_path,
        origin="STOKER",
        label="STOKER",
        suite="stoker",
        codename="stoker",
        version="0.1.4",
        architectures=["amd64"],
        components=["main"],
    )

    assert "SHA256:" in release
    assert "SHA512:" in release
    assert "main/binary-amd64/Packages" in release
