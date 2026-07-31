#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

IGNORED_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        if any(part in IGNORED_PARTS for part in item.relative_to(path).parts):
            continue
        if item.is_file():
            digest.update(item.relative_to(path).as_posix().encode())
            digest.update(item.read_bytes())
    return digest.hexdigest()[:12]


def revision(path: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=path,
            check=True,
            text=True,
            capture_output=True,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return f"bundle-{tree_digest(path)}"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required command is not installed: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Command failed with exit code {exc.returncode}") from exc


def load_mapping(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a YAML mapping in {path}")
    return value


def dependencies_are_locked(project: Path, requirements_hash: str, roles: list, collections: list) -> bool:
    dependency_root = project / ".stoker"
    lock_path = dependency_root / "dependencies.lock"
    if not lock_path.is_file():
        return False
    lock = load_mapping(lock_path)
    return (
        lock.get("requirements_sha256") == requirements_hash
        and (not roles or (dependency_root / "roles").is_dir())
        and (not collections or (dependency_root / "collections").is_dir())
    )


def vendor_dependencies(project: Path, *, resolve: bool) -> None:
    requirements = project / "requirements.yml"
    if not requirements.is_file():
        return
    contents = load_mapping(requirements)
    roles = contents.get("roles") or []
    collections = contents.get("collections") or []
    if not isinstance(roles, list) or not isinstance(collections, list):
        raise RuntimeError(f"Invalid roles/collections lists in {requirements}")

    requirements_hash = sha256(requirements)
    if dependencies_are_locked(project, requirements_hash, roles, collections):
        return
    if (roles or collections) and not resolve:
        raise RuntimeError(
            f"{project.name} has unresolved dependencies; remove --no-resolve-dependencies or vendor .stoker first"
        )

    dependency_root = project / ".stoker"
    roles_root = dependency_root / "roles"
    collections_root = dependency_root / "collections"
    roles_root.mkdir(parents=True, exist_ok=True)
    collections_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="stoker-bundle-galaxy-") as temporary:
        temp = Path(temporary)
        if roles:
            role_requirements = temp / "roles.yml"
            role_requirements.write_text(yaml.safe_dump(roles, sort_keys=False), encoding="utf-8")
            run([
                "ansible-galaxy",
                "role",
                "install",
                "--force",
                "--roles-path",
                str(roles_root),
                "-r",
                str(role_requirements),
            ])
        if collections:
            collection_requirements = temp / "collections.yml"
            collection_requirements.write_text(
                yaml.safe_dump({"collections": collections}, sort_keys=False),
                encoding="utf-8",
            )
            run([
                "ansible-galaxy",
                "collection",
                "install",
                "--force",
                "--collections-path",
                str(collections_root),
                "-r",
                str(collection_requirements),
            ])

    (dependency_root / "dependencies.lock").write_text(
        yaml.safe_dump(
            {
                "requirements_sha256": requirements_hash,
                "roles": len(roles),
                "collections": len(collections),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a verified, dependency-vendored STOKER Ansible project bundle"
    )
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "projects",
        nargs="+",
        metavar="NAME=PATH",
        help="Project name and source directory",
    )
    parser.add_argument(
        "--no-resolve-dependencies",
        action="store_true",
        help="Require dependencies to already be vendored under .stoker",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "projects": []}
    with tempfile.TemporaryDirectory(prefix="stoker-project-bundle-") as temporary:
        temporary_root = Path(temporary)
        for specification in args.projects:
            if "=" not in specification:
                parser.error(f"Project must use NAME=PATH syntax: {specification}")
            name, raw_path = specification.split("=", 1)
            source = Path(raw_path).expanduser().resolve()
            if not name or not source.is_dir():
                parser.error(f"Invalid project source: {specification}")

            staged = temporary_root / name
            shutil.copytree(
                source,
                staged,
                symlinks=True,
                ignore=shutil.ignore_patterns(*IGNORED_PARTS),
            )
            try:
                vendor_dependencies(staged, resolve=not args.no_resolve_dependencies)
            except RuntimeError as exc:
                parser.error(str(exc))

            archive = args.output / f"{name}.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(staged, arcname=name, recursive=True)
            manifest["projects"].append(
                {
                    "name": name,
                    "archive": archive.name,
                    "sha256": sha256(archive),
                    "revision": revision(source),
                }
            )

    (args.output / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    print(f"Created {args.output / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
