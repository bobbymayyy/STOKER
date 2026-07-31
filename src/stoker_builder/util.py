from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import yaml

from .errors import StokerBuildError

LOG = logging.getLogger("stoker-builder")


def load_yaml(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise StokerBuildError(f"Configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise StokerBuildError(f"Invalid YAML in {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise StokerBuildError(f"Expected a YAML mapping at the top of {path}")
    return value


def dump_yaml(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def dump_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def hash_file(path: Path, algorithm: str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def require_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise StokerBuildError(
            f"Required command '{name}' was not found. See README.md for build-host packages."
        )
    return command


def run(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture: bool = False,
    dry_run: bool = False,
    log_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [os.fspath(item) for item in argv]
    LOG.info("+ %s", " ".join(_shell_quote(item) for item in command))
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    result = subprocess.run(
        command,
        cwd=cwd,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE if capture or log_path else None,
        stderr=subprocess.STDOUT if capture or log_path else None,
        check=False,
    )
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout or "", encoding="utf-8")
    if result.returncode != 0:
        output = (result.stdout or "").strip()
        detail = f"\n{output}" if output else ""
        raise StokerBuildError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}{detail}"
        )
    return result


def copy_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    if not source.is_dir():
        raise StokerBuildError(f"Overlay path is not a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)


def ensure_empty_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def make_tree_owner_writable(path: Path) -> None:
    """Add owner-write permission to an extracted ISO tree without following symlinks."""
    if not path.is_dir():
        raise StokerBuildError(f"Cannot make missing tree writable: {path}")

    for directory, directory_names, file_names in os.walk(path, followlinks=False):
        current = Path(directory)
        if not current.is_symlink():
            current.chmod(current.stat().st_mode | 0o200)

        for name in directory_names:
            candidate = current / name
            if not candidate.is_symlink():
                candidate.chmod(candidate.stat().st_mode | 0o200)

        for name in file_names:
            candidate = current / name
            if not candidate.is_symlink():
                candidate.chmod(candidate.stat().st_mode | 0o200)


def unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _shell_quote(value: str) -> str:
    if value and all(character.isalnum() or character in "_./:=+,-" for character in value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"
