from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_runtime_module():
    path = ROOT / "scripts/runtime/stoker"
    loader = importlib.machinery.SourceFileLoader("stoker_runtime_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_bundle_creator_vendors_dependency_lock(tmp_path: Path) -> None:
    output = tmp_path / "bundle"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/create-project-bundle.py"),
            str(output),
            f"node-baseline={ROOT / 'ansible/node-baseline'}",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    manifest = yaml.safe_load((output / "manifest.yaml").read_text(encoding="utf-8"))
    entry = manifest["projects"][0]
    archive = output / entry["archive"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == entry["sha256"]

    with tarfile.open(archive, "r:gz") as bundle:
        names = set(bundle.getnames())
    assert "node-baseline/.stoker/dependencies.lock" in names
    assert not any("/.git/" in name for name in names)


def test_runtime_rejects_archive_path_traversal(tmp_path: Path) -> None:
    runtime = load_runtime_module()
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, "w") as bundle:
        info = tarfile.TarInfo("../escape")
        payload = b"bad"
        info.size = len(payload)
        import io

        bundle.addfile(info, io.BytesIO(payload))

    with pytest.raises(runtime.StokerProjectError, match="unsafe path"):
        runtime.unpack_archive(archive, tmp_path / "extract")


def test_run_parser_accepts_options_after_playbook() -> None:
    runtime = load_runtime_module()
    args = runtime.build_parser().parse_args(
        [
            "project",
            "run",
            "node-baseline",
            "deploy",
            "--inventory",
            "discovered",
            "--limit",
            "node01",
        ]
    )
    assert args.inventory == "discovered"
    assert args.limit == "node01"
