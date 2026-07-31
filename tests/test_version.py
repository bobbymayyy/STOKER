from __future__ import annotations

from pathlib import Path

import yaml

from stoker_builder import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_consistent() -> None:
    build = yaml.safe_load((ROOT / "config/stoker-build.yaml").read_text(encoding="utf-8"))
    projects = yaml.safe_load(
        (ROOT / "config/ansible-projects.yaml").read_text(encoding="utf-8")
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert __version__ == "0.1.4"
    assert build["project"]["version"] == __version__
    assert build["output"]["volume_id"] == "STOKER_0_1_4"
    assert f'version = "{__version__}"' in pyproject
    assert {project["version"] for project in projects["projects"] if project["enabled"]} == {
        __version__
    }
