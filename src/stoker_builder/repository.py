from __future__ import annotations

import gzip
import hashlib
import lzma
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .errors import StokerBuildError
from .util import require_command, run


def build_repository(
    *,
    deb_directory: Path,
    repository_root: Path,
    suite: str,
    component: str,
    architecture: str,
    origin: str,
    version: str,
    dry_run: bool = False,
) -> None:
    debs = sorted(deb_directory.glob("*.deb"))
    if not debs:
        raise StokerBuildError(
            f"No .deb packages were found in {deb_directory}. Run the resolve stage first."
        )

    if repository_root.exists():
        shutil.rmtree(repository_root)
    pool = repository_root / "pool" / component
    index_dir = repository_root / "dists" / suite / component / f"binary-{architecture}"
    pool.mkdir(parents=True)
    index_dir.mkdir(parents=True)

    for package in debs:
        shutil.copy2(package, pool / package.name)

    packages_path = index_dir / "Packages"
    if shutil.which("apt-ftparchive"):
        result = run(
            ["apt-ftparchive", "packages", f"pool/{component}"],
            cwd=repository_root,
            capture=True,
            dry_run=dry_run,
        )
    else:
        require_command("dpkg-scanpackages")
        result = run(
            ["dpkg-scanpackages", "--multiversion", f"pool/{component}", "/dev/null"],
            cwd=repository_root,
            capture=True,
            dry_run=dry_run,
        )
    if not dry_run:
        packages_text = result.stdout or ""
        packages_path.write_text(packages_text, encoding="utf-8")
        with gzip.open(index_dir / "Packages.gz", "wb", compresslevel=9) as handle:
            handle.write(packages_text.encode())
        with lzma.open(index_dir / "Packages.xz", "wb", preset=9) as handle:
            handle.write(packages_text.encode())

        release_path = repository_root / "dists" / suite / "Release"
        release_path.write_text(
            _release_file(
                repository_root / "dists" / suite,
                origin=origin,
                label=origin,
                suite=suite,
                codename=suite,
                version=version,
                architectures=[architecture],
                components=[component],
            ),
            encoding="utf-8",
        )


def sign_repository(repository_root: Path, suite: str, key: str, *, dry_run: bool = False) -> None:
    require_command("gpg")
    release = repository_root / "dists" / suite / "Release"
    if not release.exists() and not dry_run:
        raise StokerBuildError(f"Repository Release file does not exist: {release}")
    run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--local-user",
            key,
            "--clearsign",
            "--output",
            release.parent / "InRelease",
            release,
        ],
        dry_run=dry_run,
    )
    run(
        [
            "gpg",
            "--batch",
            "--yes",
            "--local-user",
            key,
            "--armor",
            "--detach-sign",
            "--output",
            release.parent / "Release.gpg",
            release,
        ],
        dry_run=dry_run,
    )


def _release_file(
    root: Path,
    *,
    origin: str,
    label: str,
    suite: str,
    codename: str,
    version: str,
    architectures: list[str],
    components: list[str],
) -> str:
    files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != "Release"]
    lines = [
        f"Origin: {origin}",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {codename}",
        f"Version: {version}",
        f"Date: {datetime.now(timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        "Description: STOKER embedded offline package repository",
    ]
    for algorithm, heading in (
        ("md5", "MD5Sum"),
        ("sha1", "SHA1"),
        ("sha256", "SHA256"),
        ("sha512", "SHA512"),
    ):
        lines.append(f"{heading}:")
        for path in files:
            digest = hashlib.new(algorithm, path.read_bytes()).hexdigest()
            relative = path.relative_to(root).as_posix()
            lines.append(f" {digest} {path.stat().st_size:16d} {relative}")
    return "\n".join(lines) + "\n"
